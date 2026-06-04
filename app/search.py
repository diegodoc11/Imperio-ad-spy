"""Búsqueda de anuncios en la Facebook Ad Library vía un actor de Apify.

La Ad Library no tiene API pública para anuncios comerciales, así que usamos un
"actor" de Apify que la rastrea. El resultado se normaliza a un formato simple.
"""
from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import quote, urlparse

DEFAULT_ACTOR = "curious_coder~facebook-ads-library-scraper"


def build_search_url(query: str, country: str = "ALL", active: bool = True) -> str:
    """Arma la URL de búsqueda de la Ad Library (la misma que usarías a mano)."""
    status = "active" if active else "all"
    return (
        "https://www.facebook.com/ads/library/?"
        f"active_status={status}&ad_type=all&country={country}"
        f"&q={quote(query)}&search_type=keyword_unordered&media_type=all"
    )


def _dig(d, *paths):
    """Devuelve el primer valor no vacío entre varias rutas tipo 'a.b.c'."""
    for path in paths:
        cur = d
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, "", [], {}):
            return cur
    return None


def _destination(snap: dict, item: dict) -> dict:
    """Detecta a dónde lleva el anuncio: WhatsApp, Instagram, Messenger, web, app…"""
    link = _dig(snap, "link_url") or _dig(item, "link_url") or ""
    cta_text = _dig(snap, "cta_text") or _dig(item, "cta_text") or ""
    cta_type = (_dig(snap, "cta_type") or "").upper()
    caption = _dig(snap, "caption") or ""
    domain = ""
    if link:
        try:
            domain = urlparse(link if "//" in link else "http://" + link).netloc.replace("www.", "")
        except Exception:
            domain = ""
    low = (str(link) + " " + cta_type + " " + str(caption)).lower()
    if "wa.me" in low or "whatsapp" in low:
        dtype, dlabel = "whatsapp", "WhatsApp"
    elif "instagram.com" in low or "ig.me" in low or cta_type == "INSTAGRAM":
        dtype, dlabel = "instagram", "Instagram"
    elif "m.me" in low or "messenger" in low or "MESSAGE" in cta_type:
        dtype, dlabel = "messenger", "Messenger / DM"
    elif "apps.apple" in low or "play.google" in low or "itunes.apple" in low or "INSTALL" in cta_type:
        dtype, dlabel = "app", "App"
    elif "fb.me" in low or "facebook.com" in low:
        dtype, dlabel = "facebook", "Facebook"
    elif link:
        dtype, dlabel = "web", (domain or "Web")
    else:
        dtype, dlabel = "ninguno", ""
    return {"cta_text": cta_text, "cta_type": cta_type, "dest_type": dtype,
            "dest_label": dlabel, "dest_domain": domain, "link_url": link}


def normalize(item: dict) -> dict:
    """Convierte un objeto crudo del actor a nuestro formato estándar."""
    snap = item.get("snapshot") or {}
    cards = snap.get("cards") or []
    card0 = (cards[0] if isinstance(cards, list) and cards else {}) or {}

    # --- Video ---
    video = None
    vids = snap.get("videos") or item.get("videos") or []
    if isinstance(vids, list) and vids:
        v0 = vids[0] or {}
        video = v0.get("video_hd_url") or v0.get("video_sd_url") or v0.get("videoUrl")
    video = video or card0.get("video_hd_url") or card0.get("video_sd_url")
    video = video or _dig(item, "video_hd_url", "video_sd_url", "videoUrl")

    # --- Miniatura ---
    thumb = None
    if isinstance(vids, list) and vids:
        thumb = (vids[0] or {}).get("video_preview_image_url")
    imgs = snap.get("images") or []
    if not thumb and isinstance(imgs, list) and imgs:
        thumb = (imgs[0] or {}).get("original_image_url") or (imgs[0] or {}).get("resized_image_url")
    if not thumb:
        thumb = (card0.get("video_preview_image_url") or card0.get("resized_image_url")
                 or card0.get("original_image_url"))
    thumb = thumb or _dig(item, "thumbnail", "image_url", "preview_image_url")

    # --- Copy / texto del anuncio ---
    copy_text = _dig(snap, "body.text")
    if not copy_text or "{{" in str(copy_text):  # anuncios dinámicos de catálogo
        cards = snap.get("cards") or []
        card0 = (cards[0] if isinstance(cards, list) and cards else {}) or {}
        copy_text = (
            _dig(snap, "title")
            or _dig(snap, "caption")
            or _dig(snap, "link_description")
            or card0.get("body")
            or card0.get("title")
            or _dig(item, "ad_creative_body", "text")
            or copy_text  # deja el template si no hay nada mejor
        )

    # --- Anunciante ---
    advertiser = _dig(snap, "page_name") or _dig(item, "page_name", "pageName", "advertiser")

    # --- Fecha de inicio ---
    start = _dig(item, "start_date_formatted", "start_date", "ad_delivery_start_time", "startDate")

    # --- ID de la biblioteca ---
    lib_id = _dig(item, "ad_archive_id", "adArchiveID", "ad_archive_ID", "adId", "id", "library_id")

    dest = _destination(snap, item)
    page_id = _dig(item, "page_id", "pageID", "snapshot.page_id")
    collation = _dig(item, "collation_count", "ads_count") or 1

    return {
        "library_id": str(lib_id) if lib_id else None,
        "advertiser": advertiser,
        "copy": copy_text,
        "start_date": start,
        "video_url": video,
        "thumbnail_url": thumb,
        "ad_url": f"https://www.facebook.com/ads/library/?id={lib_id}" if lib_id else None,
        "has_video": bool(video),
        "page_id": str(page_id) if page_id else None,
        "collation_count": collation,
        "cta_text": dest["cta_text"],
        "dest_type": dest["dest_type"],
        "dest_label": dest["dest_label"],
        "dest_domain": dest["dest_domain"],
        "link_url": dest["link_url"],
    }


def _parse_start(s):
    """Parsea la fecha de inicio del anuncio en varios formatos posibles."""
    if not s:
        return None
    s = str(s).strip()
    if s.isdigit():  # timestamp Unix (segundos o milisegundos)
        try:
            ts = int(s)
            if ts > 1_000_000_000_000:
                ts //= 1000
            return datetime.fromtimestamp(ts)
        except Exception:
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def _bucket_and_label(days):
    """Devuelve (clave_de_rango, etiqueta_humana) según los días activos."""
    if days is None:
        return ("desconocido", "?")
    m = days / 30.44
    if m >= 12:
        years = int(m // 12)
        rem = int(round(m - years * 12))
        human = f"{years} año{'s' if years > 1 else ''}"
        if rem:
            human += f" {rem} mes{'es' if rem != 1 else ''}"
    elif m >= 1:
        mm = int(round(m))
        human = f"{mm} mes{'es' if mm != 1 else ''}"
    else:
        d = int(days)
        human = f"{d} día{'s' if d != 1 else ''}"

    if m >= 24:
        b = "siempre"
    elif m >= 12:
        b = "1-2a"
    elif m >= 9:
        b = "9-12m"
    elif m >= 6:
        b = "6-9m"
    elif m >= 3:
        b = "3-6m"
    elif m >= 2:
        b = "2-3m"
    elif m >= 1:
        b = "1-2m"
    else:
        b = "0-1m"
    return (b, human)


def add_duration(ad, now):
    """Agrega días/meses activos, etiqueta y rango (bucket) al anuncio."""
    dt = _parse_start(ad.get("start_date"))
    if dt:
        days = max(0, (now - dt).days)
        bucket, human = _bucket_and_label(days)
        ad["days_active"] = days
        ad["months_active"] = round(days / 30.44, 1)
        ad["duration_label"] = human
        ad["bucket"] = bucket
    else:
        ad["days_active"] = None
        ad["months_active"] = None
        ad["duration_label"] = "?"
        ad["bucket"] = "desconocido"
    return ad


def search_ads(query: str, count: int = 30, country: str = "ALL",
               active: bool = True, token: str | None = None) -> list[dict]:
    """Lanza el actor de Apify y devuelve una lista de anuncios normalizados."""
    from apify_client import ApifyClient

    token = token or os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError(
            "Falta el token de Apify. Crea el archivo .env (copia .env.example) "
            "y pon tu APIFY_TOKEN."
        )

    client = ApifyClient(token)
    actor = os.getenv("APIFY_ACTOR", DEFAULT_ACTOR)

    run_input = {
        "urls": [{"url": build_search_url(query, country, active), "method": "GET"}],
        "count": max(10, int(count)),  # el actor exige mínimo 10
        "scrapeAdDetails": True,
        "activeStatus": "active" if active else "all",
    }

    run = client.actor(actor).call(run_input=run_input)
    if run is None or not getattr(run, "default_dataset_id", None):
        raise RuntimeError("El actor de Apify no devolvió resultados.")

    items = client.dataset(run.default_dataset_id).list_items().items
    now = datetime.now()
    ads = []
    for i, it in enumerate(items):
        a = add_duration(normalize(it), now)
        a["meta_rank"] = i  # posición en el orden de Meta (≈ por impresiones, desc)
        ads.append(a)
    ads = [a for a in ads if a.get("library_id")]
    # Por defecto: más tiempo activos primero (los "ganadores" evergreen)
    ads.sort(key=lambda a: (a.get("days_active") is None, -(a.get("days_active") or 0)))
    return ads


def build_page_url(page_id: str, active: bool = True) -> str:
    status = "active" if active else "all"
    return ("https://www.facebook.com/ads/library/?"
            f"active_status={status}&ad_type=all&country=ALL&is_targeted_country=false"
            f"&media_type=all&search_type=page&view_all_page_id={page_id}")


def search_page_ads(page_id: str, count: int = 50, active: bool = True, token: str | None = None) -> list[dict]:
    """Scrapea TODOS los anuncios activos de una página/creador por su page_id."""
    from apify_client import ApifyClient

    token = token or os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("Falta el token de Apify (.env).")
    client = ApifyClient(token)
    actor = os.getenv("APIFY_ACTOR", DEFAULT_ACTOR)
    run_input = {
        "urls": [{"url": build_page_url(page_id, active), "method": "GET"}],
        "count": max(10, int(count)),
        "scrapeAdDetails": True,
        "activeStatus": "active" if active else "all",
    }
    run = client.actor(actor).call(run_input=run_input)
    if run is None or not getattr(run, "default_dataset_id", None):
        raise RuntimeError("El actor de Apify no devolvió resultados.")
    items = client.dataset(run.default_dataset_id).list_items().items
    now = datetime.now()
    ads = []
    for i, it in enumerate(items):
        a = add_duration(normalize(it), now)
        a["meta_rank"] = i
        ads.append(a)
    return [a for a in ads if a.get("library_id")]
