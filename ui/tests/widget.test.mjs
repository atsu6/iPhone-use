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

async function harness({ reducedMotion = false, context = { displayMode: 'inline', availableDisplayModes: ['fullscreen'] }, reply } = {}) {
  let now = 0;
  let timerId = 0;
  let instance;
  let resize;
  const timers = new Map();
  const listeners = new Map();
  const calls = [];
  const lifecycle = [];
  const elements = Object.fromEntries(['app', 'screen', 'image', 'cursor'].map(id => [id, {
    style: {}, dataset: {}, hidden: id === 'screen' || id === 'cursor', clientWidth: 400, clientHeight: 800,
    removeAttribute(name) { delete this[name]; },
    animate(frames, options) {
      const animation = { frames, options, cancelled: false, cancel() { this.cancelled = true; } };
      this.animation = animation;
      return animation;
    },
  }]));
  class MockApp {
    constructor(info, capabilities, options) { Object.assign(this, { info, capabilities, options }); instance = this; }
    async connect() { lifecycle.push('connect'); }
    getHostContext() { return context; }
    async requestDisplayMode(params) { lifecycle.push(params.mode); return { mode: params.mode }; }
    callServerTool(params) {
      calls.push(params);
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
    getComputedStyle: () => ({ paddingLeft: '12px', paddingRight: '12px', paddingTop: '12px', paddingBottom: '12px' }),
    ResizeObserver: class { constructor(callback) { this.callback = callback; resize = this; } observe() {} disconnect() { this.disconnected = true; } },
    window: { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) },
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay, due: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
  });
  return {
    app: instance, calls, lifecycle, elements, document, timers, resize,
    visibility(hidden) { document.hidden = hidden; listeners.get('visibilitychange')?.(); },
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
  assert.equal([...h.timers.values()][0].delay, 200);
});

test('preserves full frame aspect ratio and maps gestures using the point viewport', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(12), viewport: { width: 400, height: 800 }, busy: true,
    events: [{ id: 1, kind: 'tap', at: 1000, point: { x: 100, y: 200 }, viewport: { width: 400, height: 800 } }] }) });
  assert.equal(h.elements.app.dataset.frameSeq, '12');
  assert.equal(h.elements.app.dataset.busy, 'true');
  assert.equal(h.elements.screen.hidden, false);
  assert.equal(h.elements.screen.style.width, '376px');
  assert.equal(h.elements.screen.style.height, '752px');
  assert.equal(h.elements.image.src, 'data:image/png;base64,test-image-only');
  assert.equal(h.elements.cursor.style.left, '25%');
  assert.equal(h.elements.cursor.style.top, '25%');
  assert.equal(h.elements.cursor.animation.options.duration, 540);
  h.app.ontoolresult({ structuredContent: preview({ events: [{ id: 2, kind: 'drag', at: 1000, from: { x: 40, y: 80 }, to: { x: 360, y: 720 }, duration_ms: 650 }] }) });
  assert.equal(h.elements.cursor.animation.frames[0].left, '10%');
  assert.equal(h.elements.cursor.animation.frames[2].top, '90%');
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

test('a reconnected server starts a new frame sequence and an unavailable stream clears stale pixels', async () => {
  const h = await harness();
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'old', frame: frame(800), frame_available: true }) });
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'new', frame: frame(1), frame_available: true }) });
  assert.equal(h.elements.app.dataset.frameSeq, '1');
  assert.equal(h.elements.screen.hidden, false);
  h.app.ontoolresult({ structuredContent: preview({ stream_id: 'new', frame_available: false }) });
  assert.equal(h.elements.screen.hidden, true);
  assert.equal(h.elements.image.src, undefined);
  assert.equal(h.elements.app.dataset.frameSeq, '0');
});

test('a broken MCP connection clears a previously visible phone frame', async () => {
  const h = await harness({ reply: async () => { throw new Error('disconnected'); } });
  h.app.ontoolresult({ structuredContent: preview({ frame: frame(19), busy: true }) });
  assert.equal(h.elements.screen.hidden, false);
  await h.tick();
  assert.equal(h.elements.screen.hidden, true);
  assert.equal(h.elements.image.src, undefined);
  assert.equal(h.elements.app.dataset.busy, 'false');
  assert.equal([...h.timers.values()][0].delay, 500);
});
