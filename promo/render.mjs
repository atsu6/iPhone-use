#!/usr/bin/env node
// Capture promo/index.html as PNG frames with the locally installed Chrome.
// No npm dependencies: it talks to Chrome over the DevTools protocol directly.
//
//   node promo/render.mjs --out <dir>                 every frame of the film
//   node promo/render.mjs --out <dir> --only 3.2,12   single stills at those seconds
//   node promo/render.mjs --meta <file.json>          only the duration and sound cues
//
// Options: --fps 60  --from 0  --to <duration>  --scale 1  --workers 6
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const WIDTH = 1920;
const HEIGHT = 1080;

function options(argv) {
  const out = { fps: 60, from: 0, to: null, scale: 1, workers: 6, out: null, only: null, meta: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i].replace(/^--/, '');
    if (!(key in out)) throw new Error(`unknown option ${argv[i]}`);
    out[key] = argv[++i];
  }
  for (const key of ['fps', 'from', 'scale', 'workers']) out[key] = Number(out[key]);
  if (out.to !== null) out.to = Number(out.to);
  if (!out.out && !out.meta) throw new Error('--out <dir> is required');
  return out;
}

class Session {
  constructor(socket) {
    this.socket = socket;
    this.seq = 0;
    this.pending = new Map();
    this.waiters = [];
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const entry = this.pending.get(message.id);
        if (!entry) return;
        this.pending.delete(message.id);
        if (message.error) entry.reject(new Error(`${entry.method}: ${message.error.message}`));
        else entry.resolve(message.result);
        return;
      }
      this.waiters = this.waiters.filter((waiter) => {
        if (waiter.method !== message.method || waiter.sessionId !== message.sessionId) return true;
        waiter.resolve(message.params);
        return false;
      });
    });
  }

  send(method, params = {}, sessionId) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, method });
      this.socket.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }

  once(method, sessionId) {
    return new Promise((resolve) => this.waiters.push({ method, sessionId, resolve }));
  }
}

async function launch(profile) {
  const child = spawn(CHROME, [
    '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    `--window-size=${WIDTH},${HEIGHT}`, '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
    '--force-color-profile=srgb', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows', '--disable-features=Translate,MediaRouter', '--mute-audio',
    'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'], detached: true });
  const endpoint = await new Promise((resolve, reject) => {
    let log = '';
    const timer = setTimeout(() => reject(new Error(`Chrome did not report a DevTools endpoint:\n${log}`)), 20000);
    child.stderr.on('data', (chunk) => {
      log += chunk;
      const match = log.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
    child.on('exit', (code) => reject(new Error(`Chrome exited early (${code}):\n${log}`)));
  });
  return { child, endpoint };
}

async function openPage(cdp, url, scale) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Emulation.setDeviceMetricsOverride',
    { width: WIDTH, height: HEIGHT, deviceScaleFactor: scale, mobile: false }, sessionId);
  const loaded = cdp.once('Page.loadEventFired', sessionId);
  await cdp.send('Page.navigate', { url }, sessionId);
  await loaded;
  const ready = await cdp.send('Runtime.evaluate',
    { expression: 'window.__ready', awaitPromise: true, returnByValue: true }, sessionId);
  if (ready.exceptionDetails) throw new Error(`page failed to initialise: ${ready.exceptionDetails.text}`);
  return { sessionId, info: ready.result.value };
}

async function capture(cdp, sessionId, seconds, file) {
  const seek = await cdp.send('Runtime.evaluate',
    { expression: `window.__seek(${seconds})`, awaitPromise: true }, sessionId);
  if (seek.exceptionDetails) {
    throw new Error(`seek(${seconds}) failed: ${seek.exceptionDetails.exception?.description || seek.exceptionDetails.text}`);
  }
  const shot = await cdp.send('Page.captureScreenshot', { format: 'png' }, sessionId);
  await writeFile(file, Buffer.from(shot.data, 'base64'));
}

// Each worker owns a whole Chrome: a second tab in one browser sits in the background,
// where frames are never produced and the page would wait for a paint forever.
async function startWorker(url, scale) {
  const profile = await mkdtemp(path.join(os.tmpdir(), 'iphone-use-promo-'));
  const { child, endpoint } = await launch(profile);
  try {
    const socket = new WebSocket(endpoint);
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', () => reject(new Error('cannot connect to Chrome')), { once: true });
    });
    const cdp = new Session(socket);
    const page = await openPage(cdp, url, scale);
    return { child, profile, socket, cdp, ...page };
  } catch (error) {
    killChrome(child);
    await rm(profile, { recursive: true, force: true }).catch(() => {});
    throw error;
  }
}

// Chrome leads its own process group, so its helpers go down with it; a helper left
// holding the stderr pipe would otherwise keep this script alive for minutes.
function killChrome(child) {
  try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
  child.stderr.destroy();
}

async function stopWorker(worker) {
  try { worker.socket.close(); } catch {}
  killChrome(worker.child);
  await new Promise((resolve) => setTimeout(resolve, 300));
  await rm(worker.profile, { recursive: true, force: true }).catch(() => {});
}

const opts = options(process.argv.slice(2));
if (opts.out) await mkdir(opts.out, { recursive: true });
const url = `${pathToFileURL(path.join(here, 'index.html')).href}?render=1`;
const started = Date.now();
const workers = [await startWorker(url, opts.scale)];
try {
  const { duration, sfx } = workers[0].info;
  let jobs;
  if (opts.meta) {
    // Only the timeline description (duration and sound cues), no pictures.
    await writeFile(opts.meta, JSON.stringify({ fps: opts.fps, duration, sfx }, null, 2));
    jobs = [];
  } else if (opts.only) {
    jobs = String(opts.only).split(',').map(Number)
      .map((seconds) => ({ seconds, file: path.join(opts.out, `still_${seconds.toFixed(2).padStart(6, '0')}.png`) }));
  } else {
    const begin = Math.round(opts.from * opts.fps);
    const end = Math.round((opts.to ?? duration) * opts.fps);
    jobs = [];
    for (let frame = begin; frame < end; frame++) {
      jobs.push({ seconds: frame / opts.fps, file: path.join(opts.out, `f_${String(frame).padStart(5, '0')}.png`) });
    }
    await writeFile(path.join(opts.out, 'meta.json'),
      JSON.stringify({ fps: opts.fps, from: opts.from, to: opts.to ?? duration, duration, sfx }, null, 2));
  }

  const wanted = Math.max(1, Math.min(opts.workers, Math.ceil(jobs.length / 8)));
  while (workers.length < wanted) workers.push(await startWorker(url, opts.scale));
  let next = 0;
  let done = 0;
  await Promise.all(workers.map(async ({ cdp, sessionId }) => {
    for (;;) {
      const job = jobs[next++];
      if (!job) return;
      await capture(cdp, sessionId, job.seconds, job.file);
      done += 1;
      if (done % 120 === 0 || done === jobs.length) {
        process.stdout.write(`\r${done}/${jobs.length} frames  ${((Date.now() - started) / 1000).toFixed(0)}s`);
      }
    }
  }));
  process.stdout.write('\n');
} finally {
  await Promise.all(workers.map(stopWorker));
}
process.exit(0);
