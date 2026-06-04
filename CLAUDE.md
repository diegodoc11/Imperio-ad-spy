# CLAUDE.md — Ad-Spy 🕵️

Contexto para Claude Code (y para cualquier desarrollador) que trabaje en esta app.
Léelo COMPLETO antes de tocar el código. La sección más importante es
**"⚠️ Lecciones aprendidas y errores a NO repetir"**.

---

## 1. Qué es

App **local** (corre en `http://localhost:8000`) para **espiar anuncios** de la
Facebook Ad Library, verlos/reproducirlos, **transcribir** los videos (gratis, en
la máquina del usuario con Whisper) y luego adaptar el copy a un negocio.

Pensada para marketers / agencias. No es SaaS: cada usuario la corre en su PC con
su propio token de Apify.

**Flujo:** buscar por palabra(s) → filtrar/ordenar → ver/reproducir → guardar los
buenos en "Seleccionados" → transcribir → llevar el texto a Claude para el copy.

---

## 2. Arquitectura (archivos)

```
ad-spy-app/
├── app/
│   ├── main.py        # Servidor FastAPI: endpoints + middleware no-cache
│   ├── search.py      # Apify: build URL, normalize(), duración/buckets, destino, meta_rank
│   ├── transcribe.py  # Whisper LOCAL (faster-whisper) + descarga de video
│   └── store.py       # Persistencia en JSON (nichos, shortlist, results pool, scraped_at)
├── static/
│   ├── index.html     # UI (una sola página, sin framework)
│   ├── app.js         # Lógica de front (vanilla JS)
│   └── styles.css     # Estilos (tema oscuro)
├── data/store.json    # Datos del usuario (NO se sube a git)
├── downloads/         # Videos .mp4 + transcripciones .txt/.srt (NO se sube)
├── .env               # Secretos/config (NO se sube — tiene el token de Apify)
├── .env.example       # Plantilla de .env (sí se sube)
├── requirements.txt   # Dependencias Python
├── iniciar.ps1        # Lanzador (Windows)
├── README.md          # Doc para usuarios/alumnos
└── CLAUDE.md          # Este archivo
```

**Stack:** Python 3.12 + FastAPI/uvicorn (backend) · HTML/CSS/JS vanilla, **sin
build step** (frontend) · `uv` para el entorno · `ffmpeg` (lo usa Whisper).

---

## 3. Decisiones de diseño (cerradas con el usuario)

- **Búsqueda = Apify**, actor `curious_coder~facebook-ads-library-scraper`.
  (No existe API pública oficial para anuncios comerciales — ver lecciones.)
- **Transcripción = Whisper LOCAL** (`faster-whisper`, modelo `small`, gratis, offline).
- **Copy = manual en Claude Code** (sin API key de Anthropic en la app).
- **Sin base de datos:** todo en `data/store.json` (suficiente para un solo usuario local).

---

## 4. Modelo de datos (`data/store.json`)

```jsonc
{
  "niches": ["Inteligencia Artificial", ...],
  "shortlist": { "<nicho>": [ad, ...] },          // guardados con ⭐
  "results":   { "<nicho>": { "ads": [ad,...], "query": "..." } }, // pool scrapeado (cap 500)
  "scraped_at":{ "<nicho>": { "<término>": "ISO-datetime" } }      // para el cooldown
}
```

**Objeto `ad` (normalizado en `search.py`):** `library_id, advertiser, copy,
start_date, video_url, thumbnail_url, ad_url, has_video, cta_text, dest_type,
dest_label, dest_domain, link_url, days_active, months_active, duration_label,
bucket, meta_rank`.

---

## 5. Endpoints (`app/main.py`)

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/` | Sirve la UI |
| GET | `/api/health` | token presente, modelo whisper, costo por resultado |
| GET | `/api/apify-usage` | gastado/límite/%/días-a-renovar (solo números, nada sensible) |
| GET/POST | `/api/niches` | listar / crear nichos |
| GET/POST | `/api/shortlist` (+ `/remove`) | seleccionados por nicho |
| GET | `/api/results` · POST `/api/results/clear` | pool scrapeado por nicho |
| GET | `/api/cooldown` | hace cuántos días se scrapeó cada término |
| GET | `/api/search` | **multi-término** (coma), busca cada uno y mezcla; guarda en el pool |
| GET | `/api/video` | descarga+cachea+sirve el .mp4 (FileResponse, soporta range) |
| GET | `/api/thumb` | proxy de miniaturas (evita bloqueos de la CDN de FB) |

Middleware: `Cache-Control: no-store` en TODA respuesta (ver lección de caché).

---

## 6. ⚠️ Lecciones aprendidas y errores a NO repetir

> Esto es lo más valioso del archivo. Cada punto = un error real que cometimos y
> cómo evitarlo.

### Datos de Facebook / Apify
1. **NO hay API oficial para anuncios comerciales.** La Ad Library API oficial de
   Meta solo cubre anuncios de política / temas sociales. Para comerciales hay que
   usar un scraper (Apify). No pierdas tiempo buscando una API gratis: no existe.
2. **Apify cobra por cada resultado que TRAE** (PAY_PER_EVENT, ~$0.00075/anuncio).
   → La deduplicación NO ahorra dinero (ya pagaste al traerlos). Lo único que
   ahorra: **no re-correr** (cooldown) o **traer menos** (count bajo).
3. **El actor exige `count >= 10`** ("Maximum charged results must be at least 10").
   Nunca mandes count menor a 10.
4. **Impresiones / reach / spend vienen NULL en anuncios comerciales.** Meta los
   oculta. NO se puede ordenar por número de impresiones. Lo más cercano es el
   **orden en que Apify los devuelve** (≈ impresiones, desc) → lo guardamos como
   `meta_rank` (posición en los resultados) y se ordena por eso.
5. **`start_date` del actor es un TIMESTAMP Unix (número).** `start_date_formatted`
   es el texto legible. → En `normalize()` se prefiere `start_date_formatted`, y el
   parser de fechas (`_parse_start`) y el `fmtDate` del front **deben** manejar
   también epoch numérico.
6. **Las URLs de video/miniatura de la CDN de FB CADUCAN** (parámetro `oe=`, pocas
   horas). Resultados viejos cacheados no reproducirán/mostrarán miniatura (sale
   placeholder). El texto/datos sí persisten. Los videos ya descargados (al ver o
   transcribir) quedan en `downloads/` y sí persisten.
7. **Búsqueda multi-término:** el usuario pega varias palabras separadas por coma.
   Si se mandan como UN solo `q`, FB devuelve casi 0. → Hay que **separar por coma
   y buscar cada término**, luego mezclar sin duplicados.

### apify-client (Python)
8. **apify-client 3.x:** `client.actor(...).call(...)` devuelve un objeto `Run`,
   **no un dict**. Usa `run.default_dataset_id` (no `run["defaultDatasetId"]`) y
   `client.dataset(id).list_items().items`.

### Frontend (los bugs que más dolieron)
9. **`esc()` debe convertir a string SIEMPRE:** `String(s ?? '')`. Un campo como
   `start_date` puede venir como **número**; hacer `.replace()` sobre un número
   lanza TypeError → **reventó el render entero y dejó la app en blanco**. Regla:
   ningún helper debe asumir que su input es string.
10. **Blinda el arranque (`init`):** envuelve cada paso en try/catch y carga los
    **resultados ANTES** que el shortlist. Un solo anuncio guardado con datos raros
    rompía `renderSel()` → tumbaba `init()` → nunca se llamaba `/api/results` →
    pantalla vacía. Además: cada tarjeta se renderiza en su propio try/catch.
11. **Caché del navegador:** durante desarrollo, sirve TODO con
    `Cache-Control: no-store` **y** versiona los estáticos (`app.js?v=N`,
    `styles.css?v=N`). Sin esto, el navegador ejecuta JS viejo y parece que "los
    cambios no funcionan" (perdimos varias iteraciones por esto). Sube el `?v=`
    cada vez que cambies un estático.
12. **No renderices cientos de tarjetas de golpe.** 500 tarjetas + 500 peticiones
    de miniatura (muchas a URLs caducadas que tardan en fallar) **satura el
    servidor y deja la pantalla en blanco**. Solución: **paginado** (60 + "Ver
    más") + **`loading="lazy"`** en las imágenes + **timeout corto** (8s) en el
    proxy de miniaturas.
13. **Caja de media 4:5 robusta:** usa `position:relative; aspect-ratio:4/5` con los
    hijos en `position:absolute; inset:0`. NO uses `display:flex` con hijos
    `height:100%` — eso ignora el aspect-ratio y los videos salían 9:16 (más altos
    que la tarjeta).
14. **`object-fit` según contexto:**
    - Imagen de anuncio estático → `contain` (se ve completa, sin recortar).
    - Miniatura/video → `cover` (llena el 4:5).
    - **Pantalla completa** (`video:fullscreen`) → `contain !important` (si no, un
      9:16 se estira a horizontal y se ve un zoom enorme recortado).
15. **Las miniaturas necesitan proxy** (`/api/thumb`): puestas directo con la URL
    de FB, el navegador las bloquea (referrer/CORS). El proxy las baja del lado del
    servidor.

### Seguridad
16. **`/api/users/me` de Apify trae datos sensibles** (¡contraseña de proxy!). El
    endpoint `/api/apify-usage` debe devolver **solo** los números de saldo, nunca
    campos sensibles.
17. **El `.env` tiene el token de Apify → JAMÁS subirlo a git.** Está en
    `.gitignore`. Si alguna vez se sube por error, **rotar el token** en Apify.

---

## 7. Cómo correr / desarrollar

```powershell
# 1. Entorno (una vez)
uv venv
uv pip install -r requirements.txt        # o: uv pip install fastapi "uvicorn[standard]" apify-client faster-whisper python-dotenv requests

# 2. Config (una vez): copia .env.example -> .env y pon tu APIFY_TOKEN

# 3. Correr
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir . --port 8000
# o doble clic en iniciar.ps1
```

- Cambios en **.py** → reiniciar uvicorn.
- Cambios en **static/** → solo refrescar el navegador (sube el `?v=` para forzar).
- `ffmpeg` debe estar en el PATH (lo usa Whisper). La primera transcripción descarga
  el modelo (~480 MB).

## 8. Convenciones
- Frontend sin framework ni build: HTML/CSS/JS plano servido por FastAPI.
- Idioma de la UI: español.
- El `bucket` de tiempo activo y `meta_rank` se calculan en backend (`add_duration`,
  `normalize`) y el front solo ordena/filtra.

## 9. Ideas futuras (no implementadas)
- Contador "nuevos vs repetidos" tras cada búsqueda.
- "Modo refresco" con cantidad baja por término.
- Integrar el paso de copy con la API de Anthropic (opcional).
- Whisper local con GPU para transcripción más rápida.
