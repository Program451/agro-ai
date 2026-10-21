"""Exercise the real PHP gateway against a local fake backend, without user secrets."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def respond(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        is_json = self.headers.get('Content-Type', '').startswith('application/json')
        data = json.dumps({'query': parse_qs(urlsplit(self.path).query),
                           'body': json.loads(body) if is_json else None}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope='module')
def gateway(tmp_path_factory):
    php = os.getenv('AGRO_TEST_PHP') or shutil.which('php')
    if not php:
        pytest.skip('PHP with cURL is required; set AGRO_TEST_PHP to php.exe')
    args = [php]
    if 'curl' not in subprocess.check_output([php, '-m'], text=True).lower().split():
        args += ['-d', f'extension_dir={Path(php).parent / "ext"}', '-d', 'extension=curl']
    root = tmp_path_factory.mktemp('php-gateway')
    # Never copy config.local.php: a test must not connect to the real laptop.
    for name in ('api.php', 'config.php'):
        shutil.copy2(ROOT / 'frontend' / name, root / name)
    backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}/api.php'
    env = dict(os.environ, AGRO_BACKEND_URL=f'http://127.0.0.1:{backend.server_port}',
               AGRO_API_TOKEN='test-only-' + 'x' * 48)
    process = subprocess.Popen(args + ['-S', f'127.0.0.1:{port}', '-t', str(root)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        for _ in range(50):
            try:
                response = requests.get(url, params={'path': '/health'}, timeout=1)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.1)
        else:
            pytest.fail('Local PHP gateway did not start with cURL')
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('path', ['/detect/image', '/detect/video'])
@pytest.mark.parametrize('override', ['0.1', '0.9'])
def test_upload_threshold_cannot_be_changed(gateway, path, override):
    result = requests.post(gateway, params={'path': path, 'conf': override},
                           files={'file': ('fixture.bin', b'fake-media')}, timeout=5)
    assert result.status_code == 200
    assert result.json()['query']['conf'] == ['0.35']


def test_camera_threshold_is_fixed_and_image_is_preserved(gateway):
    result = requests.post(gateway, params={'path': '/detect/frame', 'conf': '0.9'},
                           json={'image': 'fixture-image', 'conf': 0.1}, timeout=5)
    assert result.status_code == 200
    assert result.json()['body'] == {'image': 'fixture-image', 'conf': 0.35}


def test_advice_context_is_unchanged(gateway):
    payload = {'image': 'fixture-image', 'sensor_device_id': 'esp32-test', 'field_note': 'test'}
    result = requests.post(gateway, params={'path': '/advice'}, json=payload, timeout=5)
    assert result.status_code == 200
    assert result.json()['body'] == payload


def test_invalid_camera_body_has_clear_error(gateway):
    result = requests.post(gateway, params={'path': '/detect/frame'}, data='not-json', timeout=5)
    assert result.status_code == 400
    assert result.json()['detail'] == 'Неверный формат кадра.'
