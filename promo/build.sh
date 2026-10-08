#!/bin/sh
# Build the 40-second intro film: frames (headless Chrome) -> soundtrack -> MP4.
# Needs only what the project already requires: Node.js, Google Chrome and Xcode's swiftc.
#
#   sh promo/build.sh            1920x1080, 60 fps
#   FPS=30 sh promo/build.sh     smaller file
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
fps=${FPS:-60}
work=$(mktemp -d "${TMPDIR:-/tmp}/iphone-use-promo.XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir -p "$here/out"

echo "1/3 frames"
node "$here/render.mjs" --out "$work/frames" --fps "$fps"
echo "2/3 soundtrack"
node "$here/audio.mjs" "$work/frames/meta.json" "$work/soundtrack.wav"
echo "3/3 encode"
if ! swiftc -O "$here/encode.swift" -o "$work/encode" 2>"$work/swiftc.log"; then
  cat "$work/swiftc.log" >&2
  exit 1
fi
# Encode beside the frames and copy the results over, so nothing half-written lands in out/.
"$work/encode" "$work/frames" "$fps" "$work/intro.mp4" "$work/soundtrack.wav"
"$work/encode" "$work/frames" "$fps" "$work/intro-silent.mp4"
cp "$work/intro.mp4" "$here/out/iphone-use-intro.mp4"
cp "$work/intro-silent.mp4" "$here/out/iphone-use-intro-silent.mp4"
cp "$work/soundtrack.wav" "$here/out/iphone-use-intro-soundtrack.wav"
echo "done: $here/out/iphone-use-intro.mp4"
