<?php

declare(strict_types=1);
header('Content-Type: text/html; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');
function icon(string $name, string $class = ''): string {
    $paths = [
        'leaf' => '<path d="M20 4c-9-2-17 3-13 10 7 4 12-4 13-10Z"/><path d="m4 21 11-11"/>',
        'grid' => '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
        'photo' => '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8" cy="9" r="1.5"/><path d="m4 18 6-6 4 4 3-3 4 4"/>',
        'video' => '<rect x="3" y="5" width="13" height="14" rx="3"/><path d="m16 10 5-3v10l-5-3"/>',
        'camera' => '<path d="M8 5 9 3h6l1 2h4v15H4V5z"/><circle cx="12" cy="12" r="4"/>',
        'upload' => '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
        'arrow' => '<path d="M4 12h16m-6-6 6 6-6 6"/>',
        'scan' => '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M6 12h12"/>',
        'spark' => '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
        'bug' => '<rect x="8" y="7" width="8" height="13" rx="4"/><path d="m9 3 3 4 3-4M4 10h4m8 0h4M4 16h4m8 0h4M12 8v12"/>',
        'download' => '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
        'shield' => '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
        'temperature' => '<path d="M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0Z"/><path d="M12 8v10"/><circle cx="12" cy="18" r="1"/>',
        'drop' => '<path d="M12 3s-7 8-7 12a7 7 0 0 0 14 0c0-4-7-12-7-12Z"/><path d="M9 15a3 3 0 0 0 3 3"/>',
        'pressure' => '<circle cx="12" cy="12" r="9"/><path d="m12 12 4-4M5 12h2m10 0h2M12 5v2"/><circle cx="12" cy="12" r="1"/>',
        'altitude' => '<path d="m2 20 7-13 4 7 3-5 6 11H2Zm4-7 3 1 2-2M17 3v4m-2-2 2-2 2 2"/>',
        'rain' => '<path d="M6 15a4 4 0 0 1-1-8 6 6 0 0 1 11-1 4 4 0 1 1 2 9M8 18l-1 3m6-3-1 3m6-3-1 3"/>',
    ];
    return '<svg class="icon ' . $class . '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' . ($paths[$name] ?? $paths['leaf']) . '</svg>';
}
$modes = ['photo' => 'Фото', 'video' => 'Видео', 'camera' => 'Камера / OBS'];
require_once __DIR__ . '/sensor-source.php';
$file = getenv('AGRO_SENSOR_CSV') ?: dirname(__DIR__, 2) . '/data.csv';
function getLatestData($file) {
    try { $snapshot = agro_sensor_snapshot($file); }
    catch (RuntimeException $error) { return null; }
    if (!$snapshot || !$snapshot['reading']) return null;
    $reading = $snapshot['reading'];
    return [
        'time' => (new DateTimeImmutable($snapshot['received_at']))->setTimezone(new DateTimeZone('Asia/Almaty'))->format('Y-m-d H:i:s'),
        'temperature' => $reading['temperature_c'], 'humidity' => $reading['humidity_pct'],
        'pressure' => $reading['pressure_hpa'], 'altitude' => $reading['altitude_m'],
        'rain' => $reading['rain_raw'], 'soil' => $reading['soil_raw'],
    ];
}

// Запрос данных для автоматического обновления
if (isset($_GET['data'])) {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(
        getLatestData($file),
        JSON_UNESCAPED_UNICODE
    );
    exit;
}

$data = getLatestData($file);
?>
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#143628">
  <meta name="description" content="EginQanat AI — анализ вредителей и состояния поля по фото и видео.">
  <title>Анализ поля · EginQanat AI</title>
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="assets/app.css?v=8">
  <link rel="stylesheet" href="assets/insights.css?v=3">
  <script src="assets/camera.js?v=1" defer></script>
  <script src="assets/app.js?v=10" defer></script>
  <script src="assets/watch.js?v=1" defer></script>
  <script src="assets/insights.js?v=4" defer></script>
</head>
<body>
<a class="skip" href="#main">Перейти к анализу</a>
<aside class="sidebar">
  <a class="brand" href="./"><span class="brand-icon"><?= icon('leaf') ?></span><span>EginQanat <small>AI</small></span></a>
  <div class="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div>
  <nav aria-label="Главная навигация">
    <button class="nav-link active" id="show-analysis" aria-current="page"><?= icon('grid') ?>Анализ поля<span class="nav-dot"></span></button>
  </nav>
  <div class="sidebar-note"><div class="mini-leaf"><?= icon('leaf') ?></div><strong>Забота о поле.<br>Точность в деталях.</strong><p>Компьютерное зрение<br>для вашего хозяйства.</p><div class="field-lines"></div></div>
  <div class="sidebar-footer"><span class="connection-dot"></span><span>EginQanat AI <small>Модель YOLO11</small></span><span class="version">v2.0</span></div>
</aside>
<div class="workspace">
  <header class="topbar"><div><span class="breadcrumb">Рабочее пространство</span><span class="slash">/</span><span id="breadcrumb-current">Анализ поля</span></div><span class="top-right"><?= icon('leaf') ?> Умное земледелие</span></header>
  <main id="main">
    <section id="page-analysis">
      <div class="page-heading"><div><div class="eyebrow">НАБЛЮДАЙТЕ. АНАЛИЗИРУЙТЕ. ДЕЙСТВУЙТЕ.</div><h1>Анализ поля<span class="title-dot">.</span></h1><p>Здоровье вашего поля — в деталях.</p></div><button id="connection" class="status" title="Проверить подключение"><span class="connection-dot"></span><span id="connection-label">Проверяем подключение</span></button></div>
      <div class="tabs" role="tablist" aria-label="Источник анализа">
      <?php foreach ($modes as $mode => $label): ?>
        <button id="tab-<?= $mode ?>" class="tab <?= $mode === 'photo' ? 'active' : '' ?>" role="tab" aria-selected="<?= $mode === 'photo' ? 'true' : 'false' ?>" aria-controls="analysis-panel" tabindex="<?= $mode === 'photo' ? '0' : '-1' ?>" data-mode="<?= $mode ?>"><?= icon($mode) ?><?= $label ?></button>
      <?php endforeach; ?>
      </div>
      <div id="message" class="message" role="alert" hidden></div>
      <section id="camera-help" class="camera-help card" aria-labelledby="camera-help-title" hidden>
        <h2 id="camera-help-title">Как подключить камеру</h2>
        <ol>
          <li>Оставьте виртуальную камеру включённой в OBS.</li>
          <li>Если сайт открыт внутри ChatGPT, скопируйте адрес ниже и вставьте его в отдельный Chrome, Edge или Яндекс Браузер на этом ноутбуке. Открытие ещё одной вкладки внутри ChatGPT не меняет доступ к камере.</li>
          <li>Разрешите камеру для сайта в настройках браузера рядом с адресной строкой.</li>
          <li>Если запрет остаётся, в Windows откройте «Параметры → Конфиденциальность и безопасность → Камера». Проверьте доступ к камере и разрешение для классических приложений.</li>
          <li>Обновите сайт, нажмите «Найти камеры», выберите «OBS Virtual Camera» и нажмите «Запустить камеру».</li>
        </ol>
        <label for="camera-page-url">Адрес сайта для отдельного браузера</label>
        <div class="camera-link-row"><input id="camera-page-url" type="text" readonly><button id="copy-camera-url" class="button secondary" type="button">Скопировать адрес</button></div>
        <p id="camera-copy-status" class="small-note" aria-live="polite">Микрофон для анализа не нужен.</p>
      </section>
      <div class="analysis-grid" id="analysis-panel" role="tabpanel" aria-labelledby="tab-photo">
        <section class="input-card card">
          <div class="card-top"><div><span class="section-number">01</span><h2 id="input-title">Снимок для анализа</h2></div><span id="source-tag" class="muted-label">JPG, PNG, WEBP</span></div>
          <div id="dropzone" class="dropzone">
            <div id="empty-view">
              <div class="landscape" aria-hidden="true"><svg viewBox="0 0 320 110" fill="none"><circle cx="242" cy="26" r="15" fill="#e9edcf"/><path d="M5 85Q100 0 195 69T315 60v50H5" fill="#e4ebdd"/><path d="M5 96Q160 20 315 82v28H5" fill="#cad9bc"/><path d="M20 110q70-60 210-43M75 110q70-45 180-37M134 110q50-30 152-26M200 110q35-20 105-15" stroke="#f5f7ef" stroke-width="3"/><path d="M107 53V25m0 18Q83 44 88 25q19 0 19 18m0-7q0-19 18-18 2 18-18 18" stroke="#5d7c50" stroke-width="2.5" stroke-linecap="round"/></svg></div>
              <span class="upload-icon"><?= icon('upload') ?></span>
              <h3 id="empty-title">Здесь начинается забота о поле</h3>
              <p id="empty-description">Перетащите снимок растения или поля<br>или выберите файл на устройстве</p>
              <button class="button secondary" id="choose-file"><?= icon('photo') ?>Выбрать файл</button>
              <button class="button primary" id="connect-obs" type="button" hidden><?= icon('camera') ?><span id="connect-obs-label">Подключить OBS</span></button>
              <span id="file-hint" class="file-hint">JPG, PNG, WebP · до 20 МБ</span>
            </div>
            <img id="image-preview" alt="Снимок для анализа" hidden>
            <video id="video-preview" controls playsinline hidden></video>
            <video id="camera-video" autoplay muted playsinline hidden></video>
            <canvas id="camera-canvas" hidden aria-label="Кадр камеры с найденными объектами"></canvas>
            <div id="processing" class="processing" hidden><span class="spinner"></span><strong id="processing-text">Анализируем снимок…</strong><span>Модель работает на ноутбуке</span></div>
          </div>
          <input type="file" id="file-input" accept="image/jpeg,image/png,image/webp" hidden>
          <div class="file-meta" id="file-meta" hidden><span id="file-name"></span><button class="text-button" id="reset-file">Удалить</button></div>
          <label class="original-toggle" id="original-control" hidden><input type="checkbox" id="show-original"> Показать оригинал</label>
          <div id="camera-controls" class="camera-controls" hidden>
            <label for="camera-device">Источник видео</label>
            <div class="camera-select-row"><select id="camera-device"><option value="obs-auto">OBS Virtual Camera</option><option value="default">Камера по умолчанию</option></select><button id="refresh-cameras" class="button secondary" type="button">Найти камеры</button></div>
            <p class="small-note">В OBS выберите сцену с телефоном, дроном или камерой и нажмите «Запустить виртуальную камеру». Затем выберите OBS здесь. Для списка устройств браузер запросит доступ к камере.</p>
          </div>
          <div class="controls"><button class="button primary" id="analyze" disabled><?= icon('scan') ?><span id="analyze-label">Начать анализ</span></button><button class="button secondary" id="stop" hidden>Остановить</button></div>
          <div class="privacy-note"><?= icon('shield') ?><span>Анализ выполняется вашей моделью на ноутбуке.</span></div>
        </section>
        <section class="results-card card" aria-live="polite" aria-atomic="false">
          <div class="card-top"><div><span class="section-number">02</span><h2>Результаты анализа</h2></div><span class="small-dot"></span></div>
          <div class="result-status" id="result-status">Ожидание данных</div>
          <div id="result-empty" class="result-empty"><span class="result-illustration"><?= icon('scan') ?><i></i></span><h3>Увидеть больше</h3><p>Загрузите снимок — здесь появятся<br>найденные объекты и их уверенность.</p></div>
          <div id="result-list" class="result-list" hidden></div>
          <div class="stat-grid"><div><span><?= icon('scan') ?><span id="stat-one-label">Объекты</span></span><strong id="stat-total">—</strong></div><div><span><?= icon('bug') ?><span id="stat-two-label">Вредители</span></span><strong id="stat-pests">—</strong></div></div>
          <p class="result-note" id="result-note">Результаты появятся после анализа.</p>
          <div id="timeline" class="timeline" hidden aria-label="Число обнаружений по времени"></div>
          <div class="downloads" id="downloads" hidden><a id="download-media" class="text-button" download><?= icon('download') ?>Результат</a><button id="download-json" class="text-button">Отчёт JSON</button></div>
          <button class="button advice-button" id="advice" disabled><?= icon('spark') ?>Начать общий анализ<?= icon('arrow') ?></button>
          <p class="small-note advice-note" id="advice-note">Совместный анализ кадра и показаний ESP32.</p>
          <div id="advice-text" class="advice-text" hidden></div>
        </section>
      </div>
      <section class="ai-panel card" id="ai-panel" aria-labelledby="ai-heading">
        <div class="sensors-heading"><div><span class="sensor-kicker">GEMINI · ИЗОБРАЖЕНИЕ + ESP32</span><h2 id="ai-heading">Наблюдение и прогноз рисков</h2></div><span class="sensor-state" id="ai-provider">Проверяем Gemini</span></div>
        <p class="ai-intro">Сопоставьте вид растения с условиями на поле. Получайте наблюдения, условные риски на 24–48 часов и следующие шаги.</p>
        <button class="button secondary" id="ai-stop" hidden>Остановить AI</button>
        <p class="ai-hint" id="ai-hint">Подключите камеру / OBS или загрузите файл.</p>
        <p class="ai-disclosure">После нажатия кнопки кадр и последние показания за 30 минут отправляются в Google Gemini. В режиме наблюдения — новый запрос через 30 секунд после ответа; расходуется квота вашего API. При скрытии вкладки режим останавливается.</p>
        <div class="ai-status" id="ai-status" role="status">Готов к совместному анализу.</div>
        <div id="ai-empty" class="ai-empty"><span><?= icon('leaf') ?></span><p>Здесь появится совместный отчёт.<br>Если датчиков нет или данные устарели, это будет указано.</p></div>
        <article id="ai-report" hidden>
          <div class="ai-report-head"><a id="ai-frame-link" target="_blank" rel="noopener" title="Открыть кадр наблюдения"><img id="ai-frame" alt="Кадр, использованный в AI-отчёте"></a><div><span class="sensor-kicker">СОХРАНЁННОЕ НАБЛЮДЕНИЕ</span><p id="ai-meta"></p><p id="ai-summary"></p><button class="text-button" id="ai-export" disabled><?= icon('download') ?>Скачать отчёт и показания JSON</button></div></div>
          <div id="ai-details" class="ai-details"></div>
        </article>
        <details class="ai-journal"><summary>Журнал наблюдений</summary><p class="small-note">Сохраняются отдельные кадры, использованные показания и отчёты — до 500 наблюдений на ноутбуке. Полную видеозапись включайте в OBS.</p><div class="ai-journal-top"><p id="ai-history-note" class="small-note">Загружаем журнал…</p><button class="text-button" id="ai-refresh">Обновить</button></div><div id="ai-history"></div></details>
      </section>
      <section class="sensors-panel card" aria-labelledby="sensors-heading">
        <div class="sensors-heading"><div><span class="sensor-kicker">ТЕЛЕМЕТРИЯ ESP32</span><h2 id="sensors-heading">Что происходит на поле</h2></div><button id="refresh-sensors" class="sensor-state"><span class="connection-dot"></span><span id="sensor-status">Нет данных</span></button></div>
        <div class="sensor-grid">
<?php
// Соединяем ID карточки с названием поля из data.csv.
$sensorValues = [
    'temperature_c' => $data['temperature'] ?? '--',
    'humidity_pct'  => $data['humidity'] ?? '--',
    'pressure_hpa'  => $data['pressure'] ?? '--',
    'altitude_m'    => $data['altitude'] ?? '--',
    'rain_raw'      => $data['rain'] ?? '--',
    'soil_raw'      => $data['soil'] ?? '--',
];
?>
<?php foreach ([
    ['temperature_c','temperature','Температура','°C'],
    ['humidity_pct','drop','Влажность воздуха','%'],
    ['pressure_hpa','pressure','Давление','гПа'],
    ['altitude_m','altitude','Высота','м'],
    ['rain_raw','rain','Датчик дождя','ADC'],
] as [$key,$symbol,$label,$unit]): ?>
            <div class="sensor-tile">
              <span class="sensor-label"><?= icon($symbol) ?><?= htmlspecialchars($label, ENT_QUOTES, 'UTF-8') ?></span>
              <div><strong id="sensor-<?= htmlspecialchars($key, ENT_QUOTES, 'UTF-8') ?>"><?= htmlspecialchars((string)($sensorValues[$key] ?? '--'), ENT_QUOTES, 'UTF-8') ?></strong><span class="sensor-unit"><?= htmlspecialchars($unit, ENT_QUOTES, 'UTF-8') ?></span></div>
            </div>
<?php endforeach; ?>
        </div>
        <div class="sensor-footer"><span id="sensor-updated">Ожидаем первое показание от ESP32</span><span>Дождь: сырые значения, без калибровки</span></div>
      </section>
    </section>
    <footer><span>EginQanat AI <span class="footer-dot">·</span> Технологии на стороне вашего поля</span></footer>
  </main>
</div>
</body>
</html>
