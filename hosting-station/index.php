<?php
date_default_timezone_set('Asia/Almaty');

$file = __DIR__ . '/data.csv';

function getLatestData($file) {
    if (!is_file($file) || !is_readable($file)) {
        return null;
    }

    $handle = fopen($file, 'r');
    if (!$handle) {
        return null;
    }

    flock($handle, LOCK_SH);

    $latest = null;


    while (($row = fgetcsv($handle)) !== false) {
        if (count($row) >= 7 && preg_match('/^\d{4}-\d{2}-\d{2} /', $row[0])) {
            $latest = $row;
        }
    }

    flock($handle, LOCK_UN);
    fclose($handle);

    if (!$latest) {
        return null;
    }

    return [
        'time' => $latest[0],
        'temperature' => $latest[1],
        'humidity' => $latest[2],
        'pressure' => $latest[3],
        'altitude' => $latest[4],
        'rain' => $latest[5],
        'soil' => $latest[6]
    ];
}

// Запрос данных для автоматического обновления
if (isset($_GET['data'])) {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode(
        getLatestData($file),
        JSON_UNESCAPED_UNICODE
    );
    exit;
}

$data = getLatestData($file);
?>
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Метеостанция ESP32</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #f1f5f9;
    color: #172033;
}

header {
    background: #123b63;
    color: white;
    padding: 28px 16px;
    text-align: center;
}

header h1 {
    margin: 0 0 8px;
}

header p {
    margin: 0;
    color: #dbeafe;
}

main {
    max-width: 1000px;
    margin: 28px auto;
    padding: 0 16px;
}

.status {
    margin-bottom: 18px;
    color: #475569;
}

.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
}

.card {
    background: white;
    border-radius: 14px;
    padding: 22px;
    box-shadow: 0 3px 12px #0f172a12;
}

.label {
    font-size: 15px;
    color: #64748b;
}

.value {
    margin-top: 12px;
    font-size: 30px;
    font-weight: bold;
    overflow-wrap: anywhere;
}

.unit {
    font-size: 16px;
    color: #64748b;
}

footer {
    text-align: center;
    color: #64748b;
    padding: 24px 12px;
}

@media (max-width: 480px) {
    .value {
        font-size: 26px;
    }
}
</style>
</head>

<body>

<header>
    <h1>Метеостанция ESP32</h1>
    <p>Мониторинг окружающей среды в реальном времени</p>
</header>

<main>
    <div class="status">
        Последнее измерение:
        <strong id="time">
            <?= htmlspecialchars($data['time'] ?? 'Ожидание данных') ?>
        </strong>
    </div>

    <div class="grid">

        <div class="card">
            <div class="label">🌡️ Температура воздуха</div>
            <div class="value">
                <span id="temperature"><?= htmlspecialchars((string)($data['temperature'] ?? '--')) ?></span>
                <span class="unit">°C</span>
            </div>
        </div>

        <div class="card">
            <div class="label">💧 Влажность воздуха</div>
            <div class="value">
                <span id="humidity"><?= htmlspecialchars((string)($data['humidity'] ?? '--')) ?></span>
                <span class="unit">%</span>
            </div>
        </div>

        <div class="card">
            <div class="label">🌤️ Атмосферное давление</div>
            <div class="value">
                <span id="pressure"><?= isset($data['pressure']) ? htmlspecialchars((string)round((float)$data['pressure'], 2)) : '--' ?></span>
                <span class="unit">гПа</span>
            </div>
        </div>

        <div class="card">
            <div class="label">⛰️ Высота</div>
            <div class="value">
                <span id="altitude"><?= htmlspecialchars((string)($data['altitude'] ?? '--')) ?></span>
                <span class="unit">м</span>
            </div>
        </div>

        <div class="card">
            <div class="label">🌧️ Датчик дождя</div>
            <div class="value" id="rain">
                <?= htmlspecialchars((string)($data['rain'] ?? '--')) ?>
            </div>
            <div class="unit">Значение датчика</div>
        </div>

        <div class="card">
            <div class="label">🌱 Влажность почвы</div>
            <div class="value" id="soil">
                <?= htmlspecialchars((string)($data['soil'] ?? '--')) ?>
            </div>
            <div class="unit">Значение датчика</div>
        </div>

    </div>
</main>

<footer>
    Данные поступают с ESP32 · Обновление каждые 3 секунды
</footer>

<script>
async function updateData() {
    try {
        const response = await fetch('index.php?data=1&_=' + Date.now(), {
            cache: 'no-store'
        });

        if (!response.ok) {
            throw new Error('Ошибка загрузки');
        }

        const data = await response.json();

        if (!data) {
            return;
        }

        document.getElementById('time').textContent = data.time ?? '--';
        document.getElementById('temperature').textContent = data.temperature ?? '--';
        document.getElementById('humidity').textContent = data.humidity ?? '--';

        document.getElementById('pressure').textContent =
            data.pressure != null && data.pressure !== ''
                ? Number(data.pressure).toFixed(2)
                : '--';

        document.getElementById('altitude').textContent = data.altitude ?? '--';
        document.getElementById('rain').textContent = data.rain ?? '--';
        document.getElementById('soil').textContent = data.soil ?? '--';

    } catch (error) {
        console.log('Не удалось обновить показания:', error);
    }
}

updateData();
setInterval(updateData, 3000);
</script>

</body>
</html>