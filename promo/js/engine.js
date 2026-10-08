// A tiny timeline: every animated value is a pure function of the film time, so any
// frame can be drawn on its own (frame-by-frame capture) or played back live.
(() => {
  const clamp = (value, low = 0, high = 1) => Math.min(high, Math.max(low, value));

  function bezier(x1, y1, x2, y2) {
    const curve = (a, b, u) => 3 * a * u * (1 - u) * (1 - u) + 3 * b * u * u * (1 - u) + u * u * u;
    const slope = (a, b, u) => 3 * a * (1 - u) * (1 - 3 * u) + 3 * b * u * (2 - 3 * u) + 3 * u * u;
    return (progress) => {
      if (progress <= 0) return 0;
      if (progress >= 1) return 1;
      let u = progress;
      for (let step = 0; step < 6; step++) {
        const error = curve(x1, x2, u) - progress;
        const gradient = slope(x1, x2, u);
        if (Math.abs(error) < 1e-5 || Math.abs(gradient) < 1e-6) break;
        u = clamp(u - error / gradient);
      }
      return curve(y1, y2, u);
    };
  }

  // A damped oscillation that lands exactly on 1.
  const spring = (damping, frequency) => (progress) => {
    if (progress <= 0) return 0;
    if (progress >= 1) return 1;
    const wobble = Math.exp(-damping * progress) * Math.cos(frequency * progress);
    const residue = Math.exp(-damping) * Math.cos(frequency);
    return 1 - (wobble - residue * progress);
  };

  const ease = {
    linear: (progress) => clamp(progress),
    out: bezier(.16, 1, .3, 1),
    outSoft: bezier(.22, .8, .3, 1),
    inOut: bezier(.7, 0, .25, 1),
    in: bezier(.55, 0, .9, .3),
    move: bezier(.3, 0, .2, 1),
    pop: spring(6.2, 8.4),
    bounce: spring(5, 11.5),
  };

  const defaults = { x: 0, y: 0, xp: 0, yp: 0, s: 1, sx: 1, sy: 1, r: 0, o: 1, h: 0 };
  const transformKeys = ['x', 'y', 'xp', 'yp', 's', 'sx', 'sy', 'r'];
  const items = new Map();
  const hooks = [];
  const sounds = [];
  let sealed = false;

  const all = (target) => {
    if (typeof target === 'string') {
      const found = [...document.querySelectorAll(target)];
      if (!found.length) throw new Error(`timeline: nothing matches ${target}`);
      return found;
    }
    return Array.isArray(target) ? target : [target];
  };
  const one = (target) => all(target)[0];

  // tw('#el', { y: [40, 0], o: [0, 1] }, at, duration, easing). A bare number continues
  // from wherever the previous tween on that channel ended.
  function tw(target, props, at, duration = .6, easing = ease.out) {
    if (sealed) throw new Error('timeline is sealed');
    for (const element of all(target)) {
      let item = items.get(element);
      if (!item) items.set(element, item = { element, channels: {} });
      for (const [key, value] of Object.entries(props)) {
        const [from, to] = Array.isArray(value) ? value : [null, value];
        (item.channels[key] ||= []).push({ start: at, end: at + duration, from, to, easing });
      }
    }
  }

  const set = (target, props, at) => tw(target, props, at, 0, ease.linear);

  // hook(start, end, (progress, time) => …) runs on every frame with clamped progress.
  function hook(start, end, callback) {
    hooks.push({ start, end, callback });
  }

  const sfx = (time, name, extra = {}) => sounds.push({ t: Math.round(time * 1000) / 1000, name, ...extra });

  function seal() {
    for (const item of items.values()) {
      for (const [key, segments] of Object.entries(item.channels)) {
        segments.sort((a, b) => a.start - b.start);
        let previous = key.startsWith('--') ? 0 : defaults[key] ?? 0;
        for (const segment of segments) {
          if (segment.from === null) segment.from = previous;
          previous = segment.to;
        }
      }
      item.transforms = transformKeys.some((key) => item.channels[key]);
    }
    sounds.sort((a, b) => a.t - b.t);
    sealed = true;
  }

  function valueAt(segments, time) {
    let active = null;
    for (const segment of segments) {
      if (segment.start <= time) active = segment;
      else break;
    }
    if (!active) return segments[0].from;
    if (active.end <= active.start) return active.to;
    const progress = clamp((time - active.start) / (active.end - active.start));
    return active.from + (active.to - active.from) * active.easing(progress);
  }

  const round = (value) => Math.round(value * 1000) / 1000;

  function draw(time) {
    for (const item of items.values()) {
      const { element, channels } = item;
      const read = (key) => (channels[key] ? valueAt(channels[key], time) : defaults[key]);
      if (item.transforms) {
        element.style.transform = `translate(${round(read('x'))}px,${round(read('y'))}px) `
          + `translate(${round(read('xp'))}%,${round(read('yp'))}%) rotate(${round(read('r'))}deg) `
          + `scale(${round(read('s') * read('sx'))},${round(read('s') * read('sy'))})`;
      }
      if (channels.o) {
        const opacity = clamp(read('o'));
        element.style.opacity = round(opacity);
        element.style.visibility = opacity < .002 ? 'hidden' : 'visible';
      }
      if (channels.h) element.style.height = `${round(read('h'))}px`;
      for (const key in channels) {
        if (key.startsWith('--')) element.style.setProperty(key, round(valueAt(channels[key], time)));
      }
    }
    for (const { start, end, callback } of hooks) {
      callback(end > start ? clamp((time - start) / (end - start)) : (time >= start ? 1 : 0), time);
    }
  }

  // Wrap each character (Latin words stay whole) so a line can rise out of a clipped baseline.
  function split(target) {
    const pieces = [];
    for (const element of all(target)) {
      const walk = (node) => {
        for (const child of [...node.childNodes]) {
          if (child.nodeType === Node.ELEMENT_NODE) { walk(child); continue; }
          if (child.nodeType !== Node.TEXT_NODE) continue;
          const tokens = child.textContent.match(/[A-Za-z0-9]+|\s+|[^\sA-Za-z0-9]/gu) || [];
          const merged = [];
          for (const token of tokens) {
            if (/^[，。、？！：；,.!?]$/u.test(token) && merged.length && !/^\s+$/.test(merged.at(-1))) merged[merged.length - 1] += token;
            else merged.push(token);
          }
          const fragment = document.createDocumentFragment();
          for (const token of merged) {
            if (/^\s+$/.test(token)) { fragment.append(' '); continue; }
            const clip = document.createElement('span');
            clip.className = 'w';
            const inner = document.createElement('span');
            inner.className = 'wi';
            inner.textContent = token;
            clip.append(inner);
            fragment.append(clip);
            pieces.push(inner);
          }
          child.replaceWith(fragment);
        }
      };
      walk(element);
    }
    return pieces;
  }

  function reveal(target, at, { stagger = .032, duration = .75, easing = ease.out } = {}) {
    const pieces = split(target);
    pieces.forEach((piece, index) => tw(piece, { yp: [112, 0] }, at + index * stagger, duration, easing));
    return at + pieces.length * stagger + duration;
  }

  // Type text into an element between two times; `caret` keeps a blinking bar after it.
  function type(target, text, start, end) {
    const element = one(target);
    const glyphs = Array.from(text);
    hook(start, end, (progress) => {
      const count = Math.round(progress * glyphs.length);
      if (element.__typed === count) return;
      element.__typed = count;
      element.textContent = glyphs.slice(0, count).join('');
    });
  }

  window.TL = { tw, set, hook, sfx, seal, draw, reveal, split, type, ease, clamp, one, all, sounds };
})();
