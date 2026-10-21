<?php
declare(strict_types=1);
// Same-origin gateway: the browser never sees the laptop token or its private address.
function fail(int $code, string $message): never {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['detail' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}
// The existing hosting station remains visible even when the laptop is off.
$path = (string)($_GET['path'] ?? '');
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($method === 'GET' && $path === '/sensors') {
    require_once __DIR__ . '/sensor-source.php';
    try {
        $sensors = agro_hosted_sensors();
    } catch (RuntimeException $error) {
        fail(503, $error->getMessage());
    }
    if ($sensors !== null) {
        unset($sensors['samples']);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        header('X-Content-Type-Options: nosniff');
        echo json_encode($sensors, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
        exit;
    }
}
$config = require __DIR__ . '/config.php';
if (!extension_loaded('curl')) fail(503, 'На хостинге необходимо включить PHP cURL.');
$base = rtrim($config['backend_url'], '/');
$parts = parse_url($base);
$isLocal = in_array($parts['host'] ?? '', ['127.0.0.1', 'localhost', '[::1]'], true);
if (!$parts || !isset($parts['host']) || (($parts['scheme'] ?? '') !== 'https' && !$isLocal)
    || strlen($config['api_token']) < 32) {
    fail(503, 'Подключение к ноутбуку не настроено. Заполните config.local.php на хостинге.');
}
$path = (string)($_GET['path'] ?? '');
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$getAllowed = preg_match('~^/(health|classes|sensors|jobs/[a-f0-9]{32}|video/[a-f0-9]{32}|stream|insights/history|insights/jobs/[a-f0-9-]{36}|insights/[a-f0-9-]{36}/image)$~D', $path);
$postAllowed = in_array($path, ['/detect/image', '/detect/video', '/detect/frame', '/advice'], true);
if (!(($method === 'GET' && $getAllowed) || ($method === 'POST' && $postAllowed))) {
    fail(404, 'Маршрут не найден');
}
// Disallow cross-site form submissions. The secret remains exclusively server-side.
if ($method === 'POST') {
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    if ($origin && parse_url($origin, PHP_URL_HOST) !== explode(':', $_SERVER['HTTP_HOST'] ?? '')[0]) {
        fail(403, 'Источник запроса не разрешён');
    }
    if (($_SERVER['HTTP_SEC_FETCH_SITE'] ?? '') === 'cross-site') fail(403, 'Источник запроса не разрешён');
}
$query = [];
foreach (['conf', 'max_seconds', 'url', 'session_id'] as $key) {
    if (isset($_GET[$key]) && is_string($_GET[$key])) $query[$key] = $_GET[$key];
}
$url = $base . '/api' . $path . ($query ? '?' . http_build_query($query) : '');
$curl = curl_init($url);
$headers = ['X-Agro-Token: ' . $config['api_token']];
$binary = str_starts_with($path, '/video/') || $path === '/stream' || str_ends_with($path, '/image') && str_starts_with($path, '/insights/');
$stream = $path === '/stream';
$options = [
    CURLOPT_HTTPHEADER => $headers,
    CURLOPT_CONNECTTIMEOUT => 10,
    CURLOPT_TIMEOUT => $stream ? 600 : 90,
    CURLOPT_FOLLOWLOCATION => false,
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
];
if ($method === 'POST') {
    $options[CURLOPT_POST] = true;
    if (str_starts_with($path, '/detect/') && in_array($path, ['/detect/image', '/detect/video'], true)) {
        $file = $_FILES['file'] ?? null;
        if (!$file || ($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
            fail(413, 'Файл не принят хостингом. Проверьте upload_max_filesize и post_max_size.');
        }
        $limit = $path === '/detect/image' ? 20 * 1024 * 1024 : 200 * 1024 * 1024;
        if ($file['size'] > $limit) fail(413, 'Файл превышает допустимый размер.');
        $options[CURLOPT_POSTFIELDS] = ['file' => new CURLFile($file['tmp_name'],
            'application/octet-stream', basename($file['name']))];
    } else {
        $body = file_get_contents('php://input', false, null, 0, 28000001);
        if (strlen($body) > 28000000) fail(413, 'Запрос слишком большой.');
        $headers[] = 'Content-Type: application/json';
        $options[CURLOPT_HTTPHEADER] = $headers;
        $options[CURLOPT_POSTFIELDS] = $body;
    }
}
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
if ($binary) {
    if (isset($_SERVER['HTTP_RANGE']) && preg_match('/^bytes=\d*-\d*$/D', $_SERVER['HTTP_RANGE'])) {
        $headers[] = 'Range: ' . $_SERVER['HTTP_RANGE'];
        $options[CURLOPT_HTTPHEADER] = $headers;
    }
    @set_time_limit($stream ? 610 : 100);
    if ($stream) {
        header('X-Accel-Buffering: no');
        while (ob_get_level()) ob_end_flush();
    }
    $options[CURLOPT_HEADERFUNCTION] = function ($ch, $line) {
        if (preg_match('~^HTTP/\S+ (\d{3})~', $line, $match)) http_response_code((int)$match[1]);
        if (preg_match('~^(Content-Type|Content-Length|Content-Range|Accept-Ranges):~i', $line)) {
            header(trim($line), true);
        }
        return strlen($line);
    };
    $options[CURLOPT_WRITEFUNCTION] = function ($ch, $data) use ($stream) {
        if (connection_aborted()) return 0;
        echo $data;
        if ($stream) flush();
        return strlen($data);
    };
} else {
    $options[CURLOPT_RETURNTRANSFER] = true;
}
curl_setopt_array($curl, $options);
$result = curl_exec($curl);
$status = curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
curl_close($curl);
if ($result === false && !headers_sent()) fail(502, 'Ноутбук недоступен. Включите Python-сервер и туннель.');
if (!$binary) {
    http_response_code($status ?: 502);
    header('Content-Type: application/json; charset=utf-8');
    // Tunnel error pages are not JSON; present a useful error without leaking upstream HTML.
    if (!is_string($result) || json_decode($result) === null) {
        fail(502, 'Нет ответа от ноутбука. Проверьте сервер, туннель и адрес в настройках.');
    }
    echo $result;
}
