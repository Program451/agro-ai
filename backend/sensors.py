"""Persistent telemetry from ESP32. Unknown readings stay null, never fake zero."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlsplit

import requests

from pydantic import BaseModel, ConfigDict, Field, model_validator

DB_PATH = Path(os.getenv("AGRO_SENSOR_DB", str(Path(__file__).resolve().parent.parent / "data" / "sensors.sqlite3")))
FIELDS = ("temperature_c", "humidity_pct", "pressure_hpa", "altitude_m", "rain_raw")
feed_lock = threading.Lock()
feed_checked_at = float('-inf')


class SensorReading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    device_id: str = Field(default="esp32", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    temperature_c: float | None = Field(default=None, ge=-100, le=150)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    pressure_hpa: float | None = Field(default=None, ge=100, le=1500)
    altitude_m: float | None = Field(default=None, ge=-1000, le=20000)
    rain_raw: int | None = Field(default=None, ge=0, le=65535, strict=True)

    @model_validator(mode="before")
    @classmethod
    def ignore_uninstalled_sensor(cls, values):
        # Older ESP32 firmware still sends this placeholder; there is no soil sensor.
        return without_soil(values) if isinstance(values, dict) else values

    @model_validator(mode="after")
    def require_reading(self):
        if all(getattr(self, name) is None for name in FIELDS):
            raise ValueError("Send at least one sensor reading")
        return self


def without_soil(values):
    return {key: value for key, value in values.items() if key != "soil_raw"}


def available_context(context):
    """Exclude the uninstalled sensor, including from previously saved reports."""
    clean = dict(context)
    if isinstance(clean.get("reading"), dict):
        clean["reading"] = without_soil(clean["reading"])
    for key in ("trends", "units"):
        if isinstance(clean.get(key), dict):
            clean[key] = without_soil(clean[key])
    if isinstance(clean.get("samples"), list):
        clean["samples"] = [without_soil(sample) for sample in clean["samples"]]
    return clean


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS readings (id INTEGER PRIMARY KEY, received_at TEXT NOT NULL, payload TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS readings_time ON readings(received_at)")
    return db


def import_hosted_samples(samples):
    """Keep the station's original packet times; polling must not make old data fresh."""
    if not isinstance(samples, list) or len(samples) > 360:
        raise ValueError("Invalid sensor history")
    rows = []
    now = datetime.now(timezone.utc)
    for sample in samples:
        try:
            stamp = datetime.fromisoformat(sample["received_at"])
            if stamp.tzinfo is None or stamp > now:
                continue
            reading = SensorReading.model_validate(sample["reading"])
            # Separate the hosting station from direct, laptop-connected ESP32s.
            if reading.device_id != "esp32-hosting":
                continue
            rows.append((stamp.astimezone(timezone.utc).isoformat(),
                         json.dumps(reading.model_dump(), ensure_ascii=False)))
        except (ValueError, TypeError, KeyError):
            continue
    with connect() as db:
        inserted = 0
        for stamp, raw in rows:
            existing = db.execute("SELECT payload FROM readings WHERE received_at=?", (stamp,)).fetchall()
            if any(without_soil(json.loads(row[0])) == json.loads(raw) for row in existing):
                continue
            db.execute("INSERT INTO readings(received_at,payload) VALUES (?,?)", (stamp, raw))
            inserted += 1
        db.execute("DELETE FROM readings WHERE id NOT IN "
                   "(SELECT id FROM readings ORDER BY received_at DESC,id DESC LIMIT 10000)")
    return inserted


def sync_hosted_sensors():
    """Optional read-only feed from the PHP hosting. Existing direct ESP32s still work."""
    global feed_checked_at
    url = os.getenv("AGRO_SENSOR_FEED_URL", "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return
    if not feed_lock.acquire(blocking=False):
        return
    try:
        if time.monotonic() - feed_checked_at < 5:
            return
        feed_checked_at = time.monotonic()
        # No laptop/Gemini credentials are sent to the sensor feed.
        with requests.get(url, timeout=(3, 4), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                return
            content = bytearray()
            for chunk in response.iter_content(16384):
                content.extend(chunk)
                if len(content) > 524288:
                    return
            data = json.loads(content)
        if isinstance(data, dict) and data.get("source") == "hosting":
            import_hosted_samples(data.get("samples"))
    except (requests.RequestException, ValueError, TypeError, sqlite3.Error, OSError):
        # Retain previous values and their age when the source is unavailable.
        return
    finally:
        feed_lock.release()


def save_reading(reading):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute("INSERT INTO readings (received_at,payload) VALUES (?,?)",
                   (now, json.dumps(reading.model_dump(), ensure_ascii=False)))
        db.execute("DELETE FROM readings WHERE id <= (SELECT MAX(id)-10000 FROM readings)")
    return {"status": "saved", "received_at": now}


def latest_reading():
    sync_hosted_sensors()
    with connect() as db:
        row = db.execute("SELECT received_at,payload FROM readings ORDER BY received_at DESC,id DESC LIMIT 1").fetchone()
    if row is None:
        return {"status": "empty", "reading": None, "received_at": None, "age_seconds": None}
    timestamp, payload = row
    age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds()))
    return {"status": "stale" if age > 120 else "live", "reading": without_soil(json.loads(payload)),
            "received_at": timestamp, "age_seconds": age}


def context_at(anchor, device_id=None):
    """Use only packets received at or before the frame, from one ESP32."""
    sync_hosted_sensors()
    anchor = anchor.astimezone(timezone.utc)
    with connect() as db:
        where, args = "received_at <= ?", [anchor.isoformat()]
        if device_id:
            where += " AND json_extract(payload, '$.device_id') = ?"
            args.append(device_id)
        row = db.execute(f"SELECT received_at,payload FROM readings WHERE {where} ORDER BY received_at DESC,id DESC LIMIT 1",
                         args).fetchone()
        if not row:
            return {"status": "empty", "device_id": device_id, "reading": None,
                    "received_at": None, "age_seconds": None, "samples": [], "trends": {}}
        stamp, raw = row
        reading = without_soil(json.loads(raw))
        rows = db.execute(
            "SELECT received_at,payload FROM readings WHERE received_at >= ? AND received_at <= ? "
            "AND json_extract(payload, '$.device_id') = ? ORDER BY received_at DESC,id DESC LIMIT 360",
            ((anchor - timedelta(minutes=30)).isoformat(), anchor.isoformat(), reading["device_id"])).fetchall()
    samples = [{"received_at": t, **without_soil(json.loads(p))} for t, p in reversed(rows)]
    trends = {}
    for field in FIELDS:
        values = [(s["received_at"], s[field]) for s in samples if s.get(field) is not None]
        if len(values) < 2:
            continue
        span = (datetime.fromisoformat(values[-1][0]) - datetime.fromisoformat(values[0][0])).total_seconds()
        if span >= 60:
            trends[field] = {"first": values[0][1], "last": values[-1][1],
                             "delta": round(values[-1][1] - values[0][1], 3),
                             "minutes": round(span / 60, 1), "count": len(values)}
    age = max(0, round((anchor - datetime.fromisoformat(stamp)).total_seconds()))
    return {"status": "stale" if age > 120 else "live", "device_id": reading["device_id"],
            "reading": reading, "received_at": stamp, "age_seconds": age,
            "sample_count": len(samples), "trends": trends,
            "samples": [samples[round(i * (len(samples) - 1) / 11)] for i in range(12)] if len(samples) > 12 else samples,
            "units": {"temperature_c": "°C", "humidity_pct": "% воздуха", "pressure_hpa": "гПа",
                      "altitude_m": "м", "rain_raw": "ADC, без калибровки"},
            "time_basis": "Время получения ESP32 на хостинге (esp32-hosting) или ноутбуке; задержка передачи не измеряется."}
