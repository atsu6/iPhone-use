// Encode a folder of PNG frames (plus an optional WAV soundtrack) into an H.264 / AAC MP4
// with the system AVFoundation encoders, so the film needs no ffmpeg install.
//
//   swiftc -O promo/encode.swift -o encode
//   ./encode <framesDir> <fps> <out.mp4> [audio.wav] [megabitsPerSecond]
import AVFoundation
import CoreGraphics
import Foundation
import ImageIO

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("encode: \(message)\n".utf8))
    exit(1)
}

let arguments = CommandLine.arguments
guard arguments.count >= 4, let fps = Int32(arguments[2]), fps > 0 else {
    fail("usage: encode <framesDir> <fps> <out.mp4> [audio.wav] [megabitsPerSecond]")
}
let framesDirectory = URL(fileURLWithPath: arguments[1], isDirectory: true)
let outputURL = URL(fileURLWithPath: arguments[3])
let audioURL = arguments.count > 4 && !arguments[4].isEmpty ? URL(fileURLWithPath: arguments[4]) : nil
let megabits = arguments.count > 5 ? Double(arguments[5]) ?? 16 : 16

let names: [String]
do {
    names = try FileManager.default.contentsOfDirectory(atPath: framesDirectory.path)
        .filter { $0.hasPrefix("f_") && $0.hasSuffix(".png") }
        .sorted()
} catch {
    fail("cannot list \(framesDirectory.path): \(error.localizedDescription)")
}
guard !names.isEmpty else { fail("no f_*.png frames in \(framesDirectory.path)") }

func loadImage(_ name: String) -> CGImage? {
    let url = framesDirectory.appendingPathComponent(name)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    return CGImageSourceCreateImageAtIndex(source, 0, nil)
}

guard let firstImage = loadImage(names[0]) else { fail("cannot decode \(names[0])") }
let width = firstImage.width
let height = firstImage.height
guard width % 2 == 0, height % 2 == 0 else { fail("frame size \(width)x\(height) must be even") }

try? FileManager.default.removeItem(at: outputURL)
let writer: AVAssetWriter
do {
    writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
} catch {
    fail("cannot create \(outputURL.path): \(error.localizedDescription)")
}
writer.shouldOptimizeForNetworkUse = true

let videoInput = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoColorPropertiesKey: [
        AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
        AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
        AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2,
    ],
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: Int(megabits * 1_000_000),
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        AVVideoMaxKeyFrameIntervalKey: Int(fps) * 2,
        AVVideoExpectedSourceFrameRateKey: Int(fps),
        AVVideoAllowFrameReorderingKey: true,
    ],
])
videoInput.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: videoInput, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
])
guard writer.canAdd(videoInput) else { fail("writer rejected the video settings") }
writer.add(videoInput)

var audioReader: AVAssetReader?
var audioOutput: AVAssetReaderTrackOutput?
var audioInput: AVAssetWriterInput?
if let audioURL {
    let asset = AVURLAsset(url: audioURL)
    guard let track = asset.tracks(withMediaType: .audio).first else { fail("no audio track in \(audioURL.path)") }
    do {
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ])
        reader.add(output)
        let input = AVAssetWriterInput(mediaType: .audio, outputSettings: [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 48_000,
            AVNumberOfChannelsKey: 2,
            AVEncoderBitRateKey: 256_000,
        ])
        input.expectsMediaDataInRealTime = false
        guard writer.canAdd(input) else { fail("writer rejected the audio settings") }
        writer.add(input)
        audioReader = reader
        audioOutput = output
        audioInput = input
    } catch {
        fail("cannot read \(audioURL.path): \(error.localizedDescription)")
    }
}

guard writer.startWriting() else { fail("cannot start writing: \(writer.error?.localizedDescription ?? "unknown")") }
writer.startSession(atSourceTime: .zero)
guard let pool = adaptor.pixelBufferPool else { fail("no pixel buffer pool") }
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
let bitmapInfo = CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue

func pixelBuffer(for image: CGImage) -> CVPixelBuffer? {
    var buffer: CVPixelBuffer?
    guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &buffer) == kCVReturnSuccess, let buffer else { return nil }
    CVPixelBufferLockBaseAddress(buffer, [])
    defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
    guard let context = CGContext(data: CVPixelBufferGetBaseAddress(buffer), width: width, height: height,
                                  bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
                                  space: colorSpace, bitmapInfo: bitmapInfo) else { return nil }
    context.interpolationQuality = .none
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    return buffer
}

// Both inputs pull on their own queues; the writer interleaves the tracks.
let group = DispatchGroup()
var frameIndex = 0
var problem: String?
group.enter()
videoInput.requestMediaDataWhenReady(on: DispatchQueue(label: "promo.video")) {
    while videoInput.isReadyForMoreMediaData {
        if frameIndex >= names.count || problem != nil {
            videoInput.markAsFinished()
            group.leave()
            return
        }
        autoreleasepool {
            let name = names[frameIndex]
            guard let image = frameIndex == 0 ? firstImage : loadImage(name),
                  image.width == width, image.height == height,
                  let buffer = pixelBuffer(for: image) else {
                problem = "cannot prepare \(name)"
                return
            }
            let time = CMTime(value: CMTimeValue(frameIndex), timescale: fps)
            if !adaptor.append(buffer, withPresentationTime: time) {
                problem = "append failed at \(name): \(writer.error?.localizedDescription ?? "unknown")"
            }
            frameIndex += 1
        }
    }
}

if let audioReader, let audioOutput, let audioInput {
    guard audioReader.startReading() else { fail("cannot read audio: \(audioReader.error?.localizedDescription ?? "unknown")") }
    let limit = CMTime(value: CMTimeValue(names.count), timescale: fps)
    group.enter()
    audioInput.requestMediaDataWhenReady(on: DispatchQueue(label: "promo.audio")) {
        while audioInput.isReadyForMoreMediaData {
            guard let sample = audioOutput.copyNextSampleBuffer(),
                  CMSampleBufferGetPresentationTimeStamp(sample) < limit,
                  audioInput.append(sample) else {
                audioInput.markAsFinished()
                group.leave()
                return
            }
        }
    }
}

group.wait()
if let problem { fail(problem) }
writer.endSession(atSourceTime: CMTime(value: CMTimeValue(names.count), timescale: fps))
let finished = DispatchSemaphore(value: 0)
writer.finishWriting { finished.signal() }
finished.wait()
guard writer.status == .completed else { fail("writer failed: \(writer.error?.localizedDescription ?? "unknown")") }
let seconds = Double(names.count) / Double(fps)
print("wrote \(outputURL.path)  \(width)x\(height)  \(names.count) frames  \(String(format: "%.2f", seconds))s @ \(fps)fps")
