"""Background noise removal service.

Decodes any audio/video file with PyAV (bundled ffmpeg), runs DeepFilterNet3
speech enhancement at 48 kHz per channel in overlapping chunks, then re-encodes
at the original sample rate in the requested format.
"""

import logging
import shutil
import tempfile
import threading
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import av
import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

warnings.filterwarnings("ignore", category=UserWarning)
from df.enhance import enhance, init_df  # noqa: E402

log = logging.getLogger("noise-remover")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MODEL_SR = 48_000
CHUNK_SEC = 30
OVERLAP_SEC = 0.5
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
JOB_TTL_SEC = 60 * 60
WORK_DIR = Path(tempfile.gettempdir()) / "noise-remover-jobs"
WORK_DIR.mkdir(exist_ok=True)

OUTPUT_FORMATS = {
    # ext: (container, codec, extra codec options)
    "wav": ("wav", "pcm_s16le", {}),
    "mp3": ("mp3", "libmp3lame", {"b": "192k"}),
    "flac": ("flac", "flac", {}),
    "m4a": ("ipod", "aac", {"b": "192k"}),
}
MEDIA_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac", "m4a": "audio/mp4"}

torch.set_num_threads(max(1, torch.get_num_threads()))
model, df_state, _ = init_df(log_file=None, log_level="WARNING")
log.info("DeepFilterNet3 loaded")

# The model is not thread-safe, so jobs run one at a time in a single worker.
executor = ThreadPoolExecutor(max_workers=1)
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def decode(path: Path) -> tuple[np.ndarray, int]:
    """Decode the first audio stream to float32 [channels, samples] at its native rate."""
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError("No audio stream found in file")
        stream = container.streams.audio[0]
        sr = stream.codec_context.sample_rate or stream.rate
        channels = min(stream.codec_context.channels or 1, 2)
        layout = "stereo" if channels == 2 else "mono"
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=sr)
        parts = []
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                parts.append(out.to_ndarray())
        for out in resampler.resample(None):
            parts.append(out.to_ndarray())
    if not parts:
        raise ValueError("Audio stream is empty")
    return np.concatenate(parts, axis=1).astype(np.float32), sr


def resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    import torchaudio.functional as AF

    return AF.resample(torch.from_numpy(audio), src_sr, dst_sr).numpy()


def denoise_channel(signal: np.ndarray, atten_lim_db: float | None, on_progress) -> np.ndarray:
    """Enhance one 48 kHz channel in overlapping chunks with linear crossfades."""
    chunk = CHUNK_SEC * MODEL_SR
    overlap = int(OVERLAP_SEC * MODEL_SR)
    step = chunk - overlap
    n = signal.shape[0]
    if n <= chunk:
        on_progress(1.0)
        return enhance(model, df_state, torch.from_numpy(signal)[None], atten_lim_db=atten_lim_db)[0].numpy()

    out = np.zeros(n, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
    starts = list(range(0, n - overlap, step))
    for i, start in enumerate(starts):
        seg = signal[start : start + chunk]
        enh = enhance(model, df_state, torch.from_numpy(seg.copy())[None], atten_lim_db=atten_lim_db)[0].numpy()
        if start > 0:
            enh[:overlap] *= fade_in
            out[start : start + overlap] *= fade_in[::-1]
        out[start : start + len(enh)] += enh
        on_progress((i + 1) / len(starts))
    return out


def encode(audio: np.ndarray, sr: int, fmt: str, path: Path) -> None:
    container_fmt, codec, opts = OUTPUT_FORMATS[fmt]
    audio = np.clip(audio, -1.0, 1.0)
    layout = "stereo" if audio.shape[0] == 2 else "mono"
    with av.open(str(path), "w", format=container_fmt) as container:
        stream = container.add_stream(codec, rate=sr)
        stream.layout = layout
        if "b" in opts:
            stream.bit_rate = int(opts["b"].rstrip("k")) * 1000
        block = 4096
        for start in range(0, audio.shape[1], block):
            data = np.ascontiguousarray(audio[:, start : start + block])
            frame = av.AudioFrame.from_ndarray(data, format="fltp", layout=layout)
            frame.sample_rate = sr
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def update(job_id: str, **fields) -> None:
    with jobs_lock:
        jobs[job_id].update(fields)


def run_job(job_id: str, src: Path, fmt: str, atten_lim_db: float | None) -> None:
    started = time.time()
    try:
        update(job_id, status="processing", stage="Decoding", progress=0.02)
        audio, sr = decode(src)
        duration = audio.shape[1] / sr
        update(job_id, duration=duration, stage="Removing noise", progress=0.05)

        audio48 = resample(audio, sr, MODEL_SR)
        n_ch = audio48.shape[0]
        cleaned = []
        for ch in range(n_ch):
            cb = lambda p, ch=ch: update(job_id, progress=0.05 + 0.85 * (ch + p) / n_ch)
            cleaned.append(denoise_channel(audio48[ch], atten_lim_db, cb))
        cleaned = resample(np.stack(cleaned), MODEL_SR, sr)

        update(job_id, stage="Encoding", progress=0.92)
        out_path = src.parent / f"cleaned.{fmt}"
        encode(cleaned, sr, fmt, out_path)
        update(job_id, status="done", stage="Done", progress=1.0, output=str(out_path),
               elapsed=round(time.time() - started, 1))
        log.info("job %s done: %.1fs audio in %.1fs", job_id, duration, time.time() - started)
    except (av.error.FFmpegError, ValueError) as e:
        log.warning("job %s: unreadable input: %s", job_id, e)
        # PyAV errors also subclass ValueError, so check for them first.
        msg = "Couldn't read this file. Is it a valid audio or video file?" if isinstance(e, av.error.FFmpegError) else str(e)
        update(job_id, status="error", stage="Failed", error=msg)
    except Exception as e:  # noqa: BLE001 — surface any other failure to the UI
        log.exception("job %s failed", job_id)
        update(job_id, status="error", stage="Failed", error=str(e))


def cleanup_loop() -> None:
    while True:
        time.sleep(300)
        cutoff = time.time() - JOB_TTL_SEC
        with jobs_lock:
            expired = [jid for jid, j in jobs.items() if j["created"] < cutoff]
            for jid in expired:
                jobs.pop(jid)
        for jid in expired:
            shutil.rmtree(WORK_DIR / jid, ignore_errors=True)


threading.Thread(target=cleanup_loop, daemon=True).start()

app = FastAPI(title="Noise Remover")


@app.middleware("http")
async def no_cache_pages(request, call_next):
    # Always revalidate the UI so new tabs pick up changes after an update.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    output_format: str = Form("wav"),
    strength: int = Form(100),
):
    fmt = output_format.lower()
    if fmt not in OUTPUT_FORMATS:
        raise HTTPException(400, f"Unsupported output format: {fmt}")
    strength = max(0, min(100, strength))
    # strength 100 = full removal; lower values cap attenuation (keeps some ambience).
    atten_lim_db = None if strength >= 100 else 6 + strength * 0.44

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir()
    src = job_dir / f"input{Path(file.filename or '').suffix[:10]}"
    size = 0
    with src.open("wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(413, "File too large (max 500 MB)")
            f.write(chunk)

    stem = Path(file.filename or "audio").stem
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id, "status": "queued", "stage": "Queued", "progress": 0.0,
            "filename": f"{stem}_cleaned.{fmt}", "format": fmt, "created": time.time(),
        }
    executor.submit(run_job, job_id, src, fmt, atten_lim_db)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found or expired")
        return {k: v for k, v in job.items() if k != "output"}


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str, inline: bool = False):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "Result not available")
    return FileResponse(
        job["output"],
        media_type=MEDIA_TYPES[job["format"]],
        filename=None if inline else job["filename"],
    )


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
