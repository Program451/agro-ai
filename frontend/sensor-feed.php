<?php
declare(strict_types=1);
require_once __DIR__ . '/sensor-source.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    http_response_code(405);
    header('Allow: GET');
    echo json_encode(['detail' => 'Method not allowed']);
    exit;
}
try {
    $data = agro_hosted_sensors();
    if ($data === null) {
        http_response_code(404);
        $data = ['detail' => 'Файл показаний ESP32 пока не найден.'];
    }
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
} catch (RuntimeException $error) {
    http_response_code(503);
    echo json_encode(['detail' => $error->getMessage()], JSON_UNESCAPED_UNICODE);
}
