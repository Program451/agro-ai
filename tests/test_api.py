"""Regression checks using the user's real ONNX model, plus invalid input boundaries."""
import base64
import os
from pathlib import Path
import time
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

os.environ["AGRO_API_TOKEN"] = "test-token-" + "x" * 48
os.environ["AGRO_ENABLE_STREAMS"] = "0"
from backend import app as module


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    module.TMP_DIR = tmp_path_factory.mktemp("video")
    from backend import sensors
    sensors.DB_PATH = tmp_path_factory.mktemp("sensors") / "readings.sqlite3"
    with TestClient(module.app) as test_client:
        test_client.headers["X-Agro-Token"] = os.environ["AGRO_API_TOKEN"]
        yield test_client


def image_bytes():
    image = np.zeros((320, 480, 3), dtype=np.uint8)
    image[:] = (93, 128, 84)
    return cv2.imencode(".png", image)[1].tobytes()


def test_private_api_and_catalog(client):
    assert client.get("/api/health", headers={"X-Agro-Token": ""}).status_code == 401
    assert client.get("/api/health").json()["status"] == "ready"
    data = client.get("/api/classes").json()["classes"]
    assert len(data) == 22
    assert sum(item["is_field"] for item in data) == 5


def test_real_image_and_frame_inference(client):
    response = client.post("/api/detect/image", files={"file": ("test.png", image_bytes(), "image/png")})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["width"] == 480 and data["height"] == 320
    assert data["summary"]["total"] == len(data["detections"])
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(data["image_b64"]), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (320, 480, 3)
    frame = client.post("/api/detect/frame", json={"image": base64.b64encode(image_bytes()).decode()})
    assert frame.status_code == 200
    assert "image_b64" not in frame.json()


def test_invalid_inputs_and_origin(client):
    assert client.post("/api/detect/image", files={"file": ("x.png", b"invalid")}).status_code == 400
    assert client.post("/api/detect/image?conf=9", files={"file": ("x.png", image_bytes())}).status_code == 422
    assert client.post("/api/detect/frame", json={"image": "!!!"}).status_code == 400
    assert client.post("/api/detect/frame", json={"image": "x", "conf": "bad"}).status_code == 422
    assert client.post("/api/detect/frame", headers={"Origin": "https://untrusted.example"},
                       json={"image": "x"}).status_code == 403
    assert client.get("/api/video/not-a-job").status_code == 404
    assert client.get("/api/stream?url=file:///etc/passwd").status_code == 403


def test_video_job_and_range_download(client, tmp_path):
    path = tmp_path / "input.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    assert writer.isOpened()
    for _ in range(10):
        writer.write(np.full((120, 160, 3), 96, dtype=np.uint8))
    writer.release()
    with path.open("rb") as video:
        response = client.post("/api/detect/video?max_seconds=1", files={"file": ("test.mp4", video, "video/mp4")})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    for _ in range(120):
        data = client.get("/api/jobs/" + job_id).json()
        if data["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert data["status"] == "done", data
    assert data["result"]["frames_processed"] == 10
    assert data["result"]["browser_playable"] == bool(module.FFMPEG_BIN)
    response = client.get("/api/video/" + job_id, headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100
    assert not list(module.TMP_DIR.glob("*_in.mp4"))


def test_missing_advice_key_is_explicit(client, monkeypatch):
    from datetime import datetime, timezone
    import uuid
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post("/api/advice", json={"image": "x", "captured_at": datetime.now(timezone.utc).isoformat(),
        "session_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4())})
    assert response.status_code == 503


def test_insight_job_journal_and_image_are_authenticated(client, monkeypatch, tmp_path):
    from datetime import datetime, timezone
    import uuid
    from backend import insights
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-real")
    monkeypatch.setattr(insights, "DB_PATH", tmp_path / "insights.sqlite3")
    monkeypatch.setattr(insights, "last_started", 0)
    monkeypatch.setattr(insights, "jobs", {})
    monkeypatch.setattr(insights, "request_gemini", lambda *_: ({
        "image_relevance": "unclear", "summary": "Тест", "observations": [], "risks": [], "actions": [], "limitations": []}, "test"))
    payload = {"image": base64.b64encode(image_bytes()).decode(),
        "captured_at": datetime.now(timezone.utc).isoformat(), "session_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4())}
    start = time.monotonic()
    response = client.post("/api/advice", json=payload)
    assert response.status_code == 202
    assert time.monotonic() - start < 2  # Queues work instead of holding the PHP request open.
    path = "/api/insights/jobs/" + response.json()["job_id"]
    for _ in range(100):
        result = client.get(path)
        if result.json().get("status") == "done":
            break
        time.sleep(.05)
    assert result.json()["status"] == "done", result.text
    assert client.get("/api/insights/history").json()["observations"][0]["id"] == payload["request_id"]
    image_path = "/api" + result.json()["result"]["image_path"]
    assert client.get(image_path).headers["content-type"] == "image/jpeg"
    for target in (path, image_path, "/api/insights/history"):
        assert client.get(target, headers={"X-Agro-Token": ""}).status_code == 401


def test_nms_keeps_overlapping_different_classes():
    from engine import Detector
    detector = Detector.__new__(Detector)
    detector.input_name = "images"
    predictions = np.zeros((1, 26, 3), dtype=np.float32)
    predictions[0, :4, :] = np.array([[320, 320, 320], [320, 320, 320],
                                     [100, 100, 100], [100, 100, 100]])
    predictions[0, 4, 0] = 0.9
    predictions[0, 4, 1] = 0.8
    predictions[0, 5, 2] = 0.85
    class FakeSession:
        def run(self, *_):
            return [predictions]
    detector.session = FakeSession()
    detections = detector.infer(np.zeros((640, 640, 3), dtype=np.uint8))
    assert [item["class_id"] for item in detections] == [0, 1]


def test_esp32_readings_are_persisted_and_sensor_key_is_scoped(client, monkeypatch):
    from backend import sensors
    assert client.get("/api/sensors").json()["status"] == "empty"
    monkeypatch.setattr(module, "SENSOR_TOKEN", "sensor-test-" + "y" * 48)
    sensor_headers = {"X-Agro-Token": "", "X-Sensor-Token": module.SENSOR_TOKEN}
    payload = {"device_id": "esp32-field-01", "temperature_c": 19.5, "humidity_pct": 35,
               "pressure_hpa": 951.34, "altitude_m": 528.65, "rain_raw": 4095, "soil_raw": 0}
    response = client.post("/api/sensors", headers=sensor_headers, json=payload)
    assert response.status_code == 201, response.text
    # A sensor can write telemetry but cannot read data or access the model.
    assert client.get("/api/sensors", headers=sensor_headers).status_code == 401
    assert client.get("/api/health", headers=sensor_headers).status_code == 401
    assert client.post("/api/detect/frame", headers=sensor_headers, json={"image": "bad"}).status_code == 401
    reading = client.get("/api/sensors").json()
    expected = {key: value for key, value in payload.items() if key != "soil_raw"}
    assert reading["status"] == "live" and reading["reading"] == expected
    assert "soil_raw" not in reading["reading"]
    assert sensors.latest_reading()["reading"] == expected  # Fresh DB connection, persisted data.
    assert client.post("/api/sensors", json={"humidity_pct": 120}).status_code == 422
    assert client.post("/api/sensors", json={"device_id": "esp32"}).status_code == 422
    assert client.post("/api/sensors", json={"rain_raw": 1.5}).status_code == 422
    assert client.post("/api/sensors", json={"soil_raw": 0}).status_code == 422
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with sensors.connect() as db:
        db.execute("UPDATE readings SET received_at=?", (old,))
    assert client.get("/api/sensors").json()["status"] == "stale"
