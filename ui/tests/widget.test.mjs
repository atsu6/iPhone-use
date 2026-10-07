import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { transform } from 'esbuild';

const source = await readFile(new URL('../src/app.ts', import.meta.url), 'utf8');
const { code } = await transform(`(async () => {
${source.replace("import { App } from '@modelcontextprotocol/ext-apps';", 'const App = globalThis.MockApp;')}
})()`, { loader: 'ts', target: 'es2022' });

const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const preview = (fields = {}) => ({ server_time: 1000, frame: null, viewport: null, busy: false, paused: false, events: [], ...fields });
// Fixtures exist only in this isolated DOM test, never in the shipped widget.
const frame = (seq = 1) => ({ seq, data: 'test-image-only', mimeType: 'image/png', width: 900, height: 1800 });

async function harness({ reducedMotion = false, context = { displayMode: 'inline', availableDisplayModes: ['fullscreen'] }, reply, connectReply } = {}) {
  let now = 0;
  let timerId = 0;
  let instance;
  let resize;
  const timers = new Map();
  const listeners = new Map();
  const calls = [];
  const lifecycle = [];
  const requestOptions = [];
  let styleReads = 0;
  let imageWrites = 0;
  const elements = Object.fromEntries(['app', 'device', 'screen', 'image', 'cursor'].map(id => [id, {
    style: { setProperty(name, value) { this[name] = value; } }, dataset: {},
    hidden: ['device', 'screen', 'cursor'].includes(id), clientWidth: 400, clientHeight: 800,
    removeAttribute(name) { delete this[name]; },
    animate(frames, options) {
      const animation = { frames, options, cancelled: false, cancel() { this.cancelled = true; } };
      this.animation = animation;
      return animation;
    },
  }]));
  let imageSource;
  Object.defineProperty(elements.image, 'src', {
    configurable: true, get: () => imageSource, set: value => { imageSource = value; imageWrites++; },
  });
  elements.image.removeAttribute = name => { if (name === 'src') imageSource = undefined; };
  class MockApp {
    constructor(info, capabilities, options) { Object.assign(this, { info, capabilities, options }); instance = this; }
    async connect() { lifecycle.push('connect'); if (connectReply) await connectReply(); }
    async close() { this.onclose?.(); }
    getHostContext() { return context; }
    async requestDisplayMode(params) { lifecycle.push(params.mode); return { mode: params.mode }; }
    callServerTool(params, options) {
      calls.push(params);
      requestOptions.push(options);
      return reply ? reply(params) : Promise.resolve({ structuredContent: preview() });
    }
  }
  const document = {
    hidden: false,
    getElementById: id => elements[id],
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name),
  };
  await vm.runInNewContext(code, {
    MockApp, document,
    matchMedia: () => ({ matches: reducedMotion }),
    performance: { now: () => now },
    getComputedStyle: () => { styleReads++; return { paddingLeft: '12px', paddingRight: '12px', paddingTop: '12px', paddingBottom: '12px' }; },
    ResizeObserver: class { constructor(callback) { this.callback = callback; resize = this; } observe() {} disconnect() { this.disconnected = true; } },
    window: { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) },
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay, due: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
  });
  return {
    app: instance, calls, lifecycle, elements, document, timers, resize,
    requestOptions,
    get styleReads() { return styleReads; },
    get imageWrites() { return imageWrites; },
    visibility(hidden) { document.hidden = hidden; listeners.get('visibilitychange')?.(); },
    event(name, value = {}) { listeners.get(name)?.(value); },
    async tick() {
      const entry = [...timers.entries()].sort((a, b) => a[1].due - b[1].due)[0];
      if (!entry) return;
      timers.delete(entry[0]); now = entry[1].due; entry[1].fn(); await flush();
    },
  };
}

test('connects before requesting only fullscreen, then polls only the app frame tool', async () => {
  const h = await harness();
  assert.equal(h.app.capabilities.availableDisplayModes.join(','), 'fullscreen');
  assert.equal(h.app.options.autoResize, false);
  assert.equal(h.lifecycle.join(','), 'connect,fullscreen');
  await h.tick();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].name, 'wda_screen_frame');
  assert.equal(JSON.stringify(h.calls[0].arguments), '{"after_seq":0,"last_event_id":0}');
  assert.equal([...h.timers.values()][0].delay, 250);
  assert.equal(h.requestOptions[0].timeout, 3000);
});

test('preserves full frame aspect ratio and maps gestures using the point viewport', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(12), viewport: { width: 400, height: 800 }, busy: true,
    events: [{ id: 1, kind: 'tap', at: 1000, point: { x: 100, y: 200 }, viewport: { width: 400, height: 800 } }] }) });
  assert.equal(h.elements.app.dataset.frameSeq, '12');
  assert.equal(h.elements.app.dataset.busy, 'true');
  assert.equal(h.elements.device.hidden, false);
  assert.equal(h.elements.screen.hidden, false);
  const bezel = parseFloat(h.elements.device.style['--bezel']);
  const width = parseFloat(h.elements.device.style.width);
  const height = parseFloat(h.elements.device.style.height);
  assert.ok(Math.abs(width - 360.96) < 1e-8);
  assert.ok(Math.abs((width - 2 * bezel) / (height - 2 * bezel) - .5) < 1e-8);
  assert.ok(height <= 776);
  assert.equal(h.elements.device.dataset.orientation, 'portrait');
  assert.equal(h.elements.image.src, 'data:image/png;base64,test-image-only');
  assert.equal(h.elements.cursor.style.left, '25%');
  assert.equal(h.elements.cursor.style.top, '25%');
  assert.equal(h.elements.cursor.animation.options.duration, 540);
  h.app.ontoolresult({ structuredContent: preview({ events: [{ id: 2, kind: 'drag', at: 1000, from: { x: 40, y: 80 }, to: { x: 360, y: 720 }, duration_ms: 650 }] }) });
  assert.equal(h.elements.cursor.style.left, '10%');
  assert.equal(h.elements.cursor.animation.frames[2].transform, 'translate(320px, 640px) scale(1)');
  assert.equal(h.elements.cursor.animation.options.duration, 650);
});

test('omitted frames preserve the displayed image and acknowledgements advance once', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(7), viewport: { width: 400, height: 800 },
    events: [{ id: 3, kind: 'tap', at: 1000, point: { x: 100, y: 200 } }] }) });
  const animation = h.elements.cursor.animation;
  h.app.ontoolresult({ structuredContent: preview({ events: [{ id: 3, kind: 'tap', at: 1000, point: { x: 200, y: 400 } }] }) });
  assert.equal(h.elements.cursor.animation, animation);
  assert.equal(h.elements.image.src, 'data:image/png;base64,test-image-only');
  await h.tick();
  assert.equal(JSON.stringify(h.calls[0].arguments), '{"after_seq":7,"last_event_id":3}');
});

test('operation glow survives tool gaps, hidden panels and temporary missing frames', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'one', frame: frame(), frame_available: true }) });
  assert.equal(h.elements.app.dataset.operating, 'false');
  h.app.ontoolresult({ structuredContent: preview({ busy: true }) });
  for (let i = 0; i < 50; i++) h.app.ontoolresult({ structuredContent: preview({ busy: false }) });
  assert.equal(h.elements.app.dataset.busy, 'false');
  assert.equal(h.elements.app.dataset.operating, 'true');
  h.visibility(true);
  h.visibility(false);
  assert.equal(h.elements.app.dataset.operating, 'true');
  h.app.ontoolresult({ structuredContent: preview({ frame_available: false }) });
  assert.equal(h.elements.device.hidden, false);
  assert.equal(h.elements.app.dataset.operating, 'true');
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(2), frame_available: true }) });
  assert.equal(h.elements.device.hidden, false);
  assert.equal(h.elements.app.dataset.operating, 'true');
  h.app.ontoolresult({ structuredContent: preview({ paused: true }) });
  assert.equal(h.elements.app.dataset.operating, 'false');
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(3), busy: false }) });
  assert.equal(h.elements.app.dataset.operating, 'false');
  h.app.ontoolresult({ structuredContent: preview({ busy: true }) });
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'two', frame: frame(), busy: false }) });
  assert.equal(h.elements.app.dataset.operating, 'false');
});

test('fits the entire chassis in narrow and landscape panels while preserving image coordinates', async () => {
  const h = await harness();
  let seq = 0;
  for (const [panelWidth, panelHeight, imageWidth, imageHeight] of [[170, 450, 440, 956], [900, 270, 956, 440], [310, 140, 440, 956]]) {
    h.elements.app.clientWidth = panelWidth;
    h.elements.app.clientHeight = panelHeight;
    h.app.ontoolresult({ structuredContent: preview({ frame: { ...frame(++seq), width: imageWidth, height: imageHeight } }) });
    h.resize.callback();
    const bezel = parseFloat(h.elements.device.style['--bezel']);
    const width = parseFloat(h.elements.device.style.width);
    const height = parseFloat(h.elements.device.style.height);
    assert.ok(width <= .96 * (panelWidth - 24) + 1e-8);
    assert.ok(height <= .96 * (panelHeight - 24) + 1e-8);
    assert.ok(Math.abs((width - 2 * bezel) / (height - 2 * bezel) - imageWidth / imageHeight) < 1e-8);
    assert.equal(h.elements.device.dataset.orientation, imageWidth > imageHeight ? 'landscape' : 'portrait');
    assert.equal(h.elements.screen.style.width, undefined);
    assert.equal(h.elements.screen.style.height, undefined);
  }
});

test('a hidden panel stops polling, and slow calls never overlap', async () => {
  let resolve;
  const h = await harness({ reply: () => new Promise(done => { resolve = done; }) });
  await h.tick();
  assert.equal(h.calls.length, 1);
  h.app.ontoolresult({ structuredContent: preview() });
  await h.tick();
  assert.equal(h.calls.length, 1);
  h.visibility(true);
  resolve({ structuredContent: preview({ frame: frame(1) }) });
  await flush();
  assert.equal(h.timers.size, 0);
  assert.equal(h.elements.screen.hidden, true);
  h.visibility(false);
  await h.tick();
  assert.equal(h.calls.length, 2);
});

test('paused clears the screen, errors back off silently, teardown cancels work', async () => {
  const h = await harness({ reply: async () => ({ isError: true }) });
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(4), busy: true }) });
  h.app.ontoolresult({ structuredContent: preview({ paused: true }) });
  assert.equal(h.elements.screen.hidden, true);
  assert.equal(h.elements.image.src, undefined);
  assert.equal(h.elements.app.dataset.busy, 'false');
  assert.equal(h.elements.device.hidden, true);
  assert.equal(h.elements.app.dataset.operating, 'false');
  await h.tick();
  assert.equal([...h.timers.values()][0].delay, 500);
  await h.tick();
  assert.equal([...h.timers.values()][0].delay, 1000);
  await h.tick(); await h.tick(); await h.tick();
  assert.equal([...h.timers.values()][0].delay, 2000);
  await h.app.onteardown();
  assert.equal(h.timers.size, 0);
  assert.equal(h.resize.disconnected, true);
  assert.equal(h.elements.screen.hidden, true);
});

test('reduced motion shows a stationary cursor and old gestures are not replayed', async () => {
  const h = await harness({ reducedMotion: true, context: { displayMode: 'fullscreen', availableDisplayModes: ['fullscreen'] } });
  assert.equal(h.lifecycle.join(','), 'connect');
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(2), viewport: { width: 400, height: 800 },
    events: [{ id: 1, kind: 'drag', at: 1000, from: { x: 40, y: 80 }, to: { x: 360, y: 720 }, duration_ms: 900 }] }) });
  assert.equal(h.elements.cursor.style.left, '90%');
  assert.equal(h.elements.cursor.animation, undefined);
  h.app.ontoolresult({ structuredContent: preview({ server_time: 10000, events: [{ id: 2, kind: 'tap', at: 1000, point: { x: 200, y: 400 } }] }) });
  assert.equal(h.elements.cursor.style.left, '90%');
});

test('a reconnected server restarts acknowledgements and unavailable streams retain the last pixels', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'old', frame: frame(800), frame_available: true }) });
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'new', frame_available: false }) });
  assert.equal(h.elements.screen.hidden, false);
  await h.tick();
  assert.equal(h.calls[0].arguments.after_seq, 0);
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'new', frame: frame(1), frame_available: true }) });
  assert.equal(h.elements.app.dataset.frameSeq, '1');
  assert.equal(h.elements.screen.hidden, false);
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'new', frame_available: false }) });
  assert.equal(h.elements.screen.hidden, false);
  assert.equal(h.elements.image.src, 'data:image/png;base64,test-image-only');
  assert.equal(h.elements.app.dataset.frameSeq, '1');
});

test('failed frame calls retain the previously visible image and back off', async () => {
  const h = await harness({ reply: async () => { throw new Error('disconnected'); } });
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(19), busy: true }) });
  assert.equal(h.elements.screen.hidden, false);
  await h.tick();
  assert.equal(h.elements.screen.hidden, false);
  assert.equal(h.elements.image.src, 'data:image/png;base64,test-image-only');
  assert.equal(h.elements.app.dataset.busy, 'false');
  assert.equal(h.elements.app.dataset.operating, 'true');
  assert.equal([...h.timers.values()][0].delay, 500);
});

test('page-cache suspension retains pixels, stops work, and resumes on pageshow', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(9), busy: true }) });
  h.event('pagehide', { persisted: true });
  assert.equal(h.elements.app.dataset.pageVisible, 'false');
  assert.equal(h.elements.screen.hidden, false);
  assert.equal(h.timers.size, 0);
  h.event('pageshow', { persisted: true });
  assert.equal(h.elements.app.dataset.pageVisible, 'true');
  await h.tick();
  assert.equal(h.calls[0].arguments.after_seq, 9);
  h.event('pagehide', { persisted: false });
  assert.equal(h.elements.screen.hidden, false);
  assert.equal(h.timers.size, 0);
  h.event('focus');
  await h.tick();
  assert.equal(h.calls.length, 2);
  h.event('pagehide', { persisted: false });
  h.visibility(true);
  h.visibility(false);
  await h.tick();
  assert.equal(h.calls.length, 3);
  await h.app.onteardown();
  assert.equal(h.elements.screen.hidden, true);
});

test('transport close retains pixels and reconnects without another fullscreen request', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(8) }) });
  h.app.onclose();
  assert.equal(h.elements.screen.hidden, false);
  await h.tick();
  assert.equal(h.lifecycle.join(','), 'connect,fullscreen,connect');
  assert.equal(h.calls[0].arguments.after_seq, 8);
  await h.app.onteardown();
  h.app.onclose();
  assert.equal(h.timers.size, 0);
});

test('an initial host handshake failure retries instead of permanently disposing the view', async () => {
  let connects = 0;
  const h = await harness({ connectReply: async () => { if (++connects === 1) throw Error('host asleep'); } });
  assert.equal(h.calls.length, 0);
  assert.equal([...h.timers.values()][0].delay, 1000);
  await h.tick();
  assert.equal(connects, 2);
  assert.equal(h.calls.length, 1);
  assert.notEqual(h.resize.disconnected, true);
});

test('same-size frames avoid repeated layout reads and duplicate sequences avoid image writes', async () => {
  const h = await harness();
  for (let seq = 1; seq <= 30; seq++) h.app.ontoolresult({ structuredContent: preview({ frame: frame(seq) }) });
  assert.equal(h.styleReads, 1);
  assert.equal(h.imageWrites, 30);
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(30) }) });
  assert.equal(h.imageWrites, 30);
  h.resize.callback();
  assert.equal(h.styleReads, 2);
});

test('decode failure restores the last loaded image, while authentication pause erases its backup', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(6) }) });
  h.elements.image.onload();
  const previous = h.elements.image.src;
  h.app.ontoolresult({ structuredContent: preview({ frame: { ...frame(7), data: 'broken-fixture', width: 1800, height: 900 } }) });
  h.elements.image.onerror();
  assert.equal(h.elements.image.src, previous);
  assert.equal(h.elements.device.dataset.orientation, 'portrait');
  await h.tick();
  assert.equal(h.calls[0].arguments.after_seq, 0);
  h.app.ontoolresult({ structuredContent: preview({ paused: true }) });
  h.elements.image.onerror();
  assert.equal(h.elements.image.src, undefined);
  assert.equal(h.elements.screen.hidden, true);
});

test('unavailable and paused previews poll slowly, and focus wakes recovery immediately', async () => {
  const h = await harness({ reply: async () => ({ structuredContent: preview({ frame_available: false }) }) });
  await h.tick();
  assert.equal([...h.timers.values()][0].delay, 1000);
  h.event('focus');
  assert.equal([...h.timers.values()][0].delay, 0);
  await h.tick();
  h.visibility(true);
  assert.equal(h.elements.app.dataset.pageVisible, 'false');
  assert.equal(h.timers.size, 0);
});

test('a frame requested before authentication pause cannot restore cleared pixels', async () => {
  let resolve;
  const h = await harness({ reply: () => new Promise(done => { resolve = done; }) });
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(4) }) });
  await h.tick();
  h.app.ontoolresult({ structuredContent: preview({ paused: true }) });
  resolve({ structuredContent: preview({ frame: frame(5), paused: false }) });
  await flush();
  assert.equal(h.elements.image.src, undefined);
  assert.equal(h.elements.screen.hidden, true);
  await h.tick();
  resolve({ structuredContent: preview({ frame: frame(6), paused: false }) });
  await flush();
  assert.equal(h.elements.screen.hidden, false);
});
