"""Servidor local de la app Ad-Spy (FastAPI).

Endpoints:
  GET  /                 -> interfaz web
  GET  /api/health       -> estado (token Apify, modelo whisper)
  GET  /api/search?q=    -> busca anuncios en la Ad Library (vía Apify)
  GET  /api/video?url=   -> descarga+sirve el video para reproducirlo
  POST /api/transcribe   -> transcribe un video con Whisper local
"""
from __future__ import annotations

import os
import pathlib
from datetime import datetime, timezone

import requests
from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

BASE = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

from app import search as search_mod  # noqa: E402
from app import store as store_mod  # noqa: E402
from app import transcribe as tx  # noqa: E402

app = FastAPI(title="Ad-Spy local")


@app.middleware("http")
async def _no_cache(request, call_next):
    """Evita que el navegador use versiones viejas en caché (HTML/JS/CSS)."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response

DOWNLOADS = BASE / "downloads"
DOWNLOADS.mkdir(exist_ok=True)
STATIC = BASE / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/downloads", StaticFiles(directory=str(DOWNLOADS)), name="downloads")

STORE = store_mod.Store(BASE / "data" / "store.json")
COST_PER_RESULT = float(os.getenv("APIFY_COST_PER_RESULT", "0.00075"))
COOLDOWN_DAYS = int(os.getenv("COOLDOWN_DAYS", "12"))


def _safe_id(s: str) -> str:
    return "".join(c for c in (s or "ad") if c.isalnum() or c in "-_")[:40] or "ad"


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "apify_token": bool(os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN")),
        "whisper_model": os.getenv("WHISPER_MODEL", "small"),
        "cost_per_result": COST_PER_RESULT,
    }


@app.get("/api/apify-usage")
def apify_usage():
    """Saldo/uso de Apify del mes (solo números, nada sensible)."""
    token = os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN")
    if not token:
        return {"ok": False, "error": "sin token"}
    try:
        r = requests.get("https://api.apify.com/v2/users/me/limits",
                         params={"token": token}, timeout=20)
        d = r.json().get("data", {})
        used = (d.get("current") or {}).get("monthlyUsageUsd", 0) or 0
        limit = (d.get("limits") or {}).get("maxMonthlyUsageUsd", 0) or 0
        end = (d.get("monthlyUsageCycle") or {}).get("endAt")
        days_left, reset = None, None
        if end:
            dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            days_left = max(0, (dt - datetime.now(timezone.utc)).days)
            reset = dt.strftime("%Y-%m-%d")
        pct = round(used / limit * 100) if limit else 0
        return {"ok": True, "used": round(used, 2), "limit": round(limit, 2),
                "percent": pct, "days_left": days_left, "reset": reset}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/niches")
def get_niches():
    return {"niches": STORE.niches()}


@app.post("/api/niches")
def add_niche(payload: dict = Body(...)):
    return {"niches": STORE.add_niche(payload.get("name"))}


@app.get("/api/shortlist")
def get_shortlist(niche: str):
    ads = STORE.shortlist(niche)
    now = datetime.now()
    for a in ads:
        search_mod.add_duration(a, now)  # refresca el tiempo activo
    return {"ads": ads}


@app.post("/api/shortlist")
def add_shortlist(payload: dict = Body(...)):
    niche = payload.get("niche")
    ad = payload.get("ad") or {}
    if not niche or not ad.get("library_id"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "faltan datos"})
    STORE.add_item(niche, ad)
    return {"ok": True}


@app.post("/api/shortlist/remove")
def remove_shortlist(payload: dict = Body(...)):
    STORE.remove_item(payload.get("niche"), payload.get("library_id"))
    return {"ok": True}


@app.get("/api/cooldown")
def cooldown(niche: str = "", q: str = ""):
    """Para cada término dice hace cuántos días se scrapeó (avisar antes de re-cobrar)."""
    terms = [t.strip() for t in q.split(",") if t.strip()]
    sa = STORE.scraped_at(niche) if niche else {}
    now = datetime.now()
    out = []
    for t in terms:
        iso = sa.get(t)
        days = None
        if iso:
            try:
                days = (now - datetime.fromisoformat(iso)).days
            except Exception:
                days = None
        out.append({"term": t, "days_ago": days,
                    "recent": days is not None and days < COOLDOWN_DAYS})
    return {"cooldown_days": COOLDOWN_DAYS, "terms": out}


@app.get("/api/search")
def api_search(q: str = Query(...), count: int = 30, country: str = "ALL",
               active: bool = True, niche: str = ""):
    # Permite varios términos separados por coma: busca cada uno y junta todo
    terms = [t.strip() for t in q.split(",") if t.strip()]
    if not terms:
        return JSONResponse(status_code=400, content={"ok": False, "error": "consulta vacía"})
    try:
        all_ads, seen, per_term = [], set(), {}
        for t in terms:
            try:
                ads_t = search_mod.search_ads(t, count=count, country=country, active=active)
            except Exception as e:
                per_term[t] = f"error: {str(e)[:80]}"
                continue
            per_term[t] = len(ads_t)
            if niche:
                STORE.set_scraped(niche, t, datetime.now().isoformat())
            for a in ads_t:
                lid = str(a.get("library_id"))
                if lid and lid not in seen:
                    seen.add(lid)
                    all_ads.append(a)
        pool = STORE.merge_results(niche, all_ads, q) if niche else all_ads
        now = datetime.now()
        for a in pool:
            search_mod.add_duration(a, now)
        return {"ok": True, "new_count": len(all_ads), "count": len(pool),
                "ads": pool, "terms": per_term}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.get("/api/results")
def get_results(niche: str):
    """Devuelve los anuncios ya scrapeados (guardados) de un nicho."""
    ads = STORE.results(niche)
    now = datetime.now()
    for a in ads:
        search_mod.add_duration(a, now)
    return {"ads": ads, "query": STORE.results_query(niche)}


@app.post("/api/results/clear")
def clear_results(payload: dict = Body(...)):
    STORE.clear_results(payload.get("niche"))
    return {"ok": True}


@app.get("/api/video")
def api_video(url: str, id: str = "ad"):
    """Descarga (y cachea) el video y lo sirve para reproducir en la app."""
    dest = DOWNLOADS / f"{_safe_id(id)}.mp4"
    try:
        tx.download_video(url, dest)
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return FileResponse(str(dest), media_type="video/mp4")


@app.get("/api/thumb")
def api_thumb(url: str):
    """Proxy de miniaturas (evita bloqueos de la CDN de FB en el navegador)."""
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        return Response(content=r.content, media_type=r.headers.get("Content-Type", "image/jpeg"))
    except Exception:
        return JSONResponse(status_code=404, content={"ok": False})


@app.post("/api/transcribe")
def api_transcribe(payload: dict = Body(...)):
    lib = _safe_id(str(payload.get("library_id") or "ad"))
    url = payload.get("video_url")
    if not url:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Falta video_url"})
    try:
        dest = DOWNLOADS / f"{lib}.mp4"
        tx.download_video(url, dest)
        result = tx.transcribe_path(dest)
        (DOWNLOADS / f"{lib}.txt").write_text(result["text"], encoding="utf-8")
        (DOWNLOADS / f"{lib}.srt").write_text(tx.to_srt(result["segments"]), encoding="utf-8")
        return {"ok": True, "library_id": lib, **result}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
