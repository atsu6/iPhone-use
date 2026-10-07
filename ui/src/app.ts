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
  device?: { model?: string } | null;
};
type LiveState = 'connecting' | 'live' | 'paused' | 'offline';
type ToolName = 'refresh' | 'home' | 'screenshot';

const root = document.getElementById('app')!;
const device = document.getElementById('device')!;
const screen = document.getElementById('screen')!;
const image = document.getElementById('image')! as HTMLImageElement;
const cursor = document.getElementById('cursor')!;
const stage = document.getElementById('stage')!;
const model = document.getElementById('model')!;
const liveText = document.getElementById('live-text')!;
const toast = document.getElementById('toast')!;
const tools: Record<ToolName, HTMLButtonElement> = {
  refresh: document.getElementById('tool-refresh') as HTMLButtonElement,
  home: document.getElementById('tool-home') as HTMLButtonElement,
  screenshot: document.getElementById('tool-screenshot') as HTMLButtonElement,
};
const app = new App(
  { name: 'iPhone WDA Screen', version: '0.2.0' },
  { availableDisplayModes: ['fullscreen'] },
  { autoResize: false },
);
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let ready = false;
let disposed = false;
let inFlight = false;
let frameSeq = 0;
let frameGeneration = 0;
let streamId: string | undefined;
let eventId = 0;
let dimensions: Size | undefined;
let viewport: Size | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let failures = 0;
let animation: Animation | undefined;
let cursorTimer: ReturnType<typeof setTimeout> | undefined;
let requestedFullscreen = false;
let connecting: Promise<void> | undefined;
let suspended = false;
let lastGoodFrame: { source: string; size: Size } | undefined;
let acting = false;
let toastTimer: ReturnType<typeof setTimeout> | undefined;
const FRAME_INTERVAL = 250;
const REQUEST_TIMEOUT = 3000;
// A screenshot or Home may queue behind the phone operation already running.
const ACTION_TIMEOUT = 12000;
const LIVE_TEXT: Record<LiveState, string> = { connecting: '连接中', live: 'Live', paused: '已暂停', offline: '未连接' };
const DONE: Record<ToolName, string> = { refresh: '已刷新连接', home: '已回到主屏幕', screenshot: '截图已复制到剪贴板' };
const FAILED: Record<string, string> = {
  device_busy: '手机正在执行操作，请稍后再试',
  preview_paused: '认证接管期间已暂停',
  clipboard_unavailable: '截图未能写入剪贴板',
  wda_unreachable: '未连接到手机',
};

const validSize = (value: unknown): value is Size => {
  const size = value as Size | undefined;
  return !!size && Number.isFinite(size.width) && Number.isFinite(size.height)
    && size.width > 0 && size.height > 0;
};
const validPoint = (value: unknown): value is Point => {
  const point = value as Point | undefined;
  return !!point && Number.isFinite(point.x) && Number.isFinite(point.y);
};

function syncTools() {
  const paused = root.dataset.live === 'paused';
  tools.refresh.disabled = acting;
  // While the user authenticates on the phone nothing is captured or sent from here.
  tools.home.disabled = tools.screenshot.disabled = acting || paused;
}

function setLive(state: LiveState) {
  if (root.dataset.live === state) return;
  root.dataset.live = state;
  liveText.textContent = LIVE_TEXT[state];
  syncTools();
}

function notify(text: string, failed = false) {
  toast.textContent = text;
  toast.dataset.tone = failed ? 'error' : 'ok';
  toast.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastTimer = undefined; toast.hidden = true; }, 1800);
}

function applyTheme(theme: unknown) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
}

function hideCursor() {
  animation?.cancel();
  animation = undefined;
  if (cursorTimer) clearTimeout(cursorTimer);
  cursorTimer = undefined;
  cursor.hidden = true;
}

function clearFrame(resetOperating = true) {
  frameGeneration++;
  hideCursor();
  image.removeAttribute('src');
  device.hidden = true;
  screen.hidden = true;
  dimensions = undefined;
  lastGoodFrame = undefined;
  frameSeq = 0;
  root.dataset.frameSeq = '0';
  root.dataset.busy = 'false';
  if (resetOperating) root.dataset.operating = 'false';
}

function retainFrame() {
  hideCursor();
  root.dataset.busy = 'false';
}

const visible = () => !disposed && !suspended && !document.hidden;

// The glow's mask: a ring along the screen edge, blurred inward, plus a thin crisp rim. It is a
// static picture rebuilt only when the layout changes, so the soft falloff costs nothing per frame.
function glowMask(width: number, height: number, radius: number, band: number) {
  const round = (value: number) => Math.round(value * 100) / 100;
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${round(width)}' height='${round(height)}'>`
    + `<filter id='f' x='-30%' y='-30%' width='160%' height='160%'><feGaussianBlur stdDeviation='${round(band * .28)}'/></filter>`
    + `<rect width='${round(width)}' height='${round(height)}' rx='${round(radius)}' fill='none' stroke='#fff' stroke-width='${round(band * .9)}' filter='url(#f)'/>`
    + `<rect x='.75' y='.75' width='${round(width - 1.5)}' height='${round(height - 1.5)}' rx='${round(Math.max(0, radius - .75))}' fill='none' stroke='#fff' stroke-width='1.5'/></svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}

function fitFrame() {
  if (!dimensions) return;
  // The stage is what remains between the status pill and the toolbar.
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  const shortSide = Math.min(dimensions.width, dimensions.height);
  const bezel = shortSide * .024;
  const outerWidth = dimensions.width + 2 * bezel;
  const outerHeight = dimensions.height + 2 * bezel;
  const scale = .96 * Math.min(width / outerWidth, height / outerHeight);
  device.style.width = `${outerWidth * scale}px`;
  device.style.height = `${outerHeight * scale}px`;
  device.style.setProperty('--bezel', `${bezel * scale}px`);
  const radius = shortSide * .12 * scale;
  device.style.setProperty('--screen-radius', `${radius}px`);
  device.style.setProperty('--glow-mask', glowMask(dimensions.width * scale, dimensions.height * scale,
    radius, Math.min(bezel * scale * 3.8, radius)));
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
  const delta = gesture.kind === 'drag'
    ? `translate(${(gesture.to!.x - point.x) / size.width * screen.clientWidth}px, ${(gesture.to!.y - point.y) / size.height * screen.clientHeight}px)`
    : '';
  const frames: Keyframe[] = gesture.kind === 'drag'
    ? [
      { transform: 'translate(0, 0) scale(.85)', opacity: 0 },
      { transform: 'translate(0, 0) scale(1)', opacity: 1, offset: .08 },
      { transform: `${delta} scale(1)`, opacity: 1, offset: .86 },
      { transform: `${delta} scale(.9)`, opacity: 0 },
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
    // Sequence numbers restart with the server, but keep the last pixels until
    // its replacement is ready. Authentication pause remains an explicit erase.
    frameSeq = 0;
    eventId = 0;
    root.dataset.operating = 'false';
    retainFrame();
  }
  if (typeof preview.device?.model === 'string' && preview.device.model) model.textContent = preview.device.model;
  if (preview.paused === true) {
    clearFrame();
    setLive('paused');
    return;
  }
  if (preview.frame_available === false) {
    retainFrame();
    setLive('offline');
  } else if (preview.frame_available === true || preview.frame) {
    setLive('live');
  }
  if (validSize(preview.viewport)) viewport = preview.viewport;
  const frame = preview.frame;
  if (frame && validSize(frame) && Number.isInteger(frame.seq) && frame.seq > frameSeq
      && typeof frame.data === 'string' && frame.data.length > 0
      && ['image/jpeg', 'image/png', 'image/webp'].includes(frame.mimeType)) {
    frameSeq = frame.seq;
    root.dataset.frameSeq = String(frame.seq);
    if (!dimensions || dimensions.width !== frame.width || dimensions.height !== frame.height) {
      dimensions = { width: frame.width, height: frame.height };
      fitFrame();
    }
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
  if (!visible() || timer) return;
  timer = setTimeout(() => {
    timer = undefined;
    void poll();
  }, delay);
}

async function poll() {
  if (!visible() || inFlight) return;
  inFlight = true;
  const started = performance.now();
  let nextDelay = FRAME_INTERVAL;
  try {
    if (!ready) await connect();
    if (!visible()) return;
    const generation = frameGeneration;
    const result = await app.callServerTool({
      name: 'wda_screen_frame',
      arguments: { after_seq: frameSeq, last_event_id: eventId },
    }, { timeout: REQUEST_TIMEOUT });
    if (!visible() || generation !== frameGeneration) return;
    if (result.isError) throw new Error('preview unavailable');
    consume(result.structuredContent);
    failures = 0;
    const preview = result.structuredContent as Partial<Preview> | undefined;
    nextDelay = preview?.paused || preview?.frame_available === false
      ? 1000 : Math.max(0, FRAME_INTERVAL - (performance.now() - started));
  } catch {
    failures += 1;
    nextDelay = Math.min(2000, 500 * failures);
    retainFrame();
    if (failures > 1 && root.dataset.live !== 'paused') setLive('offline');
  } finally {
    inFlight = false;
    schedule(nextDelay);
  }
}

async function act(name: ToolName) {
  if (acting || disposed || tools[name].disabled) return;
  acting = true;
  tools[name].dataset.busy = 'true';
  syncTools();
  try {
    if (!ready) await connect();
    const result = await app.callServerTool({
      name: 'wda_screen_action',
      arguments: { action: name },
    }, { timeout: ACTION_TIMEOUT });
    const data = result.structuredContent as (Partial<Preview> & { error?: { code?: string } }) | undefined;
    if (result.isError || data?.error) {
      notify(FAILED[data?.error?.code ?? ''] ?? '操作未完成，请重试', true);
    } else {
      // A refresh answers with the new stream identity; take the next frame at once.
      if (name === 'refresh') consume(data);
      notify(DONE[name]);
      if (timer) clearTimeout(timer);
      timer = undefined;
      schedule(0);
    }
  } catch {
    notify('操作未完成，请重试', true);
  } finally {
    acting = false;
    delete tools[name].dataset.busy;
    syncTools();
  }
}
const toolHandlers = (Object.keys(tools) as ToolName[]).map(name => {
  const handler = () => { void act(name); };
  tools[name].addEventListener('click', handler);
  return [name, handler] as const;
});

function visibilityChanged() {
  root.dataset.pageVisible = String(visible());
  if (!visible()) {
    if (timer) clearTimeout(timer);
    timer = undefined;
    retainFrame();
  } else {
    if (timer) clearTimeout(timer);
    timer = undefined;
    schedule(0);
  }
}

const resizeObserver = new ResizeObserver(fitFrame);
resizeObserver.observe(stage);
image.onload = () => {
  if (dimensions && image.src) lastGoodFrame = { source: image.src, size: dimensions };
};
image.onerror = () => {
  if (lastGoodFrame && image.src !== lastGoodFrame.source) {
    image.src = lastGoodFrame.source;
    dimensions = lastGoodFrame.size;
    fitFrame();
  }
  frameSeq = 0; // Request a replacement without blanking the last decoded frame.
  retainFrame();
};
function documentVisibilityChanged() {
  if (!document.hidden) suspended = false;
  visibilityChanged();
}
document.addEventListener('visibilitychange', documentVisibilityChanged);

function pageHide() {
  // WebViews may suspend a document without putting it in the browser cache.
  // A real navigation destroys this JS context; only host teardown is terminal.
  suspended = true;
  visibilityChanged();
}
function pageShow() { suspended = false; visibilityChanged(); }
function focusChanged() { if (!document.hidden) pageShow(); }

function dispose() {
  if (disposed) return;
  disposed = true;
  ready = false;
  root.dataset.pageVisible = 'false';
  if (timer) clearTimeout(timer);
  timer = undefined;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = undefined;
  toast.hidden = true;
  for (const [name, handler] of toolHandlers) tools[name].removeEventListener('click', handler);
  clearFrame();
  resizeObserver.disconnect();
  document.removeEventListener('visibilitychange', documentVisibilityChanged);
  window.removeEventListener('pagehide', pageHide);
  window.removeEventListener('pageshow', pageShow);
  window.removeEventListener('focus', focusChanged);
}

app.ontoolresult = (result) => {
  if (!result.isError) consume(result.structuredContent);
  schedule(0);
};
app.onhostcontextchanged = (context) => { applyTheme(context?.theme); };
app.onteardown = async () => { dispose(); return {}; };
app.onclose = () => {
  ready = false;
  retainFrame();
  schedule(1000);
};
window.addEventListener('pagehide', pageHide);
window.addEventListener('pageshow', pageShow);
window.addEventListener('focus', focusChanged);

function connect() {
  if (!connecting) connecting = initialize().finally(() => { connecting = undefined; });
  return connecting;
}

async function initialize() {
  await app.connect(undefined, { timeout: REQUEST_TIMEOUT });
  if (disposed) { await app.close(); return; }
  ready = true;
  const context = app.getHostContext();
  applyTheme(context?.theme);
  if (!requestedFullscreen && context?.displayMode !== 'fullscreen'
      && context?.availableDisplayModes?.includes('fullscreen')) {
    requestedFullscreen = true;
    try { await app.requestDisplayMode({ mode: 'fullscreen' }, { timeout: REQUEST_TIMEOUT }); } catch { /* Keep the preview in the host's supported view. */ }
  }
}

root.dataset.pageVisible = String(visible());
syncTools();
try { await connect(); } catch { retainFrame(); }
schedule(ready ? 0 : 1000);
