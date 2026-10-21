'use strict';
(() => {
  let selected = null, session = crypto.randomUUID(), active = null, items = [];
  const unitNames = {
    temperature_c: ['Температура', '°C'], humidity_pct: ['Влажность воздуха', '%'],
    pressure_hpa: ['Давление', 'гПа'], altitude_m: ['Высота', 'м'],
    rain_raw: ['Дождь', 'ADC'], soil_raw: ['Почва', 'ADC'],
  };
  const stamp = value => new Date(value).toLocaleString('ru-RU');
  const node = (tag, text, css = '') => {
    const el = document.createElement(tag);
    el.textContent = text; el.className = css; return el;
  };
  const status = text => { $('ai-status').textContent = text; update(); };
  const watch = new AgroWatch(take, status);

  function update() {
    const input = mode === 'camera' ? live : Boolean(file);
    $('advice').disabled = !ready || !adviceAvailable || !input || busy || Boolean(active) || watch.running;
    $('ai-stop').hidden = !watch.running && !active;
    $('advice').title = mode === 'camera' ? 'Начать наблюдение: кадр и датчики каждые 30 секунд после ответа' : 'Анализ выбранного кадра и показаний датчиков';
  }
  function cancel(message) {
    const wasActive = active || watch.running;
    watch.stop(message || 'AI-наблюдение остановлено. Отправленный запрос может сохраниться в журнале.');
    active?.abort();
    if (!wasActive && !message) $('ai-status').textContent = 'Готов к совместному анализу.';
    update();
  }
  function delay(ms, signal) {
    return new Promise((resolve, reject) => {
      signal.throwIfAborted();
      const abort = () => { clearTimeout(timer); reject(new DOMException('Остановлено', 'AbortError')); };
      const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, ms);
      signal.addEventListener('abort', abort, { once: true });
    });
  }
  async function capture(signal) {
    let source, cleanup = () => {};
    if (mode === 'camera') {
      if (!live) throw new Error('Сначала подключите камеру / OBS.');
      source = $('camera-video');
    } else if (mode === 'photo') {
      source = new Image(); source.src = originalUrl;
      await source.decode();
    } else {
      // Analyze the original recording, without the local detector's painted boxes.
      source = document.createElement('video');
      source.muted = true; source.preload = 'auto'; source.src = originalUrl;
      cleanup = () => { source.pause(); source.removeAttribute('src'); source.load(); };
    }
    try {
      if (mode === 'video') {
        const until = Date.now() + 12000;
        while (source.readyState < 2) {
          if (source.error || Date.now() > until) throw new Error('Не удалось прочитать кадр записи. Выберите MP4, который воспроизводится в браузере.');
          await delay(100, signal);
        }
        source.currentTime = Math.min($('video-preview').currentTime || 0, Math.max(0, source.duration - .05));
        while (source.seeking || source.readyState < 2) {
          if (Date.now() > until) throw new Error('Не удалось выбрать кадр видео.');
          await delay(100, signal);
        }
      }
      signal.throwIfAborted();
      const width = source.videoWidth || source.naturalWidth, height = source.videoHeight || source.naturalHeight;
      if (!width || !height) throw new Error('Кадр ещё не готов. Повторите через несколько секунд.');
      const canvas = document.createElement('canvas'), scale = Math.min(1, 1280 / Math.max(width, height));
      canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
      canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
      return { image: canvas.toDataURL('image/jpeg', .8), captured_at: new Date().toISOString() };
    } finally { cleanup(); }
  }
  async function take(signal) {
    if (active) throw new Error('Предыдущий анализ ещё выполняется.');
    const local = new AbortController();
    active = local;
    const abort = () => local.abort();
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) local.abort();
    update();
    status('Подготавливаем данные участка…');
    try {
      const frame = await capture(local.signal);
      // The backend selects the latest ESP32 and uses optional context defaults.
      const payload = { ...frame, source: mode, session_id: session, request_id: crypto.randomUUID() };
      const job = await api('/advice', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), signal: local.signal });
      status('Готовим агрономическое заключение…');
      const deadline = Date.now() + 90000;
      while (true) {
        await delay(1500, local.signal);
        if (Date.now() > deadline) throw new Error('Ответ задерживается. Проверьте журнал позже.');
        const result = await api('/insights/jobs/' + job.job_id, { signal: local.signal });
        if (result.status === 'done') {
          local.signal.throwIfAborted();
          render(result.result);
          status('Отчёт сохранён · ' + stamp(result.result.created_at));
          await refreshHistory();
          return;
        }
      }
    } catch (error) {
      if (error.status === 429 && /квот|лимит.*исчерпан/i.test(error.message)) error.quota = true;
      throw error;
    } finally {
      signal.removeEventListener('abort', abort);
      if (active === local) active = null;
      update();
    }
  }
  function list(title, values, target) {
    if (!values.length) return;
    const section = node('section', '', 'ai-section');
    section.append(node('h3', title));
    const ul = document.createElement('ul');
    values.forEach(text => ul.append(node('li', text)));
    section.append(ul); target.append(section);
  }
  function render(data) {
    selected = data;
    $('ai-empty').hidden = true; $('ai-report').hidden = false;
    $('ai-summary').textContent = data.assessment.summary;
    $('ai-frame').src = apiUrl(data.image_path);
    $('ai-frame-link').href = apiUrl(data.image_path);
    const s = data.sensors;
    const label = { live: 'свежие показания', stale: 'показания устарели', empty: 'датчики не подключены' }[s.status];
    const source = { camera: 'Камера', photo: 'Фото', video: 'Видеозапись' }[data.source] || 'Снимок';
    $('ai-meta').textContent = `${stamp(data.captured_at)} · ${source} · ${label}`;
    const content = $('ai-details'); content.replaceChildren();
    const risks = node('section', '', 'ai-section');
    risks.append(node('h3', 'Условные риски · 24–48 часов'));
    if (!data.assessment.risks.length) risks.append(node('p', 'Недостаточно оснований для прогноза рисков поля.'));
    data.assessment.risks.forEach(risk => {
      const card = node('article', '', 'ai-risk');
      card.append(node('span', { low: 'Низкий', medium: 'Умеренный', high: 'Высокий', unknown: 'Не определён' }[risk.level], 'ai-level ' + risk.level),
        node('strong', risk.title), node('p', risk.evidence), node('p', risk.forecast));
      risks.append(card);
    });
    content.append(risks);
    list('Рекомендации', data.assessment.actions.map(a =>
      ({ now: 'Сейчас', today: 'Сегодня', check: 'Перепроверить' }[a.priority]) + ': ' + a.what + ' ' + a.why), content);
    const measures = [];
    Object.entries(unitNames).forEach(([key, [name, unit]]) => {
      const value = s.reading?.[key], trend = s.trends?.[key];
      if (value != null) measures.push(`${name}: ${value} ${unit}` +
        (trend ? ` · изменение ${trend.delta > 0 ? '+' : ''}${trend.delta} за ${trend.minutes} мин (${trend.count} замеров)` : ' · тренд пока неизвестен'));
    });
    list('Датчики, использованные в отчёте', measures, content);
    list('Ограничения оценки', [...new Set([...data.warnings, ...data.assessment.limitations])], content);
    $('ai-export').disabled = false;
  }
  async function refreshHistory() {
    try {
      items = (await api('/insights/history')).observations;
      const target = $('ai-history'); target.replaceChildren();
      $('ai-history-note').textContent = items.length ? 'Последние 50 отчётов. Выберите время, чтобы открыть кадр и данные.' : 'Сохранённых наблюдений пока нет.';
      items.forEach(item => {
        const button = node('button', stamp(item.captured_at) + ' · ' +
          (item.crop || (item.source === 'camera' ? 'Камера / OBS' : 'Файл')), 'ai-history-item');
        button.type = 'button';
        button.addEventListener('click', () => { render(item); $('ai-report').scrollIntoView({ behavior: 'smooth', block: 'start' }); });
        target.append(button);
      });
    } catch { $('ai-history-note').textContent = 'Не удалось загрузить журнал. Проверьте связь с ноутбуком.'; }
  }
  async function analyzeWithSensors() {
    if ($('advice').disabled) return;
    $('ai-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (mode === 'camera') {
      session = crypto.randomUUID(); watch.start(); update();
      return;
    }
    const signal = new AbortController().signal;
    try { await take(signal); }
    catch (error) { if (error.name !== 'AbortError') status(error.message); }
  }
  $('advice').addEventListener('click', analyzeWithSensors);
  $('ai-stop').addEventListener('click', () => cancel());
  $('ai-refresh').addEventListener('click', refreshHistory);
  $('ai-export').addEventListener('click', () => {
    if (!selected) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(selected, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'eginqanat-ai-observation-' + selected.id + '.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && (watch.running || active)) cancel('Вкладка скрыта — AI-наблюдение остановлено. Для продолжения нажмите «Начать общий анализ».');
  });
  window.addEventListener('beforeunload', () => cancel());
  window.agroInsights = { update, cancel };
  update(); refreshHistory();
})();
