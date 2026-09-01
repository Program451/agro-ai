"""
AgroAI Scout — server.
Run:  python server.py
Open: http://127.0.0.1:8000
"""
import base64
import io
import os
import shutil
import subprocess
import time
import uuid

import cv2
import numpy as np
import requests
from fastapi import FastAPI, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from engine import Detector, CLASS_NAMES, CLASS_COLORS, FIELD_CLASSES

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(APP_DIR, 'best.onnx')
TMP_DIR = os.path.join(APP_DIR, '_tmp')
os.makedirs(TMP_DIR, exist_ok=True)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # можно заменить на другую модель Groq

# Впишите свой ключ сюда между кавычками, если хотите задать его прямо в коде
# (тогда поле в браузере можно не использовать). Получить ключ: console.groq.com/keys
GROQ_API_KEY_DEFAULT = "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"  # например: "gsk_xxxxxxxxxxxxxxxxxxxxxxxx"

app = FastAPI(title="AgroAI Scout")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")

print("Загрузка модели…")
detector = Detector(MODEL_PATH)
print("Модель загружена ✅")


def summarize(detections):
    pests = [d for d in detections if not d['is_field']]
    field = [d for d in detections if d['is_field']]
    counts = {}
    for d in detections:
        counts[d['class_name']] = counts.get(d['class_name'], 0) + 1
    return {
        'total': len(detections),
        'pest_count': len(pests),
        'field_flags': [d['class_name'] for d in field],
        'counts': counts,
    }


def decode_upload_to_bgr(raw: bytes):
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def encode_bgr_to_b64jpg(img_bgr, quality=88):
    ok, buf = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return base64.b64encode(buf.tobytes()).decode('ascii')


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(APP_DIR, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/classes")
def api_classes():
    return {
        'classes': [
            {'id': cid, 'name': name, 'color': CLASS_COLORS.get(cid, '#E8B93F'), 'is_field': cid in FIELD_CLASSES}
            for cid, name in CLASS_NAMES.items()
        ]
    }


@app.post("/api/detect/image")
async def detect_image(file: UploadFile = File(...), conf: float = 0.35):
    raw = await file.read()
    img = decode_upload_to_bgr(raw)
    if img is None:
        return JSONResponse({'error': 'Не удалось прочитать изображение'}, status_code=400)
    t0 = time.time()
    detections = detector.infer(img, conf_thres=conf)
    ms = round((time.time() - t0) * 1000)
    annotated = detector.draw(img, detections)
    return {
        'detections': detections,
        'summary': summarize(detections),
        'image_b64': encode_bgr_to_b64jpg(annotated),
        'width': img.shape[1],
        'height': img.shape[0],
        'infer_ms': ms,
    }


@app.post("/api/detect/frame")
async def detect_frame(payload: dict):
    """Fast path for live webcam / drone frames sent as base64 JPEG/PNG data URLs."""
    data_url = payload.get('image', '')
    conf = float(payload.get('conf', 0.35))
    if ',' in data_url:
        data_url = data_url.split(',', 1)[1]
    raw = base64.b64decode(data_url)
    img = decode_upload_to_bgr(raw)
    if img is None:
        return JSONResponse({'error': 'bad frame'}, status_code=400)
    detections = detector.infer(img, conf_thres=conf)
    return {'detections': detections, 'summary': summarize(detections)}


FFMPEG_BIN = shutil.which('ffmpeg')


def _transcode_for_browser(raw_path: str, final_path: str) -> bool:
    """Re-encode the OpenCV-written mp4 (mpeg4/mp4v codec, unplayable in browsers)
    into H.264/yuv420p with +faststart, which every browser can play in <video>.
    Returns True on success."""
    if not FFMPEG_BIN:
        return False
    try:
        result = subprocess.run(
            [FFMPEG_BIN, '-y', '-i', raw_path,
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'veryfast',
             '-movflags', '+faststart', final_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        )
        return result.returncode == 0 and os.path.exists(final_path)
    except (subprocess.SubprocessError, OSError):
        return False


@app.post("/api/detect/video")
async def detect_video(file: UploadFile = File(...), conf: float = 0.35, max_seconds: int = 60):
    job_id = uuid.uuid4().hex[:12]
    in_path = os.path.join(TMP_DIR, f"{job_id}_in.mp4")
    raw_out_path = os.path.join(TMP_DIR, f"{job_id}_raw.mp4")
    out_path = os.path.join(TMP_DIR, f"{job_id}_out.mp4")
    with open(in_path, 'wb') as f:
        f.write(await file.read())

    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        return JSONResponse({'error': 'Не удалось открыть видео'}, status_code=400)

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames_in = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    max_frames = int(min(total_frames_in, fps * max_seconds)) if total_frames_in > 0 else int(fps * max_seconds)

    # cap output resolution for speed
    scale = min(1.0, 960 / max(w, h))
    ow, oh = int(w * scale), int(h * scale)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(raw_out_path, fourcc, fps, (ow, oh))

    detect_every = max(1, round(fps / 5))  # ~5 detections per second of footage
    last_dets = []
    class_counts = {}
    timeline = []
    frame_idx = 0
    t0 = time.time()

    while frame_idx < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if scale != 1.0:
            frame = cv2.resize(frame, (ow, oh))

        if frame_idx % detect_every == 0:
            last_dets = detector.infer(frame, conf_thres=conf)
            for d in last_dets:
                class_counts[d['class_name']] = class_counts.get(d['class_name'], 0) + 1
            timeline.append({'t': round(frame_idx / fps, 2), 'count': len(last_dets)})

        annotated = detector.draw(frame, last_dets)
        writer.write(annotated)
        frame_idx += 1

    cap.release()
    writer.release()
    os.remove(in_path)

    # Browsers can't play the mpeg4/mp4v codec OpenCV writes above — transcode to H.264.
    if not _transcode_for_browser(raw_out_path, out_path):
        # ffmpeg missing or failed: fall back to the raw file so something still plays.
        out_path = raw_out_path
    else:
        os.remove(raw_out_path)

    proc_ms = round((time.time() - t0) * 1000)

    return {
        'job_id': job_id,
        'video_url': f"/api/video/{job_id}",
        'frames_processed': frame_idx,
        'duration_sec': round(frame_idx / fps, 1),
        'class_counts': class_counts,
        'timeline': timeline,
        'process_ms': proc_ms,
    }


@app.get("/api/video/{job_id}")
def get_video(job_id: str):
    path = os.path.join(TMP_DIR, f"{job_id}_out.mp4")
    if not os.path.exists(path):
        path = os.path.join(TMP_DIR, f"{job_id}_raw.mp4")
    if not os.path.exists(path):
        return JSONResponse({'error': 'not found'}, status_code=404)
    return FileResponse(path, media_type='video/mp4', filename='agroai_result.mp4')


def _mjpeg_generator(source, conf, is_index):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError('cannot open stream')
    frame_idx = 0
    last_dets = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            if max(h, w) > 960:
                s = 960 / max(h, w)
                frame = cv2.resize(frame, (int(w * s), int(h * s)))
            if frame_idx % 3 == 0:
                last_dets = detector.infer(frame, conf_thres=conf)
            annotated = detector.draw(frame, last_dets)
            ok2, buf = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok2:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
            frame_idx += 1
    finally:
        cap.release()


@app.get("/api/stream")
def api_stream(url: str = Query(...), conf: float = 0.35):
    """Proxy + annotate a drone / IP-camera video stream (RTSP/HTTP/MJPEG)."""
    u = url.strip()
    # Accept a plain integer as a local camera/device index — this is how you plug in
    # OBS Virtual Camera: start "Start Virtual Camera" in OBS, then find its index
    # (usually 0 if it's the only camera, otherwise 1, 2… — try a few) and type it here.
    source = int(u) if u.isdigit() else u
    try:
        gen = _mjpeg_generator(source, conf, isinstance(source, int))
        return StreamingResponse(gen, media_type='multipart/x-mixed-replace; boundary=frame')
    except RuntimeError:
        return JSONResponse({'error': 'Не удалось подключиться к потоку'}, status_code=400)


@app.post("/api/advice")
async def api_advice(payload: dict):
    """Send detection results to Groq (LLM) and get a plain-language agronomy recommendation.
    The API key is provided by the client on each request and is never stored on the server."""
    api_key = (payload.get('api_key') or '').strip() or GROQ_API_KEY_DEFAULT.strip()
    if not api_key:
        return JSONResponse({
            'error': 'API-ключ Groq не найден. Впишите его в поле 🔑 в браузере или в переменную '
                      'GROQ_API_KEY_DEFAULT в начале server.py и перезапустите сервер.'
        }, status_code=400)

    context = payload.get('context', 'снимок поля')
    summary = payload.get('summary') or {}
    counts = summary.get('counts') or summary.get('class_counts') or {}
    field_flags = summary.get('field_flags') or []

    if not counts:
        counts_text = 'ничего не обнаружено'
    else:
        counts_text = ', '.join(f"{name} × {n}" for name, n in counts.items())
    flags_text = ', '.join(field_flags) if field_flags else 'не определено'

    prompt = (
        f"Ты — агроном-консультант. Система компьютерного зрения на дроне проанализировала {context} "
        f"и обнаружила следующие объекты: {counts_text}. "
        f"Отмеченное состояние поля: {flags_text}. "
        "Дай короткую практическую рекомендацию на русском языке (4-6 предложений): "
        "что означает эта находка, насколько это критично для урожая, и какие меры стоит "
        "предпринять агроному в ближайшие дни. Пиши по-деловому, без вступлений и приветствий."
    )

    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 500,
            },
            timeout=30,
        )
        data = r.json()
        if r.status_code != 200:
            err = (data.get('error') or {}).get('message', str(data))
            return JSONResponse({'error': f'Groq API: {err}'}, status_code=400)
        text = data['choices'][0]['message']['content'].strip()
        return {'advice': text}
    except requests.exceptions.RequestException as e:
        return JSONResponse({'error': f'Не удалось связаться с Groq: {e}'}, status_code=502)
    except (KeyError, IndexError, ValueError) as e:
        return JSONResponse({'error': f'Неожиданный ответ Groq: {e}'}, status_code=502)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)