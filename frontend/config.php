<?php
declare(strict_types=1);
// Keep the token server-side. It must never be embedded in HTML or JavaScript.
$config = [
    'backend_url' => getenv('AGRO_BACKEND_URL') ?: '',
    'api_token' => getenv('AGRO_API_TOKEN') ?: '',
];
$local = __DIR__ . '/config.local.php';
if (is_file($local)) {
    $override = require $local;
    if (is_array($override)) {
        $config = array_replace($config, $override);
    }
}
return $config;
