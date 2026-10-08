// Builds the repeated parts of the picture (app icons, keyboard, list rows, tool pills)
// and measures the few positions the timeline needs. Everything on the phone is a
// generic drawing: no real app artwork or user data.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const svg = (inner) => `<svg viewBox="0 0 62 62">${inner}</svg>`;

  const petals = ['#f7c948', '#f59f38', '#ee5d5b', '#d55fc1', '#8e6ee0', '#4f8cf0', '#49b8d8', '#7bc86c']
    .map((color, index) => `<ellipse cx="31" cy="19.500" rx="6.600" ry="11" fill="${color}" fill-opacity=".86" transform="rotate(${index * 45} 31 31)"/>`).join('');
  const reminder = (y, color) => `<circle cx="17" cy="${y}" r="4.200" fill="none" stroke="${color}" stroke-width="2.400"/><rect x="26" y="${y - 1.7}" width="22" height="3.400" rx="1.700" fill="#c8c8cd"/>`;

  const apps = {
    calendar: { label: '日历', html: '<div class="ic cal"><span>周四</span><b>8</b></div>' },
    photos: { label: '照片', bg: '#fff', art: petals },
    camera: { label: '相机', bg: 'linear-gradient(#e9eaee,#c2c4cb)', art: '<path d="M24 22l3-5h8l3 5z" fill="#3a3b40"/><rect x="13" y="21" width="36" height="25" rx="6" fill="#3a3b40"/><circle cx="31" cy="33.500" r="8" fill="#1d1e22" stroke="#6a6c73" stroke-width="2"/><circle cx="31" cy="33.500" r="3.400" fill="#3d5f9b"/>' },
    clock: { label: '时钟', bg: '#0b0b0c', art: '<circle cx="31" cy="31" r="23" fill="#fff"/><path d="M31 31V16M31 31l10 6" stroke="#111" stroke-width="2.600" stroke-linecap="round"/><path d="M31 31l-8 13" stroke="#ff9500" stroke-width="1.400" stroke-linecap="round"/><circle cx="31" cy="31" r="2.200" fill="#ff9500"/>' },
    weather: { label: '天气', bg: 'linear-gradient(#2e86ea,#72c2ff)', art: '<circle cx="24" cy="24" r="9" fill="#ffd43b"/><path d="M22 45a8 8 0 0 1 1.700-15.800A11 11 0 0 1 44.600 32 6.600 6.600 0 0 1 43 45Z" fill="#fff" fill-opacity=".97"/>' },
    reminders: { label: '提醒事项', bg: '#fff', art: reminder(19, '#0a84ff') + reminder(31, '#ff3b30') + reminder(43, '#ff9500') },
    notes: { label: '备忘录', bg: 'linear-gradient(#ffd84d 0 27%,#fff 27%)', art: '<path d="M8 20.500h46" stroke="#b78d24" stroke-width="1.200" stroke-dasharray="1.200 3.200"/><rect x="11" y="27.500" width="40" height="2.600" rx="1.300" fill="#d2d2d7"/><rect x="11" y="36.500" width="40" height="2.600" rx="1.300" fill="#d2d2d7"/><rect x="11" y="45.500" width="25" height="2.600" rx="1.300" fill="#d2d2d7"/>' },
    maps: { label: '地图', bg: 'linear-gradient(135deg,#d9efc6,#bfe3f4)', art: '<path d="M-2 40 30 18l34 14" stroke="#fff" stroke-width="7" fill="none"/><path d="M20 66 44-4" stroke="#ffd866" stroke-width="5" fill="none"/><path d="M40 13a8 8 0 0 1 16 0c0 6-8 14-8 14s-8-8-8-14Z" fill="#ff453a"/><circle cx="48" cy="13" r="3" fill="#fff"/>' },
    ledger: { label: '小账本', bg: 'linear-gradient(150deg,#36dba8,#0a9c74)', art: '<path d="M19 12h24v38l-4-3-4 3-4-3-4 3-4-3-4 3Z" fill="#fff"/><path d="M26 21l5 6.500 5-6.500M31 27.500V39M26 30.500h10M26 35h10" stroke="#0b9f77" stroke-width="2.400" stroke-linecap="round" stroke-linejoin="round" fill="none"/>' },
    settings: { label: '设置', bg: 'linear-gradient(#b4b7be,#6e7179)', art: '<circle cx="31" cy="31" r="15" fill="none" stroke="#eceded" stroke-width="8" stroke-dasharray="5.200 4.220"/><circle cx="31" cy="31" r="12.500" fill="none" stroke="#eceded" stroke-width="3.500"/><circle cx="31" cy="31" r="4.500" fill="#eceded"/>' },
    music: { label: '音乐', bg: 'linear-gradient(#ff6b7d,#f92d52)', art: '<path d="M26 43V21l17-4v21.500" fill="none" stroke="#fff" stroke-width="3.400" stroke-linecap="round" stroke-linejoin="round"/><ellipse cx="21.500" cy="43" rx="5.200" ry="4.200" fill="#fff"/><ellipse cx="38.500" cy="38.500" rx="5.200" ry="4.200" fill="#fff"/>' },
    files: { label: '文件', bg: '#fff', art: '<path d="M12 22a4 4 0 0 1 4-4h10l4 4h16a4 4 0 0 1 4 4v18a4 4 0 0 1-4 4H16a4 4 0 0 1-4-4Z" fill="#2f95f5"/><path d="M12 28h38v16a4 4 0 0 1-4 4H16a4 4 0 0 1-4-4Z" fill="#5db4ff"/>' },
    phone: { bg: 'linear-gradient(#5fdd72,#2dbf4c)', art: '<path d="M22.500 14.500c1.200-1.200 3.100-1.100 4.100.300l3.200 4.400c.900 1.200.700 2.900-.400 3.900l-2 1.900c1.700 3.600 4.900 6.900 8.600 8.600l1.900-2c1-1.100 2.700-1.300 3.900-.400l4.400 3.200c1.400 1 1.500 2.900.300 4.100l-2.300 2.300c-1.700 1.700-4.200 2.300-6.500 1.500-10.300-3.500-17.500-10.700-21-21-.800-2.300-.200-4.800 1.500-6.500Z" fill="#fff"/>' },
    messages: { bg: 'linear-gradient(#5fdd72,#2dbf4c)', art: '<path d="M31 14c-10.500 0-19 7-19 15.600 0 5 2.900 9.400 7.400 12.300-.300 2.200-1.300 4.200-2.900 5.800 3.300-.200 6.300-1.400 8.700-3.300 1.800.500 3.800.800 5.800.800 10.500 0 19-7 19-15.600S41.500 14 31 14Z" fill="#fff"/>' },
    browser: { bg: '#fff', art: '<circle cx="31" cy="31" r="22" fill="#1e8ff5"/><circle cx="31" cy="31" r="18.500" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="1.500" stroke-dasharray="1.200 3.640"/><path d="M42 20 34.500 34.500 27.500 27.500Z" fill="#ff3b30"/><path d="M20 42l7.500-14.500 7 7Z" fill="#fff"/>' },
    mail: { bg: 'linear-gradient(#5ac8fa,#0a7cff)', art: '<rect x="12" y="19" width="38" height="25" rx="5" fill="#fff"/><path d="M14.500 22.500 31 35l16.500-12.500" fill="none" stroke="#2a8bf0" stroke-width="2.600" stroke-linecap="round" stroke-linejoin="round"/>' },
  };
  const tile = (id) => {
    const app = apps[id];
    const face = app.html || `<div class="ic" style="background:${app.bg}">${svg(app.art)}</div>`;
    return `<div class="app" data-app="${id}">${face}${app.label ? `<div class="lb">${app.label}</div>` : ''}</div>`;
  };
  $('#grid').innerHTML = ['calendar', 'photos', 'camera', 'clock', 'weather', 'reminders', 'notes', 'maps', 'ledger', 'settings', 'music', 'files'].map(tile).join('');
  $('#dock').innerHTML = ['phone', 'messages', 'browser', 'mail'].map(tile).join('');

  const statusIcons = '<svg width="18" height="12" viewBox="0 0 18 12"><rect y="8" width="3" height="4" rx="1"/><rect x="5" y="5.500" width="3" height="6.500" rx="1"/><rect x="10" y="3" width="3" height="9" rx="1"/><rect x="15" width="3" height="12" rx="1"/></svg>'
    + '<svg width="17" height="12" viewBox="0 0 17 12"><path d="M8.500 2.400c2.300 0 4.400.900 6 2.400l1.100-1.200A10.300 10.300 0 0 0 8.500.700C5.800.700 3.300 1.800 1.400 3.600l1.100 1.200a8.600 8.600 0 0 1 6-2.400Zm0 3.500c1.400 0 2.600.500 3.600 1.400l1.100-1.200a7 7 0 0 0-9.400 0l1.100 1.200c1-.900 2.200-1.400 3.600-1.400Zm0 3.300c-.700 0-1.300.300-1.800.700l1.800 2 1.800-2c-.500-.400-1.100-.700-1.800-.700Z"/></svg>'
    + '<svg width="27" height="13" viewBox="0 0 27 13"><rect x=".500" y=".500" width="23" height="12" rx="3.800" fill="none" stroke="currentColor" stroke-opacity=".4"/><rect x="2" y="2" width="20" height="9" rx="2.500"/><path d="M25 4.500v4c.800-.300 1.500-1.100 1.500-2s-.700-1.700-1.500-2Z" fill-opacity=".45"/></svg>';
  for (const screen of document.querySelectorAll('.scr')) {
    const light = screen.id === 'home' ? ' light' : '';
    screen.insertAdjacentHTML('afterbegin', `<div class="sb${light}"><b>9:41</b><span>${statusIcons}</span></div>`);
    if (screen.id !== 'home') screen.insertAdjacentHTML('beforeend', '<div class="bar"></div>');
  }

  const key = (label, kind = '') => `<span class="key ${kind}">${label}</span>`;
  $('#kb').innerHTML = `<div class="kb-row">${[...'qwertyuiop'].map((letter) => key(letter)).join('')}</div>`
    + `<div class="kb-row">${[...'asdfghjkl'].map((letter) => key(letter)).join('')}</div>`
    + `<div class="kb-row">${key('<svg viewBox="0 0 24 24"><path d="M12 4l8 9h-4.500v6h-7v-6H4Z"/></svg>', 'fn gap')}${[...'zxcvbnm'].map((letter) => key(letter)).join('')}${key('<svg viewBox="0 0 24 24"><path d="M9 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-6-7ZM12 9.500l5 5M17 9.500l-5 5"/></svg>', 'fn gapl')}</div>`
    + `<div class="kb-row">${key('123', 'num')}${key('空格', 'space')}${key('换行', 'ret')}</div>`
    + '<div class="kb-foot"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.200 3 14.800 0 18M12 3c-3 3.200-3 14.800 0 18"/></svg><svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 11a6 6 0 0 0 12 0M12 17v4"/></svg></div>';

  const tones = { 餐: '#ff9f43', 行: '#4b9df8', 购: '#f368a0', 娱: '#8e7cf8', 居: '#2ec4a6', 宠: '#f2b233' };
  const ledger = [
    ['咖啡豆 250g', '10月7日 19:42', 68, '购'], ['地铁通勤', '10月7日 08:15', 6, '行'], ['周末超市', '10月6日 17:30', 213.4, '购'],
    ['牛肉面', '10月6日 12:10', 32, '餐'], ['电影票 ×2', '10月5日 20:05', 98, '娱'], ['猫粮 · 鸡肉味', '10月5日 10:21', 129, '宠'],
    ['共享单车', '10月5日 08:02', 1.5, '行'], ['话费充值', '10月4日 21:16', 50, '居'], ['水果拼盘', '10月4日 15:40', 45.8, '餐'],
    ['豆浆油条', '10月4日 07:48', 9.5, '餐'], ['打车回家', '10月3日 23:11', 36.2, '行'], ['书店', '10月3日 14:27', 79, '购'],
    ['奶茶', '10月3日 13:05', 18, '餐'], ['生日蛋糕', '10月2日 16:45', 168, '餐'], ['电费', '10月2日 09:00', 186, '居'],
    ['鲜花', '10月2日 08:40', 39, '购'], ['火锅', '10月1日 19:20', 96, '餐'], ['高铁票', '10月1日 10:05', 73.5, '行'],
    ['洗衣液', '10月1日 09:12', 29.9, '购'], ['停车费', '10月1日 08:30', 12, '行'], ['早餐', '10月1日 07:55', 8, '餐'],
    ['文具', '10月1日 07:30', 15.6, '购'], ['矿泉水', '10月1日 07:12', 24, '餐'], ['公交', '10月1日 06:50', 5, '行'],
  ];
  const total = ledger.reduce((sum, row) => sum + row[2], 0);
  const money = (value) => value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  $('#ledger .lsum strong').textContent = `¥${money(total)}`;
  $('#ledger .lsum small:last-child').textContent = `共 ${ledger.length} 笔 · 日均 ¥${money(total / 7)}`;
  $('#llist').innerHTML = ledger.map(([name, time, amount, kind]) =>
    `<div class="lrow"><span class="hl"></span><i style="background:${tones[kind]}">${kind}</i><div><b>${name}</b><small>${time}</small></div><em>-${money(amount)}</em></div>`).join('');
  $('#t-rows').innerHTML = ledger.slice(0, 21).map(([name, time, amount]) =>
    `<div class="t-row"><span>${name}</span><span>${time}</span><span>¥${money(amount)}</span></div>`).join('');

  // The "screenshot" in the fallback card is a small copy of the blocked ledger screen.
  const copy = $('#ledger').cloneNode(true);
  copy.querySelector('.faceid').remove();
  copy.querySelector('.ltoast').remove();
  for (const node of [copy, ...copy.querySelectorAll('[id]')]) node.removeAttribute('id');
  $('#shot-mini').append(copy);

  const spinner = '<svg class="spin" viewBox="0 0 30 30"><circle cx="15" cy="15" r="11" fill="none" stroke="#e2e2df" stroke-width="3.200"/><path d="M15 4a11 11 0 0 1 11 11" fill="none" stroke="#121213" stroke-width="3.200" stroke-linecap="round"/></svg>'
    + '<svg class="ok" viewBox="0 0 30 30"><circle cx="15" cy="15" r="13" fill="#0eb57a"/><path d="M9 15.500l4.200 4.200L21.500 11" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  for (const status of document.querySelectorAll('.st:empty')) status.innerHTML = spinner;

  // Seventeen model-facing tools, as listed in the README.
  const tools = [
    ['wda_ready', 0, -275], ['wda_tap', -210, -150], ['wda_type_text', 215, -165], ['wda_swipe', -255, 20],
    ['wda_observe', 250, 5], ['wda_launch_app', -170, 175], ['wda_collect_list', 190, 170],
    ['wda_scroll_find', -60, -400, 1], ['wda_find', -330, -300, 1], ['wda_batch', 300, -330, 1], ['wda_wait', -395, -150, 1],
    ['wda_screen', 372, -80, 1], ['wda_metrics', -415, 160, 1], ['wda_setup', 378, 105, 1], ['wda_doctor', -250, 330, 1],
    ['wda_apps', 20, 300, 1], ['wda_press_button', 270, 330, 1],
  ];
  const dots = ['#1b9cf2', '#0eb57a', '#7d6bf2'];
  $('#burst').innerHTML = tools.map(([name, x, y, far], index) =>
    `<div class="tool${far ? ' far' : ''}" data-x="${x}" data-y="${y}" style="--dot:${dots[index % 3]}"><span>${name}</span></div>`).join('');

  // Edge glow, ported from ui/src/app.ts: a baked ring mask and three wave-dot tiles.
  const round = (value) => Math.round(value * 100) / 100;
  function glowMask(width, height, radius, band) {
    const bloom = Math.min(width, height) * .27;
    const corners = [[0, 0], [width, 0], [0, height], [width, height]]
      .map(([x, y]) => `<circle cx='${round(x)}' cy='${round(y)}' r='${round(bloom)}'/>`).join('');
    const picture = `<svg xmlns='http://www.w3.org/2000/svg' width='${round(width)}' height='${round(height)}'>`
      + `<defs><linearGradient id='x'><stop stop-color='#fff'/><stop offset='.16' stop-color='#fff' stop-opacity='.85'/><stop offset='.36' stop-color='#fff' stop-opacity='0'/><stop offset='.64' stop-color='#fff' stop-opacity='0'/><stop offset='.84' stop-color='#fff' stop-opacity='.85'/><stop offset='1' stop-color='#fff'/></linearGradient>`
      + `<linearGradient id='y' x2='0' y2='1'><stop stop-color='#fff'/><stop offset='.1' stop-color='#fff' stop-opacity='.85'/><stop offset='.28' stop-color='#fff' stop-opacity='0'/><stop offset='.72' stop-color='#fff' stop-opacity='0'/><stop offset='.9' stop-color='#fff' stop-opacity='.85'/><stop offset='1' stop-color='#fff'/></linearGradient>`
      + `<mask id='ends'><rect width='100%' height='100%' fill='url(#y)'/></mask><mask id='corners'><rect width='100%' height='100%' fill='url(#x)' mask='url(#ends)'/></mask></defs>`
      + `<filter id='f' x='-30%' y='-30%' width='160%' height='160%'><feGaussianBlur stdDeviation='${round(band * .3)}'/></filter>`
      + `<filter id='g' x='-60%' y='-60%' width='220%' height='220%'><feGaussianBlur stdDeviation='${round(bloom * .42)}'/></filter>`
      + `<g mask='url(#corners)'><g fill='#fff' fill-opacity='.46' filter='url(#g)'>${corners}</g>`
      + `<rect width='${round(width)}' height='${round(height)}' rx='${round(radius)}' fill='none' stroke='#fff' stroke-width='${round(band * .9)}' filter='url(#f)'/>`
      + `<rect x='.75' y='.75' width='${round(width - 1.5)}' height='${round(height - 1.5)}' rx='${round(Math.max(0, radius - .75))}' fill='none' stroke='#fff' stroke-opacity='.9' stroke-width='1.5'/></g></svg>`;
    return `url("data:image/svg+xml,${encodeURIComponent(picture)}")`;
  }
  function glowDots(step, phase) {
    const count = 16;
    const size = round(count * step);
    const circles = [];
    for (let row = 0; row < count; row++) {
      for (let col = 0; col < count; col++) {
        const diagonal = (col + row) / count * Math.PI * 2;
        const bend = Math.sin((col - row) / count * Math.PI * 2) * .8;
        const wave = (1 + Math.sin(diagonal + bend + phase)) / 2;
        circles.push(`<circle cx='${round((col + .5) * step)}' cy='${round((row + .5) * step)}' r='${round(step * (.04 + .23 * wave))}' fill-opacity='${round(.25 + .65 * wave)}'/>`);
      }
    }
    const picture = `<svg xmlns='http://www.w3.org/2000/svg' width='${size}' height='${size}' viewBox='0 0 ${size} ${size}'><g fill='#fff'>${circles.join('')}</g></svg>`;
    return `url("data:image/svg+xml,${encodeURIComponent(picture)}")`;
  }
  const bezel = 9.65;
  const radius = 48.2;
  $('#device').style.setProperty('--glow-mask', glowMask(402, 874, radius, Math.min(bezel * 3.8, radius)));
  document.querySelectorAll('.glow-dots i').forEach((layer, phase) => {
    layer.style.backgroundImage = glowDots(Math.max(5, bezel * .95), phase * Math.PI * 2 / 3);
  });

  // The wireless link in S1: dots spaced along a shallow arc from the Codex window to the phone.
  const linkPath = $('#link-path');
  const linkLength = linkPath.getTotalLength();
  const linkDots = Math.floor(linkLength / 17);
  $('#link').insertAdjacentHTML('afterbegin', Array.from({ length: linkDots }, (_, index) => {
    const point = linkPath.getPointAtLength((index + .5) * linkLength / linkDots);
    return `<i class="link-dot" style="left:${round(point.x)}px;top:${round(point.y)}px"></i>`;
  }).join(''));

  // Wordmark letters, each in its own clipped slot.
  $('#word').innerHTML = [...'iPhone Use'].map((letter) =>
    (letter === ' ' ? '<span style="display:inline-block;width:.24em"></span>' : `<span class="w"><span class="wi">${letter}</span></span>`)).join('');

  // offsetLeft/offsetTop ignore transforms, so these stay valid while things animate.
  const within = (element, ancestor) => {
    let x = 0;
    let y = 0;
    for (let node = element; node && node !== ancestor; node = node.offsetParent) { x += node.offsetLeft; y += node.offsetTop; }
    return { x, y };
  };
  const iconCentre = (id) => {
    const icon = $(`#grid [data-app="${id}"]`).firstElementChild;
    const origin = within(icon, $('#ui'));
    return { x: origin.x + 31, y: origin.y + 31 };
  };

  const markSize = 168;
  const gap = 34;
  const wordWidth = $('#word').offsetWidth;
  const left = (1920 - markSize - gap - wordWidth) / 2;
  const centreY = 414;
  $('#mark').style.left = `${left}px`;
  $('#mark').style.top = `${centreY - markSize / 2}px`;
  $('#word').style.left = `${left + markSize + gap}px`;
  $('#word').style.top = `${centreY - 132 / 2 - 6}px`;

  window.SCENE = {
    lockup: { markX: left + markSize / 2, markY: centreY, centreY },
    icons: { notes: iconCentre('notes'), ledger: iconCentre('ledger') },
    ledgerRows: ledger.length,
  };
})();
