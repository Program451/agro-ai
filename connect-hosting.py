"""Run the laptop API and a temporary HTTPS tunnel for the hosted PHP frontend."""
from pathlib import Path
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run" / "hosting"
SITE = "https://dron.itudron.ru/agro-ai/frontend/"
LOCAL = "http://127.0.0.1:8000"


def php_config(url, token):
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname
            or not parts.hostname.endswith(".trycloudflare.com")
            or parts.username or parts.password or parts.port
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError("Invalid HTTPS tunnel address")
    if len(token) < 32:
        raise ValueError("Invalid AGRO_API_TOKEN in .env")
    quote = lambda value: value.replace("\\", "\\\\").replace("'", "\\'")
    return ("<?php\nreturn [\n    'backend_url' => '" + quote(url.rstrip("/"))
            + "',\n    'api_token' => '" + quote(token) + "',\n];\n")


def ready(url, token):
    try:
        response = requests.get(url + "/api/health", headers={"X-Agro-Token": token},
                                timeout=(3, 5), allow_redirects=False)
        return response.status_code == 200 and response.json().get("status") == "ready"
    except (requests.RequestException, ValueError):
        return False


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    # A Windows lock is released by the OS even if the console is closed.
    lock = (RUN / "launcher.lock").open("a+b")
    lock.seek(0)
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit("Подключение уже запущено. Используйте открытое окно AgroAI.")
    values = dotenv_values(ROOT / ".env")
    token = values.get("AGRO_API_TOKEN") or ""
    if len(token) < 32:
        raise SystemExit("В .env не найден AGRO_API_TOKEN. Сначала выполните setup.py.")
    executable = ROOT / "tools" / "cloudflared.exe"
    if not executable.is_file():
        raise SystemExit("Не найден tools/cloudflared.exe. Установите cloudflared от Cloudflare.")
    backend = tunnel = None
    backend_log = tunnel_log = None
    hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        if not ready(LOCAL, token):
            print("Запускаю ИИ на ноутбуке…", flush=True)
            backend_log = (RUN / "backend.log").open("w", encoding="utf-8")
            environment = dict(os.environ, AGRO_HOST="127.0.0.1", AGRO_PORT="8000")
            backend = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT,
                                       stdout=backend_log, stderr=subprocess.STDOUT,
                                       env=environment, creationflags=hidden)
            deadline = time.monotonic() + 60
            while not ready(LOCAL, token):
                if backend.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("ИИ не запустился. Подробности: run/hosting/backend.log")
                time.sleep(1)
        print("ИИ готов. Подключаю HTTPS-туннель…", flush=True)
        log_path = RUN / "tunnel.log"
        tunnel_log = log_path.open("w", encoding="utf-8")
        tunnel = subprocess.Popen([str(executable), "tunnel", "--no-autoupdate",
                                   "--protocol", "http2", "--url", LOCAL], cwd=ROOT,
                                  stdout=tunnel_log, stderr=subprocess.STDOUT,
                                  creationflags=hidden)
        deadline = time.monotonic() + 120
        url = None
        while time.monotonic() < deadline:
            if tunnel.poll() is not None:
                raise RuntimeError("Туннель остановился. Подробности: run/hosting/tunnel.log")
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com",
                              log_path.read_text(encoding="utf-8", errors="replace"))
            if match and ready(match[0], token):
                url = match[0]
                break
            time.sleep(2)
        if not url:
            raise RuntimeError("Туннель не подключился за 2 минуты. Проверьте Интернет и tunnel.log.")
        config = RUN / "config.local.php"
        temporary = config.with_suffix(".tmp")
        temporary.write_text(php_config(url, token), encoding="utf-8")
        temporary.replace(config)
        (RUN / "address.txt").write_text(url + "\n", encoding="utf-8")
        print("\nПодключение ноутбука готово.", flush=True)
        print("Загрузите этот файл на хостинг в папку agro-ai/frontend/:", flush=True)
        print(config, flush=True)
        print("Ключ Gemini остался только в .env на ноутбуке.", flush=True)
        print("Затем откройте: " + SITE, flush=True)
        print("Оставьте это окно открытым. Для остановки нажмите Ctrl+C.", flush=True)
        print("После нового запуска адрес изменится: загрузите обновлённый config.local.php.", flush=True)
        if os.name == "nt":
            os.startfile(RUN)
        while tunnel.poll() is None and (backend is None or backend.poll() is None):
            time.sleep(1)
        raise RuntimeError("Подключение прервано. Проверьте журналы в run/hosting и запустите снова.")
    except KeyboardInterrupt:
        print("\nПодключение остановлено.")
    except (RuntimeError, OSError, ValueError) as error:
        print("\nОшибка: " + str(error), file=sys.stderr)
        return 1
    finally:
        stop(tunnel)
        stop(backend)
        if tunnel_log:
            tunnel_log.close()
        if backend_log:
            backend_log.close()
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
