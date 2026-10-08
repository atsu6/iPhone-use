// The 40-second film, scene by scene. Times are seconds; scene starts sit on a
// half-second grid so the soundtrack (120 BPM) can land on them.
(() => {
  const { tw, set, hook, sfx, reveal, type, ease, one, all } = TL;
  const scene = window.SCENE;
  const DURATION = 40;
  const TAU = Math.PI * 2;

  const show = (target, at, { y = 44, duration = .7 } = {}) => tw(target, { o: [0, 1], y: [y, 0] }, at, duration, ease.out);
  const hide = (target, at, { y = -26, duration = .3 } = {}) => tw(target, { o: 0, y }, at, duration, ease.in);
  const dim = (target, at) => tw(target, { o: .22 }, at, .5, ease.outSoft);
  const press = (target, at) => { tw(target, { s: .92 }, at, .09, ease.outSoft); tw(target, { s: 1 }, at + .09, .4, ease.pop); };

  // A tool-call row: slides in with a spinner, then resolves to a green check.
  function step(target, at, done, sound = 'check') {
    const row = one(target);
    const spin = row.querySelector('.spin');
    const ok = row.querySelector('.ok');
    tw(row, { o: [0, 1], y: [18, 0] }, at, .45, ease.out);
    hook(at, done, (_, time) => { spin.style.transform = `rotate(${(time * 600) % 360}deg)`; });
    tw(spin, { o: [1, 0] }, done, .1, ease.linear);
    tw(ok, { o: [0, 1] }, done, .12, ease.linear);
    tw(ok, { s: [.3, 1] }, done, .55, ease.pop);
    if (sound) sfx(done, sound);
  }

  // Gesture indications match the widget: a neutral grey dot that presses, rebounds and fades.
  const screen = one('#screen');
  function marker(x, y) {
    const node = document.createElement('div');
    node.className = 'gesture-cursor';
    node.style.left = `${x}px`;
    node.style.top = `${y}px`;
    screen.append(node);
    return node;
  }
  function tap(x, y, at, life = 1.1) {
    const node = marker(x, y);
    tw(node, { o: [0, 1], s: [.96, 1] }, at, .08, ease.linear);
    tw(node, { s: .86 }, at + .08, .13, ease.outSoft);
    tw(node, { s: 1.08 }, at + .21, .17, ease.outSoft);
    tw(node, { s: 1 }, at + .38, .16, ease.outSoft);
    tw(node, { o: 0, s: .98 }, at + life - .2, .2, ease.linear);
    sfx(at + .1, 'tap');
    return at + .21;
  }
  function drag(x, fromY, toY, at, move = .62) {
    const node = marker(x, fromY);
    tw(node, { o: [0, 1], s: [.96, 1] }, at, .08, ease.linear);
    tw(node, { s: .9 }, at + .08, .12, ease.outSoft);
    tw(node, { y: [0, toY - fromY] }, at + .2, move, ease.move);
    tw(node, { s: 1.08 }, at + .2 + move, .16, ease.outSoft);
    tw(node, { s: 1 }, at + .36 + move, .14, ease.outSoft);
    tw(node, { o: 0, s: .98 }, at + move + .62, .2, ease.linear);
    sfx(at + .2, 'swipe');
    return at + .2;
  }

  // ───────── S0 · 0.0–2.5 · the mark and the name ─────────
  const lock = scene.lockup;
  const centreX = 960 - lock.markX;
  const letters = all('#word .wi');
  tw('#mark', { x: [centreX, centreX], y: [86, 86], s: [.2, 1], r: [-20, 0] }, .12, .85, ease.pop);
  tw('#mark', { o: [0, 1] }, .12, .16, ease.linear);
  tw('#mark', { x: 0 }, .8, .8, ease.inOut);
  tw('#word', { y: [86, 86], o: [1, 1] }, 0, 0);
  letters.forEach((letter, index) => tw(letter, { yp: [112, 0] }, 1 + index * .04, .7, ease.out));
  tw('#for', { o: [0, 1], y: [18, 0] }, 1.5, .6, ease.out);
  tw('#mark', { o: 0, y: 50, s: .94 }, 2.1, .32, ease.in);
  tw('#word', { o: 0, y: 50 }, 2.1, .32, ease.in);
  tw('#for', { o: 0, y: -36 }, 2.1, .32, ease.in);
  sfx(.14, 'pop');
  sfx(1, 'rise');

  // ───────── S1 · 2.5–6.0 · Codex, a wireless link, your own iPhone ─────────
  reveal('#h1', 2.52, { stagger: .03 });
  sfx(2.5, 'whoosh');
  show('#mac', 2.9, { y: 56 });
  tw('#mac-user', { o: [0, 1], s: [.7, 1] }, 3.2, .5, ease.pop);
  tw('#mac-row', { o: [0, 1], y: [16, 0] }, 3.45, .5, ease.out);
  tw('#widget', { o: [0, 1], x: [30, 30], y: [166, 100], s: [.56, .6] }, 3, .8, ease.out);
  set('#pill', { o: 0 }, 0);
  set('#toolbar', { o: 0 }, 0);
  const macSpin = one('#mac-st .spin');
  hook(3.4, 4.6, (_, time) => { macSpin.style.transform = `rotate(${(time * 600) % 360}deg)`; });
  tw('#mac-st .spin', { o: [1, 0] }, 4.58, .1, ease.linear);
  tw('#mac-st .ok', { o: [0, 1] }, 4.58, .12, ease.linear);
  tw('#mac-st .ok', { s: [.3, 1] }, 4.58, .55, ease.pop);
  tw('#mac-wait', { o: 0 }, 4.55, .12, ease.linear);
  tw('#mac-ready', { o: [0, 1], y: [8, 0] }, 4.6, .35, ease.out);

  // The link appears dot by dot, lands on the phone, then keeps a pulse travelling along it.
  const linkDots = all('#link .link-dot');
  tw('#link-a', { o: [0, 1] }, 3.5, .12, ease.linear);
  tw('#link-a', { s: [.2, 1] }, 3.5, .5, ease.pop);
  linkDots.forEach((dot, index) => {
    tw(dot, { o: [0, 1], s: [.2, 1] }, 3.62 + index * .72 / linkDots.length, .28, ease.out);
    for (const wave of [4.74, 5.1]) {
      tw(dot, { s: 1.75 }, wave + index * .016, .1, ease.out);
      tw(dot, { s: 1 }, wave + .1 + index * .016, .24, ease.outSoft);
    }
  });
  tw('#link-tag', { o: [0, 1], y: [12, 0] }, 4.02, .4, ease.out);
  tw('#link-b', { o: [0, 1] }, 4.36, .1, ease.linear);
  tw('#link-b', { s: [.2, 1] }, 4.36, .5, ease.pop);
  [['#link-ring-1', 4.42], ['#link-ring-2', 4.64]].forEach(([ring, at]) => {
    set(ring, { o: 0 }, 0);
    tw(ring, { s: [.15, 1], o: [.75, 0] }, at, .8, ease.out);
  });
  sfx(3.62, 'link');
  sfx(4.42, 'connect');
  tw('#offline', { o: 0 }, 4.5, .4, ease.outSoft);
  tw('#widget', { s: .622 }, 4.42, .16, ease.out);
  tw('#widget', { s: .6 }, 4.58, .45, ease.inOut);

  hide('#h1', 5.5, { y: -34 });
  tw('#mac', { o: 0, x: -70 }, 5.5, .34, ease.in);
  tw('#link', { o: 0 }, 5.5, .22, ease.linear);
  tw('#widget', { x: 0, y: 0, s: .95 }, 5.55, .85, ease.inOut);
  tw('#pill', { o: 1 }, 6.05, .4, ease.out);
  tw('#toolbar', { o: 1 }, 6.05, .4, ease.out);
  sfx(5.55, 'whoosh');

  // ───────── S2 · 6.0–10.0 · say it once ─────────
  reveal('#h2a', 6);
  reveal('#h2b', 6.22);
  show('#composer', 6.2, { y: 56 });
  const prompt = '用 iPhone Use 打开备忘录，新建一条草稿，记下周末采购清单。';
  set('#prompt-ph', { o: 0 }, 6.88);
  type('#prompt', prompt, 6.9, 8.5);
  const caret = one('#prompt-caret');
  hook(0, DURATION, (_, time) => {
    const typing = time >= 6.9 && time <= 8.5;
    caret.style.opacity = typing || Math.floor(time * 1.9) % 2 === 0 ? 1 : 0;
  });
  for (let time = 6.9; time < 8.5; time += .0925) sfx(time, 'key');
  press('#send', 8.72);
  sfx(8.74, 'send');
  hide('#composer', 8.95, { y: -34 });
  show('#runlog', 9.1, { y: 56 });
  tw('#runlog', { h: [154, 154] }, 9, 0);
  [[10.1, 212], [12.05, 270], [13.2, 328], [14.35, 386]].forEach(([at, height]) => tw('#runlog', { h: height }, at, .5, ease.out));
  step('#r1', 9.25, 9.72);
  tw('#glow', { '--on': [0, 1] }, 9.3, .5, ease.out);
  hide('#h2a', 9.5);
  hide('#h2b', 9.54);

  // ───────── S3 · 10.0–17.5 · open, tap, swipe, type ─────────
  const notes = one('#notes');
  const home = one('#home');
  const { notes: notesIcon, ledger: ledgerIcon } = scene.icons;
  notes.style.transformOrigin = `${notesIcon.x}px ${notesIcon.y}px`;
  one('#editor').style.transformOrigin = `${notesIcon.x}px ${notesIcon.y}px`;
  one('#ledger').style.transformOrigin = `${ledgerIcon.x}px ${ledgerIcon.y}px`;
  hook(0, DURATION, (_, time) => {
    const icon = time < 20.47 ? notesIcon : ledgerIcon;
    home.style.transformOrigin = `${icon.x}px ${icon.y}px`;
  });

  reveal('#h3a', 10);
  step('#r2', 10.15, 10.9);
  tw('#notes', { s: [.16, 1], '--rad': [90, 0] }, 10.32, .6, ease.out);
  tw('#notes', { o: [0, 1] }, 10.32, .14, ease.linear);
  tw('#home', { s: [1, 1.14] }, 10.32, .6, ease.out);
  sfx(10.32, 'open');

  reveal('#h3b', 12);
  dim('#h3a', 12);
  step('#r3', 12.1, 13.02);
  const swipeStart = drag(206, 640, 400, 12.15, .65);
  tw('#notes-scroll', { y: [0, -240] }, swipeStart, .65, ease.move);
  tw('#notes-scroll', { y: -292 }, swipeStart + .65, .55, ease.out);
  step('#r4', 13.25, 13.82);
  const composeAt = tap(371, 815, 13.3);
  tw('#editor', { xp: [100, 0] }, composeAt + .04, .5, ease.move);
  tw('#notes', { xp: [0, -28] }, composeAt + .04, .5, ease.move);
  tw('#notes-shade', { o: [0, .14] }, composeAt + .04, .5, ease.move);
  tw('#kb', { yp: [100, 0] }, composeAt + .3, .45, ease.out);
  set('#notes', { o: 0 }, composeAt + .6);

  reveal('#h3c', 14.3);
  dim('#h3b', 14.3);
  step('#r5', 14.4, 16.78);
  const draft = [['#ed-title', '周末采购清单'], ['#ed-1', '牛奶、鸡蛋、全麦面包'], ['#ed-2', '咖啡豆 250g'], ['#ed-3', '猫粮（鸡肉味）× 2']]
    .map(([selector, text]) => ({ element: one(selector), glyphs: Array.from(text) }));
  const draftLength = draft.reduce((sum, line) => sum + line.glyphs.length, 0);
  let typedCount = -1;
  let caretLit = null;
  hook(14.55, 16.6, (progress, time) => {
    const count = Math.round(progress * draftLength);
    const lit = (time > 14.55 && time < 16.6) || Math.floor(time * 1.9) % 2 === 0;
    if (count === typedCount && lit === caretLit) return;
    typedCount = count;
    caretLit = lit;
    let remaining = count;
    let caretPlaced = false;
    for (const line of draft) {
      const take = Math.min(line.glyphs.length, remaining);
      remaining -= take;
      line.element.textContent = line.glyphs.slice(0, take).join('');
      const last = take < line.glyphs.length || line === draft.at(-1);
      if (last && !caretPlaced) {
        caretPlaced = true;
        const bar = document.createElement('i');
        bar.className = 'caret';
        bar.style.opacity = lit ? 1 : 0;
        line.element.append(bar);
      }
    }
  });
  for (let time = 14.55; time < 16.6; time += .0683) sfx(time, 'type');
  tw('#widget', { s: 1.4, y: 240 }, 14.3, 1.05, ease.inOut);

  hide('#h3a', 16.9);
  hide('#h3b', 16.94);
  hide('#h3c', 16.98);
  hide('#runlog', 17.02, { y: -34 });
  tw('#widget', { s: .95, y: 0 }, 16.9, .75, ease.inOut);
  sfx(16.95, 'whoosh');

  // ───────── S4 · 17.5–20.5 · it reads the page ─────────
  reveal('#h4a', 17.5);
  reveal('#h4b', 17.72);
  show('#tree', 17.56, { y: 56 });
  ['#n1', '#n2', '#n3', '#n4', '#n5'].forEach((node, index) => tw(node, { o: [0, 1], x: [26, 0] }, 17.78 + index * .1, .45, ease.out));
  tw('#scan', { o: [0, 1] }, 17.82, .12, ease.linear);
  tw('#scan', { y: [-150, 880] }, 17.82, .9, ease.linear);
  tw('#scan', { o: 0 }, 18.62, .14, ease.linear);
  sfx(17.82, 'scan');
  [['#bx1', 18], ['#bx2', 18.05], ['#bx3', 18.14], ['#bx4', 18.42]].forEach(([box, at]) => {
    tw(box, { o: [0, 1], s: [.94, 1] }, at, .34, ease.out);
    sfx(at, 'blip');
  });
  tw('#n4-fill', { o: [0, 1] }, 18.8, .3, ease.out);
  tw('#n4-same', { o: [0, 1] }, 18.92, .12, ease.linear);
  tw('#n4-same', { s: [.6, 1] }, 18.92, .5, ease.pop);
  tw('#bx3-ok', { o: [0, 1] }, 18.92, .25, ease.out);
  sfx(18.92, 'check');
  tw('#boxes', { o: 0 }, 19.42, .25, ease.linear);
  const doneAt = tap(365, 76, 19.4);
  tw('#kb', { yp: 100 }, doneAt + .05, .42, ease.inOut);
  hide('#h4a', 20.02);
  hide('#h4b', 20.06);
  hide('#tree', 20.1, { y: -34 });

  // ───────── S5a · 20.5–23.5 · blocked by a pop-up: look, then tap by coordinate ─────────
  tw('#editor', { o: 0, s: .2 }, 20.14, .3, ease.in);
  tw('#home', { s: 1 }, 20.14, .32, ease.out);
  tw('#ledger', { s: [.16, 1], '--rad': [90, 0] }, 20.48, .55, ease.out);
  tw('#ledger', { o: [0, 1] }, 20.48, .14, ease.linear);
  tw('#home', { s: 1.14 }, 20.48, .55, ease.out);
  sfx(20.48, 'open');
  reveal('#h5a', 20.5);
  reveal('#h5b', 20.74);
  show('#fallback', 20.76, { y: 56 });
  tw('#popup-dim', { o: [0, 1] }, 20.98, .3, ease.out);
  tw('#popup-card', { o: [0, 1] }, 20.98, .14, ease.linear);
  tw('#popup-card', { s: [.72, 1] }, 20.98, .55, ease.pop);
  tw('#popup-x', { o: [0, 1] }, 21.12, .2, ease.linear);
  sfx(20.98, 'thud');

  tw('#fb1', { o: [0, 1], y: [18, 0] }, 21.12, .4, ease.out);
  [[-9, .06], [8, .07], [-5, .07], [0, .08]].reduce((at, [x, duration]) => { tw('#fb1', { x }, at, duration, ease.outSoft); return at + duration; }, 21.42);
  sfx(21.3, 'error');
  step('#fb2', 21.62, 22.24, null);
  tw('#flash', { o: [0, .9] }, 21.7, .05, ease.linear);
  tw('#flash', { o: 0 }, 21.75, .32, ease.out);
  sfx(21.7, 'shutter');
  tw('#shot', { o: [0, 1] }, 21.76, .14, ease.linear);
  tw('#shot', { x: [250, 0], y: [-30, 0], s: [.5, 1] }, 21.76, .6, ease.out);
  tw('#aim', { o: [0, 1], s: [2.6, 1] }, 22.02, .4, ease.out);
  sfx(22.04, 'lock');
  tw('#fb2-b', { o: [0, 1] }, 22.22, .2, ease.linear);
  step('#fb3', 22.4, 22.82);
  const closeAt = tap(337, 236, 22.44);
  tw('#popup-card', { s: .86, o: 0 }, closeAt + .03, .24, ease.in);
  tw('#popup-x', { o: 0 }, closeAt + .03, .15, ease.linear);
  tw('#popup-dim', { o: 0 }, closeAt + .06, .3, ease.out);
  hide('#h5a', 23.04);
  hide('#h5b', 23.08);
  hide('#fallback', 23.12, { y: -34 });

  // ───────── S5b · 23.5–27.5 · long lists: scroll, collect, de-duplicate ─────────
  reveal('#h6a', 23.5);
  reveal('#h6b', 23.72);
  show('#table', 23.56, { y: 56 });
  const phoneRows = all('#llist .lrow .hl');
  const tableRows = all('#t-rows .t-row');
  const pages = [
    { at: 23.9, first: 0, fresh: [0, 9], label: '第 1 页', duplicates: 0 },
    { at: 25.14, first: 6, fresh: [9, 15], label: '第 2 页', duplicates: 3 },
    { at: 26.38, first: 12, fresh: [15, 21], label: '第 3 页', duplicates: 6 },
  ];
  const arrivals = [];
  for (const page of pages) {
    for (let offset = 0; offset < 9; offset++) {
      const highlight = phoneRows[page.first + offset];
      const at = page.at + offset * .04;
      tw(highlight, { o: [0, 1] }, at, .12, ease.linear);
      tw(highlight, { o: 0 }, at + .12, .5, ease.out);
    }
    const [from, to] = page.fresh;
    for (let index = from; index < to; index++) {
      const at = page.at + .06 + (index - from) * .05;
      tw(tableRows[index], { o: [0, 1], x: [36, 0] }, at, .4, ease.out);
      arrivals.push(at);
      sfx(at, 'row');
    }
    const settle = page.at + .06 + (to - from) * .05;
    tw('#t-rows', { y: -(to - 4) * 54 }, page.at + .12, settle - page.at + .1, ease.inOut);
    if (page.duplicates) {
      tw('#t-dup-chip', { s: 1.14 }, page.at + .1, .12, ease.out);
      tw('#t-dup-chip', { s: 1 }, page.at + .22, .4, ease.pop);
    }
  }
  const pageTag = one('#t-page');
  const rowCount = one('#t-count');
  const dupCount = one('#t-dup');
  hook(0, DURATION, (_, time) => {
    let page = pages[0];
    for (const candidate of pages) if (candidate.at <= time) page = candidate;
    const count = arrivals.filter((at) => at <= time).length;
    if (pageTag.textContent !== page.label) pageTag.textContent = page.label;
    if (rowCount.textContent !== String(count)) rowCount.textContent = String(count);
    const duplicates = time >= page.at + .1 ? page.duplicates : Math.max(0, page.duplicates - 3);
    if (dupCount.textContent !== String(duplicates)) dupCount.textContent = String(duplicates);
  });
  tw('#t-edge', { o: [0, 1], x: [14, 0] }, 26.72, .35, ease.out);
  const firstSwipe = drag(206, 706, 322, 24.35, .55);
  tw('#llist', { y: [0, -384] }, firstSwipe, .55, ease.move);
  const secondSwipe = drag(206, 706, 322, 25.59, .55);
  tw('#llist', { y: -768 }, secondSwipe, .55, ease.move);
  hide('#h6a', 27.1);
  hide('#h6b', 27.14);
  hide('#table', 27.18, { y: -34 });

  // ───────── S6 · 27.5–31.5 · passwords and Face ID stay with you ─────────
  tap(363, 76, 27.26);
  reveal('#h7a', 27.5);
  reveal('#h7b', 27.74);
  tw('#faceid', { o: [0, 1] }, 27.62, .25, ease.out);
  tw('#faceid-card', { s: [.78, 1] }, 27.62, .5, ease.pop);
  sfx(27.62, 'thud');
  show('#ask', 28.02, { y: 56 });
  tw('#paused', { o: [0, 1] }, 28.3, .32, ease.outSoft);
  tw('#glow', { '--on': 0 }, 28.3, .32, ease.out);
  set('#faceid', { o: 0 }, 28.7);
  sfx(28.3, 'pause');
  tw('#pointer', { o: [0, 1] }, 29.06, .15, ease.linear);
  tw('#pointer', { x: [640, 341], y: [990, 791] }, 29.06, .68, ease.inOut);
  tw('#pointer', { s: .86 }, 29.84, .08, ease.outSoft);
  tw('#pointer', { s: 1 }, 29.92, .3, ease.pop);
  press('#ask-yes', 29.84);
  sfx(29.86, 'click');
  tw('#paused', { o: 0 }, 30.04, .36, ease.outSoft);
  tw('#glow', { '--on': 1 }, 30.04, .5, ease.out);
  tw('#ltoast', { o: [0, 1], y: [-18, 0] }, 30.22, .45, ease.out);
  sfx(30.06, 'resume');
  tw('#pointer', { o: 0 }, 30.4, .25, ease.linear);
  hide('#h7a', 31.02);
  hide('#h7b', 31.06);
  hide('#ask', 31.1, { y: -34 });

  // ───────── S7 · 31.5–35.0 · seventeen tools, one local MCP ─────────
  const burstX = 1430 - lock.markX;
  const burstY = 540 - lock.markY;
  tw('#widget', { s: .3, o: 0 }, 31.16, .44, ease.in);
  tw('#glow', { '--on': 0 }, 31.16, .3, ease.out);
  tw('#halo', { o: [0, 1], s: [.4, 1] }, 31.44, .8, ease.out);
  tw('#mark', { x: [burstX, burstX], y: [burstY, burstY], r: [-12, 0], s: [.4, 1.08] }, 31.46, .8, ease.pop);
  tw('#mark', { o: [0, 1] }, 31.46, .14, ease.linear);
  sfx(31.46, 'pop');
  reveal('#h8a', 31.5);
  reveal('#h8b', 31.74);
  all('#burst .tool').forEach((tool, index) => {
    const x = Number(tool.dataset.x);
    const y = Number(tool.dataset.y);
    const far = tool.classList.contains('far');
    const at = 31.86 + index * .024;
    tw(tool, { x: [0, x], y: [0, y], s: [.3, 1] }, at, .85, ease.pop);
    tw(tool, { o: [0, far ? .6 : 1] }, at, .18, ease.linear);
    tw(tool, { x: x * 1.05, y: y * 1.05 }, at + .85, 34.5 - at - .85, ease.linear);
    tw(tool, { x: 0, y: 0, s: .3, o: 0 }, 34.5 + index * .01, .36, ease.in);
  });
  sfx(31.86, 'burst');
  all('#facts .fact').forEach((fact, index) => {
    tw(fact, { o: [0, 1], y: [22, 0], s: [.9, 1] }, 32.75 + index * .12, .5, ease.out);
    sfx(32.75 + index * .12, 'pop', { step: index });
    hide(fact, 34.72 + index * .03);
  });
  sfx(34.5, 'gather');
  hide('#h8a', 34.7);
  hide('#h8b', 34.74);
  tw('#halo', { o: 0, s: .6 }, 34.72, .4, ease.in);

  // ───────── S8 · 35.0–40.0 · lockup, promise, where to get it ─────────
  tw('#mark', { x: 0, y: 0, s: 1 }, 35, .85, ease.inOut);
  letters.forEach((letter) => set(letter, { yp: 112 }, 35.2));
  set('#word', { o: 1, y: 0 }, 35.3);
  letters.forEach((letter, index) => tw(letter, { yp: [112, 0] }, 35.62 + index * .04, .7, ease.out));
  sfx(35.64, 'logo');
  reveal('#tagline', 36.16, { stagger: .028 });
  tw('#cta', { o: [0, 1], y: [22, 0] }, 36.98, .6, ease.out);
  sfx(37, 'pop', { step: 2 });
  tw('#world', { s: [1, 1.024] }, 35, 5, ease.linear);

  // ───────── always running: edge glow, status pill ─────────
  const glow = one('#glow');
  const colourLayers = all('#glow .glow-colors i');
  const dotLayers = all('#glow .glow-dots i');
  const ring = (value) => { const turn = ((value % 1) + 1) % 1; return Math.min(turn, 1 - turn); };
  hook(0, DURATION, (_, time) => {
    const on = Number(glow.style.getPropertyValue('--on')) || 0;
    glow.style.opacity = on * (.9 + .1 * Math.cos(time / 8 * TAU));
    if (!on) return;
    colourLayers.forEach((layer, index) => { layer.style.opacity = Math.max(0, 1 - 3 * ring(time / 8 - index / 3)); });
    dotLayers.forEach((layer, index) => { layer.style.opacity = Math.max(0, 1 - 3 * ring(time / 4 - index / 3)); });
  });

  const pill = one('#pill');
  const liveText = one('#live-text');
  const liveDot = one('#live .dot');
  const states = [[0, 'offline', '未连接'], [4.42, 'connecting', '连接中'], [4.72, 'live', 'Live'], [28.3, 'paused', '已暂停'], [30.04, 'live', 'Live']];
  hook(0, DURATION, (_, time) => {
    let state = states[0];
    for (const candidate of states) if (candidate[0] <= time) state = candidate;
    if (pill.dataset.live !== state[1]) pill.dataset.live = state[1];
    if (liveText.textContent !== state[2]) liveText.textContent = state[2];
    liveDot.style.opacity = state[1] === 'live' ? .7 + .3 * Math.cos(time / 2.4 * TAU) : '';
  });

  TL.seal();

  // ───────── player: frame-accurate seek for capture, live playback for preview ─────────
  const rendering = new URLSearchParams(location.search).has('render');
  document.body.classList.toggle('render', rendering);
  const painted = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  window.__seek = (time) => {
    TL.draw(time);
    return Promise.race([painted(), new Promise((resolve) => setTimeout(resolve, 500))]);
  };
  TL.draw(0);
  window.__ready = Promise.all([document.fonts.ready, ...[...document.images].map((image) => image.decode().catch(() => {}))])
    .then(() => ({ duration: DURATION, sfx: TL.sounds }));
  if (rendering) return;

  const viewport = one('#viewport');
  const fit = () => {
    const scale = Math.min(innerWidth / 1920, (innerHeight - 34) / 1080);
    viewport.style.transform = `translate(${(innerWidth - 1920 * scale) / 2}px,${(innerHeight - 34 - 1080 * scale) / 2}px) scale(${scale})`;
  };
  addEventListener('resize', fit);
  fit();
  const seekBar = one('#hud-seek');
  const clock = one('#hud-time');
  let now = Number(new URLSearchParams(location.search).get('t')) || 0;
  let playing = !new URLSearchParams(location.search).has('t');
  let last = performance.now();
  const paint = () => { TL.draw(now); seekBar.value = now; clock.textContent = now.toFixed(2).padStart(5, '0'); };
  const tick = (stamp) => {
    if (playing) { now = (now + (stamp - last) / 1000) % DURATION; paint(); }
    last = stamp;
    requestAnimationFrame(tick);
  };
  seekBar.addEventListener('input', () => { playing = false; now = Number(seekBar.value); paint(); });
  addEventListener('keydown', (event) => {
    if (event.code === 'Space') { playing = !playing; event.preventDefault(); }
    if (event.code === 'ArrowRight') { playing = false; now = Math.min(DURATION - .01, now + (event.shiftKey ? .1 : 1)); paint(); }
    if (event.code === 'ArrowLeft') { playing = false; now = Math.max(0, now - (event.shiftKey ? .1 : 1)); paint(); }
  });
  paint();
  requestAnimationFrame(tick);
})();
