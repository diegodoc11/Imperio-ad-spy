// ===== Ad-Spy front-end =====
let ADS = [];                 // resultados de búsqueda
let SHORTLIST = [];           // seleccionados del nicho actual
let SAVED_IDS = new Set();    // ids guardados del nicho actual
let COUNT = 50;
let COST_PER_RESULT = 0.00075;
let NICHE = localStorage.getItem('adspy_niche') || '';
let SORT = 'meta';
let RENDER_LIMIT = 60; // cuántas tarjetas mostrar de golpe (paginado)
let ADV_FILTER = null;  // filtrar por anunciante (desde la pestaña Creadores)
let CREADORES = [];     // ranking de creadores del nicho actual

const BUCKETS = [
  { k: 'siempre', l: 'Desde siempre (+2 años)' },
  { k: '1-2a', l: '1–2 años' },
  { k: '9-12m', l: '9–12 meses' },
  { k: '6-9m', l: '6–9 meses' },
  { k: '3-6m', l: '3–6 meses' },
  { k: '2-3m', l: '2–3 meses' },
  { k: '1-2m', l: '1–2 meses' },
  { k: '0-1m', l: 'Último mes' },
];
const SELECTED_BUCKETS = new Set(); // vacío = mostrar TODOS los rangos

function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function destIcon(t) { return ({ whatsapp: '💬', instagram: '📷', messenger: '✉️', facebook: '👍', app: '📱', web: '🌐' })[t] || '➡️'; }
function fmtDate(s) {
  if (!s) return '—';
  s = String(s);
  const meses = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  if (/^\d{9,13}$/.test(s)) {            // timestamp Unix (seg o ms)
    let ts = parseInt(s, 10);
    if (s.length <= 10) ts *= 1000;
    const dt = new Date(ts);
    return `${dt.getDate()} ${meses[dt.getMonth()]} ${dt.getFullYear()}`;
  }
  const p = s.slice(0, 10).split('-');
  if (p.length !== 3) return s;
  const y = p[0], mo = +p[1] - 1, d = +p[2];
  if (isNaN(d) || mo < 0 || mo > 11) return s;
  return `${d} ${meses[mo]} ${y}`;
}
function setStatus(html) { document.getElementById('status').innerHTML = html; }
function findAd(id) {
  return ADS.find(a => String(a.library_id) === String(id)) ||
         SHORTLIST.find(a => String(a.library_id) === String(id));
}

// ---------- init ----------
init();
async function init() {
  try { await loadHealth(); } catch (e) { console.error('health', e); }
  try { await loadNiches(); } catch (e) { console.error('niches', e); }
  loadApifyPill();
  try { await loadResults(); } catch (e) { console.error('results', e); }
  try { await loadShortlist(); } catch (e) { console.error('shortlist', e); }
  setCount(50);
  renderFilters();
}

async function loadHealth() {
  try {
    const d = await (await fetch('/api/health')).json();
    COST_PER_RESULT = d.cost_per_result || COST_PER_RESULT;
    document.getElementById('health').innerHTML = `🎙️ ${esc(d.whisper_model)}`;
  } catch (e) { document.getElementById('health').textContent = 'servidor?'; }
}

async function loadApifyPill() {
  const el = document.getElementById('apifyPill');
  try {
    const d = await (await fetch('/api/apify-usage')).json();
    if (!d.ok) throw 0;
    el.className = 'apify-pill ' + (d.percent >= 90 ? 'danger' : (d.percent >= 70 ? 'warn' : ''));
    el.innerHTML = `Apify <b>$${d.used}</b> / $${d.limit} · ${d.percent}%` + (d.days_left != null ? ` · ${d.days_left}d` : '');
    el.title = d.reset ? `Se renueva el ${d.reset}` : '';
  } catch (e) { el.textContent = 'Apify —'; }
}

// ---------- nichos ----------
async function loadNiches() {
  const d = await (await fetch('/api/niches')).json();
  const niches = d.niches || [];
  if (!NICHE || !niches.includes(NICHE)) NICHE = niches[0] || 'General';
  const sel = document.getElementById('niche');
  sel.innerHTML = niches.map(n => `<option ${n === NICHE ? 'selected' : ''}>${esc(n)}</option>`).join('');
  localStorage.setItem('adspy_niche', NICHE);
  document.getElementById('selNiche').textContent = NICHE;
}
async function onNicheChange() {
  NICHE = document.getElementById('niche').value;
  localStorage.setItem('adspy_niche', NICHE);
  document.getElementById('selNiche').textContent = NICHE;
  await loadShortlist();
  await loadResults();
}
async function nuevoNicho() {
  const name = (prompt('Nombre del nuevo nicho:') || '').trim();
  if (!name) return;
  await fetch('/api/niches', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
  NICHE = name;
  localStorage.setItem('adspy_niche', NICHE);
  await loadNiches();
  await loadShortlist();
}

// ---------- seleccionados (shortlist) ----------
async function loadShortlist() {
  try {
    const d = await (await fetch(`/api/shortlist?niche=${encodeURIComponent(NICHE)}`)).json();
    SHORTLIST = d.ads || [];
  } catch (e) { SHORTLIST = []; }
  SAVED_IDS = new Set(SHORTLIST.map(a => String(a.library_id)));
  document.getElementById('selCount').textContent = SHORTLIST.length;
  renderSel();
}

// resultados scrapeados guardados (no se pierden al refrescar)
async function loadResults() {
  try {
    const d = await (await fetch(`/api/results?niche=${encodeURIComponent(NICHE)}`)).json();
    ADS = d.ads || [];
    if (d.query) document.getElementById('q').value = d.query;
  } catch (e) { ADS = []; }
  RENDER_LIMIT = 60; ADV_FILTER = null;
  renderFilters(); render();
  if (ADS.length) setStatus(`📦 ${ADS.length} anuncios scrapeados (guardados) en “${esc(NICHE)}”. Filtra/ordena ⤴`);
}
async function vaciarResultados() {
  if (!confirm(`¿Vaciar los resultados scrapeados de “${NICHE}”?\n(No borra tus ⭐ Seleccionados ni las transcripciones)`)) return;
  await fetch('/api/results/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ niche: NICHE }) });
  ADS = []; renderFilters(); render(); setStatus('Resultados vaciados.');
}
async function toggleGuardar(id) {
  const ad = ADS.find(a => String(a.library_id) === String(id));
  if (!ad) return;
  if (SAVED_IDS.has(String(id))) {
    await fetch('/api/shortlist/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ niche: NICHE, library_id: id }) });
  } else {
    await fetch('/api/shortlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ niche: NICHE, ad }) });
  }
  await loadShortlist();
  render();
}
async function quitarSel(id) {
  await fetch('/api/shortlist/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ niche: NICHE, library_id: id }) });
  await loadShortlist();
  render();
}

// ---------- cantidad + costo ----------
function termCount() {
  return Math.max(1, document.getElementById('q').value.split(',').map(s => s.trim()).filter(Boolean).length);
}
function updateCost() {
  const t = termCount();
  const c = COUNT * COST_PER_RESULT * t;
  document.getElementById('costEst').textContent =
    `Costo estimado ~$${c.toFixed(c < 0.1 ? 3 : 2)}` + (t > 1 ? ` · ${t} términos` : '');
}
function setCount(n) {
  COUNT = n;
  document.querySelectorAll('.cnt').forEach(b => b.classList.toggle('active', +b.dataset.n === n));
  updateCost();
}

// ---------- vistas / pestañas ----------
function showView(v) {
  ['buscar', 'seleccionados', 'creadores'].forEach(name => {
    const el = document.getElementById('view-' + name);
    if (el) el.style.display = (name === v) ? '' : 'none';
  });
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === v));
  if (v === 'seleccionados') renderSel();
  if (v === 'creadores') renderCreadores();
}

// ---------- pestaña Creadores (quién escala) ----------
function renderCreadores() {
  const cont = document.getElementById('creadoresList');
  if (!cont) return;
  const map = {};
  ADS.forEach(a => {
    const k = a.advertiser || '(sin nombre)';
    if (!map[k]) map[k] = { name: k, count: 0, videos: 0, maxDays: -1, durLabel: '?', dests: {} };
    const m = map[k];
    m.count++;
    if (a.has_video) m.videos++;
    if ((a.days_active ?? -1) > m.maxDays) { m.maxDays = a.days_active ?? -1; m.durLabel = a.duration_label || '?'; }
    if (a.dest_type && a.dest_type !== 'ninguno') m.dests[a.dest_type] = (m.dests[a.dest_type] || 0) + 1;
  });
  CREADORES = Object.values(map).sort((x, y) => (y.count - x.count) || (y.maxDays - x.maxDays));
  document.getElementById('creadoresInfo').textContent = `${CREADORES.length} creadores · ${ADS.length} anuncios en "${NICHE}"`;
  if (!ADS.length) { cont.innerHTML = '<div class="status">No hay anuncios en este nicho todavía. Haz una búsqueda primero.</div>'; return; }
  cont.innerHTML = CREADORES.map((m, i) => {
    const dests = Object.keys(m.dests).map(d => destIcon(d)).join(' ');
    return `<div class="crow" onclick="verCreador(${i})">
      <span class="cnum">#${i + 1}</span>
      <span class="cname">${esc(m.name)}</span>
      <span class="cbig">${m.count}</span><span class="ctag">anuncios</span>
      <span class="ctag">🎥 ${m.videos}</span>
      <span class="ctag">⏱️ máx ${esc(m.durLabel)}</span>
      <span class="ctag">${dests}</span>
      <span class="cgo">ver →</span>
    </div>`;
  }).join('');
}
function verCreador(i) {
  const m = CREADORES[i]; if (!m) return;
  ADV_FILTER = m.name; RENDER_LIMIT = 60;
  showView('buscar'); render();
}
function quitarCreador() { ADV_FILTER = null; RENDER_LIMIT = 60; render(); }

// ---------- filtros por tiempo activo ----------
function bucketCounts() { const c = {}; ADS.forEach(a => { c[a.bucket] = (c[a.bucket] || 0) + 1; }); return c; }
function renderFilters() {
  const counts = bucketCounts();
  const none = SELECTED_BUCKETS.size === 0;
  let html = '<span class="flabel">⏱️ Tiempo activo:</span>';
  html += `<button class="chip${none ? ' active' : ' alt'}" onclick="clearBuckets()">Todos</button>`;
  BUCKETS.forEach(b => {
    const n = counts[b.k] || 0;
    html += `<button class="chip${SELECTED_BUCKETS.has(b.k) ? ' active' : ''}" onclick="toggleBucket('${b.k}')">${b.l}${ADS.length ? ` <b>${n}</b>` : ''}</button>`;
  });
  document.getElementById('filters').innerHTML = html;
}
function toggleBucket(k) { SELECTED_BUCKETS.has(k) ? SELECTED_BUCKETS.delete(k) : SELECTED_BUCKETS.add(k); RENDER_LIMIT = 60; renderFilters(); render(); }
function clearBuckets() { SELECTED_BUCKETS.clear(); RENDER_LIMIT = 60; renderFilters(); render(); }
function visibleAds() {
  let list = SELECTED_BUCKETS.size ? ADS.filter(a => SELECTED_BUCKETS.has(a.bucket)) : ADS;
  if (ADV_FILTER) list = list.filter(a => (a.advertiser || '(sin nombre)') === ADV_FILTER);
  return list;
}
function applySort(list) {
  const a = [...list];
  if (SORT === 'meta') a.sort((x, y) => (x.meta_rank ?? 1e9) - (y.meta_rank ?? 1e9));
  else if (SORT === 'oldest') a.sort((x, y) => (y.days_active ?? -1) - (x.days_active ?? -1));
  else if (SORT === 'newest') a.sort((x, y) => (x.days_active ?? 1e9) - (y.days_active ?? 1e9));
  else if (SORT === 'advertiser') a.sort((x, y) => String(x.advertiser || '').localeCompare(String(y.advertiser || '')));
  else if (SORT === 'video') a.sort((x, y) => (y.has_video ? 1 : 0) - (x.has_video ? 1 : 0));
  return a;
}
function setSort(v) { SORT = v; render(); renderSel(); }

// ---------- búsqueda ----------
async function buscar() {
  const q = document.getElementById('q').value.trim();
  if (!q) { setStatus('Escribe una palabra primero.'); return; }
  // Aviso de cooldown: evita re-scrapear (y re-pagar) lo reciente sin querer
  try {
    const cd = await (await fetch(`/api/cooldown?niche=${encodeURIComponent(NICHE)}&q=${encodeURIComponent(q)}`)).json();
    const rec = (cd.terms || []).filter(t => t.recent);
    if (rec.length) {
      const lista = rec.map(t => `• ${t.term} (hace ${t.days_ago} día${t.days_ago === 1 ? '' : 's'})`).join('\n');
      if (!confirm(`⚠️ Ya scrapeaste estos términos hace menos de ${cd.cooldown_days} días (volverías a pagar Apify):\n\n${lista}\n\n¿Buscar de todas formas?\n(Aceptar = busca y cobra todo · Cancelar = no busca)`)) {
        setStatus('Búsqueda cancelada para no gastar de nuevo. 👍');
        return;
      }
    }
  } catch (e) { /* si el chequeo falla, seguimos normal */ }
  const country = document.getElementById('country').value.trim() || 'ALL';
  const active = document.getElementById('active').checked;
  const btn = document.getElementById('btnBuscar');
  btn.disabled = true; btn.textContent = '⏳ Buscando…';
  const _nt = termCount();
  setStatus(`<span class="spin"></span> Buscando ${_nt > 1 ? `<b>${_nt}</b> términos` : `“${esc(q)}”`} en la Ad Library… ${_nt > 1 ? '(varios términos → puede tardar varios minutos)' : '(puede tardar 1–2 min)'}`);
  document.getElementById('grid').innerHTML = '';
  document.getElementById('visinfo').textContent = '';
  try {
    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&count=${COUNT}&country=${encodeURIComponent(country)}&active=${active}&niche=${encodeURIComponent(NICHE)}`);
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'error');
    ADS = d.ads || [];
    RENDER_LIMIT = 60; ADV_FILTER = null;
    renderFilters(); render();
    const cv = ADS.filter(a => a.has_video).length;
    let tb = '';
    if (d.terms) tb = '<br><span class="tag">por término → ' + Object.entries(d.terms).map(([k, v]) => `${esc(k)}: ${v}`).join(' · ') + '</span>';
    setStatus(`<b>${d.new_count ?? ADS.length}</b> nuevos · <b>${ADS.length}</b> en “${esc(NICHE)}” (${cv} con video). Filtra/ordena ⤴ y guarda con ☆${tb}`);
    loadApifyPill(); // refresca el saldo tras gastar
  } catch (e) {
    setStatus(`❌ Error en la búsqueda: ${esc(e.message)}. Revisa tu <code>APIFY_TOKEN</code> en <code>.env</code>.`);
  } finally {
    btn.disabled = false; btn.textContent = '🔎 Buscar';
  }
}

function render() {
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  const vis = applySort(visibleAds());
  vis.slice(0, RENDER_LIMIT).forEach(ad => { try { grid.appendChild(card(ad, 'b')); } catch (e) { console.error('card', e); } });
  let info = ADS.length ? `Mostrando ${Math.min(RENDER_LIMIT, vis.length)} de ${vis.length} (pool: ${ADS.length})` : '';
  if (ADV_FILTER) info += ` · 🏅 Creador: <b>${esc(ADV_FILTER)}</b> <a href="#" onclick="quitarCreador();return false;">✕ quitar</a>`;
  document.getElementById('visinfo').innerHTML = info;
  if (vis.length > RENDER_LIMIT) {
    const more = document.createElement('button');
    more.className = 'green';
    more.style.cssText = 'grid-column:1/-1; margin-top:8px';
    more.textContent = `▼ Ver más (${vis.length - RENDER_LIMIT} restantes)`;
    more.onclick = () => { RENDER_LIMIT += 60; render(); };
    grid.appendChild(more);
  }
}

function renderSel() {
  const g = document.getElementById('selGrid');
  if (!g) return;
  g.innerHTML = '';
  const st = document.getElementById('selStatus');
  if (!SHORTLIST.length) { st.innerHTML = `No hay seleccionados en <b>${esc(NICHE)}</b>. Guarda anuncios con ☆ desde Buscar.`; return; }
  st.textContent = '';
  applySort(SHORTLIST).forEach(ad => { try { g.appendChild(card(ad, 's')); } catch (e) { console.error('card sel', e); } });
}

// ---------- tarjeta (p = 'b' buscar | 's' seleccionados) ----------
function card(ad, p) {
  const id = ad.library_id;
  const el = document.createElement('div');
  el.className = 'card';
  el.id = `${p}card-${id}`;
  const vidBadge = ad.has_video ? '<span class="badge vid">🎥 video</span>' : '<span class="badge">imagen</span>';
  const dur = (ad.duration_label && ad.duration_label !== '?')
    ? `<span class="dur" title="desde ${esc(ad.start_date || '')}">⏱️ ${esc(ad.duration_label)}</span>` : '';
  const longcopy = (ad.copy || '').length > 180;
  const saved = SAVED_IDS.has(String(id));
  const saveBtn = (p === 'b')
    ? `<button class="${saved ? 'green' : 'ghost'}" onclick="toggleGuardar('${id}')">${saved ? '★ Guardado' : '☆ Guardar'}</button>`
    : `<button class="ghost del" onclick="quitarSel('${id}')">🗑 Quitar</button>`;
  const thumb = ad.thumbnail_url ? `/api/thumb?url=${encodeURIComponent(ad.thumbnail_url)}` : '';
  const media =
    `<div class="ph">${ad.has_video ? '🎥' : '📄'}</div>` +
    (thumb ? `<img loading="lazy"${ad.has_video ? ' class="vthumb"' : ''} src="${thumb}" alt="" onerror="this.style.display='none'">` : '') +
    (ad.has_video ? `<div class="play" onclick="verVideo('${p}','${id}')">▶</div>` : '');
  const dest = ad.dest_label
    ? `<div class="dest dest-${ad.dest_type}">${destIcon(ad.dest_type)} ${esc(ad.cta_text || ad.dest_label)}${(ad.dest_type === 'web' && ad.dest_domain) ? ` · ${esc(ad.dest_domain)}` : ''}</div>`
    : '';
  el.innerHTML = `
    <div class="head">
      <span class="name">${esc(ad.advertiser || 'Anunciante')}</span>
      ${dur}
    </div>
    <div class="sub">📅 Publicado el ${fmtDate(ad.start_date)}</div>
    <div class="media" id="${p}m-${id}">${media}</div>
    ${dest}
    <div class="copy" id="${p}c-${id}">${esc(ad.copy || '(sin texto)')}${longcopy ? ` <span class="more" onclick="document.getElementById('${p}c-${id}').classList.toggle('expanded')">…ver más</span>` : ''}</div>
    <div class="actions">
      ${vidBadge}
      ${ad.has_video ? `<button class="ghost" onclick="verVideo('${p}','${id}')">▶ Ver</button>` : ''}
      ${ad.has_video ? `<button class="green" id="${p}btx-${id}" onclick="transcribirUno('${p}','${id}')">📝 Transcribir</button>` : ''}
      ${saveBtn}
      ${ad.ad_url ? `<a href="${esc(ad.ad_url)}" target="_blank">FB ↗</a>` : ''}
    </div>
    <div class="transcript" id="${p}tx-${id}" style="display:none"></div>`;
  return el;
}

function verVideo(p, id) {
  const ad = findAd(id); if (!ad) return;
  document.getElementById(`${p}m-${id}`).innerHTML =
    `<video controls autoplay src="/api/video?id=${encodeURIComponent(id)}&url=${encodeURIComponent(ad.video_url)}"></video>`;
}

async function transcribirUno(p, id) {
  const ad = findAd(id); if (!ad) return;
  const box = document.getElementById(`${p}tx-${id}`);
  const btn = document.getElementById(`${p}btx-${id}`);
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Transcribiendo…'; }
  box.style.display = 'block';
  box.innerHTML = '<span class="spin"></span> Descargando y transcribiendo (local)…';
  try {
    const d = await (await fetch('/api/transcribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ library_id: id, video_url: ad.video_url }) })).json();
    if (!d.ok) throw new Error(d.error || 'error');
    box.innerHTML = `
      <h4>📝 Transcripción · ${esc(d.language || '')} · ${d.duration || '?'}s</h4>
      <pre id="${p}pre-${id}">${esc(d.text || '(vacío)')}</pre>
      <div class="row">
        <button class="ghost" onclick="copiar('${p}pre-${id}')">📋 Copiar</button>
        <a class="ghost dl" href="/downloads/${esc(d.library_id)}.txt" target="_blank">⬇ .txt</a>
        <a class="ghost dl" href="/downloads/${esc(d.library_id)}.srt" target="_blank">⬇ .srt</a>
      </div>`;
  } catch (e) {
    box.innerHTML = `❌ Error: ${esc(e.message)}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '📝 Re-transcribir'; }
  }
}

async function transcribirTodosSel() {
  const ids = SHORTLIST.filter(a => a.has_video).map(a => a.library_id);
  const st = document.getElementById('selStatus');
  if (!ids.length) { st.textContent = 'No hay videos para transcribir en este nicho.'; return; }
  for (let k = 0; k < ids.length; k++) {
    st.innerHTML = `<span class="spin"></span> Transcribiendo ${k + 1} de ${ids.length}…`;
    await transcribirUno('s', ids[k]);
  }
  st.innerHTML = `✅ ${ids.length} transcripciones listas. Cópialas y pásamelas para adaptar el copy.`;
}

function copiar(id) { navigator.clipboard.writeText(document.getElementById(id).textContent); }
function openHelp() { document.getElementById('help').classList.add('show'); }
function closeHelp() { document.getElementById('help').classList.remove('show'); }
