"""Run and stop the two local services. Hosted PHP only needs server.py on the laptop."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    RUN.mkdir(exist_ok=True)
    marker = RUN / "stop.request"
    if args.stop:
        marker.touch()
        print("Stop requested.")
        return
    from setup import configure
    from dotenv import load_dotenv
    configure()
    load_dotenv(ROOT / ".env")
    local = ROOT / "local-run.json"
    local_config = json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}
    php = os.getenv("AGRO_PHP_BIN") or shutil.which("php") or local_config.get("php")
    if not php or not Path(php).is_file():
        raise SystemExit("PHP not found. Install PHP 8.1+ with cURL, or set AGRO_PHP_BIN to php.exe.")
    backend_port = int(os.getenv("AGRO_PORT", "8000"))
    for port in (backend_port, 8080):
        with socket.socket() as check:
            if check.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is already in use. Stop the previous server first.")
    marker.unlink(missing_ok=True)
    children, logs = [], []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        python_log = open(RUN / "python.log", "w", encoding="utf-8")
        logs.append(python_log)
        backend = subprocess.Popen([sys.executable, str(ROOT / "server.py")], cwd=ROOT,
                                   stdout=python_log, stderr=subprocess.STDOUT, creationflags=flags)
        children.append(backend)
        request = urllib.request.Request(f"http://127.0.0.1:{backend_port}/api/health",
                                         headers={"X-Agro-Token": os.environ["AGRO_API_TOKEN"]})
        for _ in range(60):
            if backend.poll() is not None:
                raise RuntimeError("Backend failed to start. See run/python.log.")
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    if json.load(response)["status"] == "ready":
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Model startup timed out. See run/python.log.")
        php_args = [str(php)]
        modules = subprocess.check_output([str(php), "-m"], text=True, creationflags=flags)
        if "curl" not in modules.lower().split():
            php_args += ["-d", f"extension_dir={Path(php).parent / 'ext'}", "-d", "extension=curl"]
        php_args += ["-d", "upload_max_filesize=200M", "-d", "post_max_size=205M",
                     "-d", "max_execution_time=100", "-d", "memory_limit=128M",
                     "-S", "127.0.0.1:8080", "-t", str(ROOT / "frontend")]
        php_log = open(RUN / "php.log", "w", encoding="utf-8")
        logs.append(php_log)
        frontend = subprocess.Popen(php_args, cwd=ROOT, stdout=php_log,
                                    stderr=subprocess.STDOUT, creationflags=flags)
        children.append(frontend)
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("PHP failed to start. See run/php.log.")
        (RUN / "state.json").write_text(json.dumps({"launcher": os.getpid(), "backend": backend.pid,
            "frontend": frontend.pid, "url": "http://127.0.0.1:8080"}), encoding="utf-8")
        print("AgroAI running at http://127.0.0.1:8080", flush=True)
        if not args.no_browser:
            webbrowser.open("http://127.0.0.1:8080")
        while not marker.exists() and all(child.poll() is None for child in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
        for log in logs:
            log.close()
        marker.unlink(missing_ok=True)
        (RUN / "state.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
