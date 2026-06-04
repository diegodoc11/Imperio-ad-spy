# 🕵️ Ad-Spy — Espía de Anuncios con IA

App **local** para investigar anuncios de la **Facebook Ad Library**, verlos,
**transcribir los videos gratis** (con IA en tu propia PC) y adaptar el copy a tu
negocio. Ideal para marketers, agencias, creadores e infoproductores.

> Hecha para correr en **tu computadora** (no es una web pública). Cada quien usa
> su propia cuenta de Apify. Tus datos no salen de tu máquina (salvo las búsquedas
> que Apify hace y la transcripción, que es 100% local).

---

## ✨ Qué hace

- 🔎 **Busca anuncios** por una o **varias palabras** (separadas por coma).
- 🌍 **Filtra por país** (Colombia, México, España, todos…).
- ⏱️ **Muestra cuánto lleva activo** cada anuncio y permite **filtrar por rango**
  (último mes, 3–6 meses, 1–2 años, etc.). *Los que llevan meses activos suelen ser
  los ganadores: nadie mantiene pagando un anuncio que no funciona.*
- ▶️ **Reproduce los videos** dentro de la app (y a pantalla completa en vertical).
- ➡️ Indica **a dónde envía** cada anuncio (WhatsApp, Instagram, web, app…).
- ⭐ **Guarda** tus favoritos en "Seleccionados" (organizado por **nicho**).
- 📝 **Transcribe** los videos **gratis y local** (Whisper) → copias el texto.
- 💰 Muestra tu **saldo de Apify** y el **costo estimado** de cada búsqueda.
- 🔁 **Guarda lo scrapeado** (no se pierde al cerrar) y te **avisa** si vas a
  re-scrapear algo reciente, para no gastar de más.

---

## 🧰 Requisitos

- **Python 3.10+** (probado en 3.12)
- **ffmpeg** (lo usa la transcripción) — en el PATH
- **[uv](https://docs.astral.sh/uv/)** (recomendado) o `pip`
- Una **cuenta de Apify** (tiene plan gratis) y su **API token**
- Windows, macOS o Linux

---

## 🚀 Instalación

```bash
# 1) Clona el repo
git clone https://github.com/TU-USUARIO/ad-spy.git
cd ad-spy

# 2) Crea el entorno e instala dependencias
uv venv
uv pip install -r requirements.txt
#   (sin uv:  python -m venv .venv  &&  .venv/Scripts/pip install -r requirements.txt)

# 3) Configura tu token (ver abajo)
#    copia .env.example a .env  y pega tu APIFY_TOKEN
```

### 🔑 Obtener tu token de Apify
1. Crea cuenta en https://apify.com (el plan gratis sirve para empezar).
2. Ve a **Settings → Integrations → Personal API token** y cópialo.
3. Pégalo en el archivo **`.env`** en la línea `APIFY_TOKEN=`.

> El actor de scraping usado es `curious_coder/facebook-ads-library-scraper`
> (Apify cobra ~$0.00075 por anuncio que trae).

---

## ▶️ Cómo iniciarla

```bash
# Windows (doble clic):  iniciar.ps1
# o por terminal (cualquier SO):
.venv/Scripts/python -m uvicorn app.main:app --app-dir . --port 8000
```
Abre **http://localhost:8000** en tu navegador.

---

## 🧭 Cómo usarla

1. Elige tu **Nicho** arriba (o crea uno con ➕). Lo que guardes queda separado por nicho.
2. **Busca**: escribe una o varias palabras (`claude, automatizar con ia, anuncios con ia`),
   elige país y cantidad. Mira el **costo estimado** y pulsa **Buscar**.
3. **Filtra** por ⏱️ tiempo activo y **ordena** (≈ impresiones de Meta, más antiguo, etc.).
4. **▶ Ver** para reproducir; **☆ Guardar** los buenos (van a **⭐ Seleccionados**).
5. En **⭐ Seleccionados**, pulsa **📝 Transcribir** (gratis, local) y copia el texto.
6. Lleva esa transcripción a tu IA favorita para **adaptar el copy** a tu oferta.

---

## 💰 Costos

| Parte | Costo |
|---|---|
| Búsqueda (Apify) | ~**$0.00075 por anuncio** (ej. 50 ≈ $0.04; 7 términos × 20 ≈ $0.10) |
| Transcripción (Whisper local) | **Gratis** (corre en tu PC) |
| Adaptar copy | Gratis si lo haces a mano / en tu IA |

La app te muestra tu saldo de Apify y el costo estimado **antes** de buscar, y te
**avisa** si vas a repetir un término que ya scrapeaste hace poco.

---

## ⚠️ Límites honestos (importante)

- **No se puede ver el nº de impresiones/gasto** de anuncios comerciales: Meta solo
  publica eso para anuncios de política/temas sociales. La app ordena por el
  **orden de Meta** (≈ impresiones), no por un número exacto.
- **Los enlaces de video/imagen de Facebook caducan** a las pocas horas. En
  resultados viejos puede que el video no cargue (sale un placeholder); el texto,
  fecha y destino siempre quedan. Lo que ya reproduzcas/transcribas se guarda local.
- **Apify cobra por lo que trae**, aunque ya lo tuvieras: por eso la app avisa antes
  de re-scrapear, pero no puede "evitar" el cobro de un re-scrapeo.

---

## 🔒 Seguridad y privacidad

- El archivo **`.env` contiene tu token de Apify — NUNCA lo subas a GitHub.**
  Ya está en `.gitignore`. Si alguna vez lo subiste por error, **rota el token** en Apify.
- Tus búsquedas, seleccionados y transcripciones se guardan **solo en tu PC**
  (`data/` y `downloads/`, también ignorados por git).

## ⚖️ Uso responsable

Herramienta para **investigación e inspiración**. La Facebook Ad Library es pública,
pero respeta los Términos de Servicio de Meta/Apify y **no copies anuncios tal cual**:
úsalos para entender qué funciona y crear lo tuyo, mejor.

---

## 👤 Autor

Creado por **[tu nombre]** para su comunidad y alumnos de IA.
- 🎥 YouTube: [tu canal]
- 👥 Comunidad: [tu comunidad]

*Construido con [Claude Code](https://claude.com/claude-code). Ver `CLAUDE.md` para
la arquitectura y las lecciones técnicas del proyecto.*
