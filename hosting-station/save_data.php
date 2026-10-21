<?php
header('Content-Type: application/json; charset=utf-8');
date_default_timezone_set('Asia/Almaty');

if ($_SERVER['REQUEST_METHOD'] !== 'GET' &&
    $_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode([
        'status' => 'error',
        'message' => 'Method not allowed'
    ]);
    exit;
}

function readNumber($name, $min, $max) {
    if (!isset($_REQUEST[$name]) || $_REQUEST[$name] === '') {
        return null;
    }

    $value = filter_var($_REQUEST[$name], FILTER_VALIDATE_FLOAT);

    if ($value === false || $value < $min || $value > $max) {
        return null;
    }

    return (float)$value;
}

// Принимаем имена параметров из ESP32
$temp     = readNumber('temp', -50, 100);
$hum      = readNumber('hum', 0, 100);
$pressure = readNumber('pressure', 300, 1200); // гПа
$altitude = readNumber('altitude', -1000, 10000);
$rain     = readNumber('rain', 0, 100000);
$soil     = readNumber('soil', 0, 100000);

// Проверяем обязательные показания
if ($temp === null || $hum === null || $pressure === null) {
    http_response_code(400);
    echo json_encode([
        'status' => 'error',
        'message' => 'Missing or invalid temp, hum or pressure'
    ]);
    exit;
}

$file = __DIR__ . '/data.csv';
$handle = fopen($file, 'c+');

if (!$handle) {
    http_response_code(500);
    echo json_encode([
        'status' => 'error',
        'message' => 'Cannot open data.csv'
    ]);
    exit;
}

if (!flock($handle, LOCK_EX)) {
    fclose($handle);
    http_response_code(500);
    echo json_encode([
        'status' => 'error',
        'message' => 'Cannot lock data.csv'
    ]);
    exit;
}

fseek($handle, 0, SEEK_END);
$isEmpty = ftell($handle) === 0;

if ($isEmpty) {
    fputcsv($handle, [
        'time', 'temp', 'hum', 'pressure',
        'altitude', 'rain', 'soil'
    ]);
}

$time = date('Y-m-d H:i:s');

fputcsv($handle, [
    $time,
    $temp,
    $hum,
    $pressure,
    $altitude ?? '',
    $rain ?? '',
    $soil ?? ''
]);

fflush($handle);
flock($handle, LOCK_UN);
fclose($handle);

echo json_encode([
    'status' => 'ok',
    'message' => 'Data saved',
    'time' => $time
]);
