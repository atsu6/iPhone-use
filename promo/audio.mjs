#!/usr/bin/env node
// Synthesise the film's soundtrack: a light 120 BPM bed in D major plus interface sounds
// placed on the timeline's events. Everything is generated here, so there are no samples
// or licences to track.
//
//   node promo/audio.mjs <meta.json> <out.wav>
import { readFile, writeFile } from 'node:fs/promises';

const [metaPath, outPath] = process.argv.slice(2);
if (!metaPath || !outPath) {
  console.error('usage: node audio.mjs <meta.json> <out.wav>');
  process.exit(1);
}
const meta = JSON.parse(await readFile(metaPath, 'utf8'));
const RATE = 48000;
const DURATION = meta.duration;
const LENGTH = Math.round(RATE * DURATION);
const TAU = Math.PI * 2;

// Buses: dry mix, a reverb send, and a tempo-delay send for the plucked voice.
const bus = () => [new Float32Array(LENGTH), new Float32Array(LENGTH)];
const dry = bus();
const room = bus();
const echo = bus();
const pump = new Float32Array(LENGTH).fill(1);
// Relative levels of the parts. Small speakers carry little below 150 Hz, so the bed leans
// on the mallets and pad rather than on kick and bass.
const MIX = { kick: .3, bass: .14, pad: .05, mallet: .16, hat: .06, clap: .13, cues: 1.8 };
let trim = 1;

let seed = 0x1f2e3d4c;
const random = () => {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
  return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
};

const note = (name) => {
  const [, letter, sharp, octave] = name.match(/^([A-G])(#?)(\d)$/);
  const semitone = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[letter] + (sharp ? 1 : 0);
  return 440 * 2 ** ((semitone - 9) / 12 + Number(octave) - 4);
};

function write(index, left, right, send = 0, tap = 0) {
  if (index < 0 || index >= LENGTH) return;
  left *= trim;
  right *= trim;
  dry[0][index] += left;
  dry[1][index] += right;
  if (send) { room[0][index] += left * send; room[1][index] += right * send; }
  if (tap) { echo[0][index] += left * tap; echo[1][index] += right * tap; }
}
const panned = (pan) => [Math.cos((pan + 1) * Math.PI / 4), Math.sin((pan + 1) * Math.PI / 4)];

// A pitched voice built from a few sine partials: [frequency multiple, level, decay scale].
function tone(at, frequency, {
  length = .5, attack = .003, decay = .2, gain = .2, pan = 0, send = 0, tap = 0,
  partials = [[1, 1, 1]], glide = null, release = .02,
} = {}) {
  const start = Math.round(at * RATE);
  const count = Math.round(length * RATE);
  const [left, right] = panned(pan);
  const phases = partials.map(() => 0);
  for (let offset = 0; offset < count; offset++) {
    const time = offset / RATE;
    const pitch = glide ? frequency * (glide.to / frequency) ** Math.min(1, time / glide.time) : frequency;
    const fade = Math.min(1, (length - time) / release);
    const rise = 1 - Math.exp(-time / attack);
    let sample = 0;
    for (let index = 0; index < partials.length; index++) {
      const [multiple, level, scale] = partials[index];
      if (pitch * multiple > RATE * .45) continue;
      phases[index] += TAU * pitch * multiple / RATE;
      sample += Math.sin(phases[index]) * level * Math.exp(-time / (decay * scale));
    }
    sample *= gain * rise * fade;
    write(start + offset, sample * left, sample * right, send, tap);
  }
}

// Filtered noise: a swept band-pass (state-variable) for swishes, hats, claps and risers.
function noise(at, {
  length = .2, gain = .1, pan = 0, send = 0, from = 2000, to = from, q = 1.2,
  attack = .004, decay = .08, swell = false, high = false,
} = {}) {
  const start = Math.round(at * RATE);
  const count = Math.round(length * RATE);
  const [left, right] = panned(pan);
  let low = 0;
  let band = 0;
  for (let offset = 0; offset < count; offset++) {
    const time = offset / RATE;
    const progress = offset / count;
    const centre = from * (to / from) ** progress;
    const tune = 2 * Math.sin(Math.PI * Math.min(centre, RATE / 6.5) / RATE);
    const input = random() * 2 - 1;
    const top = input - low - band / q;
    band += tune * top;
    low += tune * band;
    const shape = swell
      ? Math.sin(Math.PI * progress) ** 2 * (progress < .7 ? progress / .7 : 1)
      : (1 - Math.exp(-time / attack)) * Math.exp(-time / decay);
    const edge = Math.min(1, (length - time) / .01);
    const sample = (high ? top : band) * gain * shape * edge;
    write(start + offset, sample * left, sample * right, send);
  }
}

// ───────── the bed ─────────
const BEAT = .5;
const chords = {
  D: { pad: ['D3', 'A3', 'E4', 'F#4'], arp: ['D4', 'F#4', 'A4', 'E5', 'F#5', 'A5'], bass: 'D2' },
  Bm: { pad: ['B2', 'F#3', 'A3', 'D4'], arp: ['B3', 'D4', 'F#4', 'A4', 'D5', 'F#5'], bass: 'B1' },
  G: { pad: ['G3', 'B3', 'D4', 'F#4'], arp: ['B3', 'D4', 'G4', 'B4', 'D5', 'F#5'], bass: 'G2' },
  A: { pad: ['A3', 'C#4', 'E4', 'F#4'], arp: ['A3', 'C#4', 'E4', 'A4', 'C#5', 'E5'], bass: 'A2' },
};
// [start, length, chord] in seconds. Scene starts land on D where they can.
const harmony = [
  [0, 2, 'D'], [2, 2, 'D'], [4, 1, 'G'], [5, 1, 'A'], [6, 2, 'D'], [8, 2, 'A'],
  [10, 2, 'D'], [12, 2, 'Bm'], [14, 2, 'G'], [16, 2, 'A'], [18, 2, 'D'], [20, 2, 'Bm'],
  [22, 2, 'G'], [24, 2, 'D'], [26, 2, 'Bm'], [28, 2, 'G'], [30, 2, 'A'], [32, 2, 'D'],
  [34, 1, 'G'], [35, 1, 'A'], [36, 4, 'D'],
];
const chordAt = (time) => chords[harmony.findLast(([start]) => start <= time + 1e-6)[2]];
const FULL = [10, 27.5];        // drums at full strength
const HUSH = [28.3, 30.04];     // preview paused: the groove drops out
const LIFT = [32, 36];          // tools burst, into the lockup
const within = (time, [from, to]) => time >= from - 1e-6 && time < to - 1e-6;

// Kick, and the gentle duck it puts on the pad and bass.
function kick(at, gain = 1) {
  const start = Math.round(at * RATE);
  let phase = 0;
  for (let offset = 0; offset < RATE * .32; offset++) {
    const time = offset / RATE;
    phase += TAU * (46 + 118 * Math.exp(-time / .028)) / RATE;
    const body = Math.sin(phase) * Math.exp(-time / .13) * Math.min(1, time / .0015);
    const click = (random() * 2 - 1) * Math.exp(-time / .0016) * .16;
    const sample = (body + click) * MIX.kick * gain * Math.min(1, (.32 - time) / .02);
    write(start + offset, sample, sample);
  }
  for (let offset = 0; offset < RATE * .3; offset++) {
    const index = start + offset;
    if (index >= LENGTH) break;
    const seconds = offset / RATE;
    const duck = 1 - .4 * gain * Math.min(1, seconds / .006) * Math.exp(-seconds / .09);
    pump[index] = Math.min(pump[index], duck);
  }
}
for (let time = 6; time < 36 - 1e-6; time += BEAT) {
  if (within(time, [27.5, 30])) continue;
  const strength = within(time, FULL) || within(time, LIFT) ? 1 : (time < 10 ? .62 : .78);
  kick(time, strength);
}
kick(36, 1.1);

// Pad: soft stacked partials with a slow swell, cross-fading from chord to chord.
for (const [start, length, name] of harmony) {
  const last = start + length >= DURATION - .01;
  for (const [voice, pitch] of chords[name].pad.entries()) {
    const frequency = note(pitch);
    const begin = Math.round(Math.max(0, start - .25) * RATE);
    const total = Math.round((length + (last ? 0 : .9)) * RATE);
    const detune = [1 - .0016, 1 + .0016];
    const phase = [[0, 0, 0, 0], [0, 0, 0, 0]];
    for (let offset = 0; offset < total; offset++) {
      const index = begin + offset;
      if (index >= LENGTH) break;
      const time = offset / RATE;
      const swell = Math.min(1, time / .55) ** 1.5;
      const tail = Math.min(1, Math.max(0, (total / RATE - time) / 1.1)) ** 1.5;
      const clock = index / RATE;
      const level = (clock < 2 ? .35 + .65 * clock / 2 : 1) * (within(clock, HUSH) ? 1.25 : 1);
      const amount = MIX.pad * swell * tail * level * (.72 + .28 * pump[index]);
      for (let side = 0; side < 2; side++) {
        let sample = 0;
        for (let harmonic = 0; harmonic < 4; harmonic++) {
          phase[side][harmonic] += TAU * frequency * detune[side] * (harmonic + 1) / RATE;
          sample += Math.sin(phase[side][harmonic] + voice) / (harmonic + 1) ** 1.55;
        }
        dry[side][index] += sample * amount;
        room[side][index] += sample * amount * .5;
      }
    }
  }
}

// Clap on two and four, closed hats on the off-beats.
for (let time = 10; time < 36 - 1e-6; time += BEAT) {
  if (within(time, [27.5, 32])) continue;
  const beat = Math.round(time / BEAT) % 4;
  if (beat === 1 || beat === 3) {
    for (const [delay, level] of [[0, .5], [.011, .7], [.023, 1]]) {
      noise(time + delay, { length: .16, gain: MIX.clap * level, from: 1500, to: 1300, q: 1.6, attack: .001, decay: .05, send: .35, pan: -.06 });
    }
  }
}
for (let time = 10.25; time < 36 - 1e-6; time += BEAT) {
  if (within(time, [27.5, 32])) continue;
  const open = within(time, LIFT) && Math.round((time - .25) / BEAT) % 2 === 1;
  noise(time, { length: open ? .16 : .06, gain: MIX.hat * (.8 + .4 * random()) * (within(time, LIFT) ? 1.2 : 1), from: 9000, q: .9, attack: .0008, decay: open ? .05 : .018, high: true, pan: .14 });
}

// Bass: round sine with a touch of second harmonic, pushed along in eighths.
const bassLine = [1, 0, .7, .8, 0, .7, .85, .6];
for (let step = 0; step < (36 - 6) / .25; step++) {
  const time = 6 + step * .25;
  if (within(time, [27.5, 30])) continue;
  const level = bassLine[step % 8];
  if (!level) continue;
  const frequency = note(chordAt(time).bass) * (step % 8 === 3 ? 2 : 1);
  const start = Math.round(time * RATE);
  let phase = 0;
  for (let offset = 0; offset < RATE * .24; offset++) {
    const seconds = offset / RATE;
    phase += TAU * frequency / RATE;
    const envelope = Math.min(1, seconds / .006) * Math.exp(-seconds / .2) * Math.min(1, (.24 - seconds) / .02);
    const index = start + offset;
    if (index >= LENGTH) break;
    const sample = (Math.sin(phase) + .5 * Math.sin(phase * 2) + .24 * Math.sin(phase * 3) + .1 * Math.sin(phase * 4)) * MIX.bass * level * envelope * (.45 + .55 * pump[index]);
    write(index, sample, sample);
  }
}
for (const [time, length, name] of [[28, 2, 'G'], [36, 3.6, 'D']]) {
  tone(time, note(chords[name].bass), { length, attack: .05, decay: length * .7, gain: MIX.bass, partials: [[1, 1, 1], [2, .45, .8], [3, .2, .6]], release: .4 });
}

// Plucked arpeggio: a mallet-like voice with a ping-pong echo.
const mallet = [[1, 1, 1], [2, .36, .6], [4, .3, .26], [6.3, .08, .12]];
const figures = [[0, 2, 3, 2, 4, 2, 3, 5], [0, 3, 2, 4, 3, 5, 4, 2]];
for (let step = 0; step < (36 - 2.5) / .25; step++) {
  const time = 2.5 + step * .25;
  const bar = Math.floor(time / 2);
  const slot = Math.round((time - bar * 2) / .25) % 8;
  if (within(time, HUSH) && slot % 2 === 1) continue;
  if (time < 6 && slot % 2 === 1 && slot !== 7) continue;
  const tones = chordAt(time).arp;
  const pitch = note(tones[figures[bar % 2][slot]]);
  const accent = slot % 4 === 0 ? 1 : (slot % 2 === 0 ? .8 : .62);
  const section = time < 6 ? .6 : within(time, HUSH) ? .55 : within(time, LIFT) ? 1.1 : 1;
  tone(time, pitch, { length: .9, decay: .21, gain: MIX.mallet * accent * section, pan: [-.32, .32, .32, -.32, .32, -.32, -.32, .32][slot], send: .35, tap: .5, partials: mallet });
  if (within(time, LIFT) && slot % 2 === 0) tone(time, pitch * 2, { length: .6, decay: .12, gain: MIX.mallet * .36, pan: slot % 4 ? -.5 : .5, send: .5, tap: .4, partials: mallet });
}
// A rising run into the lockup, then the closing chord.
['A4', 'C#5', 'E5', 'A5', 'C#6', 'E6'].forEach((pitch, index) => {
  tone(35.25 + index * .125, note(pitch), { length: .7, decay: .16, gain: MIX.mallet * (.7 + index * .08), pan: -.5 + index * .2, send: .5, tap: .35, partials: mallet });
});
['D3', 'A3', 'D4', 'F#4', 'A4', 'E5', 'F#5', 'D6'].forEach((pitch, index) => {
  tone(36 + index * .012, note(pitch), { length: 3.6, decay: 1.05, gain: MIX.mallet * .9, pan: -.6 + index * .17, send: .7, tap: .25, partials: mallet, release: .3 });
});
noise(36, { length: 2.6, gain: .022, from: 6800, to: 4200, q: .8, attack: .004, decay: .7, send: .3, high: true });

// Lifts into the bigger scene changes.
for (const [at, length, gain] of [[9.3, .7, .09], [31.1, .9, .11], [35.1, .9, .13]]) {
  noise(at, { length, gain, from: 500, to: 6500, q: 1.1, swell: true, send: .4 });
}

// ───────── interface sounds, one per timeline event ─────────
const bell = [[1, 1, 1], [2.76, .32, .5], [5.4, .12, .25]];
const soft = [[1, 1, 1], [2, .2, .6]];
const scale = ['D5', 'E5', 'F#5', 'A5', 'B5', 'D6', 'E6', 'F#6', 'A6'];
let rowStep = 0;
let lastRow = -10;
const sounds = {
  pop: (at, { step = 0 }) => tone(at, note(['A5', 'D6', 'F#6'][step % 3]) * .5, { length: .22, decay: .07, gain: .16, glide: { to: note(['A5', 'D6', 'F#6'][step % 3]), time: .05 }, send: .4, partials: soft }),
  rise: (at) => { noise(at, { length: .6, gain: .04, from: 700, to: 5200, q: 1, swell: true, send: .5 }); tone(at, note('D5'), { length: .5, decay: .3, gain: .05, glide: { to: note('A5'), time: .4 }, send: .5, partials: soft }); },
  whoosh: (at) => noise(at, { length: .45, gain: .05, from: 900, to: 3600, q: .9, swell: true, send: .35 }),
  link: (at) => ['D5', 'F#5', 'A5'].forEach((pitch, index) => tone(at + index * .25, note(pitch), { length: .4, decay: .11, gain: .07, pan: -.1 + index * .1, send: .6, tap: .25, partials: bell })),
  connect: (at) => { tone(at, note('A5'), { length: .5, decay: .16, gain: .13, send: .6, tap: .3, partials: bell }); tone(at + .11, note('D6'), { length: .9, decay: .28, gain: .15, send: .7, tap: .3, partials: bell }); },
  key: (at) => { const lift = .8 + random() * .4; noise(at, { length: .03, gain: .028 * lift, from: 3200 + random() * 1200, q: 2, attack: .0006, decay: .007, pan: random() * .5 - .25 }); },
  type: (at) => { const lift = .8 + random() * .4; noise(at, { length: .03, gain: .034 * lift, from: 2300 + random() * 700, q: 2.4, attack: .0006, decay: .008, pan: .45 }); tone(at, 1250 + random() * 240, { length: .03, decay: .008, gain: .012 * lift, pan: .45 }); },
  send: (at) => tone(at, 330, { length: .16, decay: .06, gain: .13, glide: { to: 660, time: .07 }, send: .3, partials: soft }),
  check: (at) => { tone(at, note('F#6'), { length: .32, decay: .09, gain: .085, send: .5, pan: -.25, partials: bell }); tone(at + .055, note('A6'), { length: .4, decay: .11, gain: .07, send: .5, pan: -.25, partials: bell }); },
  open: (at) => { noise(at, { length: .4, gain: .04, from: 600, to: 3200, q: 1, swell: true, pan: .45, send: .4 }); tone(at + .02, 150, { length: .22, decay: .07, gain: .12, glide: { to: 240, time: .12 }, pan: .45, partials: soft }); },
  swipe: (at) => noise(at, { length: .5, gain: .045, from: 2600, to: 900, q: 1.1, swell: true, pan: .45, send: .25 }),
  tap: (at) => { tone(at, 880, { length: .07, decay: .018, gain: .1, glide: { to: 620, time: .03 }, pan: .45, send: .2 }); noise(at, { length: .02, gain: .04, from: 2600, q: 2, attack: .0005, decay: .005, pan: .45 }); },
  scan: (at) => noise(at, { length: .9, gain: .035, from: 1400, to: 7200, q: 2.2, swell: true, pan: .45, send: .5 }),
  blip: (at) => tone(at, note('A6') * (1 + random() * .12), { length: .07, decay: .02, gain: .04, pan: .45, send: .4 }),
  thud: (at) => tone(at, 140, { length: .25, decay: .07, gain: .2, glide: { to: 78, time: .1 }, pan: .4, partials: soft }),
  error: (at) => { tone(at, note('F#4'), { length: .16, decay: .07, gain: .1, pan: -.3, send: .3, partials: [[1, 1, 1], [2, .3, .7], [3, .16, .5]] }); tone(at + .13, note('C4'), { length: .26, decay: .1, gain: .1, pan: -.3, send: .3, partials: [[1, 1, 1], [2, .3, .7], [3, .16, .5]] }); },
  shutter: (at) => { for (const delay of [0, .07]) noise(at + delay, { length: .05, gain: .11, from: 3600, q: 1.1, attack: .0006, decay: .012, pan: .45, send: .25 }); },
  lock: (at) => { tone(at, note('E6'), { length: .09, decay: .03, gain: .06, pan: -.2, send: .4 }); tone(at + .07, note('A6'), { length: .16, decay: .05, gain: .06, pan: -.2, send: .4 }); },
  row: (at) => { rowStep = at - lastRow > .4 ? 0 : rowStep + 1; lastRow = at; tone(at, note(scale[rowStep % scale.length]), { length: .14, decay: .04, gain: .05, pan: -.3 + (rowStep % 9) * .03, send: .45, partials: soft }); },
  pause: (at) => { tone(at, note('A5'), { length: .3, decay: .1, gain: .1, send: .6, partials: bell }); tone(at + .13, note('E5'), { length: .6, decay: .2, gain: .1, send: .7, partials: bell }); },
  click: (at) => { noise(at, { length: .025, gain: .09, from: 2400, q: 1.8, attack: .0005, decay: .006, pan: -.3 }); tone(at, 1500, { length: .03, decay: .008, gain: .03, pan: -.3 }); },
  resume: (at) => { tone(at, note('E5'), { length: .3, decay: .1, gain: .1, send: .6, partials: bell }); tone(at + .12, note('A5'), { length: .3, decay: .1, gain: .1, send: .6, partials: bell }); tone(at + .24, note('D6'), { length: .8, decay: .26, gain: .11, send: .7, tap: .3, partials: bell }); },
  burst: (at) => { noise(at, { length: .6, gain: .05, from: 800, to: 6000, q: 1, swell: true, send: .5 }); ['D5', 'F#5', 'A5', 'D6', 'F#6', 'A6'].forEach((pitch, index) => tone(at + index * .05, note(pitch), { length: .5, decay: .12, gain: .055, pan: -.6 + index * .24, send: .6, tap: .3, partials: bell })); },
  gather: (at) => noise(at, { length: .5, gain: .05, from: 5200, to: 700, q: 1, swell: true, send: .4 }),
  logo: (at) => noise(at, { length: .5, gain: .035, from: 1200, to: 6800, q: 1.2, swell: true, send: .5 }),
};
trim = MIX.cues;
for (const event of meta.sfx) {
  const play = sounds[event.name];
  if (!play) throw new Error(`no sound defined for "${event.name}"`);
  play(event.t, event);
}
trim = 1;

// ───────── tempo echo, room, and the master ─────────
{
  const delay = Math.round(.375 * RATE);
  const line = [new Float32Array(LENGTH), new Float32Array(LENGTH)];
  const state = [0, 0];
  for (let index = 0; index < LENGTH; index++) {
    for (let side = 0; side < 2; side++) {
      const fed = index >= delay ? line[1 - side][index - delay] : 0;
      state[side] += .42 * (fed - state[side]);
      line[side][index] = echo[side][index] + state[side] * .36;
      const wet = index >= delay ? line[side][index - delay] : 0;
      dry[side][index] += wet * .5;
      room[side][index] += wet * .25;
    }
  }
}
{
  const combs = [1557, 1617, 1491, 1422, 1277, 1356];
  const passes = [225, 556, 441, 341];
  for (let side = 0; side < 2; side++) {
    const spread = side * 23;
    const lines = combs.map((size) => ({ buffer: new Float32Array(size + spread), index: 0, store: 0 }));
    const filters = passes.map((size) => ({ buffer: new Float32Array(size + spread), index: 0 }));
    const input = room[side];
    for (let index = 0; index < LENGTH; index++) {
      let sum = 0;
      for (const line of lines) {
        const out = line.buffer[line.index];
        line.store = out * .72 + line.store * .28;
        line.buffer[line.index] = input[index] * .09 + line.store * .8;
        line.index = (line.index + 1) % line.buffer.length;
        sum += out;
      }
      for (const filter of filters) {
        const held = filter.buffer[filter.index];
        const out = held - sum;
        filter.buffer[filter.index] = sum + held * .5;
        filter.index = (filter.index + 1) % filter.buffer.length;
        sum = out;
      }
      dry[side][index] += sum * .42;
    }
  }
}

let peak = 0;
for (let side = 0; side < 2; side++) {
  let previousIn = 0;
  let previousOut = 0;
  for (let index = 0; index < LENGTH; index++) {
    // 25 Hz high-pass removes any offset, then a soft knee keeps peaks polite.
    const input = dry[side][index];
    const output = input - previousIn + .9967 * previousOut;
    previousIn = input;
    previousOut = output;
    const time = index / RATE;
    const fade = Math.min(1, time / .02) * (time > DURATION - 1.6 ? Math.cos((time - (DURATION - 1.6)) / 1.6 * Math.PI / 2) ** 2 : 1);
    dry[side][index] = Math.tanh(output * 1.25) * fade;
    peak = Math.max(peak, Math.abs(dry[side][index]));
  }
}
// Level the two sides (the detuned pad drifts a little), then bring the peak to -1 dBFS.
const power = dry.map((side) => side.reduce((sum, value) => sum + value * value, 0));
const balance = [Math.min(1, Math.sqrt(power[1] / power[0])), Math.min(1, Math.sqrt(power[0] / power[1]))];
const scaleTo = .89 / peak;
let energy = 0;
const pcm = Buffer.alloc(44 + LENGTH * 4);
pcm.write('RIFF', 0);
pcm.writeUInt32LE(36 + LENGTH * 4, 4);
pcm.write('WAVEfmt ', 8);
pcm.writeUInt32LE(16, 16);
pcm.writeUInt16LE(1, 20);
pcm.writeUInt16LE(2, 22);
pcm.writeUInt32LE(RATE, 24);
pcm.writeUInt32LE(RATE * 4, 28);
pcm.writeUInt16LE(4, 32);
pcm.writeUInt16LE(16, 34);
pcm.write('data', 36);
pcm.writeUInt32LE(LENGTH * 4, 40);
for (let index = 0; index < LENGTH; index++) {
  for (let side = 0; side < 2; side++) {
    const value = dry[side][index] * scaleTo * balance[side];
    energy += value * value;
    const dither = (random() - random()) / 32768;
    pcm.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round((value + dither) * 32767))), 44 + index * 4 + side * 2);
  }
}
await writeFile(outPath, pcm);
const rms = 10 * Math.log10(energy / (LENGTH * 2));
console.log(`wrote ${outPath}  ${DURATION}s  peak -1.0 dBFS  rms ${rms.toFixed(1)} dBFS  ${meta.sfx.length} cues`);
