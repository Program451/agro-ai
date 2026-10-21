<?php
declare(strict_types=1);

// Existing ESP32 CSV: time,temp,hum,pressure,altitude,rain,soil.
// The writer stores Almaty time and pressure in hPa already.
function agro_sensor_snapshot(string $file, ?int $now = null): ?array {
    if (!is_file($file)) return null;
    $now ??= time();
    $handle = @fopen($file, 'rb');
    if (!$handle) throw new RuntimeException('Не удалось прочитать показания ESP32.');
    $samples = [];
    try {
        if (!flock($handle, LOCK_SH | LOCK_NB)) {
            throw new RuntimeException('ESP32 обновляет файл. Повторите запрос.');
        }
        // Read only the tail, even if the station has recorded data for months.
        $size = fstat($handle)['size'];
        if ($size > 1048576) {
            fseek($handle, -1048576, SEEK_END);
            fgets($handle); // Discard the first, possibly truncated record.
        }
        $zone = new DateTimeZone('Asia/Almaty');
        $utc = new DateTimeZone('UTC');
        $fields = [
            'temperature_c' => [-100, 150], 'humidity_pct' => [0, 100],
            'pressure_hpa' => [100, 1500], 'altitude_m' => [-1000, 20000],
            'rain_raw' => [0, 65535], 'soil_raw' => [0, 65535],
        ];
        while (($line = fgets($handle, 4096)) !== false) {
            // fputcsv terminates every complete packet with a newline.
            if (!str_ends_with($line, "\n")) continue;
            $row = str_getcsv(trim($line), ',', '"', '');
            if (count($row) !== 7) continue;
            $stamp = DateTimeImmutable::createFromFormat('!Y-m-d H:i:s', $row[0], $zone);
            if (!$stamp || $stamp->format('Y-m-d H:i:s') !== $row[0] || $stamp->getTimestamp() > $now) continue;
            $reading = ['device_id' => 'esp32-hosting'];
            $column = 1;
            foreach ($fields as $name => [$min, $max]) {
                $raw = trim((string)$row[$column++]);
                $value = $raw !== '' && is_numeric($raw) ? (float)$raw : null;
                $integer = str_ends_with($name, '_raw');
                if ($value !== null && (!is_finite($value) || $value < $min || $value > $max
                    || ($integer && floor($value) !== $value))) $value = null;
                $reading[$name] = $value !== null && $integer ? (int)$value : $value;
            }
            if ($reading['temperature_c'] === null || $reading['humidity_pct'] === null
                || $reading['pressure_hpa'] === null) continue;
            $samples[] = ['received_at' => $stamp->setTimezone($utc)->format('c'), 'reading' => $reading];
        }
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
    usort($samples, fn($a, $b) => strcmp($a['received_at'], $b['received_at']));
    $samples = array_slice($samples, -360);
    $latest = $samples ? $samples[count($samples) - 1] : null;
    $age = $latest ? max(0, $now - strtotime($latest['received_at'])) : null;
    return [
        'status' => $latest ? ($age > 120 ? 'stale' : 'live') : 'empty',
        'reading' => $latest['reading'] ?? null,
        'received_at' => $latest['received_at'] ?? null,
        'age_seconds' => $age,
        'source' => 'hosting', 'source_label' => 'ESP32 · хостинг',
        'samples' => $samples,
    ];
}

function agro_hosted_sensors(): ?array {
    $path = getenv('AGRO_SENSOR_CSV') ?: dirname(__DIR__, 2) . '/data.csv';
    return agro_sensor_snapshot($path);
}
