<?php
declare(strict_types=1);
require __DIR__ . '/../frontend/sensor-source.php';
function check($condition, $message) { if (!$condition) throw new RuntimeException($message); }
$file = tempnam(sys_get_temp_dir(), 'agro-test-');
$now = strtotime('2026-10-22T00:00:00+00:00');
$row = '"2026-10-20 04:50:02",19.6,35,951.39,528.25,2448,0' . "\n";
try {
    foreach (['', "\n", "time,temp,hum,pressure,altitude,rain,soil\n"] as $prefix) {
        file_put_contents($file, $prefix . $row);
        $data = agro_sensor_snapshot($file, $now);
        check(!array_key_exists('soil_raw', $data['reading']), 'Legacy soil placeholder is not a measurement');
        check($data['reading']['pressure_hpa'] === 951.39, 'Pressure is already in hPa');
        check($data['received_at'] === '2026-10-19T23:50:02+00:00', 'Almaty to UTC');
        check($data['status'] === 'stale', 'Historical data is not live');
        check(count($data['samples']) === 1, 'No lost first row');
    }
    file_put_contents($file, $row . '"2026-10-22 05:00:00",20,0,951.39,,0,' . "\n");
    $data = agro_sensor_snapshot($file, $now);
    check($data['status'] === 'live', 'Fresh data must be live');
    check($data['reading']['humidity_pct'] === 0.0, 'Zero humidity is not missing');
    check($data['reading']['altitude_m'] === null, 'Missing values stay null');
    check($data['reading']['rain_raw'] === 0, 'Real zero rain reading is retained');
    file_put_contents($file, '"2026-10-22 05:00:00",20,35,951.39,500,0' . "\n");
    $data = agro_sensor_snapshot($file, $now);
    check($data['status'] === 'live' && $data['reading']['rain_raw'] === 0, 'Five-sensor packets are supported');
    check(!str_contains(json_encode($data), 'soil_raw'), 'No soil in the complete feed');
    file_put_contents($file, $row
        . '"2026-99-20 04:50:02",20,35,951.39,500,100,0' . "\n"
        . '"2027-01-01 04:50:02",20,35,951.39,500,100,0' . "\n"
        . '"2026-10-21 04:50:02",20,35,NaN,500,100,0' . "\n"
        . '"2026-10-21 04:50:02",20,35,951.39,500,100,0');
    check(count(agro_sensor_snapshot($file, $now)['samples']) === 1, 'Skip invalid, future and incomplete packets');
    file_put_contents($file, str_repeat($row, 24000));
    check(count(agro_sensor_snapshot($file, $now)['samples']) === 360, 'Bound history and large files');
    file_put_contents($file, '');
    check(agro_sensor_snapshot($file, $now)['status'] === 'empty', 'Empty source has no invented values');
    check(agro_sensor_snapshot($file . '.missing', $now) === null, 'Local installations may have no CSV');
    echo "Sensor CSV checks passed.\n";
} finally { unlink($file); }
