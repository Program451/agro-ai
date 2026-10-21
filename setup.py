"""Create private configuration without printing or overwriting existing secrets."""
import argparse
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def configure(backend_url=None):
    env = ROOT / ".env"
    if not env.exists():
        token = secrets.token_urlsafe(48)
        env.write_text(
            f"AGRO_API_TOKEN={token}\nAGRO_HOST=127.0.0.1\nAGRO_PORT=8000\n"
            "AGRO_ENABLE_STREAMS=0\nGEMINI_API_KEY=\n", encoding="utf-8")
    else:
        match = re.search(r"^AGRO_API_TOKEN=(.+)$", env.read_text(encoding="utf-8-sig"), re.M)
        if not match or len(match[1].strip()) < 32:
            raise SystemExit("Invalid AGRO_API_TOKEN in .env. Use a random token of at least 32 characters.")
        token = match[1].strip().strip("'\"")
    config = ROOT / "frontend" / "config.local.php"
    env_text = env.read_text(encoding="utf-8-sig")
    if not re.search(r"^AGRO_SENSOR_TOKEN=.+$", env_text, re.M):
        with env.open("a", encoding="utf-8") as target:
            target.write("\nAGRO_SENSOR_TOKEN=" + secrets.token_urlsafe(48) + "\n")
    if backend_url is not None:
        parts = urlsplit(backend_url)
        if (parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost"))) or not parts.hostname or parts.query or parts.fragment or parts.username:
            raise SystemExit("Use an HTTPS backend URL or http://127.0.0.1:8000 for local preview.")
    if not config.exists() or backend_url is not None:
        url = (backend_url or "http://127.0.0.1:8000").rstrip("/")
        quote = lambda text: text.replace("\\", "\\\\").replace("'", "\\'")
        config.write_text(
            "<?php\nreturn [\n    'backend_url' => '" + quote(url) +
            "',\n    'api_token' => '" + quote(token) + "',\n];\n", encoding="utf-8")
    print("Configuration ready: .env (laptop), frontend/config.local.php (hosting). Secret was not printed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", help="Public HTTPS URL from your laptop tunnel")
    configure(parser.parse_args().backend_url)
