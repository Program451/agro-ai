"""No external API calls: validate synchronization, persistence and provider boundaries."""
import base64
from datetime import datetime, timezone, timedelta
import json
import uuid
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from backend import insights, sensors


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(sensors, "DB_PATH", tmp_path / "sensors.sqlite3")
    monkeypatch.setattr(insights, "DB_PATH", tmp_path / "insights.sqlite3")
    monkeypatch.setattr(insights, "last_started", 0)
    monkeypatch.setenv("GEMINI_API_KEY", "private-test-key")
    monkeypatch.setenv("GEMINI_MODEL", insights.DEFAULT_MODEL)


def add(at, device="field", **values):
    reading = sensors.SensorReading(device_id=device, **values)
    with sensors.connect() as db:
        db.execute("INSERT INTO readings(received_at,payload) VALUES (?,?)", (at.isoformat(), reading.model_dump_json()))


def payload(**changes):
    image = cv2.imencode(".jpg", np.zeros((40, 60, 3), dtype=np.uint8))[1]
    return insights.InsightPayload(image=base64.b64encode(image).decode(), source="camera",
        captured_at=datetime.now(timezone.utc), session_id=uuid.uuid4(), request_id=uuid.uuid4()).model_copy(update=changes)


def assessment():
    return {"image_relevance": "unclear", "summary": "Недостаточно данных", "observations": [],
            "risks": [], "actions": [], "limitations": ["Культура неизвестна"]}


def test_sensor_context_never_uses_future_or_other_device():
    at = datetime.now(timezone.utc)
    add(at - timedelta(minutes=4), temperature_c=18, soil_raw=50)
    add(at - timedelta(seconds=10), temperature_c=20, soil_raw=0)
    add(at - timedelta(seconds=5), device="another", temperature_c=99)
    add(at + timedelta(seconds=2), temperature_c=80)
    data = sensors.context_at(at, "field")
    assert data["status"] == "live" and data["age_seconds"] == 10
    assert "soil_raw" not in data["reading"]
    assert data["trends"]["temperature_c"]["delta"] == 2
    assert data["sample_count"] == 2
    assert all(s["device_id"] == "field" for s in data["samples"])
    assert sensors.context_at(at, "missing")["status"] == "empty"
    assert sensors.context_at(at)["device_id"] == "another"
    assert sensors.context_at(at)["trends"] == {}  # One sample is not a trend.


def test_stale_and_downsampled_context():
    at = datetime.now(timezone.utc)
    for i in range(60):
        add(at - timedelta(seconds=180 + (59 - i) * 5), temperature_c=i)
    data = sensors.context_at(at)
    assert data["status"] == "stale"
    assert len(data["samples"]) == 12
    assert data["samples"][0]["temperature_c"] == 0 and data["samples"][-1]["temperature_c"] == 59


def test_image_and_sensor_evidence_persist_together(monkeypatch):
    p = payload()
    add(p.captured_at - timedelta(seconds=2), temperature_c=19.5, soil_raw=0)
    mock = Mock(return_value=(assessment(), "gemini-test"))
    monkeypatch.setattr(insights, "request_gemini", mock)
    detector = Mock()
    detector.infer.return_value = [{"name_ru": "Растение", "confidence": .7}]
    report = insights.analyze(p, detector)
    jpeg, evidence = mock.call_args.args
    assert jpeg.startswith(b"\xff\xd8")
    assert "soil_raw" not in json.dumps(evidence["sensors"])
    assert evidence["sensor_alignment"] == "live_capture"
    assert evidence["yolo_hypotheses"] == [{"name": "Растение", "confidence": .7}]
    assert insights.history(p.session_id) == [report]
    assert insights.snapshot(p.request_id) == jpeg
    # Old saved reports must also omit soil readings in history and cached retries.
    legacy = json.loads(json.dumps(report))
    legacy["sensors"]["reading"]["soil_raw"] = 0
    legacy["sensors"]["units"]["soil_raw"] = "ADC"
    legacy["sensors"]["trends"]["soil_raw"] = {"delta": 0}
    legacy["sensors"]["samples"][0]["soil_raw"] = 0
    with insights.connect() as db:
        db.execute("UPDATE observations SET result=? WHERE id=?",
                   (json.dumps(legacy), str(p.request_id)))
    assert insights.history(p.session_id) == [report]
    # An identical retry returns the persisted report without paying for a second call.
    assert insights.analyze(p, detector) == report
    assert mock.call_count == 1
    with pytest.raises(HTTPException) as conflict:
        insights.analyze(p.model_copy(update={"crop": "another"}), detector)
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as limited:
        insights.analyze(payload(), detector)
    assert limited.value.status_code == 429
    assert mock.call_count == 1


def test_missing_sensors_and_recording_are_not_claimed_synchronous(monkeypatch):
    monkeypatch.setattr(insights, "request_gemini", lambda *_: (assessment(), "test"))
    detector = Mock(); detector.infer.return_value = []
    result = insights.analyze(payload(source="video"), detector)
    assert result["sensors"]["status"] == "empty"
    assert any("дату съёмки" in warning and "условия в записи могут отличаться" in warning for warning in result["warnings"])
    assert any("измерьте текущую температуру" in warning for warning in result["warnings"])
    assert any("несколько последовательных замеров" in warning for warning in result["warnings"])


def test_provider_uses_image_structured_output_and_header_only(monkeypatch):
    answer = assessment()
    answer["image_relevance"] = "non_field"
    answer["risks"] = [{"title": "Ошибка модели", "level": "high", "basis": "image", "evidence": "x", "forecast": "x"}]
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"candidates": [{"finishReason": "STOP",
        "content": {"parts": [{"text": json.dumps(answer)}]}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(insights.requests, "post", post)
    result, model = insights.request_gemini(b"jpeg", {"sensors": {"status": "empty"}})
    url = post.call_args.args[0]; options = post.call_args.kwargs
    assert "private-test-key" not in url
    assert options["headers"]["x-goog-api-key"] == "private-test-key"
    assert not options["allow_redirects"]
    assert options["json"]["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/jpeg"
    assert options["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert result["risks"] == []  # Non-field scenes cannot get a field forecast.


@pytest.mark.parametrize("sensor_status,expected", [
    ("live", ["image", "sensors", "combined"]),
    ("stale", ["image"]), ("empty", ["image"]),
])
def test_current_sensor_forecasts_require_live_readings(monkeypatch, sensor_status, expected):
    answer = assessment()
    answer["image_relevance"] = "plant"
    answer["risks"] = [
        {"title": "Условный риск", "level": "medium", "basis": basis,
         "evidence": "Проверочное основание", "forecast": "Если условия сохранятся…"}
        for basis in ("image", "sensors", "combined")
    ]
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"candidates": [{"finishReason": "STOP",
        "content": {"parts": [{"text": json.dumps(answer)}]}}]}
    monkeypatch.setattr(insights.requests, "post", Mock(return_value=response))
    result, _ = insights.request_gemini(b"jpeg", {"sensors": {"status": sensor_status}})
    assert [risk["basis"] for risk in result["risks"]] == expected


@pytest.mark.parametrize("code,expected", [(401, 503), (403, 503), (404, 503), (429, 429), (500, 502)])
def test_provider_errors_do_not_leak_key_or_upstream_body(monkeypatch, code, expected):
    response = Mock(status_code=code, ok=False, text="private-test-key")
    monkeypatch.setattr(insights.requests, "post", Mock(return_value=response))
    with pytest.raises(HTTPException) as error:
        insights.request_gemini(b"jpeg", {})
    assert error.value.status_code == expected
    assert "private-test-key" not in error.value.detail


@pytest.mark.parametrize("candidate", [
    {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}},
    {"finishReason": "STOP", "content": {"parts": [{"text": "not JSON"}]}},
])
def test_truncated_or_invalid_report_is_rejected(monkeypatch, candidate):
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"candidates": [candidate]}
    monkeypatch.setattr(insights.requests, "post", Mock(return_value=response))
    with pytest.raises(HTTPException) as error:
        insights.request_gemini(b"jpeg", {})
    assert error.value.status_code == 502


def test_old_capture_and_invalid_image_do_not_call_provider(monkeypatch):
    mock = Mock()
    monkeypatch.setattr(insights, "request_gemini", mock)
    for p in (payload(image="bad"), payload(captured_at=datetime.now(timezone.utc) - timedelta(minutes=3))):
        with pytest.raises(HTTPException) as error:
            insights.analyze(p, Mock())
        assert error.value.status_code == 400
    mock.assert_not_called()
