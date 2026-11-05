/*
 * Голосовой виджет записи на консультацию.
 * Встраивание на любой сайт:
 *   <script src="https://ВАШ-СЕРВЕР/static/widget.js" data-server="https://ВАШ-СЕРВЕР" defer></script>
 * Опции: data-open="1" — открыть панель сразу; data-inline="#id" — встроить в элемент вместо плавающей кнопки.
 */
(function () {
  const script = document.currentScript;
  const SERVER = (script && script.dataset.server) || location.origin;
  const WS_URL = SERVER.replace(/^http/, 'ws') + '/ws';
  const INLINE = script && script.dataset.inline;
  const AUTO_OPEN = script && script.dataset.open === '1';

  // ---------- стили ----------
  const css = `
  .vb-root{--vb-bg:#ffffff;--vb-fg:#14212b;--vb-muted:#5f6f7a;--vb-line:#e3e8ec;--vb-soft:#f3f6f8;
    --vb-accent:#0b6e4f;--vb-accent-2:#12a37a;--vb-accent-soft:#e3f4ee;--vb-danger:#c2410c;--vb-user:#14212b;--vb-user-fg:#fff;
    font-family:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--vb-fg);font-size:15px;line-height:1.45;}
  @media (prefers-color-scheme: dark){.vb-root{--vb-bg:#111a20;--vb-fg:#e8eef2;--vb-muted:#93a3ae;--vb-line:#24323b;--vb-soft:#18242c;
    --vb-accent:#2cc79a;--vb-accent-2:#5fe0b8;--vb-accent-soft:#143128;--vb-user:#e8eef2;--vb-user-fg:#111a20;}}
  .vb-root *{box-sizing:border-box}
  .vb-root.vb-inline{height:100%}
  .vb-fab{position:fixed;right:24px;bottom:24px;z-index:2147483000;display:flex;align-items:center;gap:10px;
    border:0;border-radius:999px;padding:14px 20px 14px 16px;background:var(--vb-accent);color:#fff;font:inherit;font-weight:600;
    box-shadow:0 10px 30px rgba(11,110,79,.35);cursor:pointer;transition:transform .15s}
  .vb-fab:hover{transform:translateY(-2px)}
  .vb-fab svg{width:22px;height:22px}
  .vb-panel{position:fixed;right:24px;bottom:24px;z-index:2147483001;width:380px;max-width:calc(100vw - 32px);
    height:600px;max-height:calc(100vh - 48px);background:var(--vb-bg);border:1px solid var(--vb-line);border-radius:20px;
    box-shadow:0 24px 60px rgba(10,30,40,.22);display:none;flex-direction:column;overflow:hidden}
  .vb-root.vb-inline .vb-panel{position:relative;right:auto;bottom:auto;width:100%;max-width:none;height:100%;max-height:none;display:flex;box-shadow:none}
  .vb-open .vb-panel{display:flex}.vb-open .vb-fab{display:none}
  @media (max-width:480px){.vb-root:not(.vb-inline) .vb-panel{right:8px;left:8px;bottom:8px;width:auto;max-width:none;height:calc(100vh - 16px);max-height:none}}
  .vb-head{display:flex;align-items:center;gap:12px;padding:16px 18px;border-bottom:1px solid var(--vb-line)}
  .vb-orb{width:40px;height:40px;border-radius:50%;flex:none;background:radial-gradient(circle at 35% 30%,var(--vb-accent-2),var(--vb-accent));
    box-shadow:0 0 0 0 rgba(18,163,122,.5);transition:box-shadow .1s}
  .vb-title{font-weight:650;font-size:15px}
  .vb-status{font-size:12.5px;color:var(--vb-muted)}
  .vb-x{margin-left:auto;border:0;background:transparent;color:var(--vb-muted);cursor:pointer;padding:6px;border-radius:8px;font-size:20px;line-height:1}
  .vb-x:hover{background:var(--vb-soft)}
  .vb-log{flex:1;overflow-y:auto;padding:16px 18px;display:flex;flex-direction:column;gap:10px;background:var(--vb-soft)}
  .vb-empty{margin:auto;text-align:center;color:var(--vb-muted);max-width:260px;font-size:14px}
  .vb-empty b{display:block;color:var(--vb-fg);font-size:16px;margin-bottom:6px}
  .vb-msg{max-width:85%;padding:9px 13px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}
  .vb-msg.agent{align-self:flex-start;background:var(--vb-bg);border:1px solid var(--vb-line);border-bottom-left-radius:4px}
  .vb-msg.user{align-self:flex-end;background:var(--vb-user);color:var(--vb-user-fg);border-bottom-right-radius:4px}
  .vb-sys{align-self:center;font-size:12px;color:var(--vb-muted);padding:2px 8px}
  .vb-sys.err{color:var(--vb-danger)}
  .vb-card{align-self:stretch;background:var(--vb-bg);border:1.5px solid var(--vb-accent);border-radius:14px;padding:14px 16px}
  .vb-card h4{margin:0 0 8px;font-size:14px;color:var(--vb-accent);display:flex;align-items:center;gap:6px}
  .vb-card .num{font-size:20px;font-weight:700;letter-spacing:.5px;margin-bottom:8px}
  .vb-card dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:13.5px}
  .vb-card dt{color:var(--vb-muted)}.vb-card dd{margin:0}
  .vb-card .acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
  .vb-btn{border:1px solid var(--vb-line);background:var(--vb-bg);color:var(--vb-fg);border-radius:10px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer;text-decoration:none}
  .vb-btn:hover{border-color:var(--vb-accent)}
  .vb-card form{display:flex;gap:6px;margin-top:8px}
  .vb-card input{flex:1;min-width:0;border:1px solid var(--vb-line);background:var(--vb-bg);color:var(--vb-fg);border-radius:10px;padding:7px 10px;font:inherit;font-size:13px}
  .vb-card.cancel{border-color:var(--vb-danger)}.vb-card.cancel h4{color:var(--vb-danger)}
  .vb-foot{padding:16px 18px 18px;border-top:1px solid var(--vb-line);display:flex;align-items:center;gap:14px;background:var(--vb-bg)}
  .vb-call{width:58px;height:58px;border-radius:50%;border:0;flex:none;cursor:pointer;display:grid;place-items:center;
    background:var(--vb-accent);color:#fff;transition:background .15s,transform .1s}
  .vb-call:active{transform:scale(.96)}
  .vb-call.on{background:var(--vb-danger)}
  .vb-call svg{width:26px;height:26px}
  .vb-hint{font-size:13px;color:var(--vb-muted)}
  .vb-hint b{display:block;color:var(--vb-fg);font-size:14px;font-weight:600}
  `;

  const ICON_MIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  const ICON_END = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1c0 .39-.23.74-.56.9-.98.49-1.87 1.12-2.66 1.85-.18.18-.43.28-.7.28-.28 0-.53-.11-.71-.29L.29 13.08a.996.996 0 0 1 0-1.41C3.34 8.78 7.46 7 12 7s8.66 1.78 11.71 4.67c.18.18.29.43.29.71 0 .28-.11.53-.29.71l-2.48 2.48c-.18.18-.43.29-.71.29-.27 0-.52-.11-.7-.28a11.27 11.27 0 0 0-2.67-1.85.996.996 0 0 1-.56-.9v-3.1C15.15 9.25 13.6 9 12 9z"/></svg>';

  const STATUS = {
    idle: 'Готова помочь', connecting: 'Подключаюсь…', connected: 'На связи', listening: 'Слушаю',
    thinking: 'Думаю…', speaking: 'Говорю', tool: 'Проверяю…', ended: 'Разговор завершён',
  };
  const TOOL_LABEL = {
    get_available_slots: 'Смотрю свободное время…', book_appointment: 'Оформляю запись…',
    cancel_appointment: 'Отменяю запись…', request_callback: 'Передаю заявку менеджеру…',
  };

  // ---------- разметка ----------
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  const root = document.createElement('div');
  root.className = 'vb-root' + (INLINE ? ' vb-inline vb-open' : '');
  root.innerHTML = `
    <button class="vb-fab" type="button" aria-label="Поговорить с ассистентом">${ICON_MIC}<span>Записаться голосом</span></button>
    <section class="vb-panel" role="dialog" aria-label="Голосовой ассистент">
      <header class="vb-head">
        <div class="vb-orb" aria-hidden="true"></div>
        <div><div class="vb-title">Ассистент <span class="vb-company"></span></div><div class="vb-status">${STATUS.idle}</div></div>
        ${INLINE ? '' : '<button class="vb-x" type="button" aria-label="Закрыть">×</button>'}
      </header>
      <div class="vb-log" aria-live="polite">
        <div class="vb-empty"><b>Поговорите с ассистентом</b>Ответит на вопросы об услугах и запишет на консультацию. Нажмите на кнопку микрофона и разрешите доступ к нему.</div>
      </div>
      <footer class="vb-foot">
        <button class="vb-call" type="button" aria-label="Начать разговор">${ICON_MIC}</button>
        <div class="vb-hint"><b>Начать разговор</b>Лучше в наушниках — так ассистент не услышит сам себя</div>
      </footer>
    </section>`;
  (INLINE ? document.querySelector(INLINE) : document.body).appendChild(root);

  const $ = (s) => root.querySelector(s);
  const logEl = $('.vb-log'), statusEl = $('.vb-status'), callBtn = $('.vb-call'), hintEl = $('.vb-hint'), orb = $('.vb-orb');
  let cfg = { company: '', rate: 44100, in_rate: 44100, email_enabled: false, mic_gate: 0.06 };
  fetch(SERVER + '/api/config').then((r) => r.json()).then((c) => { cfg = c; $('.vb-company').textContent = c.company; }).catch(() => {});

  $('.vb-fab').onclick = () => root.classList.add('vb-open');
  const x = $('.vb-x');
  if (x) x.onclick = () => { stop(); root.classList.remove('vb-open'); };
  if (AUTO_OPEN) root.classList.add('vb-open');

  function setStatus(s, text) { statusEl.textContent = text || STATUS[s] || s; }
  function scroll() { logEl.scrollTop = logEl.scrollHeight; }
  function clearEmpty() { const e = $('.vb-empty'); if (e) e.remove(); }
  function addMsg(role, text) {
    clearEmpty();
    const d = document.createElement('div');
    d.className = 'vb-msg ' + role;
    d.textContent = text;
    logEl.appendChild(d); scroll();
    return d;
  }
  function addSys(text, err) {
    clearEmpty();
    const d = document.createElement('div');
    d.className = 'vb-sys' + (err ? ' err' : '');
    d.textContent = text;
    logEl.appendChild(d); scroll();
  }
  const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function addBookingCard(b, cancelled) {
    clearEmpty();
    const d = document.createElement('div');
    d.className = 'vb-card' + (cancelled ? ' cancel' : '');
    d.innerHTML = `
      <h4>${cancelled ? '✕ Запись отменена' : '✓ Вы записаны'}</h4>
      <div class="num">${esc(b.number)}</div>
      <dl>
        <dt>Когда</dt><dd>${esc(b.when)} (МСК)</dd>
        <dt>Тема</dt><dd>${esc(b.service)}</dd>
        <dt>Имя</dt><dd>${esc(b.client_name)}</dd>
        <dt>Телефон</dt><dd>${esc(b.phone)}</dd>
      </dl>
      ${cancelled ? '' : `<div class="acts">
        <a class="vb-btn" href="${SERVER}/api/bookings/${encodeURIComponent(b.number)}.ics" download>📅 Добавить в календарь</a>
      </div>
      ${cfg.email_enabled ? `<form><input type="email" placeholder="email для подтверждения" required><button class="vb-btn">Отправить</button></form>` : ''}`}`;
    const form = d.querySelector('form');
    if (form) form.onsubmit = async (e) => {
      e.preventDefault();
      const email = form.querySelector('input').value;
      const r = await fetch(`${SERVER}/api/bookings/${encodeURIComponent(b.number)}/email`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }),
      });
      form.outerHTML = r.ok ? '<div class="vb-sys">Письмо отправлено на ' + esc(email) + '</div>' : '<div class="vb-sys err">Не удалось отправить письмо</div>';
    };
    logEl.appendChild(d); scroll();
  }

  // ---------- аудио ----------
  let ws = null, ctx = null, mic = null, node = null, src = null;
  let playTime = 0, sources = [], agentBubble = null, ending = false, active = false;
  let outNode = null, loopPcs = [], outEl = null; // вывод голоса через WebRTC-петлю, чтобы работало эхоподавление
  let segs = []; // [{start, dur}] — куски текущего ответа агента, чтобы посчитать, сколько прозвучало

  function playPcm(buf) {
    const pcm = new Int16Array(buf);
    if (!pcm.length || !ctx) return;
    const ab = ctx.createBuffer(1, pcm.length, cfg.rate);
    const ch = ab.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const s = ctx.createBufferSource();
    s.buffer = ab;
    s.connect(duckNode());
    const t = Math.max(ctx.currentTime + 0.03, playTime);
    s.start(t);
    playTime = t + ab.duration;
    segs.push({ start: t, dur: ab.duration });
    sources.push(s);
    s.onended = () => { sources = sources.filter((x) => x !== s); };
  }
  // общий регулятор громкости ассистента: приглушаем, пока не ясно, перебивает ли клиент
  let duck = null, duckTarget = null;
  function duckNode() {
    const target = outNode || ctx.destination;
    if (!duck || duckTarget !== target) {
      duck = ctx.createGain(); duck.connect(target); duckTarget = target;
    }
    return duck;
  }
  function setDuck(v) { if (duck && ctx) duck.gain.setTargetAtTime(v, ctx.currentTime, 0.04); }
  function playedInfo() {
    if (!ctx || !segs.length) return { ms: 0, full: true };
    const now = ctx.currentTime;
    let played = 0, total = 0;
    for (const g of segs) { total += g.dur; played += Math.max(0, Math.min(g.dur, now - g.start)); }
    return { ms: Math.round(played * 1000), full: played >= total - 0.02 };
  }
  // Chrome гасит эхо только у звука, пришедшего через WebRTC. Поэтому голос ассистента
  // отправляем через локальную пару RTCPeerConnection и играем полученный поток в <audio>.
  const IS_WEBKIT_ONLY = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) ||
    /^((?!chrome|chromium|crios|android|edg).)*safari/i.test(navigator.userAgent);
  async function setupEchoSafeOutput() {
    if (IS_WEBKIT_ONLY) { outNode = null; return; }
    try {
      const dest = ctx.createMediaStreamDestination();
      const a = new RTCPeerConnection(), b = new RTCPeerConnection();
      a.onicecandidate = (e) => e.candidate && b.addIceCandidate(e.candidate).catch(() => {});
      b.onicecandidate = (e) => e.candidate && a.addIceCandidate(e.candidate).catch(() => {});
      const gotTrack = new Promise((res) => { b.ontrack = (e) => res(e.streams[0] || new MediaStream([e.track])); });
      dest.stream.getTracks().forEach((t) => a.addTrack(t, dest.stream));
      const offer = await a.createOffer(); await a.setLocalDescription(offer); await b.setRemoteDescription(offer);
      const answer = await b.createAnswer(); await b.setLocalDescription(answer); await a.setRemoteDescription(answer);
      const stream = await Promise.race([gotTrack, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 3000))]);
      outEl = new Audio(); outEl.autoplay = true; outEl.srcObject = stream;
      await outEl.play();
      loopPcs = [a, b]; outNode = dest;
    } catch (e) {
      console.warn('echo-safe output unavailable, fallback to direct output', e);
      outNode = null;
    }
  }
  function teardownOutput() {
    duck = null; duckTarget = null;
    loopPcs.forEach((pc) => { try { pc.close(); } catch (e) {} });
    loopPcs = []; outNode = null;
    if (outEl) { try { outEl.pause(); outEl.srcObject = null; } catch (e) {} outEl = null; }
  }
  function clearPlayback() {
    sources.forEach((s) => { try { s.stop(); } catch (e) {} });
    sources = []; playTime = 0;
    setDuck(1);
  }

  async function start() {
    if (active) return;
    active = true; ending = false;
    callBtn.classList.add('on'); callBtn.innerHTML = ICON_END; callBtn.setAttribute('aria-label', 'Завершить разговор');
    hintEl.innerHTML = '<b>Говорите</b>Можно перебивать ассистента';
    setStatus('connecting');
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      await ctx.resume();
      setStatus('connecting', 'Включаю звук…');
      await Promise.race([setupEchoSafeOutput(), new Promise((r) => setTimeout(r, 2500))]);
      if (!loopPcs.length) teardownOutput(); // не успело — играем напрямую
      mic = await navigator.mediaDevices.getUserMedia({
        // autoGainControl выключен: он «подтягивает» дальний фоновый разговор до громкости голоса
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false, channelCount: 1 },
      });
      if (ctx.state !== 'running') { try { await ctx.resume(); } catch (e) {} }
      ctx.onstatechange = () => {
        if (active && ctx && ctx.state !== 'running') addSys('Коснитесь экрана, чтобы включить звук');
      };
      await ctx.audioWorklet.addModule(SERVER + '/static/pcm-worklet.js');
      src = ctx.createMediaStreamSource(mic);
      node = new AudioWorkletNode(ctx, 'pcm-capture', { processorOptions: { targetRate: cfg.in_rate || cfg.rate } });
      src.connect(node);
      // узел должен быть подключён к графу, иначе process() не вызывается в некоторых браузерах
      const mute = ctx.createGain(); mute.gain.value = 0; node.connect(mute); mute.connect(ctx.destination);
    } catch (e) {
      addSys('Нет доступа к микрофону: ' + e.message, true);
      return stop();
    }

    setStatus('connecting', 'Подключаюсь к серверу…');
    ws = new WebSocket(WS_URL);
    ws.binaryType = 'arraybuffer';
    let serverReady = false;
    const wsTimer = setTimeout(() => {
      if (!active || serverReady) return;
      if (!ws || ws.readyState !== 1) {
        addSys('Сервер не отвечает: соединение для голоса не установилось за 10 секунд. Проверьте интернет или попробуйте через VPN.', true);
      } else {
        addSys('Сервер на связи, но ассистент не подключился за 10 секунд. Попробуйте ещё раз.', true);
      }
      stop(false);
    }, 10000);
    // Адаптивные ворота и перебивание на стороне браузера.
    // Виджет запоминает громкость голоса клиента (пока ассистент молчит) и пропускает только звук
    // сопоставимой громкости: дальние разговоры тише и отсекаются. Порог подстраивается сам.
    // Предзапись 300 мс — чтобы не терять начало слова; удержание 400 мс — чтобы не рвать фразу.
    let gateOpenUntil = 0, wasOpen = false, bargeSent = false, ducked = false;
    const preroll = [], voiceLv = [], hist = [];
    const botSpeaking = () => !!ctx && playTime > ctx.currentTime + 0.05;
    const pct = (arr, q) => { const a = [...arr].sort((x, y) => x - y); return a[Math.floor((a.length - 1) * q)]; };
    node.port.onmessage = (e) => {
      const lvl = e.data.level || 0;
      const now = performance.now();
      const speaking = botSpeaking();
      if (!speaking && lvl >= 0.04) { voiceLv.push(lvl); if (voiceLv.length > 60) voiceLv.shift(); }
      const voice = voiceLv.length >= 8 ? pct(voiceLv, 0.6) : 0;      // типичная громкость клиента
      const gate = Math.max(cfg.mic_gate || 0, voice * (cfg.gate_ratio || 0.35));
      if (lvl >= gate) gateOpenUntil = now + 400;
      const open = gate === 0 || now < gateOpenUntil;
      // Перебивание в два шага, чтобы фон не обрывал ассистента. Считаем «громкие» куски по 100 мс
      // в скользящем окне (в речи есть паузы между слогами, поэтому не требуем непрерывности):
      //  1) ≥3 из последних 5 → приглушаем ассистента (обратимо); тишина 0.5 с → громкость возвращается;
      //  2) ≥6 из последних 12 → это реплика: отменяем ответ и обрезаем непрозвучавшее.
      // Эхоподавление Chrome глушит голос клиента, пока говорит ассистент, поэтому порог ниже обычной громкости.
      // Без эхоподавления (Safari/iPhone) микрофон слышит самого ассистента — там не перебиваем из браузера.
      const bargeLevel = voice ? Math.max(0.05, voice * 0.4) : 0.1;
      hist.push(speaking && !!outNode && lvl >= bargeLevel ? 1 : 0); if (hist.length > 12) hist.shift();
      const last5 = hist.slice(-5).reduce((a, b) => a + b, 0), last12 = hist.reduce((a, b) => a + b, 0);
      if (speaking && !bargeSent) {
        if (last5 >= 3 && !ducked) { ducked = true; setDuck(0.2); }
        if (ducked && last5 === 0) { ducked = false; setDuck(1); }
        if (last12 >= 6 && ws && ws.readyState === 1) {
          bargeSent = true; ducked = false; hist.length = 0;
          ws.send(JSON.stringify({ type: 'barge', ...playedInfo() }));
          clearPlayback(); segs = [];
          if (agentBubble) { agentBubble.textContent += ' …'; agentBubble = null; }
        }
      }
      if (!speaking) { bargeSent = false; if (ducked) { ducked = false; setDuck(1); } }
      orb.style.boxShadow = `0 0 0 ${open ? Math.min(14, lvl * 40) : 0}px rgba(18,163,122,.25)`;
      if (!ws || ws.readyState !== 1) return;
      if (open) {
        if (!wasOpen) { while (preroll.length) ws.send(preroll.shift()); }
        ws.send(e.data.pcm);
      } else {
        ws.send(new ArrayBuffer(e.data.pcm.byteLength));
        preroll.push(e.data.pcm); if (preroll.length > 3) preroll.shift();
      }
      wasOpen = open;
    };
    ws.onmessage = (e) => {
      if (typeof e.data !== 'string') return playPcm(e.data);
      const m = JSON.parse(e.data);
      switch (m.type) {
        case 'status':
          if (m.state === 'connected') { serverReady = true; clearTimeout(wsTimer); }
          setStatus(m.state); break;
        case 'clear': {
          if (m.need_played && ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'played', ...playedInfo() }));
          clearPlayback(); segs = [];
          if (agentBubble) agentBubble.textContent += ' …';
          agentBubble = null; break;
        }
        case 'user_text': addMsg('user', m.text); break;
        case 'agent_start': agentBubble = null; segs = []; break;
        case 'agent_delta':
          if (!agentBubble) agentBubble = addMsg('agent', '');
          agentBubble.textContent += m.text; scroll(); break;
        case 'agent_done': agentBubble = null; break;
        case 'tool': setStatus('tool', TOOL_LABEL[m.name] || STATUS.tool); break;
        case 'booking': addBookingCard(m.booking, false); break;
        case 'booking_cancelled': addBookingCard(m.booking, true); break;
        case 'callback': addSys('Заявка на обратный звонок передана менеджеру'); break;
        case 'error': serverReady = true; clearTimeout(wsTimer); addSys(m.message, true); break;
        case 'end': {
          ending = true;
          const wait = ctx ? Math.max(0, playTime - ctx.currentTime) * 1000 + 400 : 0;
          setTimeout(() => stop(true), wait);
          break;
        }
      }
    };
    ws.onclose = () => { if (active) stop(ending); };
    let opened = false;
    ws.onopen = () => { opened = true; setStatus('connecting', 'Связь с сервером есть, подключаю ассистента…'); };
    ws.onerror = () => addSys(opened ? 'Связь с сервером прервалась' :
      'Не удалось подключиться к серверу. На iPhone это бывает из-за сертификата сайта — откройте на компьютере или в другом браузере.', true);
  }

  function stop(finished) {
    if (!active) return;
    active = false;
    try { ws && ws.readyState === 1 && ws.send(JSON.stringify({ type: 'stop' })); } catch (e) {}
    try { ws && ws.close(); } catch (e) {}
    ws = null;
    clearPlayback();
    teardownOutput();
    try { src && src.disconnect(); node && node.disconnect(); } catch (e) {}
    if (mic) mic.getTracks().forEach((t) => t.stop());
    if (ctx) ctx.close();
    mic = node = src = ctx = null;
    orb.style.boxShadow = '';
    callBtn.classList.remove('on'); callBtn.innerHTML = ICON_MIC; callBtn.setAttribute('aria-label', 'Начать разговор');
    hintEl.innerHTML = '<b>Начать новый разговор</b>Нажмите на микрофон';
    setStatus(finished ? 'ended' : 'idle');
    if (finished) addSys('Разговор завершён');
  }

  callBtn.onclick = () => (active ? stop(true) : start());
  // iOS: любое касание будит «уснувший» звук
  ['touchend', 'click'].forEach((ev) => document.addEventListener(ev, () => {
    if (active && ctx && ctx.state !== 'running') ctx.resume().catch(() => {});
  }, true));
  window.VoiceBookingWidget = { open: () => root.classList.add('vb-open'), start, stop };
})();
