'use strict';
const $ = id => document.getElementById(id);
let mode = 'photo', file = null, originalUrl = null, resultUrl = null, report = null;
let busy = false, ready = false, adviceAvailable = false, classes = [], revision = 0;
let controller = null, cameraStream = null, cameraTimer = null;
let live = false;
let sensorTimer = null, sensorLoading = false, cameraDevicesLoading = false;
const modes = {
  photo: { title: 'Снимок для анализа', empty: 'Здесь начинается забота о поле', description: 'Перетащите снимок растения или поля\nили выберите файл на устройстве', hint: 'JPG, PNG, WebP · до 20 МБ', tag: 'JPG, PNG, WEBP', action: 'Начать анализ' },
  video: { title: 'Видеозапись обхода', empty: 'Ваше поле в движении', description: 'Загрузите видеозапись обхода поля.\nПроанализируем первые 60 секунд.', hint: 'MP4, MOV, AVI, WebM · до 200 МБ', tag: 'ДО 60 СЕКУНД', action: 'Обработать видео' },
  camera: { title: 'OBS и камеры устройства', empty: 'Ваша сцена OBS — в EginQanat AI', description: 'В OBS нажмите «Запуск виртуальной камеры».\nЗатем нажмите «Подключить OBS» здесь.', hint: 'Запись в OBS не включает виртуальную камеру. Сайт откройте на том же ноутбуке.', tag: 'ПРЯМОЙ ЭФИР', action: 'Запустить камеру' },
};
function apiUrl(path, params = {}) {
  return 'api.php?' + new URLSearchParams({ path, ...params });
}
async function api(path, options = {}, params = {}) {
  const response = await fetch(apiUrl(path, params), options);
  let data;
  try { data = await response.json(); }
  catch { throw new Error('Хостинг вернул некорректный ответ. Проверьте PHP и настройки загрузки.'); }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : data.error;
    const error = new Error(detail || 'Запрос не выполнен. Проверьте файл и настройки.');
    error.status = response.status;
    throw error;
  }
  return data;
}
function message(text = '') {
  $('message').textContent = text;
  $('message').hidden = !text;
}
function cameraError(error) {
  message(cameraAccess.errorMessage(error));
  $('camera-help').hidden = false;
  $('camera-page-url').value = new URL(location.pathname, location.origin).href;
}
$('copy-camera-url').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('camera-page-url').value);
    $('camera-copy-status').textContent = 'Адрес скопирован. Вставьте его в адресную строку отдельного браузера.';
  } catch {
    $('camera-page-url').focus();
    $('camera-page-url').select();
    $('camera-copy-status').textContent = 'Адрес выделен. Нажмите Ctrl+C, затем вставьте его в отдельный браузер.';
  }
});
function updateButton() {
  $('analyze').disabled = busy || live || !ready || cameraDevicesLoading || ((mode === 'photo' || mode === 'video') && !file);
  $('connect-obs').disabled = busy || live || !ready || cameraDevicesLoading;
  $('connect-obs-label').textContent = mode === 'camera' && busy ? 'Подключаем OBS…' : 'Подключить OBS';
  $('choose-file').disabled = busy;
  $('reset-file').disabled = busy;
  $('camera-device').disabled = busy || live || cameraDevicesLoading;
  $('refresh-cameras').disabled = busy || live || cameraDevicesLoading;
  $('stop').hidden = !live;
  window.agroInsights?.update();
}
function clearResults() {
  report = null;
  if (resultUrl && resultUrl.startsWith('blob:')) URL.revokeObjectURL(resultUrl);
  resultUrl = null;
  $('result-list').replaceChildren();
  $('result-list').hidden = true;
  $('result-empty').hidden = false;
  $('result-status').textContent = 'Ожидание данных';
  $('stat-total').textContent = '—';
  $('stat-pests').textContent = '—';
  $('stat-one-label').textContent = 'Объекты';
  $('stat-two-label').textContent = 'Вредители';
  $('result-note').textContent = 'Результаты появятся после анализа.';
  $('downloads').hidden = true;
  $('advice').disabled = true;
  $('advice-text').hidden = true;
  $('timeline').hidden = true;
  $('original-control').hidden = true;
  $('show-original').checked = false;
}
function stopLive() {
  window.agroInsights?.cancel();
  live = false;
  clearTimeout(cameraTimer);
  if (cameraStream) cameraStream.getTracks().forEach(track => track.stop());
  cameraStream = null;
  $('camera-video').srcObject = null;
  $('camera-canvas').hidden = true;
  $('empty-view').hidden = false;
  $('dropzone').classList.remove('has-media');
  updateButton();
}
function resetInput() {
  revision++;
  if (controller) controller.abort();
  busy = false;
  stopLive();
  file = null;
  $('file-input').value = '';
  if (originalUrl) URL.revokeObjectURL(originalUrl);
  originalUrl = null;
  $('image-preview').hidden = true;
  $('image-preview').removeAttribute('src');
  $('video-preview').pause();
  $('video-preview').removeAttribute('src');
  $('video-preview').load();
  $('video-preview').hidden = true;
  $('file-meta').hidden = true;
  $('processing').hidden = true;
  clearResults();
  message();
  $('camera-help').hidden = true;
  updateButton();
}
function selectMode(next) {
  resetInput();
  mode = next;
  const config = modes[next];
  document.querySelectorAll('[data-mode]').forEach(tab => {
    const active = tab.dataset.mode === next;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  $('analysis-panel').setAttribute('aria-labelledby', 'tab-' + next);
  $('input-title').textContent = config.title;
  $('empty-title').textContent = config.empty;
  $('empty-description').textContent = config.description;
  $('empty-description').style.whiteSpace = 'pre-line';
  $('file-hint').textContent = config.hint;
  $('source-tag').textContent = config.tag;
  $('analyze-label').textContent = config.action;
  $('choose-file').hidden = !['photo', 'video'].includes(next);
  $('connect-obs').hidden = next !== 'camera';
  $('dropzone').classList.toggle('camera-mode', next === 'camera');
  $('camera-controls').hidden = next !== 'camera';
  $('file-input').accept = next === 'photo' ? 'image/jpeg,image/png,image/webp' : 'video/mp4,video/quicktime,video/x-msvideo,video/webm';
  updateButton();
  if (next === 'camera') listCameras(false);
}
document.querySelectorAll('[data-mode]').forEach(tab => {
  tab.addEventListener('click', () => selectMode(tab.dataset.mode));
  tab.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const names = Object.keys(modes);
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? names.length - 1 :
      (names.indexOf(mode) + (event.key === 'ArrowRight' ? 1 : names.length - 1)) % names.length;
    selectMode(names[nextIndex]);
    $('tab-' + mode).focus();
  });
});
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => {
  const page = button.dataset.page;
  if (page !== 'analysis') { revision++; controller?.abort(); busy = false; stopLive(); $('processing').hidden = true; updateButton(); }
  ['analysis', 'catalog'].forEach(name => $('page-' + name).hidden = name !== page);
  document.querySelectorAll('.nav-link').forEach(item => item.classList.toggle('active', item.dataset.page === page));
  $('breadcrumb-current').textContent = { analysis: 'Анализ поля', catalog: 'Каталог классов' }[page];
  window.scrollTo({ top: 0, behavior: 'instant' });
}));
$('choose-file').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', event => handleFile(event.target.files[0]));
$('video-preview').addEventListener('error', () => {
  if (mode === 'video' && file && !busy) {
    message(report ? 'Браузер не воспроизводит результат. Скачайте видео для просмотра.' :
      'Браузер не может показать оригинал, но видео можно отправить на анализ.');
  }
});
$('reset-file').addEventListener('click', resetInput);
$('dropzone').addEventListener('dragover', event => {
  event.preventDefault();
  if (!busy && ['photo', 'video'].includes(mode)) $('dropzone').classList.add('drag');
});
$('dropzone').addEventListener('dragleave', () => $('dropzone').classList.remove('drag'));
$('dropzone').addEventListener('drop', event => {
  event.preventDefault();
  $('dropzone').classList.remove('drag');
  if (!busy && ['photo', 'video'].includes(mode)) handleFile(event.dataTransfer.files[0]);
});
function handleFile(selected) {
  if (!selected || busy) return;
  const image = mode === 'photo';
  const supported = image ? /\.(jpe?g|png|webp)$/i : /\.(mp4|mov|avi|webm|m4v|mkv)$/i;
  if (!supported.test(selected.name)) { message('Выберите ' + (image ? 'JPG, PNG или WebP.' : 'видеофайл MP4, MOV, AVI или WebM.')); return; }
  if (selected.size > (image ? 20 : 200) * 1024 * 1024) { message('Размер файла превышает ' + (image ? 20 : 200) + ' МБ.'); return; }
  resetInput();
  file = selected;
  originalUrl = URL.createObjectURL(file);
  const preview = $(image ? 'image-preview' : 'video-preview');
  preview.src = originalUrl;
  preview.hidden = false;
  $('empty-view').hidden = true;
  $('dropzone').classList.add('has-media');
  $('file-name').textContent = file.name + ' · ' + (file.size / 1048576).toFixed(1) + ' МБ';
  $('file-meta').hidden = false;
  $('result-status').textContent = 'Готово к анализу';
  updateButton();
}
function label(name) { return classes.find(item => item.name === name)?.name_ru || name; }
function renderRows(items) {
  $('result-empty').hidden = true;
  $('result-list').hidden = false;
  $('result-list').replaceChildren();
  if (!items.length) {
    const note = document.createElement('p');
    note.className = 'empty-result';
    note.textContent = 'При выбранном пороге объекты не найдены. Это не подтверждает отсутствие вредителей: проверьте качество снимка и осмотрите растения.';
    $('result-list').append(note);
  }
  items.forEach(item => {
    const row = document.createElement('div'), dot = document.createElement('span');
    const text = document.createElement('span'), value = document.createElement('strong');
    row.className = 'detection-row';
    dot.className = 'swatch';
    dot.style.backgroundColor = item.color || '#90a66f';
    text.textContent = item.label;
    value.textContent = item.value;
    row.append(dot, text, value);
    $('result-list').append(row);
  });
}
function displayDetections(data) {
  renderRows(data.detections.map(item => ({
    color: item.color, label: item.name_ru || label(item.class_name), value: Math.round(item.confidence * 100) + '%'
  })));
  $('stat-total').textContent = data.summary.total;
  $('stat-pests').textContent = data.summary.pest_count;
  $('result-status').textContent = 'Анализ завершён';
  $('result-note').textContent = `Распознавание: ${data.infer_ms} мс. Проверьте находки на изображении.`;
  window.agroInsights?.update();
}
function jpgBlob(value) {
  const bytes = Uint8Array.from(atob(value), char => char.charCodeAt(0));
  return new Blob([bytes], { type: 'image/jpeg' });
}
async function analyzeFile() {
  if (!file || busy) return;
  const current = ++revision;
  clearResults(); message();
  busy = true;
  controller = new AbortController();
  updateButton();
  $('processing').hidden = false;
  $('processing-text').textContent = mode === 'photo' ? 'Анализируем снимок…' : 'Отправляем видео на ноутбук…';
  try {
    const data = new FormData();
    data.append('file', file);
    let result = await api('/detect/' + (mode === 'photo' ? 'image' : 'video'),
      { method: 'POST', body: data, signal: controller.signal });
    if (current !== revision) return;
    if (mode === 'video') {
      const jobId = result.job_id;
      const deadline = Date.now() + 30 * 60 * 1000;
      while (true) {
        if (current !== revision) return;
        if (Date.now() > deadline) throw new Error('Видео обрабатывается слишком долго. Проверьте ноутбук.');
        $('processing-text').textContent = 'Видео в обработке. Это может занять несколько минут…';
        await new Promise(resolve => setTimeout(resolve, 1800));
        if (current !== revision) return;
        const job = await api('/jobs/' + jobId, { signal: controller.signal });
        if (job.status === 'error') throw new Error(job.error);
        if (job.status === 'done') { result = job.result; break; }
      }
    }
    if (current !== revision) return;
    report = result;
    if (mode === 'photo') {
      displayDetections(result);
      resultUrl = URL.createObjectURL(jpgBlob(result.image_b64));
      $('image-preview').src = resultUrl;
      $('original-control').hidden = false;
      $('download-media').download = 'eginqanat-ai-result.jpg';
    } else {
      renderRows(Object.entries(result.class_counts).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({
        label: label(name), value: count + '×', color: classes.find(item => item.name === name)?.color
      })));
      $('stat-one-label').textContent = 'Кадров';
      $('stat-two-label').textContent = 'Видов';
      $('stat-total').textContent = result.frames_processed;
      $('stat-pests').textContent = Object.keys(result.class_counts).length;
      $('result-status').textContent = 'Видео обработано · ' + result.duration_sec + ' с';
      $('result-note').textContent = 'Сумма обнаружений по кадрам. Один объект может учитываться несколько раз.';
      resultUrl = apiUrl('/video/' + result.job_id);
      if (result.browser_playable) {
        $('video-preview').src = resultUrl;
        $('video-preview').load();
      }
      $('download-media').download = 'eginqanat-ai-result.mp4';
      window.agroInsights?.update();
      if (result.warning) message(result.warning);
      $('timeline').replaceChildren();
      const max = Math.max(1, ...result.timeline.map(item => item.count));
      result.timeline.forEach(item => {
        const bar = document.createElement('span');
        bar.style.height = Math.max(3, item.count / max * 100) + '%';
        bar.title = item.t + ' с: ' + item.count + ' объектов';
        $('timeline').append(bar);
      });
      $('timeline').hidden = false;
    }
    $('download-media').href = resultUrl;
    $('downloads').hidden = false;
  } catch (error) {
    if (current === revision && error.name !== 'AbortError') message(error.message);
  } finally {
    if (current === revision) { busy = false; $('processing').hidden = true; updateButton(); }
  }
}
$('show-original').addEventListener('change', () => $('image-preview').src = $('show-original').checked ? originalUrl : resultUrl);
$('download-json').addEventListener('click', () => {
  if (!report) return;
  const { image_b64, ...data } = report;
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'eginqanat-ai-report.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function startCamera() {
  if (busy || live || cameraDevicesLoading || !ready) return;
  const current = ++revision;
  clearResults(); message(); busy = true; updateButton();
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Камера работает на HTTPS-сайте или localhost.');
    let deviceId = $('camera-device').value;
    if (deviceId === 'obs-auto') {
      const devices = await cameraAccess.devices(true);
      if (current !== revision) return;
      const obs = devices.find(device => device.kind === 'videoinput' && /obs/i.test(device.label));
      if (!obs) throw new Error('OBS Virtual Camera не найдена. Включите её в OBS и нажмите «Найти камеры», затем выберите устройство.');
      deviceId = obs.deviceId;
    }
    const constraints = { width: { ideal: 1280 }, height: { ideal: 720 }, aspectRatio: { ideal: 16 / 9 } };
    if (deviceId !== 'default') constraints.deviceId = { exact: deviceId };
    const stream = await navigator.mediaDevices.getUserMedia({ video: constraints, audio: false });
    if (current !== revision) { stream.getTracks().forEach(track => track.stop()); return; }
    cameraStream = stream;
    $('camera-help').hidden = true;
    const video = $('camera-video');
    video.srcObject = stream;
    await video.play();
    if (current !== revision) return;
    live = true;
    $('empty-view').hidden = true;
    $('camera-canvas').hidden = false;
    $('dropzone').classList.add('has-media');
    const capture = document.createElement('canvas'), canvas = $('camera-canvas');
    let failures = 0;
    async function nextFrame() {
      if (!live || current !== revision) return;
      capture.width = video.videoWidth; capture.height = video.videoHeight;
      if (!capture.width) { cameraTimer = setTimeout(nextFrame, 400); return; }
      const ctx = capture.getContext('2d');
      ctx.drawImage(video, 0, 0);
      canvas.width = capture.width; canvas.height = capture.height;
      canvas.getContext('2d').drawImage(capture, 0, 0);
      controller = new AbortController();
      try {
        const data = await api('/detect/frame', {
          method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: capture.toDataURL('image/jpeg', 0.75) })
        });
        if (!live || current !== revision) return;
        const draw = canvas.getContext('2d');
        draw.drawImage(capture, 0, 0);
        data.detections.forEach(item => {
          const [x1, y1, x2, y2] = item.box;
          draw.strokeStyle = item.color; draw.lineWidth = 2;
          draw.strokeRect(x1, y1, x2 - x1, y2 - y1);
          const text = (item.name_ru || item.class_name) + ' ' + Math.round(item.confidence * 100) + '%';
          draw.font = '14px sans-serif';
          const y = Math.max(20, y1);
          draw.fillStyle = item.color;
          draw.fillRect(x1, y - 20, draw.measureText(text).width + 10, 20);
          draw.fillStyle = '#152018'; draw.fillText(text, x1 + 5, y - 5);
        });
        report = data; displayDetections(data);
        $('result-status').textContent = 'Камера · текущий кадр';
        failures = 0;
      } catch (error) {
        if (!live || current !== revision) return;
        failures++;
        message(error.message);
        if (failures >= 3) { revision++; stopLive(); return; }
      }
      if (live && current === revision) cameraTimer = setTimeout(nextFrame, 600);
    }
    nextFrame();
  } catch (error) {
    if (current === revision) { stopLive(); cameraError(error); }
  } finally {
    if (current === revision) { busy = false; updateButton(); }
  }
}

async function listCameras(askPermission) {
  if (cameraDevicesLoading || live) return;
  cameraDevicesLoading = true;
  updateButton();
  const current = revision;
  try {
    const devices = await cameraAccess.devices(askPermission);
    if (current !== revision) return;
    const previous = $('camera-device').value;
    $('camera-device').replaceChildren(new Option('OBS Virtual Camera — найти автоматически', 'obs-auto'),
      new Option('Камера по умолчанию', 'default'));
    devices.filter(device => device.deviceId).forEach((device, index) => {
      $('camera-device').append(new Option(device.label || `Камера ${index + 1}`, device.deviceId));
    });
    const obs = devices.find(device => /obs/i.test(device.label));
    $('camera-device').value = previous === 'obs-auto' && obs ? obs.deviceId :
      [...$('camera-device').options].some(option => option.value === previous) ? previous : 'obs-auto';
    if (askPermission) {
      $('camera-help').hidden = true;
      message(obs ? 'OBS Virtual Camera найдена. Включите виртуальную камеру в OBS и нажмите «Подключить OBS» в области просмотра.' :
        'Список камер обновлён. Если OBS нет в списке, запустите виртуальную камеру в OBS и повторите поиск.');
    }
  } catch (error) {
    if (askPermission && current === revision) cameraError(error);
  } finally {
    cameraDevicesLoading = false;
    updateButton();
  }
}
$('refresh-cameras').addEventListener('click', () => listCameras(true));
navigator.mediaDevices?.addEventListener?.('devicechange', () => {
  if (mode === 'camera' && !live && !busy) listCameras(false);
});

async function updateSensors() {
  if (sensorLoading) return;
  clearTimeout(sensorTimer);
  sensorLoading = true;
  const fields = ['temperature_c', 'humidity_pct', 'pressure_hpa', 'altitude_m', 'rain_raw'];
  try {
    const data = await api('/sensors');
    const reading = data.reading;
    fields.forEach(name => {
      const value = reading?.[name];
      $('sensor-' + name).textContent = value == null ? '—' :
        Number(value).toLocaleString('ru-RU', { minimumFractionDigits: name.endsWith('_raw') ? 0 : 2,
          maximumFractionDigits: name.endsWith('_raw') ? 0 : 2 });
    });
    $('refresh-sensors').className = 'sensor-state ' + (data.status === 'live' ? 'online' : data.status === 'stale' ? 'offline' : '');
    $('sensor-status').textContent = { empty: 'Нет данных', live: 'Данные поступают', stale: 'Данные устарели' }[data.status] || 'Нет данных';
    const stamp = data.received_at ? new Date(data.received_at).toLocaleString('ru-RU', {
      timeZone: 'Asia/Almaty', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    }) : '';
    $('sensor-updated').textContent = reading ?
      `${data.source_label || reading.device_id} · ${stamp} (UTC+5). ` +
        (data.status === 'stale' ? 'Новых измерений нет. Проверьте питание и Wi-Fi ESP32.' : 'Проверяем обновления каждые 5 секунд.') :
      'Ожидаем первое показание от ESP32';
  } catch {
    $('refresh-sensors').className = 'sensor-state offline';
    $('sensor-status').textContent = 'Не удалось обновить данные';
    // Existing readings remain visible with an explicit offline indicator.
  } finally {
    sensorLoading = false;
    sensorTimer = setTimeout(updateSensors, document.hidden ? 30000 : 5000);
  }
}
$('refresh-sensors').addEventListener('click', updateSensors);
$('analyze').addEventListener('click', () => mode === 'camera' ? startCamera() : analyzeFile());
$('connect-obs').addEventListener('click', () => {
  if (busy || live || cameraDevicesLoading || !ready) return;
  $('camera-device').value = 'obs-auto';
  startCamera();
});
$('stop').addEventListener('click', () => {
  revision++; controller?.abort(); busy = false; stopLive(); $('result-status').textContent = 'Трансляция остановлена';
});
async function checkHealth() {
  $('connection-label').textContent = 'Проверяем подключение';
  try {
    const health = await api('/health');
    ready = health.status === 'ready';
    adviceAvailable = health.advice_available;
    $('connection').className = 'status ' + (ready ? 'online' : 'offline');
    $('connection-label').textContent = ready ? 'Модель подключена' : 'Модель загружается';
    $('advice-note').textContent = adviceAvailable ? 'По запросу кадр и показания отправляются в Gemini.' : 'Для рекомендаций задайте GEMINI_API_KEY в .env на ноутбуке.';
    if (!classes.length) {
      classes = (await api('/classes')).classes;
      $('class-catalog').replaceChildren();
      classes.forEach(item => {
        const card = document.createElement('article'), name = document.createElement('strong');
        const english = document.createElement('p'), group = document.createElement('small');
        card.className = 'class-item';
        name.textContent = item.name_ru; english.textContent = item.name;
        group.textContent = item.is_field ? 'Состояние поля' : 'Вредитель';
        card.append(name, english, group); $('class-catalog').append(card);
      });
    }
  } catch (error) {
    ready = false;
    $('connection').className = 'status offline';
    $('connection-label').textContent = 'Ноутбук не подключён';
    message(error.message);
    if (!classes.length) $('class-catalog').textContent = 'Включите бэкенд на ноутбуке и нажмите индикатор подключения, чтобы загрузить каталог.';
  }
  updateButton();
}
$('connection').addEventListener('click', () => { message(); checkHealth(); });
window.addEventListener('beforeunload', () => {
  if (cameraStream) cameraStream.getTracks().forEach(track => track.stop());
  controller?.abort();
});
checkHealth();
updateSensors();
