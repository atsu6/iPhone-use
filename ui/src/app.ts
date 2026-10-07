import { App } from '@modelcontextprotocol/ext-apps';

type Size = { width: number; height: number };
type Point = { x: number; y: number };
type Frame = Size & { seq: number; data: string; mimeType: string };
type Gesture = {
  id: number;
  kind: 'tap' | 'drag';
  at: number;
  point?: Point;
  from?: Point;
  to?: Point;
  duration_ms?: number;
  viewport?: Size;
};
type Preview = {
  server_time: number;
  stream_id?: string;
  frame: Frame | null;
  frame_available?: boolean;
  viewport: Size | null;
  busy: boolean;
  paused: boolean;
  events: Gesture[];
};

const root = document.getElementById('app')!;
const device = document.getElementById('device')!;
const screen = document.getElementById('screen')!;
const image = document.getElementById('image')! as HTMLImageElement;
const cursor = document.getElementById('cursor')!;
const app = new App(
  { name: 'iPhone WDA Screen', version: '0.1.13' },
  { availableDisplayModes: ['fullscreen'] },
  { autoResize: false },
);
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let ready = false;
let disposed = false;
let inFlight = false;
let frameSeq = 0;
let streamId: string | undefined;
let eventId = 0;
let dimensions: Size | undefined;
let viewport: Size | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let failures = 0;
let animation: Animation | undefined;
let cursorTimer: ReturnType<typeof setTimeout> | undefined;
let requestedFullscreen = false;

const validSize = (value: unknown): value is Size => {
  const size = value as Size | undefined;
  return !!size && Number.isFinite(size.width) && Number.isFinite(size.height)
    && size.width > 0 && size.height > 0;
};
const validPoint = (value: unknown): value is Point => {
  const point = value as Point | undefined;
  return !!point && Number.isFinite(point.x) && Number.isFinite(point.y);
};

function hideCursor() {
  animation?.cancel();
  animation = undefined;
  if (cursorTimer) clearTimeout(cursorTimer);
  cursorTimer = undefined;
  cursor.hidden = true;
}

function clearFrame(resetOperating = true) {
  hideCursor();
  image.removeAttribute('src');
  device.hidden = true;
  screen.hidden = true;
  dimensions = undefined;
  frameSeq = 0;
  root.dataset.frameSeq = '0';
  root.dataset.busy = 'false';
  if (resetOperating) root.dataset.operating = 'false';
}

function fitFrame() {
  if (!dimensions) return;
  const style = getComputedStyle(root);
  const width = Math.max(0, root.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
  const height = Math.max(0, root.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom));
  const shortSide = Math.min(dimensions.width, dimensions.height);
  const bezel = shortSide * .024;
  const outerWidth = dimensions.width + 2 * bezel;
  const outerHeight = dimensions.height + 2 * bezel;
  const scale = .96 * Math.min(width / outerWidth, height / outerHeight);
  device.style.width = `${outerWidth * scale}px`;
  device.style.height = `${outerHeight * scale}px`;
  device.style.setProperty('--bezel', `${bezel * scale}px`);
  device.style.setProperty('--screen-radius', `${shortSide * .12 * scale}px`);
  device.dataset.orientation = dimensions.width > dimensions.height ? 'landscape' : 'portrait';
}

function pointStyle(point: Point, size: Size) {
  return {
    left: `${Math.max(0, Math.min(1, point.x / size.width)) * 100}%`,
    top: `${Math.max(0, Math.min(1, point.y / size.height)) * 100}%`,
  };
}

function showGesture(gesture: Gesture) {
  if (screen.hidden) return;
  const size = validSize(gesture.viewport) ? gesture.viewport : viewport;
  if (!size) return;
  if (dimensions && Math.abs((size.width / size.height) / (dimensions.width / dimensions.height) - 1) > .08) return;
  const point = gesture.kind === 'tap' ? gesture.point : gesture.from;
  if (!validPoint(point)) return;
  if (gesture.kind === 'drag' && !validPoint(gesture.to)) return;
  hideCursor();
  Object.assign(cursor.style, pointStyle(point, size));
  cursor.hidden = false;
  const duration = gesture.kind === 'drag'
    ? Math.max(120, Math.min(5000, gesture.duration_ms || 400))
    : 540;
  if (reducedMotion.matches) {
    if (gesture.kind === 'drag') Object.assign(cursor.style, pointStyle(gesture.to!, size));
    cursorTimer = setTimeout(hideCursor, 350);
    return;
  }
  const frames: Keyframe[] = gesture.kind === 'drag'
    ? [
      { ...pointStyle(point, size), transform: 'scale(.85)', opacity: 0 },
      { ...pointStyle(point, size), transform: 'scale(1)', opacity: 1, offset: .08 },
      { ...pointStyle(gesture.to!, size), transform: 'scale(1)', opacity: 1, offset: .86 },
      { ...pointStyle(gesture.to!, size), transform: 'scale(.9)', opacity: 0 },
    ]
    : [
      { transform: 'scale(.65)', opacity: 0 },
      { transform: 'scale(1)', opacity: 1, offset: .2 },
      { transform: 'scale(1.35)', opacity: 0 },
    ];
  animation = cursor.animate(frames, { duration, easing: gesture.kind === 'drag' ? 'linear' : 'ease-out' });
  animation.onfinish = hideCursor;
}

function consume(value: unknown) {
  if (disposed || !value || typeof value !== 'object') return;
  const preview = value as Partial<Preview>;
  if (typeof preview.stream_id === 'string' && preview.stream_id !== streamId) {
    streamId = preview.stream_id;
    clearFrame();
  }
  if (preview.paused === true) {
    clearFrame();
    return;
  }
  // A temporary frame gap does not end an operation; pause/connection resets do.
  if (preview.frame_available === false) clearFrame(false);
  if (validSize(preview.viewport)) viewport = preview.viewport;
  const frame = preview.frame;
  if (frame && validSize(frame) && Number.isInteger(frame.seq) && frame.seq >= frameSeq
      && typeof frame.data === 'string' && frame.data.length > 0
      && ['image/jpeg', 'image/png', 'image/webp'].includes(frame.mimeType)) {
    frameSeq = frame.seq;
    root.dataset.frameSeq = String(frame.seq);
    dimensions = { width: frame.width, height: frame.height };
    fitFrame();
    image.src = `data:${frame.mimeType};base64,${frame.data}`;
    device.hidden = false;
    screen.hidden = false;
  }
  if (typeof preview.busy === 'boolean') root.dataset.busy = String(preview.busy);
  // Keep the edge light on between tools and while the model plans its next action.
  if (preview.busy === true) root.dataset.operating = 'true';
  if (Array.isArray(preview.events)) {
    for (const gesture of preview.events) {
      if (!Number.isInteger(gesture.id) || gesture.id <= eventId) continue;
      eventId = gesture.id;
      const age = (preview.server_time || Date.now()) - gesture.at;
      if (Number.isFinite(age) && age >= -1000 && age <= 2500
          && (gesture.kind === 'tap' || gesture.kind === 'drag')) {
        root.dataset.operating = 'true';
        showGesture(gesture);
      }
    }
  }
}

function schedule(delay: number) {
  if (disposed || document.hidden || !ready || timer) return;
  timer = setTimeout(() => {
    timer = undefined;
    void poll();
  }, delay);
}

async function poll() {
  if (disposed || document.hidden || !ready || inFlight) return;
  inFlight = true;
  const started = performance.now();
  let nextDelay = 200;
  try {
    const result = await app.callServerTool({
      name: 'wda_screen_frame',
      arguments: { after_seq: frameSeq, last_event_id: eventId },
    });
    if (disposed || document.hidden) return;
    if (result.isError) throw new Error('preview unavailable');
    consume(result.structuredContent);
    failures = 0;
    nextDelay = Math.max(0, 200 - (performance.now() - started));
  } catch {
    failures += 1;
    nextDelay = Math.min(2000, 500 * failures);
    clearFrame();
  } finally {
    inFlight = false;
    schedule(nextDelay);
  }
}

function visibilityChanged() {
  if (document.hidden) {
    if (timer) clearTimeout(timer);
    timer = undefined;
    hideCursor();
    root.dataset.busy = 'false';
  } else schedule(0);
}

const resizeObserver = new ResizeObserver(fitFrame);
resizeObserver.observe(root);
image.onerror = () => clearFrame();
document.addEventListener('visibilitychange', visibilityChanged);

function dispose() {
  if (disposed) return;
  disposed = true;
  ready = false;
  if (timer) clearTimeout(timer);
  timer = undefined;
  clearFrame();
  resizeObserver.disconnect();
  document.removeEventListener('visibilitychange', visibilityChanged);
  window.removeEventListener('pagehide', dispose);
}

app.ontoolresult = (result) => {
  if (!result.isError) consume(result.structuredContent);
  schedule(0);
};
app.onteardown = async () => { dispose(); return {}; };
app.onclose = dispose;
window.addEventListener('pagehide', dispose, { once: true });

try {
  await app.connect();
  ready = true;
  const context = app.getHostContext();
  if (!requestedFullscreen && context?.displayMode !== 'fullscreen'
      && context?.availableDisplayModes?.includes('fullscreen')) {
    requestedFullscreen = true;
    try { await app.requestDisplayMode({ mode: 'fullscreen' }); } catch { /* Keep the preview in the host's supported view. */ }
  }
  schedule(0);
} catch {
  dispose();
}
