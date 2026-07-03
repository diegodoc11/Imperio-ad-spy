"""Transcripción de audio 100% local con faster-whisper (sin API, corre en tu PC).

Usa ffmpeg (ya instalado) para leer el audio del .mp4. La primera vez descarga
el modelo de Whisper desde internet; después funciona offline.
"""
from __future__ import annotations

import os
import pathlib

import requests

_MODEL = None  # se carga una sola vez (lazy)


def get_model():
    """Carga el modelo de Whisper una sola vez y lo reutiliza."""
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        size = os.getenv("WHISPER_MODEL", "small")
        device = os.getenv("WHISPER_DEVICE", "cpu")
        compute = os.getenv("WHISPER_COMPUTE", "int8")
        print(f"[whisper] Cargando modelo '{size}' ({device}/{compute})... "
              "(la primera vez descarga el modelo, puede tardar)")
        _MODEL = WhisperModel(size, device=device, compute_type=compute)
        print("[whisper] Modelo listo.")
    return _MODEL


def download_file(url: str, dest: pathlib.Path) -> pathlib.Path:
    """Descarga cualquier archivo binario (video o imagen) a disco, si no existe ya."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    with requests.get(url, headers=headers, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    return dest


def download_video(url: str, dest: pathlib.Path) -> pathlib.Path:
    """Descarga el video del anuncio a disco (si no existe ya)."""
    return download_file(url, dest)


def transcribe_path(path, language: str | None = None) -> dict:
    """Transcribe un archivo local y devuelve texto + segmentos con tiempos."""
    model = get_model()
    segments, info = model.transcribe(
        str(path), language=language, vad_filter=True, beam_size=1
    )
    segs = []
    for s in segments:
        segs.append({
            "start": round(s.start, 2),
            "end": round(s.end, 2),
            "text": s.text.strip(),
        })
    text = " ".join(s["text"] for s in segs).strip()
    return {
        "language": info.language,
        "duration": round(info.duration, 1),
        "segments": segs,
        "text": text,
    }


def to_srt(segments) -> str:
    """Convierte los segmentos a formato .srt (subtítulos con tiempos)."""
    def ts(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t - int(t)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    out = []
    for i, seg in enumerate(segments, 1):
        out.append(str(i))
        out.append(f"{ts(seg['start'])} --> {ts(seg['end'])}")
        out.append(seg["text"])
        out.append("")
    return "\n".join(out)
