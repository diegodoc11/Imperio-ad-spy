"""Servidor local de la app Ad-Spy (FastAPI).

Endpoints:
  GET  /                 -> interfaz web
  GET  /api/health       -> estado (token Apify, modelo whisper)
  GET  /api/search?q=    -> busca anuncios en la Ad Library (vía Apify)
  GET  /api/video?url=   -> descarga+sirve el video para reproducirlo
  POST /api/transcribe   -> transcribe un video con Whisper local
"""
from __future__ import annotations

import io
import os
import pathlib
import threading
import time
import zipfile
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
POOL_MAX = int(os.getenv("POOL_MAX", "3000"))  # máx. anuncios acumulados por nicho
VIDEO_TTL_HOURS = int(os.getenv("VIDEO_TTL_HOURS", "72"))


def cleanup_old_videos():
    """Borra media (.mp4/.jpg) no vista en VIDEO_TTL_HOURS, salvo la de Seleccionados."""
    try:
        cutoff = time.time() - VIDEO_TTL_HOURS * 3600
        saved = STORE.all_shortlisted_ids()
        for f in list(DOWNLOADS.glob("*.mp4")) + list(DOWNLOADS.glob("*.jpg")):
            if f.stem in saved:
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _cleanup_loop():
    while True:
        cleanup_old_videos()
        time.sleep(6 * 3600)


threading.Thread(target=_cleanup_loop, daemon=True).start()


def _safe_id(s: str) -> str:
    return "".join(c for c in (s or "ad") if c.isalnum() or c in "-_")[:40] or "ad"


def _cache_ad_media(ad: dict) -> dict:
    """Descarga a disco el video y/o la imagen del anuncio, para que sobrevivan a la
    caducidad de las URLs de la CDN de Facebook (que mueren en horas/días)."""
    out = {"video": None, "image": None}
    lid = _safe_id(str(ad.get("library_id") or ""))
    if not lid or lid == "ad":
        return out
    vurl = ad.get("video_url")
    if ad.get("has_video") and vurl:
        try:
            tx.download_video(vurl, DOWNLOADS / f"{lid}.mp4")
            out["video"] = "ok"
        except Exception as e:
            out["video"] = f"err: {str(e)[:60]}"
    iurl = ad.get("thumbnail_url")
    if iurl:
        try:
            tx.download_file(iurl, DOWNLOADS / f"{lid}.jpg")
            out["image"] = "ok"
        except Exception as e:
            out["image"] = f"err: {str(e)[:60]}"
    return out


def _mark_extras(ads):
    """Agrega tiempo activo y si ya existe la transcripción (.txt) de cada anuncio."""
    now = datetime.now()
    for a in ads:
        search_mod.add_duration(a, now)
        lid = _safe_id(str(a.get("library_id") or ""))
        a["has_transcript"] = (DOWNLOADS / f"{lid}.txt").exists()
    return ads


# ---------- 🔬 Modo investigación ----------
# Transcribe EN LOTE los mejores videos de un nicho (los que más tiempo llevan activos =
# los que están vendiendo) y exporta un informe con copy + guion para analizar el nicho.
_RESEARCH: dict = {}  # nicho -> estado del trabajo en curso
_RESEARCH_LOCK = threading.Lock()


def _by_winner(a: dict):
    """Orden 'ganadores primero': más meses activo, desempate por orden de Meta."""
    return (-(a.get("months_active") or 0), a.get("meta_rank") if a.get("meta_rank") is not None else 10**9)


def _research_pick(niche: str, top_n: int) -> list:
    ads = [a for a in STORE.results(niche) if a.get("has_video") and a.get("video_url")]
    _mark_extras(ads)
    ads.sort(key=_by_winner)
    return ads[:top_n]


def _research_worker(niche: str, ads: list):
    st = _RESEARCH[niche]
    for a in ads:
        lid = _safe_id(str(a.get("library_id") or ""))
        st["current"] = a.get("advertiser") or lid
        try:
            if not (DOWNLOADS / f"{lid}.txt").exists():
                dest = DOWNLOADS / f"{lid}.mp4"
                tx.download_video(a["video_url"], dest)
                result = tx.transcribe_path(dest)
                (DOWNLOADS / f"{lid}.txt").write_text(result["text"], encoding="utf-8")
                (DOWNLOADS / f"{lid}.srt").write_text(tx.to_srt(result["segments"]), encoding="utf-8")
            if a.get("thumbnail_url"):  # la imagen también sirve de referencia
                try:
                    tx.download_file(a["thumbnail_url"], DOWNLOADS / f"{lid}.jpg")
                except Exception:
                    pass
            st["done"] += 1
        except Exception as e:
            st["failed"] += 1
            st["errors"].append(f"{a.get('advertiser') or lid}: {str(e)[:70]}")
    st["status"] = "done"
    st["current"] = ""


@app.post("/api/research/start")
def research_start(payload: dict = Body(...)):
    """Arranca (en segundo plano) la transcripción de los top-N videos del nicho."""
    niche = payload.get("niche")
    top_n = int(payload.get("top_n") or 30)
    if not niche:
        return JSONResponse(status_code=400, content={"ok": False, "error": "falta niche"})
    with _RESEARCH_LOCK:
        cur = _RESEARCH.get(niche)
        if cur and cur.get("status") == "running":
            return {"ok": True, "already_running": True, **cur}
        ads = _research_pick(niche, top_n)
        _RESEARCH[niche] = {"status": "running", "total": len(ads), "done": 0,
                            "failed": 0, "current": "", "errors": []}
    threading.Thread(target=_research_worker, args=(niche, ads), daemon=True).start()
    return {"ok": True, **_RESEARCH[niche]}


@app.get("/api/research/status")
def research_status(niche: str):
    idle = {"status": "idle", "total": 0, "done": 0, "failed": 0, "current": "", "errors": []}
    return {"ok": True, **(_RESEARCH.get(niche) or idle)}


@app.get("/api/research/export")
def research_export(niche: str, top_n: int = 60):
    """Informe .md del nicho: copy + guion de los videos transcritos (ganadores primero)
    y el copy de los anuncios de imagen. Es lo que se le pasa a Claude para analizar."""
    ads = _mark_extras(STORE.results(niche))
    vids = sorted([a for a in ads if a.get("has_transcript")], key=_by_winner)
    imgs = sorted([a for a in ads if not a.get("has_video")], key=_by_winner)

    def meta(a: dict) -> list:
        cta = a.get("cta_text") or "—"
        dest = a.get("dest_label") or a.get("dest_type") or "—"
        dom = f" · {a.get('dest_domain')}" if a.get("dest_domain") else ""
        return [
            f"- **Tiempo activo:** {a.get('months_active') or 0} meses (publicado {a.get('start_date') or '?'})",
            f"- **CTA:** {cta} → {dest}{dom}",
            f"- **Copias del anuncio:** {a.get('collation_count') or 1} · FB: {a.get('ad_url') or '—'}",
        ]

    L = [f"# 🔬 Investigación de anuncios — {niche}",
         f"_Generado: {datetime.now():%Y-%m-%d %H:%M}_  ",
         f"Pool: **{len(ads)}** anuncios · **{len(vids)}** videos transcritos · **{len(imgs)}** solo imagen",
         "", "## A) VIDEOS con guion transcrito (ordenados: más tiempo activo primero)", ""]
    for i, a in enumerate(vids[:top_n], 1):
        lid = _safe_id(str(a.get("library_id") or ""))
        guion = (DOWNLOADS / f"{lid}.txt").read_text(encoding="utf-8", errors="ignore").strip()
        L += [f"### {i}. {a.get('advertiser') or '(sin nombre)'}", *meta(a), "",
              f"**Copy del anuncio:**  \n{(a.get('copy') or '(sin texto)').strip()}", "",
              f"**Guion del video (transcripción):**  \n{guion or '(vacío)'}", "", "---", ""]
    L += ["## B) ANUNCIOS DE IMAGEN (solo copy; ordenados: más tiempo activo primero)", ""]
    for i, a in enumerate(imgs[:top_n], 1):
        L += [f"### {i}. {a.get('advertiser') or '(sin nombre)'}", *meta(a), "",
              f"**Copy:**  \n{(a.get('copy') or '(sin texto)').strip()}", "", "---", ""]
    out = DOWNLOADS / f"investigacion_{_safe_id(niche)}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return FileResponse(str(out), media_type="text/markdown", filename=out.name)


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
    _mark_extras(ads)
    return {"ads": ads}


@app.post("/api/shortlist")
def add_shortlist(payload: dict = Body(...)):
    niche = payload.get("niche")
    ad = payload.get("ad") or {}
    if not niche or not ad.get("library_id"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "faltan datos"})
    STORE.add_item(niche, ad)
    # Blindar la media: al seleccionar, descarga video+imagen a disco en segundo plano
    # (sin bloquear la respuesta) para que sobrevivan a la caducidad de las URLs de FB.
    threading.Thread(target=_cache_ad_media, args=(ad,), daemon=True).start()
    return {"ok": True}


@app.post("/api/shortlist/remove")
def remove_shortlist(payload: dict = Body(...)):
    STORE.remove_item(payload.get("niche"), payload.get("library_id"))
    return {"ok": True}


@app.post("/api/shortlist/cache-media")
def cache_shortlist_media():
    """Descarga a disco el video/imagen de TODOS los seleccionados que aún tengan
    enlace vivo (backfill). Bloquea hasta terminar; devuelve un reporte."""
    ads = STORE.all_shortlisted_ads()
    rep = {"total": len(ads), "video_ok": 0, "video_err": 0, "image_ok": 0, "image_err": 0}
    for ad in ads:
        r = _cache_ad_media(ad)
        if r["video"] == "ok":
            rep["video_ok"] += 1
        elif r["video"]:
            rep["video_err"] += 1
        if r["image"] == "ok":
            rep["image_ok"] += 1
        elif r["image"]:
            rep["image_err"] += 1
    return {"ok": True, **rep}


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
        pool = STORE.merge_results(niche, all_ads, q, max_items=POOL_MAX) if niche else all_ads
        _mark_extras(pool)
        return {"ok": True, "new_count": len(all_ads), "count": len(pool),
                "ads": pool, "terms": per_term}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.get("/api/results")
def get_results(niche: str):
    """Devuelve los anuncios ya scrapeados (guardados) de un nicho."""
    ads = STORE.results(niche)
    _mark_extras(ads)
    return {"ads": ads, "query": STORE.results_query(niche)}


@app.post("/api/results/clear")
def clear_results(payload: dict = Body(...)):
    STORE.clear_results(payload.get("niche"))
    return {"ok": True}


@app.post("/api/results/remove")
def remove_result(payload: dict = Body(...)):
    n = STORE.remove_result(payload.get("niche"), payload.get("library_id"))
    return {"ok": True, "removed": n}


@app.post("/api/results/remove-advertiser")
def remove_results_advertiser(payload: dict = Body(...)):
    n = STORE.remove_results_by_advertiser(payload.get("niche"), payload.get("advertiser"))
    return {"ok": True, "removed": n}


@app.get("/api/download-all")
def download_all(niche: str, source: str = "pool"):
    """ZIP con transcripciones (.txt). source=shortlist usa los Seleccionados."""
    ads = STORE.shortlist(niche) if source == "shortlist" else STORE.results(niche)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for a in ads:
            lid = _safe_id(str(a.get("library_id") or ""))
            txt = DOWNLOADS / f"{lid}.txt"
            if txt.exists():
                adv = "".join(c for c in (a.get("advertiser") or "anuncio")
                              if c.isalnum() or c in " -_").strip()[:40] or "anuncio"
                try:
                    z.writestr(f"{adv}_{lid}.txt", txt.read_text(encoding="utf-8"))
                except Exception:
                    pass
    buf.seek(0)
    fn = f"transcripciones_{_safe_id(niche)}.zip"
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@app.get("/api/page-ads")
def page_ads(page_id: str, niche: str = "", count: int = 50):
    """Scrapea toda la biblioteca activa de un creador (por page_id) y la mezcla al pool."""
    if not page_id:
        return JSONResponse(status_code=400, content={"ok": False, "error": "falta page_id"})
    try:
        ads = search_mod.search_page_ads(page_id, count=count)
        pool = STORE.merge_results(niche, ads, max_items=POOL_MAX) if niche else ads
        _mark_extras(pool)
        return {"ok": True, "new_count": len(ads), "count": len(pool), "ads": pool}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.get("/api/video")
def api_video(url: str, id: str = "ad"):
    """Descarga (y cachea) el video y lo sirve para reproducir en la app."""
    dest = DOWNLOADS / f"{_safe_id(id)}.mp4"
    try:
        tx.download_video(url, dest)
        os.utime(dest, None)  # marca "visto ahora" → reinicia el reloj de auto-limpieza
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return FileResponse(str(dest), media_type="video/mp4")


@app.get("/api/thumb")
def api_thumb(url: str, id: str = ""):
    """Proxy de miniaturas. Si el anuncio tiene la imagen guardada en disco (por estar
    en Seleccionados), la sirve desde ahí — así se ve aunque la URL de FB ya caducó.
    Si no, la baja del lado del servidor (evita bloqueos de la CDN de FB en el navegador)."""
    if id:
        local = DOWNLOADS / f"{_safe_id(id)}.jpg"
        if local.exists() and local.stat().st_size > 0:
            return FileResponse(str(local), media_type="image/jpeg")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if r.status_code == 200:
            return Response(content=r.content, media_type=r.headers.get("Content-Type", "image/jpeg"))
    except Exception:
        pass
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
