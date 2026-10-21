"""FastAPI API for the original YOLO11 model; PHP serves the interface."""
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time
import threading
from urllib.parse import urlsplit
import uuid

# Bound decompression before OpenCV allocates a decoded image.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "40000000")
import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from engine import Detector, CLASS_NAMES, CLASS_COLORS, FIELD_CLASSES, CLASS_NAMES_RU
from backend.sensors import SensorReading, latest_reading, save_reading
from backend import insights

APP_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = Path(os.getenv("AGRO_DATA_DIR", str(APP_DIR / "_tmp")))
MODEL_PATH = Path(os.getenv("AGRO_MODEL_PATH", str(APP_DIR / "best.onnx")))
ORIGINS = [s.strip() for s in os.getenv(
    "AGRO_ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080"
).split(",") if s.strip()]
IMAGE_LIMIT, VIDEO_LIMIT = 20 * 1024 * 1024, 200 * 1024 * 1024
FFMPEG_BIN = os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg")
detector = None
API_TOKEN = os.getenv("AGRO_API_TOKEN", "")
SENSOR_TOKEN = os.getenv("AGRO_SENSOR_TOKEN", "")
jobs = {}
jobs_lock = threading.Lock()
video_slots = threading.BoundedSemaphore(2)
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agro-video")


def cleanup_results():
    for path in TMP_DIR.glob("*.mp4"):
        if re.fullmatch(r"[0-9a-f]{32}_(in|raw|out)\.mp4", path.name):
            try:
                if path.stat().st_mtime < time.time() - 86400:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass


@asynccontextmanager
async def lifespan(app):
    global detector
    if len(API_TOKEN) < 32:
        raise RuntimeError("Set AGRO_API_TOKEN to a random secret of at least 32 characters. Run setup.py first.")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_results()
    detector = Detector(str(MODEL_PATH))
    yield
    detector = None


app = FastAPI(title="AgroAI Scout API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS,
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"])


@app.middleware("http")
async def check_origin(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        api_access = bool(API_TOKEN) and secrets.compare_digest(
            request.headers.get("x-agro-token", "").encode("utf-8"), API_TOKEN.encode("utf-8")
        )
        sensor_access = (
            request.method == "POST" and request.url.path == "/api/sensors"
            and len(SENSOR_TOKEN) >= 32 and secrets.compare_digest(
                request.headers.get("x-sensor-token", "").encode("utf-8"), SENSOR_TOKEN.encode("utf-8"))
        )
        if not api_access and not sensor_access:
            return JSONResponse({"detail": "Нет доступа к API"}, status_code=401)
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin not in ORIGINS:
        return JSONResponse({"detail": "Источник запроса не разрешён"}, status_code=403)
    length = request.headers.get("content-length", "0")
    if length.isdigit() and int(length) > VIDEO_LIMIT + 1024 * 1024:
        return JSONResponse({"detail": "Файл слишком большой"}, status_code=413)
    return await call_next(request)


class FramePayload(BaseModel):
    image: str = Field(min_length=1, max_length=28_000_000)
    conf: float = Field(default=0.35, ge=0.1, le=0.9)


def summarize(detections):
    counts = {}
    for item in detections:
        counts[item["class_name"]] = counts.get(item["class_name"], 0) + 1
    return {"total": len(detections), "pest_count": sum(not d["is_field"] for d in detections),
            "field_flags": list(dict.fromkeys(d["class_name"] for d in detections if d["is_field"])),
            "counts": counts}


def decode_image(raw):
    if not raw or len(raw) > IMAGE_LIMIT:
        raise HTTPException(413 if raw else 400, "Допустим размер изображения до 20 МБ")
    try:
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        image = None
    if image is None:
        raise HTTPException(400, "Не удалось прочитать изображение. Используйте JPG, PNG или WebP.")
    if image.shape[0] * image.shape[1] > 40_000_000:
        raise HTTPException(413, "Максимальное разрешение — 40 мегапикселей")
    return image


def infer_image(raw, conf, annotated=True):
    image = decode_image(raw)
    start = time.perf_counter()
    detections = detector.infer(image, conf_thres=conf)
    result = {"detections": detections, "summary": summarize(detections),
              "infer_ms": round((time.perf_counter() - start) * 1000),
              "width": image.shape[1], "height": image.shape[0]}
    if annotated:
        ok, jpg = cv2.imencode(".jpg", detector.draw(image, detections))
        if not ok:
            raise HTTPException(500, "Не удалось подготовить результат")
        result["image_b64"] = base64.b64encode(jpg).decode("ascii")
    return result


async def read_upload(file, limit):
    raw = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            raw.extend(chunk)
            if len(raw) > limit:
                raise HTTPException(413, f"Максимальный размер файла: {limit // 1024 // 1024} МБ")
    finally:
        await file.close()
    return bytes(raw)


@app.get("/")
def index():
    return {"service": "AgroAI Scout API", "frontend": "http://127.0.0.1:8080", "docs": "/docs"}


@app.get("/api/health")
def health():
    return {"status": "ready" if detector else "loading", "model": "YOLO11 · ONNX",
            "classes": len(CLASS_NAMES), "ffmpeg": bool(FFMPEG_BIN),
            "advice_available": bool(os.getenv("GEMINI_API_KEY")),
            "advice_provider": "Gemini", "insight_interval_seconds": insights.INTERVAL,
            "gemini_model": os.getenv("GEMINI_MODEL", insights.DEFAULT_MODEL)}


@app.get("/api/classes")
def classes():
    return {"classes": [{"id": cid, "name": name, "name_ru": CLASS_NAMES_RU[cid],
                         "color": CLASS_COLORS[cid], "is_field": cid in FIELD_CLASSES}
                        for cid, name in CLASS_NAMES.items()]}


@app.get("/api/sensors")
def sensors():
    return latest_reading()


@app.post("/api/sensors", status_code=201)
def receive_sensors(reading: SensorReading):
    return save_reading(reading)


@app.post("/api/detect/image")
async def detect_image(file: UploadFile = File(...), conf: float = Query(0.35, ge=0.1, le=0.9)):
    return await run_in_threadpool(infer_image, await read_upload(file, IMAGE_LIMIT), conf)


@app.post("/api/detect/frame")
def detect_frame(payload: FramePayload):
    try:
        raw = base64.b64decode(payload.image.split(",", 1)[-1], validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(400, "Некорректный кадр камеры")
    return infer_image(raw, payload.conf, annotated=False)


def process_video(in_path, job_id, conf, max_seconds):
    raw_path, out_path = TMP_DIR / f"{job_id}_raw.mp4", TMP_DIR / f"{job_id}_out.mp4"
    cap, writer, successful = cv2.VideoCapture(str(in_path)), None, False
    start = time.perf_counter()
    try:
        if not cap.isOpened():
            raise HTTPException(400, "Не удалось прочитать видео")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps < 1 or fps > 120:
            fps = 25
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if w < 2 or h < 2:
            raise HTTPException(400, "Некорректный размер видеокадра")
        scale = min(1, 960 / max(w, h))
        size = (max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2))
        writer = cv2.VideoWriter(str(raw_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        if not writer.isOpened():
            raise HTTPException(500, "Не удалось создать выходное видео")
        frame_idx, last_dets, counts, timeline = 0, [], {}, []
        every = max(1, round(fps / 5))
        while frame_idx < int(fps * max_seconds):
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, size)
            if frame_idx % every == 0:
                last_dets = detector.infer(frame, conf_thres=conf)
                for item in last_dets:
                    counts[item["class_name"]] = counts.get(item["class_name"], 0) + 1
                timeline.append({"t": round(frame_idx / fps, 2), "count": len(last_dets)})
            writer.write(detector.draw(frame, last_dets))
            frame_idx += 1
        writer.release()
        writer = None
        if not frame_idx:
            raise HTTPException(400, "В видео нет доступных кадров")
        playable = False
        if FFMPEG_BIN:
            try:
                proc = subprocess.run(
                    [FFMPEG_BIN, "-y", "-i", str(raw_path), "-an", "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-preset", "veryfast", "-movflags", "+faststart", str(out_path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
                playable = proc.returncode == 0 and out_path.exists()
            except (OSError, subprocess.SubprocessError):
                pass
        if playable:
            raw_path.unlink(missing_ok=True)
        else:
            out_path.unlink(missing_ok=True)
        successful = True
        return {"job_id": job_id, "video_url": f"/api/video/{job_id}",
                "frames_processed": frame_idx, "duration_sec": round(frame_idx / fps, 1),
                "class_counts": counts, "timeline": timeline,
                "process_ms": round((time.perf_counter() - start) * 1000), "browser_playable": playable,
                "warning": None if playable else "Для просмотра в браузере установите FFmpeg. Видео можно скачать."}
    finally:
        cap.release()
        if writer:
            writer.release()
        in_path.unlink(missing_ok=True)
        if not successful:
            raw_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)


@app.post("/api/detect/video")
async def detect_video(file: UploadFile = File(...), conf: float = Query(0.35, ge=0.1, le=0.9),
                       max_seconds: int = Query(60, ge=1, le=120)):
    cleanup_results()
    if not video_slots.acquire(blocking=False):
        await file.close()
        raise HTTPException(429, "Очередь видео занята. Попробуйте через несколько минут.")
    job_id = uuid.uuid4().hex
    in_path, total = TMP_DIR / f"{job_id}_in.mp4", 0
    queued = False
    try:
        with in_path.open("wb") as dest:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > VIDEO_LIMIT:
                    raise HTTPException(413, "Максимальный размер видео — 200 МБ")
                dest.write(chunk)
        with jobs_lock:
            cutoff = time.time() - 86400
            for old_id in list(jobs):
                if jobs[old_id]["created"] < cutoff and jobs[old_id]["status"] in ("done", "error"):
                    del jobs[old_id]
            jobs[job_id] = {"status": "queued", "created": time.time()}
        executor.submit(run_video_job, in_path, job_id, conf, max_seconds)
        queued = True
        return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=202)
    finally:
        await file.close()
        if not queued:
            in_path.unlink(missing_ok=True)
            video_slots.release()


def run_video_job(in_path, job_id, conf, max_seconds):
    try:
        with jobs_lock:
            jobs[job_id]["status"] = "processing"
        result = process_video(in_path, job_id, conf, max_seconds)
        with jobs_lock:
            jobs[job_id].update(status="done", result=result)
    except Exception as error:
        message = error.detail if isinstance(error, HTTPException) else "Ошибка обработки видео"
        with jobs_lock:
            jobs[job_id].update(status="error", error=message)
    finally:
        video_slots.release()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Задача не найдена. Возможно, сервер был перезапущен.")
        return dict(job)


@app.get("/api/video/{job_id}")
def video(job_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, "Видео не найдено")
    for suffix in ("out", "raw"):
        path = TMP_DIR / f"{job_id}_{suffix}.mp4"
        if path.exists():
            return FileResponse(path, media_type="video/mp4")
    raise HTTPException(404, "Видео не найдено или срок хранения истёк")


def open_stream(url):
    url = url.strip()
    if url.isdigit() and len(url) <= 2:
        # DirectShow enumerates OBS Virtual Camera as well as physical cameras on Windows.
        cap = cv2.VideoCapture(int(url), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
    else:
        parsed = urlsplit(url)
        if parsed.scheme not in ("rtsp", "rtsps", "http", "https") or not parsed.hostname:
            raise HTTPException(400, "Укажите RTSP/HTTP-адрес или номер камеры 0–99")
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
    if not cap.isOpened():
        cap.release()
        raise HTTPException(400, "Не удалось подключиться к потоку. Проверьте адрес и сеть.")
    ok, frame = cap.read()
    if not ok:
        cap.release()
        raise HTTPException(400, "Подключение открыто, но кадры не поступают")
    return cap, frame


def stream_frames(cap, first, conf):
    frame, index, detections = first, 0, []
    try:
        while frame is not None:
            h, w = frame.shape[:2]
            scale = min(1, 960 / max(h, w))
            if scale < 1:
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            if index % 3 == 0:
                detections = detector.infer(frame, conf_thres=conf)
            ok, jpg = cv2.imencode(".jpg", detector.draw(frame, detections))
            if ok:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
            ok, frame = cap.read()
            if not ok:
                break
            index += 1
    finally:
        cap.release()


@app.get("/api/stream")
def stream(request: Request, url: str = Query(..., max_length=2048),
           conf: float = Query(0.35, ge=0.1, le=0.9)):
    if os.getenv("AGRO_ENABLE_STREAMS", "0") != "1":
        raise HTTPException(403, "Включите AGRO_ENABLE_STREAMS=1 на ноутбуке для доступа к дрону")
    origin, referer = request.headers.get("origin"), request.headers.get("referer")
    ref = urlsplit(referer) if referer else None
    if (origin and origin not in ORIGINS) or (ref and f"{ref.scheme}://{ref.netloc}" not in ORIGINS):
        raise HTTPException(403, "Источник запроса не разрешён")
    if request.headers.get("sec-fetch-site") == "cross-site" and not origin and not ref:
        raise HTTPException(403, "Источник запроса не разрешён")
    cap, first = open_stream(url)
    return StreamingResponse(stream_frames(cap, first, conf),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/advice", status_code=202)
def advice(payload: insights.InsightPayload):
    return insights.submit(payload, detector)


@app.get("/api/insights/jobs/{job_id}")
def insight_job(job_id: uuid.UUID):
    return insights.job_status(job_id)


@app.get("/api/insights/history")
def insight_history(session_id: uuid.UUID | None = None):
    return {"observations": insights.history(session_id)}


@app.get("/api/insights/{observation_id}/image")
def insight_image(observation_id: uuid.UUID):
    return Response(insights.snapshot(observation_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})
