/**
 * NoAIVerdad · frontend v6
 * Vistas: Conexiones (la red de pagadores, anunciantes, mensajes repetidos, términos; ruta #/resumen), Mapa (provincias + panel de prensa y redes),
 * Comparar y Método. Cada vista tiene su propia URL (hash).
 *
 * Principios: nunca mostrar contenido sin fuente; distinguir "sin datos" de "error" de "filtrado";
 * mostrar rangos como rangos y estimaciones como estimaciones.
 */
"use strict";

// ---------------------------------------------------------------------------
// Configuración y estado
// ---------------------------------------------------------------------------
const obtenerBackendUrl = () => {
  const hostname = window.location.hostname;
  // Puerto 3600: copia de desarrollo que corre junto a otra versión (su servidor de datos está en el 8600); el resto usa 3000 → 8000.
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "") return `http://localhost:${window.location.port === "3600" ? 8600 : 8000}`;
  // Abierta desde otro dispositivo de la red local («INICIAR NoAIVerdad (red local).bat»: la página sale del puerto 3000 de un equipo): los datos
  // están en ese mismo equipo, en el puerto 8000. Un dominio publicado (puerto 80 o 443) no entra aquí.
  if (window.location.port === "3000") return `${window.location.protocol}//${hostname}:8000`;
  if (window.VITE_API_URL) return window.VITE_API_URL;
  if (window.API_URL) return window.API_URL;
  return "https://noaiverdad-production.up.railway.app";
};

const SECCIONES = {
  meta_ads: "Anuncios políticos de Meta",
  noticias: "Noticias de prensa",
  prensa_local: "Prensa local",
  verificaciones: "Verificaciones",
  bluesky: "Publicaciones en Bluesky",
  youtube: "Videos de YouTube",
  reddit: "Conversaciones en Reddit",
  tweets: "Publicaciones en X"
};
// sección -> campo de la respuesta de /api/noticias
const CAMPO_SECCION = { noticias: "tiempo_real", prensa_local: "prensa_local", verificaciones: "verificaciones", tweets: "tweets_recientes", bluesky: "bluesky_posts", youtube: "youtube_videos", reddit: "reddit_posts", meta_ads: "meta_ads" };
const PERIODOS = { todo: "Todo el período", "7": "Últimos 7 días", "30": "Últimos 30 días", "90": "Últimos 90 días", "365": "Último año" };
const TABS = ["red", "mensajes", "entidades", "termino", "info"];       // «anunciantes» ya no es una pestaña: es la ventana flotante «Resumen» (rs-flot)
const CACHE_FEED_MS = 10 * 60 * 1000;

const provinciasEcuador = [
  { id: "azuay", nombre: "Azuay", lat: -2.9001, lng: -79.0059 },
  { id: "bolivar", nombre: "Bolívar", lat: -1.5925, lng: -79.0030 },
  { id: "canar", nombre: "Cañar", lat: -2.7397, lng: -78.8486 },
  { id: "carchi", nombre: "Carchi", lat: 0.8115, lng: -77.7171 },
  { id: "chimborazo", nombre: "Chimborazo", lat: -1.6636, lng: -78.6546 },
  { id: "cotopaxi", nombre: "Cotopaxi", lat: -0.9328, lng: -78.6155 },
  { id: "el_oro", nombre: "El Oro", lat: -3.2581, lng: -79.9554 },
  { id: "esmeraldas", nombre: "Esmeraldas", lat: 0.9592, lng: -79.6536 },
  { id: "galapagos", nombre: "Galápagos", lat: -0.9010, lng: -89.6013 },
  { id: "guayas", nombre: "Guayas", lat: -2.1894, lng: -79.8891 },
  { id: "imbabura", nombre: "Imbabura", lat: 0.3392, lng: -78.1222 },
  { id: "loja", nombre: "Loja", lat: -3.9931, lng: -79.2042 },
  { id: "los_rios", nombre: "Los Ríos", lat: -1.8022, lng: -79.5344 },
  { id: "manabi", nombre: "Manabí", lat: -1.0546, lng: -80.4544 },
  { id: "morona_santiago", nombre: "Morona Santiago", lat: -2.3023, lng: -78.1182 },
  { id: "napo", nombre: "Napo", lat: -0.9938, lng: -77.8129 },
  { id: "orellana", nombre: "Orellana", lat: -0.4665, lng: -76.9872 },
  { id: "pastaza", nombre: "Pastaza", lat: -1.4837, lng: -78.0026 },
  { id: "pichincha", nombre: "Pichincha", lat: -0.2298, lng: -78.5250 },
  { id: "santa_elena", nombre: "Santa Elena", lat: -2.2270, lng: -80.8594 },
  { id: "santo_domingo", nombre: "Santo Domingo de los Tsáchilas", lat: -0.2530, lng: -79.1754 },
  { id: "sucumbios", nombre: "Sucumbíos", lat: 0.0847, lng: -76.8828 },
  { id: "tungurahua", nombre: "Tungurahua", lat: -1.2417, lng: -78.6195 },
  { id: "zamora_chinchipe", nombre: "Zamora Chinchipe", lat: -4.0692, lng: -78.9567 }
];
const provinciaPorId = (id) => provinciasEcuador.find((p) => p.id === id) || null;

const state = {
  sinCne: (() => { try { return localStorage.getItem("noai_sin_cne") === "1"; } catch (e) { return false; } })(),
  soloActivos: (() => { try { return localStorage.getItem("noai_solo_activos") === "1"; } catch (e) { return false; } })(),
  fechas: { desde: null, hasta: null },      // rango de fechas global ("AAAA-MM-DD"); null = todo el período. No se guarda: al recargar vuelve a todo
  backendUrl: obtenerBackendUrl(),
  vista: "mapa",
  // vista Provincias
  map: null,
  burbujas: {},
  provincia: null,
  seccion: "noticias",
  periodo: "todo",
  sinListaCompleta: false,  // true si este servidor no tiene /api/ads/anuncios: el chip «Anuncios» usa entonces la lista corta de siempre
  mapaDatos: null,          // { provincias:[...], fuera_de_ecuador_impresiones, estado }
  mapaPendiente: null,      // selección y encuadre guardados del Mapa, si la página se recargó en otra pestaña: se aplican al abrirlo (ver navegar)
  feedCache: {},
  datos: null,              // { provincia, seccion, data }
  seq: 0,
  abort: null,
  // vista Conexiones (antes «Resumen»: la ruta #/resumen y los nombres internos conservan ese nombre)
  resumen: { alcance: "todas", tab: "red", seq: 0, top: null, tipo: "", soloBase: false, stats: null, orden: { clave: "gasto", dir: "desc" }, buscar: "", visibles: 15, abiertos: new Set(), mensajes: null, alcanceMetric: "impresiones", tendenciasCargadas: false },
  // vista Comparar
  comparar: { alcances: ["pichincha", "guayas"], seq: 0 },
  tiles: null,
  hashAplicado: null
};

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);

function escaparHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function normalizar(texto) {
  return String(texto || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
}

/** Solo enlaces http(s); cualquier otra cosa (p. ej. javascript:) se descarta. */
function urlSegura(url) {
  const u = String(url || "");
  return /^https?:\/\//i.test(u) ? u : "";
}

function enlace(url, texto, clase = "link-ext") {
  const seguro = urlSegura(url);
  if (!seguro) return "";
  return `<a href="${escaparHtml(seguro)}" target="_blank" rel="noopener noreferrer" class="${clase}">${escaparHtml(texto)}</a>`;
}

const fmtNum = (n) => Number(n || 0).toLocaleString("es-EC");
const fmtCompacto = (n) => new Intl.NumberFormat("es-EC", { notation: "compact", maximumFractionDigits: 1 }).format(Number(n || 0));
const fmtUsd = (n) => `USD ${fmtNum(n)}`;

function fechaComoDate(valor) {
  if (!valor) return null;
  const soloFecha = String(valor).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const d = soloFecha ? new Date(+soloFecha[1], +soloFecha[2] - 1, +soloFecha[3]) : new Date(valor);
  return isNaN(d.getTime()) ? null : d;
}

function formatearFechaSafe(valor) {
  if (!valor) return "";
  const d = fechaComoDate(valor);
  return d ? d.toLocaleDateString("es-EC", { day: "numeric", month: "short", year: "numeric" }) : String(valor);
}

function fmtFechaHora(iso) {
  const d = fechaComoDate(iso);
  return d ? d.toLocaleString("es-EC", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
}

/** Rango {min, max} de Meta (que publica rangos, no cifras exactas). */
function formatearRango(rango, moneda) {
  if (!rango || (rango.min == null && rango.max == null)) return "No disponible";
  const pref = moneda ? `${moneda} ` : "";
  if (rango.max == null) return `${pref}más de ${fmtNum(rango.min)}`;
  if (rango.min == null) return `${pref}hasta ${fmtNum(rango.max)}`;
  return `${pref}${fmtNum(rango.min)} – ${fmtNum(rango.max)}`;
}

async function fetchJSON(url, { timeout = 30000, signal, headers } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  if (signal) signal.addEventListener("abort", () => ctrl.abort());
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    if (e.name === "AbortError") throw new Error(signal && signal.aborted ? "cancelado" : "tiempo de espera agotado");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Pide una ruta de la API al primer origen que responda: el backend configurado, el propio origen de la página
 * (la app de escritorio de Electron incluye su propio /api/noticias) y localhost:8000.
 */
function origenesApi() {
  // la copia de desarrollo (puerto 3600) nunca cae al servidor de la otra versión (8000): si el suyo no responde, se ve el error
  // en el showcase publicado solo existe el propio dominio (el proxy de Netlify): nunca se prueba localhost desde el equipo del visitante
  const showcase = !!(window.NOAI_CONFIG && window.NOAI_CONFIG.showcase);
  const lista = showcase ? [window.location.origin]
    : [state.backendUrl, window.location.origin, window.NOAI_API_BASE_URL, window.location.port === "3600" ? null : "http://localhost:8000"];
  return lista.filter((o, i) => o && /^https?:\/\//.test(o) && lista.indexOf(o) === i).map((o) => o.replace(/\/$/, ""));
}

async function fetchApi(ruta, opciones = {}) {
  if (state.sinCne && /^\/api\/(ads|dashboard|noticias)/.test(ruta)) ruta += (ruta.includes("?") ? "&" : "?") + "sin_cne=true";
  if (state.soloActivos && /^\/api\/(ads|dashboard|noticias)/.test(ruta)) ruta += (ruta.includes("?") ? "&" : "?") + "solo_activos=true";
  if (state.fechas.desde && /^\/api\/(ads|dashboard|noticias)/.test(ruta)) ruta += (ruta.includes("?") ? "&" : "?") + `fecha_desde=${state.fechas.desde}&fecha_hasta=${state.fechas.hasta || state.fechas.desde}`;
  let ultimoError = new Error("sin origen disponible");
  for (const origen of origenesApi()) {
    try {
      return await fetchJSON(origen + ruta, opciones);
    } catch (e) {
      if (e.message === "cancelado") throw e;
      ultimoError = e;
    }
  }
  throw ultimoError;
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/** Etiqueta de afiliación política de una página o pagador. Verificada: con enlace a la fuente. Sin verificar: borde punteado. */
function badgeAfil(af, prefijo = "") {
  if (!af || !af.afiliacion) return "";
  const url = /^https?:\/\/\S+$/.test(af.fuente || "") ? af.fuente : "";
  const txt = af.afiliacion.length > 40 ? af.afiliacion.slice(0, 39) + "…" : af.afiliacion;
  const marca = af.verificado ? "" : "Sin verificar · ";
  const titulo = af.verificado ? `Afiliación: ${af.afiliacion}` : `Sin verificar (falta confirmar la fuente): ${af.afiliacion}`;
  const tag = `<span class="tag tag-afil${af.verificado ? "" : " pendiente"}" title="${escaparHtml(titulo)}">${escaparHtml(prefijo + marca + txt)}</span>`;
  return url ? `<a class="afil-link" href="${escaparHtml(url)}" target="_blank" rel="noopener noreferrer" aria-label="${escaparHtml(titulo)}. Abrir la fuente">${tag}</a>` : tag;
}
const filaAfil = (a) => {
  const b = badgeAfil(a.afiliacion) + badgeAfil(a.pagador_afiliacion, "Pagador: ");
  return b ? `<div class="afil-fila">${b}</div>` : "";
};

function esqueleto(filas = 3) {
  const anchos = ["w100", "w80", "w60"];
  return `<div class="skeleton-list" aria-hidden="true">${Array.from({ length: filas }, (_, i) => `<div class="skeleton ${anchos[i % 3]}"></div>`).join("")}</div>`;
}

const ICONOS_ESTADO = {
  info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>`,
  error: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M12 3 2.5 20h19L12 3z"/><path d="M12 10v4M12 17h.01"/></svg>`
};

function cajaEstado({ titulo, descripcion = "", tipo = "info", boton = null, filas = 3 }) {
  return `
    <div class="state state-${tipo}" role="${tipo === "error" ? "alert" : "status"}">
      ${tipo === "carga" ? `<div class="spinner" aria-hidden="true"></div>` : `<div class="state-icon">${ICONOS_ESTADO[tipo] || ICONOS_ESTADO.info}</div>`}
      <div class="state-title">${escaparHtml(titulo)}</div>
      ${descripcion ? `<p>${descripcion}</p>` : ""}
      ${tipo === "carga" ? esqueleto(filas) : ""}
      ${boton ? `<button type="button" class="btn" data-accion="${escaparHtml(boton.accion)}">${escaparHtml(boton.texto)}</button>` : ""}
    </div>`;
}

function errorEnCaja(el, mensaje, reintentar) {
  el.innerHTML = cajaEstado({ tipo: "error", titulo: "No se pudo cargar", descripcion: escaparHtml(mensaje), boton: { accion: "reintentar", texto: "Reintentar" } });
  el.querySelector("[data-accion='reintentar']")?.addEventListener("click", reintentar);
}

function sinMovimiento() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const listaDe = (v) => Array.isArray(v) ? v.filter(Boolean) : (v && typeof v === "object" ? Object.values(v).filter(Boolean) : []);

/** Copia guardada por el colector en Firebase (solo con sesión iniciada): se usa si la consulta en vivo no trae resultados. */
async function datosGuardadosFirebase(provincia, seccion) {
  const fb = window.NoAIFirebaseSync;
  if (!fb || !fb.consultarNoticiasFirebase) return null;
  try {
    const snap = await fb.consultarNoticiasFirebase(provincia);
    if (!snap) return null;
    const campo = CAMPO_SECCION[seccion];
    let items = listaDe(snap[campo]);
    if (!items.length && seccion === "bluesky") items = listaDe(snap.bluesky_posts_nacionales);
    if (!items.length) return null;
    const cuando = snap.actualizado_en ? fmtFechaHora(snap.actualizado_en) : "fecha desconocida";
    return {
      provincia,
      [campo]: items,
      estados: { [seccion]: { configurado: true, ok: true, total: items.length, aviso: `Datos guardados por el colector (${cuando}). El servidor no devolvió resultados nuevos.` } },
      _guardado: true
    };
  } catch (e) {
    return null;
  }
}

function etiquetaAlcance(id) {
  if (!id || id === "todas") return "Nacional";
  const p = provinciaPorId(id);
  return p ? p.nombre : id;
}

function provinciaPorNombre(nombre) {
  const n = normalizar(nombre);
  return provinciasEcuador.find((p) => normalizar(p.nombre) === n) || null;
}

// ---------------------------------------------------------------------------
// Tema
// ---------------------------------------------------------------------------
function initSinCne() {
  const btn = $("btn-sin-cne");
  if (!btn) return;
  const pinta = () => btn.setAttribute("aria-checked", String(state.sinCne));
  pinta();
  btn.addEventListener("click", () => {
    state.sinCne = !state.sinCne;
    try { localStorage.setItem("noai_sin_cne", state.sinCne ? "1" : "0"); } catch (e) { /* sin almacenamiento */ }
    pinta();
    refrescarPorFiltroCne();
  });
}

/** «Solo activos»: igual que el del CNE, afecta a toda la web (el servidor filtra todas las respuestas con anuncios). */
function initSoloActivos() {
  const btn = $("btn-solo-activos");
  if (!btn) return;
  const pinta = () => btn.setAttribute("aria-checked", String(state.soloActivos));
  pinta();
  btn.addEventListener("click", () => {
    state.soloActivos = !state.soloActivos;
    try { localStorage.setItem("noai_solo_activos", state.soloActivos ? "1" : "0"); } catch (e) { /* sin almacenamiento */ }
    pinta();
    refrescarPorFiltroCne();
  });
}

// ---------------------------------------------------------------------------
// Calendario de la barra superior: un día o un rango «desde – hasta» para toda la web. El servidor deja los anuncios que circularon esos días.
// Es un calendario propio (no el del navegador), para que se vea igual en todos los equipos.
// ---------------------------------------------------------------------------
const MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const isoDeFecha = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fechaDeIso = (iso) => { const [a, m, d] = iso.split("-").map(Number); return new Date(a, m - 1, d); };
const diaCorto = (iso, conAnio = true) => { const d = fechaDeIso(iso); return `${d.getDate()} ${MESES_CORTOS[d.getMonth()]}${conAnio ? " " + d.getFullYear() : ""}`; };
/** «3 nov 2026» (un día) o «12 oct – 5 nov 2026» (rango; el año del primero solo si es distinto). */
const textoRango = (desde, hasta) => (!desde ? "" : desde === hasta || !hasta ? diaCorto(desde) : `${diaCorto(desde, desde.slice(0, 4) !== hasta.slice(0, 4))} – ${diaCorto(hasta)}`);

function initFechas() {
  const btn = $("btn-fechas");
  if (!btn) return;
  const panel = document.createElement("div");
  panel.id = "fechas-panel"; panel.className = "fechas-panel"; panel.hidden = true;
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Elegir fechas");
  document.body.appendChild(panel);
  const hoy = () => isoDeFecha(new Date());
  // Solo hay datos del período que descarga el servidor (120 días salvo que su estado diga otra cosa)
  const minimo = () => { const dias = Number(state.resumen.top && state.resumen.top.estado && state.resumen.top.estado.dias) || 120; const d = new Date(); d.setDate(d.getDate() - dias); return isoDeFecha(d); };
  const cal = { mes: null, a: null, b: null };           // mes que se ve y selección en curso (a = b: un solo día)
  const pintaBoton = () => {
    const activo = !!state.fechas.desde;
    $("fechas-etiqueta").textContent = activo ? textoRango(state.fechas.desde, state.fechas.hasta) : "Fechas";
    btn.classList.toggle("activo", activo);
    btn.title = activo ? `Solo los anuncios que circularon ${state.fechas.desde === state.fechas.hasta ? "el" : "del"} ${textoRango(state.fechas.desde, state.fechas.hasta).replace(" – ", " al ")}. Pulsa para cambiar las fechas.`
      : "Elige un día o un rango de fechas: toda la web mostrará solo los anuncios que circularon entonces";
  };
  const pinta = () => {
    const min = minimo(), max = hoy(), y = cal.mes.getFullYear(), m = cal.mes.getMonth();
    const primero = new Date(y, m, 1), huecos = (primero.getDay() + 6) % 7, dias = new Date(y, m + 1, 0).getDate();      // la semana empieza en lunes
    const celdas = [];
    for (let i = 0; i < huecos; i++) celdas.push(`<span class="fp-hueco"></span>`);
    for (let d = 1; d <= dias; d++) {
      const iso = isoDeFecha(new Date(y, m, d)), fuera = iso < min || iso > max;
      const extremo = iso === cal.a || iso === cal.b, dentro = cal.a && cal.b && iso > cal.a && iso < cal.b;
      celdas.push(`<button type="button" class="fp-dia${extremo ? " sel" : ""}${dentro ? " en-rango" : ""}${iso === max ? " hoy" : ""}" data-dia="${iso}" ${fuera ? "disabled" : ""} aria-pressed="${extremo || !!dentro}" aria-label="${d} de ${MESES_LARGOS[m]} de ${y}">${d}</button>`);
    }
    const antes = isoDeFecha(new Date(y, m, 0)) >= min, despues = isoDeFecha(new Date(y, m + 1, 1)) <= max;
    const resumen = !cal.a ? "Elige un día. Para un rango, elige después el otro extremo."
      : cal.a === cal.b ? `Un día: <strong>${diaCorto(cal.a)}</strong>. Elige otro día para hacer un rango.`
        : `Del <strong>${diaCorto(cal.a, cal.a.slice(0, 4) !== cal.b.slice(0, 4))}</strong> al <strong>${diaCorto(cal.b)}</strong>.`;
    panel.innerHTML = `
      <div class="fp-cab">
        <button type="button" class="icon-btn" data-mes="-1" aria-label="Mes anterior" ${antes ? "" : "disabled"}>‹</button>
        <strong>${MESES_LARGOS[m]} de ${y}</strong>
        <button type="button" class="icon-btn" data-mes="1" aria-label="Mes siguiente" ${despues ? "" : "disabled"}>›</button>
      </div>
      <div class="fp-semana" aria-hidden="true"><span>lu</span><span>ma</span><span>mi</span><span>ju</span><span>vi</span><span>sá</span><span>do</span></div>
      <div class="fp-dias">${celdas.join("")}</div>
      <div class="fp-atajos"><button type="button" class="chip" data-atajo="0">Hoy</button><button type="button" class="chip" data-atajo="6">Últimos 7 días</button><button type="button" class="chip" data-atajo="29">Últimos 30 días</button></div>
      <p class="fp-resumen xsmall" aria-live="polite">${resumen}</p>
      <p class="xsmall muted">Quedan los anuncios que circularon en esas fechas (hay datos desde el ${diaCorto(min)}). Los montos son los de todo el anuncio, no solo los de esos días: Meta no los publica por día.</p>
      <div class="fp-pie">
        <button type="button" class="btn" data-fp="todo" ${state.fechas.desde || cal.a ? "" : "disabled"}>Todo el período</button>
        <button type="button" class="btn btn-primary" data-fp="aplicar" ${cal.a ? "" : "disabled"}>Aplicar</button>
      </div>`;
  };
  const coloca = () => {          // debajo del botón, sin salirse de la pantalla
    const r = btn.getBoundingClientRect(), ancho = panel.offsetWidth || 300;
    panel.style.top = `${Math.round(r.bottom + 6)}px`;
    panel.style.left = `${Math.round(Math.max(8, Math.min(r.left, window.innerWidth - ancho - 8)))}px`;
  };
  const cerrar = (devolverFoco) => { if (panel.hidden) return; panel.hidden = true; btn.setAttribute("aria-expanded", "false"); if (devolverFoco) btn.focus(); };
  const abrir = () => {
    cal.a = state.fechas.desde; cal.b = state.fechas.hasta;
    const base = fechaDeIso(cal.b || hoy()); cal.mes = new Date(base.getFullYear(), base.getMonth(), 1);
    pinta(); panel.hidden = false; btn.setAttribute("aria-expanded", "true"); coloca();
    const foco = panel.querySelector(".fp-dia.sel") || panel.querySelector(".fp-dia.hoy") || panel.querySelector(".fp-dia:not([disabled])"); if (foco) foco.focus();
  };
  const aplicar = (desde, hasta) => {
    if (state.fechas.desde === desde && state.fechas.hasta === hasta) { cerrar(true); return; }
    state.fechas = { desde, hasta };
    pintaBoton(); cerrar(true);
    refrescarPorFiltroCne();
  };
  btn.addEventListener("click", () => (panel.hidden ? abrir() : cerrar(false)));
  panel.addEventListener("click", (ev) => {
    const dia = ev.target.closest("[data-dia]"), mes = ev.target.closest("[data-mes]"), atajo = ev.target.closest("[data-atajo]"), fp = ev.target.closest("[data-fp]");
    if (dia) {
      const iso = dia.dataset.dia;
      if (!cal.a || cal.a !== cal.b || iso === cal.a) { cal.a = iso; cal.b = iso; }          // primer clic (o empezar de nuevo): un solo día
      else if (iso < cal.a) cal.a = iso; else cal.b = iso;                                    // segundo clic: el otro extremo del rango
      pinta(); (panel.querySelector(`[data-dia="${iso}"]`) || panel).focus();
    } else if (mes && !mes.disabled) {
      cal.mes = new Date(cal.mes.getFullYear(), cal.mes.getMonth() + Number(mes.dataset.mes), 1); pinta();
      (panel.querySelector(`[data-mes="${mes.dataset.mes}"]:not([disabled])`) || panel.querySelector(".fp-dia:not([disabled])") || panel).focus();
    } else if (atajo) {
      const d = new Date(); d.setDate(d.getDate() - Number(atajo.dataset.atajo));
      cal.b = hoy(); cal.a = isoDeFecha(d) < minimo() ? minimo() : isoDeFecha(d);
      const f = fechaDeIso(cal.b); cal.mes = new Date(f.getFullYear(), f.getMonth(), 1); pinta();
      (panel.querySelector("[data-fp=aplicar]") || panel).focus();
    } else if (fp && fp.dataset.fp === "aplicar" && cal.a) aplicar(cal.a, cal.b || cal.a);
    else if (fp && fp.dataset.fp === "todo") aplicar(null, null);
  });
  document.addEventListener("click", (ev) => { if (!panel.hidden && !panel.contains(ev.target) && !btn.contains(ev.target) && document.body.contains(ev.target)) cerrar(false); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !panel.hidden) { ev.stopPropagation(); cerrar(true); } }, true);
  window.addEventListener("resize", () => { if (!panel.hidden) coloca(); });
  pintaBoton();
}

/** Al cambiar el filtro del CNE, «solo activos» o las fechas se vuelven a pedir los datos de la vista abierta y se descarta lo guardado de las demás. */
function refrescarPorFiltroCne() {
  state.mapaDatos = null;
  state.resumen.top = null; state.resumen.red = null; state.resumen.mensajes = null; state.resumen.stats = null;
  state.resumen.tendenciasCargadas = false;
  cargarMapaDatos();
  if (state.vista === "resumen") cargarResumen(state.resumen.alcance);
  else if (state.vista === "comparar") cargarComparacion();
  else if (state.vista === "mapa" && state.provincia) cargarSeccion(state.provincia.nombre, state.seccion, { forzar: true });
}

// ---------------------------------------------------------------------------
// Tutorial para usuarios nuevos
// ---------------------------------------------------------------------------
const PASOS_TUTORIAL = [
  { titulo: "Bienvenido a NoAIVerdad (beta)", html: `
    <p>NoAIVerdad es una herramienta cívica para periodistas y verificadores. Muestra <strong>quién paga anuncios políticos en Meta en Ecuador</strong>, dónde llegan y qué páginas se parecen entre sí.</p>
    <p><strong>No dice qué es verdad.</strong> Da pistas para investigar: coincidencias, pagadores compartidos y mensajes repetidos. Cada pista debe verificarse con otras fuentes.</p>
    <p class="muted">Esta es una versión de prueba. Si algo no se entiende o falla, anótalo: tus comentarios ayudan a mejorarla.</p>` },
  // Los pasos que dependen de la vista de la red se arman al mostrarse, con sus colores (y el tema claro u oscuro).
  { titulo: "Conexiones: la red de pagadores", ir: ["resumen", "Abrir Conexiones"], get html() {
    const o = usarOrbital(), c = colorAristaVista;
    return `
    <p><strong>Conexiones</strong> ocupa toda la pantalla con una red. ${o
    ? "Cada esfera es una página; las esferas grandes con nombre son provincias («soles»): sus páginas giran a su alrededor. Cada rombo es un pagador y gira alrededor de la página que paga."
    : "Cada punto es una página o un pagador; los círculos grandes con nombre son provincias."}</p>
    <ul><li><span style="color:${c("alcance")}">──</span> une cada página con la provincia donde llega más${o ? " (la órbita también lo muestra)" : ""}.</li>
    <li><span style="color:${c("pagador")}">━━</span> el pagador declarado es distinto de la página.</li>
    <li><span style="color:${c("texto")}">╍╍</span> textos casi idénticos. <span style="color:${c("enlace")}">┅┅</span> el mismo enlace.</li>
    <li><span style="color:${c("partido")}">══</span> misma organización política (unida a la página del partido): línea sutil hasta que eliges un partido, filtras por «partido» o seleccionas un nodo.</li></ul>
    <p>El tamaño del punto es la inversión estimada.${o ? " Un halo agrupa páginas enlazadas: naranja si comparten pagador, gris si repiten un texto, azul si comparten un enlace. Pulsa una línea gris punteada para leer los mensajes repetidos entre esas dos páginas." : ""} Son <strong>pistas, no pruebas</strong>: las agencias y los partidos pagan por terceros legítimamente.</p>`;
  } },
  { titulo: "Moverte por la red", get html() {
    const o = usarOrbital();
    return `
    <ul><li><strong>Rueda del ratón</strong> o pellizco con dos dedos: acercar y alejar.</li>
    <li><strong>Arrastra el fondo</strong> para mover la vista. <strong>Arrastra un punto</strong> ${o
    ? "para estirarlo: ofrece resistencia y vuelve a su órbita al soltarlo. Si arrastras una <em>provincia</em>, se mueve todo su sistema (el botón «Reorganizar sistemas», en Filtros, lo devuelve a su sitio)."
    : "para reubicarlo."}</li>
    <li><strong>Clic en un punto:</strong> sus conexiones se resaltan y su detalle aparece en el panel derecho, con la lista de todos sus anuncios. En una <em>provincia</em> verás dos cuentas: los anuncios que llegan allí y los de las páginas con base allí, además de botones para ver su prensa o enfocar solo esa provincia.</li>
    <li>Botón <strong>⤢</strong>: ajusta todo a la pantalla. Tecla <strong>Esc</strong>: cierra paneles y quita la selección.</li>
    <li>Botón <strong>Leyenda</strong> (abajo a la izquierda): pliega o despliega la leyenda para ver mejor la red. Se recuerda tu elección.</li>${o
    ? `
    <li>Botón <strong>Mapa</strong> (abajo a la derecha): pone cada sol sobre su provincia, en la capital, encima del mapa de Ecuador; con «Compacta» (en Filtros) vuelven a agruparse. Un sol que se movió para no tapar a otro se une a su capital con una línea punteada. <strong>Galápagos</strong> te lleva a las islas.</li>`
    : ""}</ul>`;
  } },
  { titulo: "Filtros: resaltan, no ocultan", get html() {
    const o = usarOrbital();
    return `
    <p>El botón <strong>Filtros</strong> abre un panel a la izquierda. Allí puedes resaltar:</p>
    <ul><li>un tipo de conexión (pagador, texto, enlace, partido);</li>
    <li>un <strong>partido político</strong>: ${o ? "sus nodos se resaltan con el color del partido y el resto se atenúa" : "sus nodos se acercan y cambian de color"};</li>
    <li>un nombre (buscar), el color de los puntos, y hasta qué fecha mostrar anuncios.</li></ul>
    <p>Lo que no coincide se <strong>atenúa</strong>, pero nunca desaparece. También puedes descargar la imagen o un CSV de la red.</p>`;
  } },
  { titulo: "Mapa: noticias por provincia", ir: ["mapa", "Abrir el Mapa"], html: `
    <p>En <strong>Mapa</strong>, cada punto es una provincia. Los anuncios están en Conexiones; aquí ves lo que se publica en cada provincia.</p>
    <ul><li>Haz clic en una provincia del mapa (o elígela en la lista) para abrir su panel.</li>
    <li>Elige una fuente: <em>Prensa</em>, <em>Prensa local</em> (medios y portales de esa provincia), <em>Verificaciones</em>, <em>Bluesky</em>, <em>YouTube</em> o <em>Reddit</em>, y un período.</li>
    <li>Sirve para contrastar lo que ves en la red con lo que dice la prensa local y los verificadores.</li></ul>` },
  { titulo: "Más secciones", get html() {
    const o = usarOrbital();
    return `
    <p>La barra superior de Conexiones abre paneles que se deslizan por la derecha y, en su extremo derecho, la ventana <strong>Resumen</strong>:</p>
    <ul><li><strong>Resumen:</strong> totales y ranking de anunciantes por inversión, con descarga CSV y «Copiar cita» para tu nota. Es una ventana flotante: se mueve por su cabecera, cambia de tamaño desde sus bordes y puede quedar abierta junto a otro panel. Si seleccionas algo en la red (una página, un pagador o una línea), cuenta solo eso.</li>
    <li><strong>Mensajes repetidos:</strong> anuncios con texto casi idéntico en páginas distintas.${o ? " Mientras está seleccionada, las líneas grises punteadas de texto repetido se iluminan en la red." : ""} Los grupos esperables (una misma organización, un partido y sus candidatos…) se marcan como revisados y dejan de contarse.</li>
    <li><strong>Entidades:</strong> personas, partidos y medios; aquí se editan las afiliaciones y, con «Ver anuncios», se listan todos los que publican o pagan.</li>
    <li><strong>Buscar:</strong> cuenta menciones de un término en prensa, verificaciones y anuncios.</li>
    <li><strong>ⓘ:</strong> fuente de los datos, fecha de actualización y cómo se calcula cada cifra.</li></ul>
    <p>El selector de la izquierda cambia el alcance: empieza con todo el país y puedes enfocar una provincia.</p>`;
  } },
  { titulo: "Dos filtros para todo el sitio", html: `
    <p>Los anuncios de la autoridad electoral (CNE) suelen encabezar el gasto y tapan al resto. El interruptor <strong>Ocultar CNE</strong>, arriba a la derecha, los quita.</p>
    <p>El interruptor <strong>Solo activos</strong> deja únicamente los anuncios que siguen circulando (sin fecha de fin): sirve para ver qué se está mostrando ahora y qué páginas siguen pagando. Los terminados desaparecen de la red, las listas, las cifras y las descargas.</p>
    <p>Ambos afectan a Conexiones y Comparar, y tu elección se recuerda.</p>` },
  { titulo: "Afiliación política", ir: ["resumen", "Ir a Conexiones"], html: `
    <p>Meta no publica la afiliación política. Aquí se registra a mano, <strong>solo con una fuente</strong>.</p>
    <ul><li><span class="tag tag-afil">Verificada</span> tiene afiliación y enlace a la fuente. <span class="tag tag-afil pendiente">Sin verificar</span> es una propuesta.</li>
    <li>En <strong>Conexiones → Entidades</strong> puedes cambiar tipo, partido, afiliación y fuente, y pulsar <em>Guardar</em>. «Verificada» exige un enlace.</li>
    <li>Si dos entradas son la misma persona (otra página, o el pagador con otro nombre), márcalas con su casilla o con <strong>Shift + clic</strong> en el nombre y pulsa <em>Unificar</em>.</li>
    <li>Un <strong>medio</strong> que informa sin alinearse con un partido se marca con el partido <em>Neutral</em> (gris en la red); si está alineado, se escribe su partido.</li>
    <li>Una entidad de tipo <em>partido</em> (por ejemplo, la página oficial) se une a todos los nodos de su partido.</li>
    <li>Una línea punteada del color del partido une los <strong>soles</strong> (provincias) donde ese partido tiene candidatos. Las que dependen de candidatos sin verificar solo salen al incluir los partidos sin verificar.</li></ul>
    <p>Registra solo a figuras públicas y organizaciones, y solo lo que una fuente afirme. Los cambios se guardan en tu equipo.</p>` },
  { titulo: "Cómo leer los números", html: `
    <ul><li>Meta publica la inversión y las impresiones como <strong>rangos</strong>; la cifra estimada es el punto medio.</li>
    <li>Por provincia, cada anuncio cuenta en proporción a su alcance allí: es una <strong>estimación</strong>.</li>
    <li>Un texto repetido o un pagador compartido es un <strong>indicador</strong>, no una acusación.</li>
    <li>La pestaña <strong>Comparar</strong> pone dos o tres provincias lado a lado, y <strong>Método</strong> explica fuentes y límites.</li></ul>` },
  { titulo: "Listo para empezar", html: `
    <p>Puedes volver a este tutorial cuando quieras con el botón <strong>?</strong> de la barra superior.</p>
    <p>Sugerencia para empezar: abre <strong>Conexiones</strong>, activa <strong>Ocultar CNE</strong>, haz clic en una provincia y mira qué páginas la rodean.</p>` }
];
const tutorial = { paso: 0, retorno: null };

function pintarTutorial() {
  const p = PASOS_TUTORIAL[tutorial.paso], total = PASOS_TUTORIAL.length;
  $("tuto-num").textContent = `Paso ${tutorial.paso + 1} de ${total}`;
  $("tuto-titulo").textContent = p.titulo;
  $("tuto-cuerpo").innerHTML = p.html + (p.ir ? `<p><button type="button" class="btn" data-ir="${p.ir[0]}">${escaparHtml(p.ir[1])} →</button></p>` : "");
  $("tuto-puntos").innerHTML = PASOS_TUTORIAL.map((_, i) => `<span class="${i === tutorial.paso ? "on" : ""}"></span>`).join("");
  $("tuto-atras").disabled = tutorial.paso === 0;
  $("tuto-sig").textContent = tutorial.paso === total - 1 ? "Empezar" : "Siguiente";
}

function abrirTutorial(paso = 0) {
  tutorial.paso = paso; tutorial.retorno = document.activeElement;
  pintarTutorial();
  $("tutorial-overlay").hidden = false;
  $("tuto-sig").focus();
}

function cerrarTutorial() {
  $("tutorial-overlay").hidden = true;
  try { if ($("tuto-no-mostrar").checked || tutorial.paso === PASOS_TUTORIAL.length - 1) localStorage.setItem("noai_tutorial_visto", "1"); } catch (e) { /* sin almacenamiento */ }
  if (tutorial.retorno && tutorial.retorno.focus) tutorial.retorno.focus();
}

function initTutorial() {
  $("btn-tutorial")?.addEventListener("click", () => abrirTutorial(0));
  $("tuto-cerrar")?.addEventListener("click", cerrarTutorial);
  $("tuto-atras")?.addEventListener("click", () => { if (tutorial.paso > 0) { tutorial.paso -= 1; pintarTutorial(); } });
  $("tuto-sig")?.addEventListener("click", () => {
    if (tutorial.paso < PASOS_TUTORIAL.length - 1) { tutorial.paso += 1; pintarTutorial(); } else cerrarTutorial();
  });
  $("tuto-cuerpo")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ir]");
    if (b) { cerrarTutorial(); navegar({ vista: b.dataset.ir }); }
  });
  $("tutorial-overlay")?.addEventListener("click", (e) => { if (e.target.id === "tutorial-overlay") cerrarTutorial(); });
  document.addEventListener("keydown", (e) => {
    const ov = $("tutorial-overlay");
    if (!ov || ov.hidden) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cerrarTutorial(); }
    else if (e.key === "ArrowRight") $("tuto-sig").click();
    else if (e.key === "ArrowLeft") $("tuto-atras").click();
    else if (e.key === "Tab") {   // el foco se queda dentro del cuadro
      const f = [...ov.querySelectorAll("button, input, a[href]")].filter((x) => !x.disabled && x.offsetParent !== null);
      if (!f.length) return;
      const primero = f[0], ultimo = f[f.length - 1];
      if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
      else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
    }
  }, true);
  let visto = false;
  try { visto = localStorage.getItem("noai_tutorial_visto") === "1"; } catch (e) { /* sin almacenamiento */ }
  if (!visto) setTimeout(() => { if (!document.querySelector("#modal-auth-overlay.active")) abrirTutorial(0); }, 900);
}

function initTheme() {
  let guardado = null;
  try { guardado = localStorage.getItem("noai_theme"); } catch (e) { /* sin almacenamiento */ }
  const sistema = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  aplicarTema(guardado || sistema);
  $("btn-theme")?.addEventListener("click", () => {
    aplicarTema((document.documentElement.getAttribute("data-theme") || "light") === "dark" ? "light" : "dark");
  });
}

function aplicarTema(tema) {
  document.documentElement.setAttribute("data-theme", tema);
  try { localStorage.setItem("noai_theme", tema); } catch (e) { /* sin almacenamiento */ }
  const logo = $("brand-logo-img");
  if (logo) logo.src = tema === "dark" ? "img/LOGO_WHITE.png" : "img/LOGO_BLACK.png";
  const btn = $("btn-theme");
  if (btn) btn.setAttribute("aria-label", tema === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro");
  actualizarBurbujas();
  if (typeof redOrbital !== "undefined" && redOrbital && state.vista === "resumen") renderRed();      // la red orbital vuelve a dibujarse con los colores del tema (conserva cámara y selección)
}

// ---------------------------------------------------------------------------
// Selectores de provincia
// ---------------------------------------------------------------------------
function poblarSelect(el, { nacional = false, vacio = null, seleccionado = null } = {}) {
  if (!el) return;
  const opciones = [];
  if (vacio) opciones.push(`<option value="">${escaparHtml(vacio)}</option>`);
  if (nacional) opciones.push(`<option value="todas">Nacional (todas las provincias)</option>`);
  provinciasEcuador.forEach((p) => opciones.push(`<option value="${p.id}">${escaparHtml(p.nombre)}</option>`));
  el.innerHTML = opciones.join("");
  if (seleccionado !== null) el.value = seleccionado;
}

// ---------------------------------------------------------------------------
// Mapa de burbujas
// ---------------------------------------------------------------------------
function colorCss(variable, respaldo) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
  return v || respaldo;
}

/** Teselas de OpenStreetMap; el CSS las atenúa (gris, o invertidas en tema oscuro) para que destaquen las burbujas. */
function urlTeselas() {
  return "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
}

function initMap() {
  const limites = L.latLngBounds(L.latLng(-5.1, -92.1), L.latLng(1.7, -75.2));
  state.map = L.map("map", { center: [-1.7, -78.4], zoom: 7, minZoom: 6, maxBounds: limites, maxBoundsViscosity: 1.0, zoomControl: false });
  L.control.zoom({ position: "topright" }).addTo(state.map);
  state.tiles = L.tileLayer(urlTeselas(), {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(state.map);

  const ControlGalapagos = L.Control.extend({
    options: { position: "bottomright" },
    onAdd() {
      const b = L.DomUtil.create("button", "leaflet-galapagos-btn");
      b.type = "button";
      b.textContent = "Ir a Galápagos";
      b.setAttribute("aria-label", "Ir a las islas Galápagos en el mapa");
      L.DomEvent.on(b, "click", (e) => { L.DomEvent.stop(e); state.map.flyTo([-0.62, -90.35], 7, { animate: !sinMovimiento(), duration: 1.2 }); });
      return b;
    }
  });
  new ControlGalapagos().addTo(state.map);

  provinciasEcuador.forEach((p) => {
    const b = L.circleMarker([p.lat, p.lng], { radius: 8, weight: 2, className: "bubble" }).addTo(state.map);
    b.bindTooltip(`<strong>${escaparHtml(p.nombre)}</strong>`, { className: "bubble-tooltip", direction: "top", offset: [0, -4] });
    b.on("click", (e) => { L.DomEvent.stopPropagation(e); navegar({ vista: "mapa", provincia: p.id }); });
    const el = b.getElement();
    if (el) {
      el.setAttribute("tabindex", "0");
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", `Provincia de ${p.nombre}`);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navegar({ vista: "mapa", provincia: p.id }); }
      });
      el.addEventListener("focus", () => b.openTooltip());
      el.addEventListener("blur", () => b.closeTooltip());
    }
    state.burbujas[p.id] = b;
  });

  actualizarBurbujas();
  setTimeout(() => state.map && state.map.invalidateSize(), 250);
  window.addEventListener("resize", () => state.map && state.map.invalidateSize());
  cargarMapaDatos();
}

async function cargarMapaDatos() {
  try {
    state.mapaDatos = await fetchApi(`/api/ads/mapa`, { timeout: 60000 });
  } catch (e) {
    state.mapaDatos = { provincias: [], fuera_de_ecuador_impresiones: 0, estado: { mensaje: `No se pudieron cargar los datos del mapa (${e.message}).` }, error: true };
  }
  actualizarBurbujas();
  if (!state.provincia) renderIntro();
}

function actualizarBurbujas() {
  if (!state.map) return;
  const relleno = colorCss("--bubble", "#1877f2");
  const acento = colorCss("--focus", "#4f46e5");
  provinciasEcuador.forEach((p) => {
    const b = state.burbujas[p.id];
    if (!b) return;
    const seleccionada = state.provincia && state.provincia.id === p.id;
    b.setRadius(seleccionada ? 11 : 9);
    b.setStyle({ color: seleccionada ? acento : relleno, fillColor: relleno, fillOpacity: seleccionada ? 0.6 : 0.42, weight: seleccionada ? 4 : 2 });
    b.setTooltipContent(`<strong>${escaparHtml(p.nombre)}</strong>`);
    if (seleccionada) b.bringToFront();
  });
}


// ---------------------------------------------------------------------------
// Navegación y URL (hash)
// ---------------------------------------------------------------------------
const VISTAS = { mapa: "view-mapa", resumen: "view-resumen", comparar: "view-comparar", metodo: "view-acerca" };
// La pestaña se llama «Conexiones» (antes «Resumen»); la ruta #/resumen y los ids internos conservan el nombre antiguo para no romper enlaces ya compartidos.
const TITULOS = { mapa: "Mapa", resumen: "Conexiones", comparar: "Comparar", metodo: "Método y fuentes" };

function mostrarVista(vista) {
  if (!VISTAS[vista]) vista = "mapa";
  state.vista = vista;
  Object.entries(VISTAS).forEach(([nombre, id]) => $(id)?.classList.toggle("active", nombre === vista));
  document.querySelectorAll(".nav button").forEach((b) => {
    if (b.dataset.vista === vista) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  document.title = `${TITULOS[vista]} · NoAIVerdad`;
  const activo = document.querySelector(".nav button[aria-current]");
  if (activo && activo.scrollIntoView) activo.scrollIntoView({ inline: "center", block: "nearest" });
  if (vista === "mapa") setTimeout(() => state.map && state.map.invalidateSize(), 120);
  if (vista === "resumen") aplicarTamanoPanelDer();       // el tamaño guardado del panel se acota con la vista ya visible
  const v = $(VISTAS[vista]);
  if (v && vista !== "mapa") v.scrollTop = 0;
}

function construirHash() {
  if (state.vista === "resumen") return `#/resumen/${state.resumen.alcance || "todas"}/${state.resumen.tab}`;
  if (state.vista === "comparar") return `#/comparar/${state.comparar.alcances.join("/")}`;
  if (state.vista === "metodo") return "#/metodo";
  if (state.provincia) {
    const partes = ["mapa", state.provincia.id, state.seccion];
    if (state.periodo !== "todo") partes.push(state.periodo);
    return "#/" + partes.join("/");
  }
  return "#/mapa";
}

// El mapa recuerda provincia, sección, período y encuadre: al recargar la página (p. ej. tras cambios) vuelve a lo que había, sin saltar al zoom global.
const CLAVE_MAPA = "noai_mapa";

function guardarMapa() {
  if (!state.map || state.mapaPendiente) return;      // con lo guardado aún sin aplicar, no se pisa con el mapa sin tocar
  try {
    const c = state.map.getCenter();
    localStorage.setItem(CLAVE_MAPA, JSON.stringify({ prov: state.provincia ? state.provincia.id : null, seccion: state.seccion, periodo: state.periodo, lat: c.lat, lng: c.lng, zoom: state.map.getZoom() }));
  } catch (e) { /* sin almacenamiento */ }
}

function leerMapaGuardado() {
  try {
    const g = JSON.parse(localStorage.getItem(CLAVE_MAPA) || "null");
    return g && Number.isFinite(g.lat) && Number.isFinite(g.lng) && Number.isFinite(g.zoom) ? g : null;
  } catch (e) { return null; }
}

function escribirHash(reemplazar = false) {
  const hash = construirHash();
  guardarMapa();
  state.hashAplicado = hash;
  if (location.hash === hash) return;
  try { history[reemplazar ? "replaceState" : "pushState"](null, "", hash); } catch (e) { location.hash = hash; }
}

/** El Mapa muestra prensa, verificaciones y redes; los anuncios están en Conexiones. */
const seccionDelMapa = (s) => !!SECCIONES[s] && s !== "meta_ads";

const alcanceValido = (a) => a === "todas" || !!provinciaPorId(a);

/** ¿Se vuelve a cargar una página que ya estaba abierta en esta pestaña (recargar, atrás/adelante)? Un enlace abierto de cero no cuenta. */
function cargaDeNuevo() {
  try { const t = (performance.getEntriesByType("navigation")[0] || {}).type; return t === "reload" || t === "back_forward"; } catch (e) { return false; }
}

function leerHash() {
  const [vista, a, b, c] = (location.hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
  if (!vista || vista === "resumen" || vista === "dashboard") {         // sin ruta se abre Conexiones
    if (b === "anunciantes") return { vista: "resumen", alcance: alcanceValido(a) ? a : "todas", tab: TABS[0], resumenFlot: true };       // enlaces de antes: abren la ventana «Resumen»
    return { vista: "resumen", alcance: alcanceValido(a) ? a : "todas", tab: TABS.includes(b) ? b : TABS[0] };
  }
  if (vista === "comparar") {
    const comp = [a, b, c].filter((x) => x && alcanceValido(x));
    return { vista: "comparar", comp: comp.length >= 2 ? comp : ["pichincha", "guayas"] };
  }
  if (vista === "metodo") return { vista: "metodo" };
  const ruta = { vista: "mapa" };
  if (a && provinciaPorId(a)) ruta.provincia = a;
  if (b && seccionDelMapa(b)) ruta.seccion = b;
  if (c && PERIODOS[c]) ruta.periodo = c;
  return ruta;
}

/** Punto único de navegación: actualiza estado, vista, URL y carga datos. */
function navegar(ruta, { historial = true } = {}) {
  const vista = ruta.vista || state.vista;

  if (vista === "mapa") {
    // La página se recargó en otra pestaña: al abrir el Mapa por primera vez recupera la provincia, la fuente, el período y el encuadre que tenía.
    const guardado = state.mapaPendiente;
    state.mapaPendiente = null;
    if (guardado && !ruta.provincia && !ruta.limpiar) {
      if (guardado.prov && provinciaPorId(guardado.prov)) ruta.provincia = guardado.prov;
      if (!ruta.seccion && seccionDelMapa(guardado.seccion)) ruta.seccion = guardado.seccion;
      if (!ruta.periodo && PERIODOS[guardado.periodo]) ruta.periodo = guardado.periodo;
    }
    if (ruta.seccion) state.seccion = ruta.seccion;
    if (ruta.periodo) state.periodo = ruta.periodo;
    sincronizarPanel();
    const veniaDeOtraVista = state.vista !== "mapa";       // el mapa no estaba a la vista: no tiene sentido animar el viaje hasta la provincia
    const conservarEncuadre = veniaDeOtraVista && !!state.provincia && state.provincia.id === ruta.provincia;      // la misma provincia que ya estaba abierta: se queda el zoom que tenía
    mostrarVista("mapa");
    if (ruta.limpiar) limpiarProvincia();
    else if (ruta.provincia) {
      const prov = provinciaPorId(ruta.provincia);
      if (prov) seleccionarProvincia(prov, { animar: !veniaDeOtraVista, conservarEncuadre });
    } else if (state.provincia && ruta.seccion) {
      cargarSeccion(state.provincia.nombre, state.seccion);
    }
    if (guardado && !ruta.limpiar && (!ruta.provincia || ruta.provincia === guardado.prov)) {
      state.map.invalidateSize({ animate: false });           // el mapa estaba oculto: su tamaño aún no se conocía
      state.map.setView([guardado.lat, guardado.lng], guardado.zoom, { animate: false });
    }
  } else if (vista === "resumen") {
    state.resumen.tab = ruta.tab || state.resumen.tab;
    mostrarVista("resumen");
    activarTab(state.resumen.tab, { desdeRuta: true });
    if (ruta.resumenFlot) alternarFlot(true);
    const alcance = ruta.alcance || state.resumen.alcance;
    if (alcance !== state.resumen.alcance || !state.resumen.top) { state.resumen.alcance = alcance; cargarResumen(alcance); }
    $("resumen-alcance").value = state.resumen.alcance;
  } else if (vista === "comparar") {
    if (ruta.comp) state.comparar.alcances = ruta.comp.slice(0, 3);
    mostrarVista("comparar");
    renderSelectoresComparar();
    cargarComparacion();
  } else {
    mostrarVista("metodo");
  }
  escribirHash(!historial);
}

function aplicarHash() {
  if (location.hash === state.hashAplicado) return;
  state.hashAplicado = location.hash;
  const ruta = leerHash();
  if (ruta.vista === "mapa" && !ruta.provincia) { mostrarVista("mapa"); limpiarProvincia(); return; }
  navegar(ruta, { historial: false });
}

function initNav() {
  document.querySelectorAll(".nav button").forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.vista, origen = state.vista;
    // Conexiones empieza sin provincia de enfoque («todas»): el menú no hereda la provincia del Mapa. La provincia se enfoca a propósito
    // (selector, «Ver solo X», botón «Conexiones» del panel del Mapa) y se recuerda hasta que la cambies. Al ir al Mapa desde Conexiones
    // se abre la provincia enfocada; con «todas» el Mapa se queda como estaba.
    const enfocada = state.resumen.alcance;
    if (v === "mapa" && origen === "resumen" && enfocada && enfocada !== "todas") navegar({ vista: "mapa", provincia: enfocada });
    else navegar({ vista: v });
  }));
  const brand = $("brand");
  brand?.addEventListener("click", () => navegar({ vista: "resumen" }));
  brand?.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navegar({ vista: "resumen" }); } });
  window.addEventListener("popstate", aplicarHash);
  window.addEventListener("hashchange", aplicarHash);
}

// ---------------------------------------------------------------------------
// Vista Provincias: panel y feed
// ---------------------------------------------------------------------------
function sincronizarPanel() {
  document.querySelectorAll("#source-chips .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.seccion === state.seccion)));
  const fp = $("filter-period");
  if (fp && fp.value !== state.periodo) fp.value = state.periodo;
  const ps = $("province-select");
  if (ps) ps.value = state.provincia ? state.provincia.id : "";
}

function initPanel() {
  poblarSelect($("province-select"), { vacio: "Selecciona una provincia" });

  $("province-select")?.addEventListener("change", debounce((e) => {
    if (e.target.value) navegar({ vista: "mapa", provincia: e.target.value });
    else navegar({ vista: "mapa", limpiar: true });
  }, 500));

  $("source-chips")?.addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    state.seccion = b.dataset.seccion;
    sincronizarPanel();
    if (state.provincia) cargarSeccion(state.provincia.nombre, state.seccion);
    actualizarTituloPanel();
    escribirHash();
  });

  $("filter-period")?.addEventListener("change", (e) => {
    state.periodo = e.target.value;
    if (usaListaCompleta()) cargarSeccion(state.provincia.nombre, "meta_ads");      // la lista de anuncios se pide ya con el período
    else if (state.datos) renderizarFeed();
    escribirHash();
  });

  $("go-resumen")?.addEventListener("click", () => state.provincia && navegar({ vista: "resumen", alcance: state.provincia.id }));
  $("go-comparar")?.addEventListener("click", () => state.provincia && navegar({ vista: "comparar", comp: [state.provincia.id, "todas"] }));

  $("sidebar-content")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-accion], [data-prov]");
    if (!b) return;
    if (b.dataset.prov) { navegar({ vista: "mapa", provincia: b.dataset.prov }); return; }
    if (b.dataset.accion === "reintentar" && state.provincia) cargarSeccion(state.provincia.nombre, state.seccion, { forzar: true });
    if (b.dataset.accion === "quitar-periodo") { state.periodo = "todo"; sincronizarPanel(); renderizarFeed(); escribirHash(); }
  });
}

function actualizarTituloPanel() {
  const acciones = $("panel-actions");
  const titulo = $("sidebar-title");
  if (!acciones || !titulo) return;
  acciones.hidden = !state.provincia;
  titulo.textContent = state.provincia ? state.provincia.nombre : "Selecciona una provincia";      // sin provincia no debe quedar el nombre anterior
}

function limpiarProvincia() {
  state.provincia = null;
  state.datos = null;
  state.seq++;
  if (state.abort) state.abort.abort();
  sincronizarPanel();
  actualizarTituloPanel();
  actualizarBurbujas();
  renderIntro();
}

function renderIntro() {
  const c = $("sidebar-content");
  if (!c || state.provincia) return;
  c.innerHTML = `
    <div class="state" style="padding-top:24px">
      <div class="state-title">Elige una provincia</div>
      <p>Haz clic en una provincia del mapa o usa la lista de arriba. Verás prensa, verificaciones y publicaciones de esa provincia.</p>
    </div>
    `;
}

function seleccionarProvincia(provincia, { animar = true, conservarEncuadre = false } = {}) {
  const anterior = state.provincia;
  state.provincia = provincia;
  sincronizarPanel();
  actualizarTituloPanel();
  actualizarBurbujas();

  state.map.invalidateSize({ animate: false });
  if (!conservarEncuadre) {
    try { state.map.flyTo([provincia.lat, provincia.lng], 8, { animate: animar && !sinMovimiento(), duration: 1.1 }); }
    catch (e) { state.map.setView([provincia.lat, provincia.lng], 8, { animate: false }); }
  }

  if (!anterior || anterior.id !== provincia.id || !state.datos || state.datos.seccion !== state.seccion) {
    cargarSeccion(provincia.nombre, state.seccion);
  }
}

/** ¿La pestaña Mapa muestra la lista completa de anuncios de la provincia (y no la corta de /api/noticias)? */
const usaListaCompleta = () => !!state.provincia && state.seccion === "meta_ads" && !state.sinListaCompleta;

/**
 * Pestaña Mapa, chip «Anuncios»: la lista completa y paginada de los anuncios que llegan a la provincia (al menos el 5 % de su
 * alcance), la misma que el detalle de la red, en lugar de los 15 primeros. El período es el del selector del panel.
 */
function montarAnunciosMapa(provinciaNombre) {
  const contenedor = $("sidebar-content");
  contenedor.removeAttribute("aria-busy");
  state.datos = null;                          // lo que hay en pantalla ya no es un feed de /api/noticias
  contenedor.innerHTML = "";
  const caja = document.createElement("section");
  caja.className = "rs-anuncios rs-anuncios-mapa";
  contenedor.appendChild(caja);
  contenedor.scrollTop = 0;
  montarListaAnuncios(caja, { alcance: provinciaNombre, dias: /^\d+$/.test(state.periodo) ? state.periodo : "" }, {
    titulo: SECCIONES.meta_ads, provincia: provinciaNombre, ordenInicial: "impresiones",
    // Si este servidor no tiene el endpoint (404/400) o falla, se vuelve al camino de siempre (/api/noticias, con su respaldo de Firebase).
    alFallar: (e) => {
      if (/HTTP (404|400)/.test(e.message)) state.sinListaCompleta = true;
      if (state.provincia && state.provincia.nombre === provinciaNombre && state.seccion === "meta_ads") cargarSeccion(provinciaNombre, "meta_ads", { forzar: true, antiguo: true });
    }
  });
}

async function cargarSeccion(provinciaNombre, seccion, { forzar = false, antiguo = false } = {}) {
  const contenedor = $("sidebar-content");
  state.seccion = seccion;
  sincronizarPanel();

  const seq = ++state.seq;
  if (state.abort) state.abort.abort();
  state.abort = new AbortController();

  if (seccion === "meta_ads" && !antiguo && !state.sinListaCompleta) { montarAnunciosMapa(provinciaNombre); return; }

  const clave = `${provinciaNombre}|${seccion}`;
  const enCache = state.feedCache[clave];
  if (!forzar && enCache && Date.now() - enCache.ts < CACHE_FEED_MS) {
    state.datos = { provincia: provinciaNombre, seccion, data: enCache.data };
    renderizarFeed();
    return;
  }

  contenedor.setAttribute("aria-busy", "true");
  contenedor.innerHTML = cajaEstado({ tipo: "carga", titulo: `Cargando ${SECCIONES[seccion].toLowerCase()}...`, descripcion: `Consultando las fuentes para <strong>${escaparHtml(provinciaNombre)}</strong>.` });

  try {
    const ruta = `/api/noticias?provincia=${encodeURIComponent(provinciaNombre)}&seccion=${encodeURIComponent(seccion)}`;
    let data = null;
    let falla = null;
    try {
      data = await fetchApi(ruta, { signal: state.abort.signal, timeout: 45000 });
    } catch (e) {
      if (e.message === "cancelado") throw e;
      falla = e;
    }
    if (seq !== state.seq) return;
    if (!data || (!data.error && !listaDe(data[CAMPO_SECCION[seccion]]).length)) {
      const guardado = await datosGuardadosFirebase(provinciaNombre, seccion);
      if (seq !== state.seq) return;
      if (guardado) data = guardado;
      else if (!data) throw falla || new Error("sin respuesta");
    }
    if (!data.error && !data._guardado) state.feedCache[clave] = { ts: Date.now(), data };
    state.datos = { provincia: provinciaNombre, seccion, data };
    renderizarFeed();
  } catch (error) {
    if (seq !== state.seq || error.message === "cancelado") return;
    console.error("Error al cargar el feed:", error);
    state.datos = null;
    contenedor.removeAttribute("aria-busy");
    contenedor.innerHTML = cajaEstado({
      tipo: "error",
      titulo: "No se pudo cargar la información",
      descripcion: `El servidor no respondió para <strong>${escaparHtml(provinciaNombre)}</strong> (${escaparHtml(error.message)}). Comprueba tu conexión e inténtalo de nuevo.`,
      boton: { accion: "reintentar", texto: "Reintentar" }
    });
  }
}

// --- Período ---------------------------------------------------------------
function fechaDeItem(item, seccion) {
  if (seccion === "meta_ads") return fechaComoDate(item.fecha_fin || item.date);
  return fechaComoDate(item.fecha || item.date || item.reviewDate || item.claimDate);
}

function dentroDelPeriodo(item, seccion) {
  if (state.periodo === "todo") return true;
  if (seccion === "meta_ads" && item.activo) return true;
  const d = fechaDeItem(item, seccion);
  return !!d && (Date.now() - d.getTime()) <= Number(state.periodo) * 86400000;
}

// --- Calificaciones de verificadores ----------------------------------------
function clasificarRating(texto) {
  const t = String(texto || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  if (!t) return "sin";
  if (/no es falso/.test(t)) return "verdadero";
  if (/(parcial|media verdad|mixt|impreciso|sin contexto|descontextual|exagerad|discutible|enganos)/.test(t)) return "mixto";
  if (/(no es (cierto|verdad)|fals|engan|incorrect|fake|inexact|desmentid|manipulad|alterad|sin sustento|no hay evidencia)/.test(t)) return "falso";
  if (/(verdader|cierto|correcto|confirmad|real\b|true|exacto)/.test(t)) return "verdadero";
  return "otro";
}
const CLASE_RATING = { falso: "tag-bad", mixto: "tag-warn", verdadero: "tag-ok", otro: "tag-info", sin: "" };

// --- Tarjetas -----------------------------------------------------------------
function tarjetaNoticia(n) {
  return `
    <article class="item" data-fuente="noticias">
      <div class="item-top"><span class="item-source">${escaparHtml(n.fuente)}</span><span class="item-date">${escaparHtml(formatearFechaSafe(n.fecha))}</span></div>
      <h4 class="item-title">${escaparHtml(n.titulo)}</h4>
      <div class="item-foot">${enlace(n.url, "Leer la noticia")}</div>
    </article>`;
}

function tarjetaVerificacion(v) {
  const clase = clasificarRating(v.textualRating);
  const fecha = formatearFechaSafe(v.reviewDate || v.claimDate);
  const afirmacion = v.text || v.title || "";
  return `
    <article class="item" data-fuente="verificaciones">
      <div class="item-top"><span class="item-source">${escaparHtml(v.publisher || "Verificador")}</span>${fecha ? `<span class="item-date">${escaparHtml(fecha)}</span>` : ""}</div>
      <h4 class="item-title">«${escaparHtml(afirmacion)}»</h4>
      ${v.claimant ? `<div class="item-sub">Atribuida a: ${escaparHtml(v.claimant)}</div>` : ""}
      <div class="rating">${v.textualRating ? `Calificación del verificador: <span class="tag ${CLASE_RATING[clase]}">${escaparHtml(v.textualRating)}</span>` : "Revisión publicada, sin calificación."}</div>
      ${v.title && v.title !== afirmacion ? `<div class="item-sub">Revisión: ${escaparHtml(v.title)}</div>` : ""}
      <div class="item-foot">${enlace(v.url, "Leer la verificación")}<span class="muted">vía Google Fact Check</span></div>
    </article>`;
}

function tarjetaRedSocial(p, fuente, etiqueta) {
  const usuario = fuente === "tweets" ? (p.user || {}) : (p.author || {});
  const nombre = usuario.name || "Cuenta";
  const handle = usuario.username || usuario.handle || "";
  const s = p.stats || {};
  const reposts = fuente === "tweets" ? s.retweets : s.reposts;
  const c = p.cuenta || {};
  const creada = c.creada ? new Date(c.creada).getFullYear() : null;
  const cuenta = [creada ? `cuenta creada en ${creada}` : "", c.seguidores != null ? `${fmtNum(c.seguidores)} seguidores` : ""].filter(Boolean).join(" · ");
  const fecha = fuente === "bluesky" ? String(p.date || "").split("T")[0] : p.date;
  return `
    <article class="item" data-fuente="${fuente}">
      <div class="item-top"><span class="item-source">${escaparHtml(nombre)} <span class="muted">${escaparHtml(handle)}</span></span><span class="item-date">${escaparHtml(formatearFechaSafe(fecha))}</span></div>
      <div class="item-text">${escaparHtml(p.text)}</div>
      ${cuenta ? `<div class="item-sub">${escaparHtml(cuenta)}</div>` : ""}
      <div class="item-stats">${fmtNum(s.likes)} me gusta · ${fmtNum(reposts)} reposts · ${fmtNum(s.replies)} respuestas · ${fmtNum(s.quotes)} citas</div>
      <div class="item-foot">${enlace(p.link, `Ver en ${etiqueta}`)}</div>
    </article>`;
}

const ROLES_ANUNCIO = { pagina: "Publica la página", pagador: "Paga este anuncio", ambos: "Publica y paga" };

/** Tarjeta de un anuncio de Meta. opciones.provincia: nombre para «x % en …»; opciones.rol: papel de una entidad (Entidades). */
/** Tipos de anunciante para filtrar listas (el servidor los agrupa según «tipo» en Entidades). */
const TIPOS_ANUNCIANTE = [["", "Todos los tipos"], ["candidatos", "Candidatos y políticos"], ["instituciones", "Instituciones públicas"], ["medios", "Medios"],
  ["agencias", "Agencias y empresas"], ["otros", "Otros"], ["sin_clasificar", "Sin clasificar"]];
const opcionesTipo = (actual) => TIPOS_ANUNCIANTE.map(([v, t]) => `<option value="${v}"${v === actual ? " selected" : ""}>${t}</option>`).join("");

/** Una celda de CSV: entre comillas, y con una comilla simple delante si empieza como fórmula (=, +, -, @) para que Excel no la ejecute. */
function celdaCsv(v) {
  let t = String(v ?? "");
  if (/^[=+\-@\t\r]/.test(t)) t = "'" + t;
  return `"${t.replace(/"/g, '""')}"`;
}

/** Descarga un CSV (UTF-8 con BOM, para Excel). */
function descargarCsvArchivo(nombre, cabeceras, filas) {
  const csv = "\uFEFF" + [cabeceras.map(celdaCsv).join(",")].concat(filas.map((f) => f.map(celdaCsv).join(","))).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = nombre;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

const nombreArchivoSeguro = (t) => normalizar(t).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "anuncios";
const fechaHoyIso = () => new Date().toISOString().slice(0, 10);

const CABECERA_ANUNCIO = ["id_anuncio", "pagina", "page_id", "pagador_declarado", "pagado_por_tercero", "tipo_anunciante", "partido", "afiliacion", "afiliacion_verificada",
  "texto", "enlace_biblioteca", "fecha_inicio", "fecha_fin", "activo", "moneda", "gasto_min", "gasto_max", "gasto_estimado", "impresiones_min", "impresiones_max",
  "impresiones_estimadas", "plataformas", "provincia_principal", "porcentaje_provincia_principal", "alcance_por_provincia", "porcentaje_en_la_provincia_consultada"];

/** La fila CSV de un anuncio (tal como lo devuelve /api/ads/anuncios con completo=1): texto, enlace, fechas, gasto, impresiones y alcance por provincia. */
function filaCsvAnuncio(ad) {
  const medio = (r) => (r && (r.min != null || r.max != null) ? ((r.min ?? r.max) + (r.max ?? r.min)) / 2 : "");
  const af = ad.afiliacion || null;
  const regs = (ad.regiones || []).slice().sort((a, b) => b.porcentaje - a.porcentaje);
  const rp = ad.region_principal;
  const gasto = ad.gasto || {}, imp = ad.impresiones || {};
  return [ad.id, ad.page_name, ad.page_id, ad.financiador, ad.pagado_por_tercero ? "sí" : "no", af ? (af.tipo || "") : "", af ? (af.partido || "") : "", af ? af.afiliacion : "",
    af ? (af.verificado ? "sí" : "no") : "", ad.text, ad.link, ad.date, ad.fecha_fin || "", ad.activo ? "sí" : "no", ad.moneda, gasto.min ?? "", gasto.max ?? "", medio(gasto),
    imp.min ?? "", imp.max ?? "", medio(imp), (ad.plataformas || []).join(" | "), rp ? rp.region : "", rp ? Math.round(rp.porcentaje * 1000) / 10 : "",
    regs.map((r) => `${r.region} ${Math.round(r.porcentaje * 1000) / 10} %`).join("; "),
    typeof ad.porcentaje_provincia === "number" ? Math.round(ad.porcentaje_provincia * 1000) / 10 : ""];
}

function tarjetaMeta(ad, { provincia = "", rol = "", descargable = false } = {}) {
  const plataformas = (ad.plataformas || []).map((p) => String(p).toLowerCase()).join(", ");
  const rp = ad.region_principal;
  const alcance = (typeof ad.porcentaje_provincia === "number") ? `${Math.round(ad.porcentaje_provincia * 100)} % en ${provincia || "esta provincia"}`
    : (rp ? `Sobre todo ${rp.region} (${Math.round(rp.porcentaje * 100)} %)` : "Sin datos regionales");
  const fin = ad.fecha_fin ? ` – ${escaparHtml(formatearFechaSafe(ad.fecha_fin))}` : "";
  return `
    <article class="item" data-fuente="meta_ads">
      <div class="item-top"><span class="item-source">${escaparHtml(ad.page_name || "Página sin nombre")}${ad.page_name ? ` <button type="button" class="ficha-lapiz" data-ficha data-ficha-nombre="${escaparHtml(ad.page_name)}" data-ficha-id="${escaparHtml(ad.page_id || "")}" title="Validar el perfil de esta entidad" aria-label="Validar el perfil de ${escaparHtml(ad.page_name)}">✎</button>` : ""}</span><span class="item-tags">${ROLES_ANUNCIO[rol] ? `<span class="tag">${ROLES_ANUNCIO[rol]}</span>` : ""}<span class="tag ${ad.activo ? "tag-info" : ""}">${ad.activo ? "Activo" : "Finalizado"}</span></span></div>
      ${filaAfil(ad)}
      <div class="item-text">${ad.text ? escaparHtml(ad.text) : "<em>(Anuncio sin texto)</em>"}</div>
      <dl class="facts">
        <div class="wide"><dt>Pagado por</dt><dd>${escaparHtml(ad.financiador) || "No declarado"}</dd></div>
        <div><dt>Inversión (rango)</dt><dd>${escaparHtml(formatearRango(ad.gasto, ad.moneda))}</dd></div>
        <div><dt>Alcance</dt><dd>${escaparHtml(alcance)}</dd></div>
      </dl>
      <details class="more">
        <summary>Más detalles</summary>
        <dl class="facts">
          <div><dt>Impresiones (rango)</dt><dd>${escaparHtml(formatearRango(ad.impresiones))}</dd></div>
          <div><dt>Fechas</dt><dd>${escaparHtml(formatearFechaSafe(ad.date))}${fin}</dd></div>
          ${plataformas ? `<div><dt>Plataformas</dt><dd>${escaparHtml(plataformas)}</dd></div>` : ""}
        </dl>
      </details>
      <div class="item-foot">${enlace(ad.link, "Ver en la Biblioteca de Anuncios")}${descargable ? ` <button type="button" class="link-btn" data-an="uno" data-ad-id="${escaparHtml(ad.id)}" title="Descarga este anuncio en CSV: texto, enlace, fechas, gasto, impresiones y alcance por provincia">Descargar este anuncio</button>` : ""}</div>
    </article>`;
}

// ---------------------------------------------------------------------------
// Lista de TODOS los anuncios de un nodo de la red o de una entidad, paginada bajo demanda (GET /api/ads/anuncios)
// ---------------------------------------------------------------------------
const ANUNCIOS_POR_TANDA = 20;
const MAX_EXPORTAR_ANUNCIOS = 5000;

/**
 * Monta en `cont` la lista de anuncios que cumplen `filtro` (parámetros de /api/ads/anuncios: alcance, dias, pagina, pagador,
 * region, entidad…). `alcance` = los anuncios que llegan a esa provincia; `region` = los de las páginas con base allí.
 * opciones: titulo, provincia (para «x % en …»), nota (aclaración bajo el resumen), mostrarRol (papel de una entidad),
 * ordenInicial (recientes | inversion | impresiones), alFallar(error) (si falla la primera carga: el llamador puede tomar otro camino).
 * Muestra una tanda y deja «Mostrar más» / «Mostrar todos»; cambiar el orden vuelve a empezar.
 */
function montarListaAnuncios(cont, filtro, { titulo = "Anuncios", provincia = "", nota = "", mostrarRol = false, ordenInicial = "recientes", alFallar = null } = {}) {
  const U = { desde: 0, total: null, orden: ordenInicial, token: 0, error: "", tipo: "", ads: new Map() };
  const variosAnunciantes = !!(filtro.alcance || filtro.region);          // en la lista de una página o un pagador el tipo de anunciante no distingue nada
  cont.innerHTML = `
    <div class="rs-an-cab">
      <h3>${escaparHtml(titulo)} <span class="rs-an-n"></span></h3>
      ${variosAnunciantes ? `<label class="xsmall">Tipo
        <select class="rs-an-tipo" aria-label="Filtrar por tipo de anunciante" title="Solo se puede filtrar por tipo lo que está clasificado en Entidades; el resto va en «Sin clasificar»">${opcionesTipo("")}</select></label>` : ""}
      <label class="xsmall">Orden
        <select class="rs-an-orden" aria-label="Ordenar los anuncios">
          <option value="recientes">Más recientes</option><option value="inversion">Mayor inversión</option><option value="impresiones">Más impresiones</option>
        </select></label>
    </div>
    <div class="rs-an-acciones"><button type="button" class="btn" data-an="csv" title="Descarga todos estos anuncios (hasta ${fmtNum(MAX_EXPORTAR_ANUNCIOS)}) en CSV, con su texto, enlace, fechas, gasto, impresiones y alcance por provincia">Descargar CSV</button><span class="xsmall muted rs-an-descarga" role="status" aria-live="polite"></span></div>
    <p class="rs-an-resumen xsmall muted" aria-live="polite"></p>
    <p class="rs-an-aviso xsmall muted"></p>
    ${nota ? `<p class="rs-an-nota xsmall muted">${escaparHtml(nota)}</p>` : ""}
    <div class="rs-an-lista"></div>
    <div class="rs-an-pie" aria-live="polite"></div>`;
  const lista = cont.querySelector(".rs-an-lista"), pie = cont.querySelector(".rs-an-pie"), nEl = cont.querySelector(".rs-an-n"), resEl = cont.querySelector(".rs-an-resumen"), avisoEl = cont.querySelector(".rs-an-aviso");
  cont.querySelector(".rs-an-orden").value = U.orden;

  const ruta = (limite) => {
    const p = new URLSearchParams();
    Object.entries(filtro).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
    p.set("orden", U.orden); p.set("desde", String(U.desde)); p.set("limite", String(limite)); p.set("completo", "1");
    if (U.tipo) p.set("tipo", U.tipo);
    return `/api/ads/anuncios?${p}`;
  };
  const pintarPie = (cargando) => {
    if (cargando) { pie.innerHTML = `<span class="xsmall muted"><span class="spinner spinner-s" aria-hidden="true"></span> Cargando anuncios…</span>`; return; }
    if (U.error) {
      pie.innerHTML = `<div class="notice xsmall" role="alert">${escaparHtml(U.error)}</div><button type="button" class="btn" data-an="reintentar">Reintentar</button>`;
    } else if (U.total === 0) {
      pie.innerHTML = `<span class="xsmall muted">${filtro.alcance && provincia ? `No hay anuncios que lleguen a ${escaparHtml(provincia)}${filtro.dias ? " en este período" : ""}.` : "No hay anuncios que cumplan este filtro."}</span>`;
    } else if (U.total != null && U.desde < U.total) {
      const quedan = U.total - U.desde;
      pie.innerHTML = `<button type="button" class="btn" data-an="mas">Mostrar ${fmtNum(Math.min(ANUNCIOS_POR_TANDA, quedan))} más</button>`
        + (quedan > ANUNCIOS_POR_TANDA ? `<button type="button" class="btn" data-an="todos">Mostrar todos (${fmtNum(quedan)} restantes)</button>` : "");
    } else pie.innerHTML = U.total ? `<span class="xsmall muted">Se muestran los ${fmtNum(U.total)} anuncios.</span>` : "";
  };

  /** Pide una tanda. Devuelve la respuesta, o null si falló o quedó obsoleta (otro orden, otro nodo). */
  async function pedir(limite) {
    const mio = ++U.token;
    pintarPie(true);
    try {
      const d = await fetchApi(ruta(limite), { timeout: 60000 });
      if (mio !== U.token || !cont.isConnected) return null;
      U.error = ""; U.total = d.total;
      if (!U.desde) {
        nEl.textContent = `(${fmtNum(d.total)})`;
        const r = d.resumen || {}, g = r.gasto || {}, gp = r.gasto_prorrateado;
        // Con una provincia (`alcance`) hay dos importes: el prorrateado por el % de alcance allí (el del mapa y el resumen) y el precio completo de esos anuncios.
        const inversion = gp
          ? `inversión estimada en ${provincia || "la provincia"} ${fmtUsd(gp.medio)} (prorrateada por el % de alcance) · a precio completo ${fmtUsd(g.medio)} (rango ${fmtUsd(g.min)}–${fmtUsd(g.max)})`
          : `inversión estimada ${fmtUsd(g.medio)} (rango ${fmtUsd(g.min)}–${fmtUsd(g.max)})`;
        resEl.textContent = d.total
          ? `${fmtNum(r.paginas)} ${r.paginas === 1 ? "página" : "páginas"} · ${fmtNum(r.pagadores)} ${r.pagadores === 1 ? "pagador declarado" : "pagadores declarados"} · ${fmtNum(r.activos)} ${r.activos === 1 ? "activo" : "activos"} · ${inversion}`
          : "";
        const avisos = [];
        if (d.estado && d.estado.parcial) avisos.push("Resultados parciales: Meta tenía más anuncios de los que se descargan; los totales pueden ser mayores.");
        if (d.nota) avisos.push(d.nota);
        avisoEl.textContent = d.total ? avisos.join(" ") : "";
      }
      (d.anuncios || []).forEach((a) => U.ads.set(String(a.id), a));
      lista.insertAdjacentHTML("beforeend", (d.anuncios || []).map((a) => tarjetaMeta(a, { provincia, rol: mostrarRol ? a.rol : "", descargable: true })).join(""));
      U.desde += (d.anuncios || []).length;
      if (!(d.anuncios || []).length) U.total = U.desde;     // el servidor ya no tiene más: evita pedir sin fin
      pintarPie(false);
      return d;
    } catch (e) {
      if (mio !== U.token || !cont.isConnected) return null;
      if (alFallar && !U.desde) { alFallar(e); return null; }
      U.error = /HTTP 404/.test(e.message)
        ? "Este servidor todavía no ofrece la lista completa de anuncios (falta /api/ads/anuncios). Reinicia el backend con la versión actualizada."
        : `No se pudieron cargar los anuncios (${e.message}).`;
      pintarPie(false);
      return null;
    }
  }
  async function pedirTodos() {
    while (U.total == null || U.desde < U.total) { if (!(await pedir(100))) break; }
  }
  const reiniciar = () => { U.token++; U.desde = 0; U.total = null; U.error = ""; U.ads.clear(); lista.innerHTML = ""; nEl.textContent = ""; resEl.textContent = ""; return pedir(ANUNCIOS_POR_TANDA); };

  /** Descarga en CSV todos los anuncios de esta lista (con su orden y tipo), de 100 en 100, hasta MAX_EXPORTAR_ANUNCIOS. */
  async function exportarCsv(boton) {
    const estadoEl = cont.querySelector(".rs-an-descarga"), textoBoton = boton.textContent;
    boton.disabled = true;
    const filas = [];
    let desde = 0, total = null;
    try {
      while ((total === null || desde < total) && filas.length < MAX_EXPORTAR_ANUNCIOS) {
        const p = new URLSearchParams();
        Object.entries(filtro).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
        p.set("orden", U.orden); p.set("desde", String(desde)); p.set("limite", "100"); p.set("completo", "1");
        if (U.tipo) p.set("tipo", U.tipo);
        const d = await fetchApi(`/api/ads/anuncios?${p}`, { timeout: 60000 });
        total = d.total;
        if (!(d.anuncios || []).length) break;
        filas.push(...d.anuncios);
        desde += d.anuncios.length;
        estadoEl.textContent = `Preparando… ${fmtNum(Math.min(filas.length, total))} de ${fmtNum(Math.min(total, MAX_EXPORTAR_ANUNCIOS))}`;
      }
      if (!filas.length) { estadoEl.textContent = "No hay anuncios que descargar."; return; }
      descargarCsvArchivo(`noaiverdad-anuncios-${nombreArchivoSeguro(titulo)}-${fechaHoyIso()}.csv`, CABECERA_ANUNCIO, filas.map(filaCsvAnuncio));
      estadoEl.textContent = `CSV descargado (${fmtNum(filas.length)} anuncios${total > filas.length ? ` de ${fmtNum(total)}: el tope por archivo es ${fmtNum(MAX_EXPORTAR_ANUNCIOS)}; acota con el orden, el tipo o el período` : ""}).`;
    } catch (e) {
      estadoEl.textContent = `No se pudo preparar la descarga (${e.message}).`;
    } finally {
      boton.disabled = false; boton.textContent = textoBoton;
    }
  }

  cont.addEventListener("click", (ev) => {
    const accion = ev.target.closest("[data-an]");
    if (!accion || !cont.contains(accion)) return;
    if (accion.dataset.an === "mas") pedir(ANUNCIOS_POR_TANDA);
    else if (accion.dataset.an === "todos") pedirTodos();
    else if (accion.dataset.an === "reintentar") (U.desde ? pedir(ANUNCIOS_POR_TANDA) : reiniciar());
    else if (accion.dataset.an === "csv") exportarCsv(accion);
    else if (accion.dataset.an === "uno") {
      const ad = U.ads.get(accion.dataset.adId);
      if (ad) descargarCsvArchivo(`noaiverdad-anuncio-${nombreArchivoSeguro(ad.page_name || "")}-${ad.id}.csv`, CABECERA_ANUNCIO, [filaCsvAnuncio(ad)]);
    }
  });
  cont.querySelector(".rs-an-tipo")?.addEventListener("change", (ev) => { U.tipo = ev.target.value; reiniciar(); });
  cont.querySelector(".rs-an-orden").addEventListener("change", (ev) => { U.orden = ev.target.value; reiniciar(); });
  pedir(ANUNCIOS_POR_TANDA);
}

/** Fila de /api/ads/mapa de una provincia (anuncios que llegan a ella, anunciantes, inversión prorrateada), o null si aún no se cargó. */
function cifrasDeProvincia(nombre) {
  const filas = (state.mapaDatos && state.mapaDatos.provincias) || [];
  return filas.find((f) => normalizar(f.provincia) === normalizar(nombre)) || null;
}

/** Enlaces del detalle de una provincia hacia el resto de la app: su prensa y verificaciones (Mapa) y, desde el alcance nacional, enfocar solo esa provincia. */
function crucesDeProvincia(prov, nacional) {
  const fila = document.createElement("div");
  fila.className = "rs-cruces";
  const boton = (texto, alClic) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn btn-ghost"; b.textContent = texto;
    b.addEventListener("click", alClic);
    return b;
  };
  fila.append(boton(`Prensa y verificaciones de ${prov.nombre} →`, () => navegar({ vista: "mapa", provincia: prov.id, seccion: "noticias" })));
  if (nacional) fila.append(boton(`Ver solo ${prov.nombre}`, () => navegar({ vista: "resumen", alcance: prov.id })));
  return fila;
}

/** Botones excluyentes (aria-pressed) para elegir qué lista de anuncios mostrar; el primero empieza activo. */
function selectorDeListas(opciones) {
  const seg = document.createElement("div");
  seg.className = "segmented rs-seg";
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", "Qué anuncios mostrar");
  const botones = opciones.map(({ texto, montar }, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = texto; b.setAttribute("aria-pressed", String(i === 0));
    b.addEventListener("click", () => {
      if (b.getAttribute("aria-pressed") === "true") return;
      botones.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      montar();
    });
    return b;
  });
  seg.append(...botones);
  return seg;
}

/** Detalle de un nodo de la red en el panel derecho: su resumen y, debajo, TODOS sus anuncios. */
function mostrarDetalleNodo(n, vs) {
  const panel = $("red-detalle");
  const alcance = state.resumen.alcance, sel = $("resumen-alcance");
  const nombreAlcance = alcance && alcance !== "todas" && sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "";
  const nacional = !alcance || alcance === "todas";
  const prov = n.tipo === "provincia" ? provinciaPorNombre(n.nombre) : null;
  // «Llegan aquí» solo donde el número del mapa es el mismo universo: con alcance nacional, o en la propia provincia del alcance.
  const llegan = prov && (nacional || prov.id === alcance) ? cifrasDeProvincia(n.nombre) : null;
  panel.innerHTML = n.tipo === "provincia" ? htmlDetalleHub(n, vs, llegan) : htmlDetalle(n, vs);
  if (prov) panel.appendChild(crucesDeProvincia(prov, nacional));
  const caja = document.createElement("section");
  caja.className = "rs-anuncios";
  if (n.tipo === "provincia") {
    const listaBase = () => montarListaAnuncios(caja, { alcance, region: n.nombre }, { titulo: `Anuncios de páginas con base en ${n.nombre}`, provincia: n.nombre,
      nota: n.anuncios_total == null
        ? `Anuncios de las páginas cuya provincia principal es ${n.nombre}. La red dibuja solo las páginas con más inversión, así que aquí puede haber más que en el gráfico.`
        : (n.paginas_total > n.paginas
          ? `El gráfico dibuja las ${fmtNum(n.paginas)} páginas de mayor inversión; esta lista incluye las ${fmtNum(n.paginas_total)}.`
          : `Anuncios de las ${fmtNum(n.paginas_total)} páginas cuya provincia principal es ${n.nombre}; todas están en el gráfico.`) });
    const listaLlegan = () => montarListaAnuncios(caja, { alcance: n.nombre }, { titulo: `Anuncios que llegan a ${n.nombre}`, provincia: n.nombre, ordenInicial: "impresiones" });
    if (llegan && n.anuncios_total != null) {
      panel.appendChild(selectorDeListas([
        { texto: `Con base aquí (${fmtNum(n.anuncios_total)})`, montar: listaBase },
        { texto: `Llegan aquí (${fmtNum(llegan.anuncios)})`, montar: listaLlegan }]));
    }
    panel.appendChild(caja);
    listaBase();
    abrirDerecho("detalle");
    return;
  }
  panel.appendChild(caja);
  if (n.tipo === "pagador") {
    montarListaAnuncios(caja, { alcance, pagador: n.nombre, solo_terceros: "true" }, { titulo: "Todos los anuncios que paga", provincia: nombreAlcance });
  } else {
    montarListaAnuncios(caja, { alcance, pagina: n.nombre }, { titulo: "Todos los anuncios de la página", provincia: nombreAlcance });
  }
  abrirDerecho("detalle");
}

// --- Dos anuncios lado a lado: el panel que abre una línea de texto repetido de la red ---------------------------------------------------------
const fechaMs = (s) => { const t = Date.parse(String(s || "").slice(0, 10)); return Number.isNaN(t) ? null : t; };

/** El par de anuncios (uno de cada página) publicados más cerca en el tiempo; a igualdad, el más antiguo. */
function parMasCercano(anuncios, a, b) {
  const deA = anuncios.filter((v) => v.page_name === a), deB = anuncios.filter((v) => v.page_name === b);
  let mejor = null;
  for (const x of deA) for (const y of deB) {
    const fx = fechaMs(x.fecha), fy = fechaMs(y.fecha), d = fx != null && fy != null ? Math.abs(fx - fy) : Infinity, s = (fx || 0) + (fy || 0);
    if (!mejor || d < mejor.d || (d === mejor.d && s < mejor.s)) mejor = { x, y, d, s };
  }
  return mejor;
}

/**
 * Marca en cada texto las palabras que no están en el otro (subsecuencia común más larga, sin mayúsculas ni signos). Conserva los saltos de línea.
 * Devuelve el HTML de los dos textos; con textos muy largos no marca nada.
 */
function resaltarDiferencias(ta, tb) {
  const A = String(ta || "").split(/(\s+)/), B = String(tb || "").split(/(\s+)/);
  const palabras = (T) => T.map((t, i) => (/^\s*$/.test(t) ? -1 : i)).filter((i) => i >= 0);
  const ia = palabras(A), ib = palabras(B);
  if (ia.length > 450 || ib.length > 450) return [escaparHtml(ta), escaparHtml(tb)];
  const clave = (w) => _normBusqueda(w).replace(/[^a-z0-9]+/g, "") || w;
  const ka = ia.map((i) => clave(A[i])), kb = ib.map((i) => clave(B[i])), n = ka.length, m = kb.length;
  const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = ka[i] === kb[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const cambiaA = new Set(), cambiaB = new Set();
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (ka[i] === kb[j]) { i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) cambiaA.add(i++); else cambiaB.add(j++);
  }
  while (i < n) cambiaA.add(i++);
  while (j < m) cambiaB.add(j++);
  const pintar = (T, idx, cambia) => {
    const lugar = new Map(idx.map((p, k) => [p, k]));
    return T.map((t, p) => (lugar.has(p) && cambia.has(lugar.get(p)) ? `<mark class="dif">${escaparHtml(t)}</mark>` : escaparHtml(t))).join("");
  };
  return [pintar(A, ia, cambiaA), pintar(B, ib, cambiaB)];
}

/** Una columna del lado a lado: la página, su anuncio completo y SU enlace a la Biblioteca de Meta. */
function columnaAnuncio(x, htmlTexto, afil) {
  const fin = x.fecha_fin ? ` · fin ${escaparHtml(formatearFechaSafe(x.fecha_fin))}` : "";
  return `
    <div class="par-col">
      <div class="par-cab"><strong>${escaparHtml(x.page_name)}</strong>${badgeAfil(afil)}<span class="tag ${x.activo ? "tag-info" : ""}">${x.activo ? "Activo" : "Finalizado"}</span></div>
      <div class="par-fecha">Desde ${escaparHtml(formatearFechaSafe(x.fecha))}${fin}</div>
      <div class="par-texto">${htmlTexto || "<em>(Anuncio sin texto)</em>"}</div>
      <dl class="facts">
        <div class="wide"><dt>Pagado por</dt><dd>${escaparHtml(x.financiador) || "No declarado"}</dd></div>
        <div><dt>Inversión (rango)</dt><dd>${escaparHtml(formatearRango(x.gasto, x.moneda))}</dd></div>
        <div><dt>Impresiones (rango)</dt><dd>${escaparHtml(formatearRango(x.impresiones))}</dd></div>
      </dl>
      ${enlace(x.link, "Ver este anuncio en la Biblioteca de Meta ↗", "btn par-enlace")}
    </div>`;
}

/** Un mensaje repetido entre las páginas `a` y `b`: sus dos anuncios publicados más cerca en el tiempo, lado a lado, y el resto con su enlace. */
function htmlMensajePar(g, i, total, a, b) {
  const det = g.detalle, par = parMasCercano(det.anuncios, a, b);
  const afil = (nombre) => (g.paginas.find((p) => p.page_name === nombre) || {}).afiliacion || null;
  const parecido = g.n_textos > 1 ? `${g.n_textos} variantes · similitud ≥ ${Math.round(g.similitud_minima * 100)} %` : "texto idéntico";
  const rev = esGrupoRevisado(g) ? `<span class="tag tag-ok" title="${escaparHtml(g.revision.motivo_texto)}${g.revision.nota ? `: ${escaparHtml(g.revision.nota)}` : ""}">Revisado</span>` : "";
  const cab = `<div class="group-meta"><strong>Mensaje ${i + 1} de ${total}</strong><span>${fmtNum(g.anuncios)} anuncios en ${g.n_paginas} páginas</span><span>${escaparHtml(parecido)}</span>${rev}</div>`;
  if (!par) return `<article class="group${rev ? " revisado" : ""}">${cab}<div class="group-text">“${escaparHtml(g.texto)}”</div></article>`;
  const ta = det.textos[par.x.t] || "", tb = det.textos[par.y.t] || "";
  const [ha, hb] = ta === tb ? [escaparHtml(ta), escaparHtml(tb)] : resaltarDiferencias(ta, tb);
  const dias = Math.round(par.d / 86400000);
  const distancia = par.d === Infinity ? "" : par.d === 0 ? "Los dos anuncios empezaron el mismo día." : `Los dos anuncios empezaron con ${dias} día${dias === 1 ? "" : "s"} de diferencia.`;
  const nota = ta === tb ? "Texto idéntico en los dos anuncios." : "Las palabras marcadas son las que cambian de un anuncio al otro.";
  const otros = det.anuncios.filter((v) => v !== par.x && v !== par.y), porPagina = new Map();
  otros.forEach((v) => { if (!porPagina.has(v.page_name)) porPagina.set(v.page_name, []); porPagina.get(v.page_name).push(v); });
  const enlaceFecha = (v) => enlace(v.link, `${formatearFechaSafe(v.fecha)} ↗`) || escaparHtml(formatearFechaSafe(v.fecha));
  const masAnuncios = otros.length || det.omitidos ? `
    <details class="par-otros">
      <summary>${otros.length ? `${fmtNum(otros.length)} anuncio${otros.length === 1 ? "" : "s"} más con este mensaje, cada uno con su enlace` : "Más anuncios con este mensaje"}</summary>
      ${[...porPagina].map(([pagina, lista]) => `<div><strong>${escaparHtml(pagina)}</strong>: ${lista.map(enlaceFecha).join(" · ")}</div>`).join("")}
      ${det.omitidos ? `<div class="muted">y ${fmtNum(det.omitidos)} más que no se listan aquí (están en la Biblioteca de Meta).</div>` : ""}
    </details>` : "";
  return `
    <article class="group${rev ? " revisado" : ""}">
      ${cab}
      <div class="par-anuncios">${columnaAnuncio(par.x, ha, afil(par.x.page_name))}${columnaAnuncio(par.y, hb, afil(par.y.page_name))}</div>
      <div class="par-distancia">${[distancia, nota].filter(Boolean).join(" ")}</div>
      ${masAnuncios}
    </article>`;
}

/** «También en: …»: las demás páginas del grupo de una línea pulsada (las que repiten el mismo texto o enlace y quedan encendidas en la red). */
function htmlGrupoDeLinea(e, que) {
  const otras = (e.grupo || []).filter((n) => n !== e.a.nombre && n !== e.b.nombre);
  if (!otras.length) return "";
  return `<div class="xsmall muted" style="margin:4px 0 10px">${que} también en ${fmtNum(otras.length)} ${otras.length === 1 ? "página más" : "páginas más"} (encendidas en la red): ${otras.slice(0, 12).map(escaparHtml).join(", ")}${otras.length > 12 ? "…" : ""}</div>`;
}

/** Detalle de una línea de partido de la red: equivale a filtrar por ese partido; lista sus páginas a la vista con su inversión. */
function mostrarDetallePartido(e) {
  pedidoTextoDeLinea++;
  const m = (e.miembros || []).filter((n) => n.tipo !== "provincia").sort((x, y) => ((y.gasto || {}).medio || 0) - ((x.gasto || {}).medio || 0));
  const provs = (e.miembros || []).filter((n) => n.tipo === "provincia").length;
  const total = m.reduce((s, n) => s + ((n.gasto || {}).medio || 0), 0), anuncios = m.reduce((s, n) => s + (n.anuncios || 0), 0);
  const color = coloresPartido.get(e.partido) || "#a855f7";
  $("red-detalle").innerHTML = `
    <div><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${escaparHtml(color)};margin-right:6px"></span><strong>${escaparHtml(e.partido || "Partido")}</strong> · partido</div>
    <div class="muted" style="margin:4px 0 10px">${fmtNum(m.length)} ${m.length === 1 ? "página o pagador" : "páginas o pagadores"} en la red${provs > 1 ? ` · ${fmtNum(provs)} provincias` : ""} · ${fmtNum(anuncios)} anuncios · inversión estimada ${escaparHtml(fmtUsd(total))}</div>
    ${m.map((n) => `<div style="display:flex;justify-content:space-between;gap:10px;margin:4px 0"><span>${escaparHtml(n.nombre)}${n.afiliacion_estado === "pendiente" ? ` <span class="muted xsmall">(sin verificar)</span>` : ""}</span><span class="muted" style="white-space:nowrap">${escaparHtml(fmtUsd((n.gasto || {}).medio || 0))}</span></div>`).join("")}
    <p class="xsmall muted" style="margin-top:12px">La red deja encendidas solo las páginas registradas con este partido y atenúa el resto, como al filtrar por él; la ventana <strong>Resumen</strong> también se limita a ellas. Para quitar las demás del resto de listas, usa la lista <strong>Partido</strong> del panel Filtros. Pulsa el fondo para volver a ver todo.</p>`;
  abrirDerecho("detalle");
}

/** El texto de un anuncio con el enlace compartido resaltado (el mismo enlace exacto, o cualquiera del dominio si se compara por dominio). */
function resaltarEnlace(texto, g) {
  const dominio = g.por_dominio ? g.clave : "", urls = new Set(g.urls || []);
  return String(texto || "").split(/(https?:\/\/[^\s)\]>"']+)/i).map((t, k) => {
    if (k % 2 === 0) return escaparHtml(t);
    const limpia = t.replace(/[.,;:!?]+$/, ""), host = (limpia.match(/^https?:\/\/(?:www\.)?([^/?#]+)/i) || [])[1] || "";
    const es = urls.has(limpia) || (dominio && host.toLowerCase() === dominio) || (!dominio && limpia.toLowerCase().includes(g.clave.split("?")[0].toLowerCase()));
    return es ? `<mark class="dif">${escaparHtml(t)}</mark>` : escaparHtml(t);
  }).join("");
}

/** Un enlace compartido entre las páginas `a` y `b`: sus dos anuncios publicados más cerca en el tiempo, lado a lado, y el resto con su enlace. */
function htmlEnlacePar(g, i, total, a, b) {
  const det = g.detalle, par = parMasCercano(det.anuncios, a, b);
  const afil = (nombre) => (g.paginas.find((p) => p.page_name === nombre) || {}).afiliacion || null;
  const como = g.por_dominio ? (g.n_urls > 1 ? `mismo sitio · ${fmtNum(g.n_urls)} direcciones distintas` : "mismo sitio") : "la misma dirección";
  const cab = `<div class="group-meta"><strong>Enlace ${i + 1} de ${total}</strong><span>${fmtNum(g.anuncios)} anuncios de estas dos páginas</span><span>${escaparHtml(como)}</span></div>
    <div class="group-text" style="overflow-wrap:anywhere"><code>${escaparHtml(g.clave)}</code></div>`;
  const tambien = (g.otras_paginas || []).length ? `<div class="xsmall muted" style="margin-top:6px">También lo usan: ${g.otras_paginas.map(escaparHtml).join(", ")}</div>` : "";
  if (!par) return `<article class="group">${cab}${tambien}</article>`;
  const dias = Math.round(par.d / 86400000);
  const distancia = par.d === Infinity ? "" : par.d === 0 ? "Los dos anuncios empezaron el mismo día." : `Los dos anuncios empezaron con ${dias} día${dias === 1 ? "" : "s"} de diferencia.`;
  const nota = g.por_dominio ? "El enlace marcado lleva al mismo sitio; la dirección exacta puede ser distinta en cada anuncio." : "El enlace marcado es el mismo en los dos anuncios.";
  const otros = det.anuncios.filter((v) => v !== par.x && v !== par.y), porPagina = new Map();
  otros.forEach((v) => { if (!porPagina.has(v.page_name)) porPagina.set(v.page_name, []); porPagina.get(v.page_name).push(v); });
  const enlaceFecha = (v) => enlace(v.link, `${formatearFechaSafe(v.fecha)} ↗`) || escaparHtml(formatearFechaSafe(v.fecha));
  const masAnuncios = otros.length || det.omitidos ? `
    <details class="par-otros">
      <summary>${otros.length ? `${fmtNum(otros.length)} anuncio${otros.length === 1 ? "" : "s"} más con este enlace, cada uno con su enlace a Meta` : "Más anuncios con este enlace"}</summary>
      ${[...porPagina].map(([pagina, lista]) => `<div><strong>${escaparHtml(pagina)}</strong>: ${lista.map(enlaceFecha).join(" · ")}</div>`).join("")}
      ${det.omitidos ? `<div class="muted">y ${fmtNum(det.omitidos)} más que no se listan aquí (están en la Biblioteca de Meta).</div>` : ""}
    </details>` : "";
  return `
    <article class="group">
      ${cab}
      <div class="par-anuncios">${columnaAnuncio(par.x, resaltarEnlace(det.textos[par.x.t], g), afil(par.x.page_name))}${columnaAnuncio(par.y, resaltarEnlace(det.textos[par.y.t], g), afil(par.y.page_name))}</div>
      <div class="par-distancia">${[distancia, nota].filter(Boolean).join(" ")}</div>
      ${tambien}
      ${masAnuncios}
    </article>`;
}

/** Detalle de una línea de «mismo enlace» de la red: TODOS los enlaces que comparten sus dos páginas, cada uno con sus dos anuncios lado a lado. */
async function mostrarDetalleEnlace(e) {
  const panel = $("red-detalle"), R = state.resumen, a = e.a.nombre, b = e.b.nombre, pedido = ++pedidoTextoDeLinea;   // si había otra comparación cargándose, ya no debe pintarse
  const cab = `<strong>Mismo enlace</strong> · ${escaparHtml(a)} ↔ ${escaparHtml(b)}`;
  const aviso = `<p class="xsmall muted" style="margin-top:12px">Un indicador, no una prueba: dos páginas pueden enlazar al mismo sitio por pertenecer a la misma organización o campaña, o por compartir una noticia o un formulario público.</p>`;
  panel.innerHTML = `${cab}<br><span class="muted">Buscando los anuncios…</span>`;
  abrirDerecho("detalle");
  let d = null;
  try {
    d = await fetchApi(`/api/ads/enlaces/par?pagina_a=${encodeURIComponent(a)}&pagina_b=${encodeURIComponent(b)}&provincia=${encodeURIComponent(R.alcance)}`, { timeout: 60000 });
  } catch (err) { d = null; }
  if (pedido !== pedidoTextoDeLinea || R.der !== "detalle") return;    // mientras tanto se pulsó otra cosa
  if (!d || !Array.isArray(d.grupos)) {
    const urls = e.detalles || [];
    panel.innerHTML = `<div>${cab}</div>${urls.map((u) => `<div style="margin:6px 0;overflow-wrap:anywhere">· <code>${escaparHtml(u)}</code></div>`).join("")}
      ${htmlGrupoDeLinea(e, "Aparece")}<span class="muted">No se pudo cargar la comparación de anuncios.</span>${aviso}`;
    return;
  }
  const grupos = d.grupos.filter((g) => g.detalle);
  const anuncios = grupos.reduce((s, g) => s + g.anuncios, 0);
  const fechas = grupos.flatMap((g) => [g.primer_anuncio, g.ultimo_anuncio]).filter(Boolean).sort();
  const plural = (n, uno, varios) => `${fmtNum(n)} ${n === 1 ? uno : varios}`;
  panel.innerHTML = `
    <div>${cab}</div>
    ${htmlGrupoDeLinea(e, "Alguno de estos enlaces aparece")}
    <div class="muted" style="margin:4px 0 12px">${plural(grupos.length, "enlace compartido", "enlaces compartidos")} · ${plural(anuncios, "anuncio", "anuncios")}${fechas.length ? ` · del ${escaparHtml(formatearFechaSafe(fechas[0]))} al ${escaparHtml(formatearFechaSafe(fechas[fechas.length - 1]))}` : ""}</div>
    ${grupos.length ? grupos.map((g, i) => htmlEnlacePar(g, i, grupos.length, a, b)).join("") : `<p class="muted">Esta línea no tiene enlaces compartidos con los filtros actuales.</p>`}
    ${aviso}`;
}

let pedidoTextoDeLinea = 0;
/** Detalle de una línea de texto repetido de la red: TODOS los mensajes duplicados entre sus dos páginas, cada uno con sus dos anuncios lado a lado. */
async function mostrarDetalleTexto(e) {
  const panel = $("red-detalle"), R = state.resumen, a = e.a.nombre, b = e.b.nombre, pedido = ++pedidoTextoDeLinea;
  const cab = `<strong>Texto repetido</strong> · ${escaparHtml(a)} ↔ ${escaparHtml(b)}`;
  panel.innerHTML = `${cab}<br><span class="muted">Buscando los anuncios…</span>`;
  abrirDerecho("detalle");
  let d = null;
  try {
    d = await fetchApi(`/api/ads/textos-duplicados/par?pagina_a=${encodeURIComponent(a)}&pagina_b=${encodeURIComponent(b)}&provincia=${encodeURIComponent(R.alcance)}`, { timeout: 60000 });
  } catch (err) { d = null; }
  if (pedido !== pedidoTextoDeLinea || R.der !== "detalle") return;    // mientras tanto se pulsó otra cosa
  if (!d || !Array.isArray(d.grupos)) {
    panel.innerHTML = `${cab}<br>${(e.detalles || []).map((t) => `· <em>«${escaparHtml(t)}…»</em>`).join("<br>")}<br><span class="muted">No se pudo cargar la comparación de anuncios.</span>`;
    return;
  }
  const grupos = d.grupos.filter((g) => g.detalle)
    .sort((x, y) => Number(esGrupoRevisado(x)) - Number(esGrupoRevisado(y)) || y.anuncios - x.anuncios);       // primero los que cuentan como señal
  const anuncios = grupos.reduce((s, g) => s + g.anuncios, 0), revisados = grupos.filter(esGrupoRevisado).length;
  const fechas = grupos.flatMap((g) => [g.primer_anuncio, g.ultimo_anuncio]).filter(Boolean).sort();
  const plural = (n, uno, varios) => `${fmtNum(n)} ${n === 1 ? uno : varios}`;
  panel.innerHTML = `
    <div>${cab}</div>
    ${htmlGrupoDeLinea(e, "Alguno de estos textos se repite")}
    <div class="muted" style="margin:4px 0 12px">${plural(grupos.length, "mensaje duplicado", "mensajes duplicados")} · ${plural(anuncios, "anuncio", "anuncios")}${fechas.length ? ` · del ${escaparHtml(formatearFechaSafe(fechas[0]))} al ${escaparHtml(formatearFechaSafe(fechas[fechas.length - 1]))}` : ""}${revisados ? ` · ${plural(revisados, "ya revisado", "ya revisados")}` : ""}</div>
    ${grupos.length ? grupos.map((g, i) => htmlMensajePar(g, i, grupos.length, a, b)).join("") : `<p class="muted">Esta línea no tiene mensajes en la lista actual.</p>`}
    <p class="xsmall muted" style="margin-top:12px">Un indicador, no una prueba: dos páginas pueden repetir un mensaje por ser la misma persona u organización, un partido y sus candidatos, o un gobierno y los medios que lo difunden.</p>
    <div class="group-acciones"><button type="button" class="btn" id="texto-ver-todos">Ver todos los mensajes repetidos</button></div>`;
  $("texto-ver-todos").addEventListener("click", () => { activarTab("mensajes"); escribirHash(); });
}

function tarjetaVideo(v) {
  return `
    <article class="item" data-fuente="youtube">
      <div class="item-top"><span class="item-source">${escaparHtml(v.canal || v.fuente || "YouTube")}</span><span class="item-date">${escaparHtml(formatearFechaSafe(v.fecha))}</span></div>
      <h4 class="item-title">${escaparHtml(v.titulo)}</h4>
      <div class="item-foot">${enlace(v.url, "Ver en YouTube")}</div>
    </article>`;
}

function tarjetaReddit(p) {
  const texto = String(p.text || "");
  const resumen = texto.length > 280 ? texto.slice(0, 280) + "…" : texto;
  return `
    <article class="item" data-fuente="reddit">
      <div class="item-top"><span class="item-source">${escaparHtml(p.fuente || "Reddit")}</span><span class="item-date">${escaparHtml(formatearFechaSafe(p.fecha))}</span></div>
      <h4 class="item-title">${escaparHtml(p.titulo)}</h4>
      ${resumen ? `<div class="item-text">${escaparHtml(resumen)}</div>` : ""}
      <div class="item-foot">${enlace(p.url, "Ver en Reddit")}</div>
    </article>`;
}

function renderizarFeed() {
  const contenedor = $("sidebar-content");
  contenedor.removeAttribute("aria-busy");
  if (!state.datos) return;

  const { provincia, seccion, data } = state.datos;
  const campo = CAMPO_SECCION[seccion];
  const crudos = data[campo] || [];
  const estado = (data.estados && data.estados[seccion]) || data.meta_estado || null;
  const items = crudos.filter((it) => dentroDelPeriodo(it, seccion));
  const nombre = SECCIONES[seccion];

  if (data.error) {
    contenedor.innerHTML = cajaEstado({ tipo: "error", titulo: "El servidor reportó un problema", descripcion: escaparHtml(data.mensaje || "Inténtalo de nuevo."), boton: { accion: "reintentar", texto: "Reintentar" } });
    return;
  }

  if (!items.length) {
    if (seccion === "tweets" && estado && estado.configurado === false) {
      contenedor.innerHTML = cajaEstado({ tipo: "info", titulo: "X estará disponible pronto", descripcion: "La API oficial de X es de pago. La integración está lista y se activará cuando haya financiamiento. Mientras tanto, puedes ver Bluesky." });
    } else if (crudos.length) {
      contenedor.innerHTML = cajaEstado({ tipo: "info", titulo: "Hay resultados fuera del período elegido", descripcion: `Se encontraron <strong>${crudos.length}</strong> resultado(s) para ${escaparHtml(provincia)}, pero ninguno cae en «${escaparHtml(PERIODOS[state.periodo])}».`, boton: { accion: "quitar-periodo", texto: "Mostrar todo el período" } });
    } else if (estado && estado.habilitado === false) {
      contenedor.innerHTML = cajaEstado({ tipo: "info", titulo: `${nombre}: desactivado en este servidor`, descripcion: escaparHtml(estado.mensaje || "") });
    } else if (estado && estado.configurado === false) {
      contenedor.innerHTML = cajaEstado({ tipo: "info", titulo: `${nombre}: fuente no configurada`, descripcion: escaparHtml(estado.mensaje || "") });
    } else if (estado && estado.ok === false) {
      contenedor.innerHTML = cajaEstado({ tipo: "error", titulo: `${nombre}: la fuente no respondió`, descripcion: escaparHtml(estado.mensaje || "Inténtalo de nuevo más tarde."), boton: { accion: "reintentar", texto: "Reintentar" } });
    } else {
      const extra = seccion === "meta_ads" && estado && estado.total_nacional != null ? ` Hay ${fmtNum(estado.total_nacional)} anuncios políticos a nivel nacional en el período consultado.` : "";
      contenedor.innerHTML = cajaEstado({ tipo: "info", titulo: `${nombre}: sin resultados`, descripcion: escaparHtml((estado && estado.mensaje) || `No se encontraron resultados para ${provincia}.`) + escaparHtml(extra) });
    }
    return;
  }

  const parcialMeta = seccion === "meta_ads" && estado && estado.parcial ? "Resultados parciales: Meta tenía más anuncios de los que se descargan; los totales pueden ser mayores. " : "";
  const estimacion = seccion === "meta_ads" ? "Los montos son estimaciones a partir de rangos publicados por Meta, no cifras exactas. " : "";
  const aviso = (estado && estado.aviso) || parcialMeta || estimacion ? `<div class="notice info" role="note">${escaparHtml(parcialMeta + estimacion + ((estado && estado.aviso) || ""))}</div>` : "";
  const ocultos = crudos.length - items.length;
  const filtrados = ocultos > 0 ? `<div class="notice info" role="note">${ocultos} resultado(s) ocultos por el período «${escaparHtml(PERIODOS[state.periodo])}». <button type="button" class="link-btn" data-accion="quitar-periodo">Mostrar todo</button></div>` : "";

  let titulo = `${nombre} · ${items.length}`;
  let derecha = "";
  let tarjetas = "";
  if (seccion === "noticias" || seccion === "prensa_local") tarjetas = items.map(tarjetaNoticia).join("");
  else if (seccion === "verificaciones") tarjetas = items.map(tarjetaVerificacion).join("");
  else if (seccion === "tweets") tarjetas = items.map((p) => tarjetaRedSocial(p, "tweets", "X")).join("");
  else if (seccion === "bluesky") tarjetas = items.map((p) => tarjetaRedSocial(p, "bluesky", "Bluesky")).join("");
  else if (seccion === "youtube") tarjetas = items.map(tarjetaVideo).join("");
  else if (seccion === "reddit") tarjetas = items.map(tarjetaReddit).join("");
  else if (seccion === "meta_ads") {
    const total = estado && estado.total_provincia != null ? estado.total_provincia : items.length;
    titulo = `${nombre}: ${items.length} de ${fmtNum(total)}`;
    derecha = "ordenados por impresiones";
  }
  if (seccion === "meta_ads") tarjetas = items.map(tarjetaMeta).join("");

  contenedor.innerHTML = `${aviso}${filtrados}<div class="list-head"><h3>${escaparHtml(titulo)}</h3><span class="xsmall muted">${escaparHtml(derecha)}</span></div>${tarjetas}`;
  contenedor.scrollTop = 0;
}

// ---------------------------------------------------------------------------
// Vista Conexiones (ruta #/resumen)
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Panel derecho de Conexiones: tamaño ajustable y red centrada en lo seleccionado
// ---------------------------------------------------------------------------
// Un asa en su borde cambia su ancho (borde izquierdo, a partir de 641 px) o su alto (en móviles es una hoja que sube desde abajo, con el asa arriba).
// El tamaño se guarda en este equipo. Cuando algo se selecciona o el panel cambia de tamaño, la red recentra lo seleccionado en la parte que el panel no tapa.
const PANEL_DER = { anchoMin: 300, altoMin: 150, claveAncho: "noai_rs_der_ancho", claveAlto: "noai_rs_der_alto" };
const panelEsHoja = () => !!(window.matchMedia && window.matchMedia("(max-width: 640px)").matches);
const leerTamanoPanel = (clave) => { try { const v = Number(localStorage.getItem(clave)); return v > 0 ? v : null; } catch (e) { return null; } };
const guardarTamanoPanel = (clave, v) => { try { if (v == null) localStorage.removeItem(clave); else localStorage.setItem(clave, String(Math.round(v))); } catch (e) { /* sin almacenamiento */ } };

/** Menor y mayor tamaño que puede tener el panel con el espacio que hay (alto de la hoja en móviles; ancho en el resto). */
function limitesPanelDer() {
  const sec = $("view-resumen"), ancho = sec.clientWidth || window.innerWidth, alto = sec.clientHeight || window.innerHeight;      // con la vista oculta no hay medidas: se usa la ventana
  if (panelEsHoja()) return { min: PANEL_DER.altoMin, max: Math.max(PANEL_DER.altoMin, Math.round(alto * 0.92)) };
  return { min: PANEL_DER.anchoMin, max: Math.max(PANEL_DER.anchoMin, Math.min(ancho - 200, 1000)) };      // siempre quedan ≥ 200 px de red a la vista
}

/** Pone el tamaño guardado (acotado a lo que cabe ahora) en las variables CSS que leen el panel y los controles del lienzo. */
function aplicarTamanoPanelDer() {
  const sec = $("view-resumen"), hoja = panelEsHoja(), lim = limitesPanelDer();
  for (const [prop, clave] of [["--rs-der-w", PANEL_DER.claveAncho], ["--rs-der-h", PANEL_DER.claveAlto]]) {
    const v = leerTamanoPanel(clave), esta = (prop === "--rs-der-h") === hoja;
    if (v && esta) sec.style.setProperty(prop, Math.min(lim.max, Math.max(lim.min, v)) + "px");
    else if (!v) sec.style.removeProperty(prop);
    else sec.style.setProperty(prop, v + "px");               // el tamaño de la otra disposición (se acota cuando esa se use)
  }
  actualizarAriaAsa();
}

function actualizarAriaAsa() {
  const asa = $("rs-der-asa"), panel = $("rs-der");
  if (!asa || !panel) return;
  const hoja = panelEsHoja(), lim = limitesPanelDer();
  asa.setAttribute("aria-orientation", hoja ? "horizontal" : "vertical");
  asa.setAttribute("aria-valuemin", String(lim.min)); asa.setAttribute("aria-valuemax", String(lim.max));
  asa.setAttribute("aria-valuenow", String(Math.round(hoja ? panel.offsetHeight : panel.offsetWidth)));
}

/** Lo que tapan los paneles abiertos y la barra de arriba sobre el lienzo de la red, en px: { izq, der, arriba, abajo }. Cuenta el tamaño final del panel aunque aún se esté deslizando. */
function zonaCubiertaRed() {
  const lienzo = $("red-lienzo"), z = { izq: 0, der: 0, arriba: 0, abajo: 0 };
  if (!lienzo) return z;
  const c = lienzo.getBoundingClientRect(), acota = (v, max) => Math.max(0, Math.min(max, v));
  const izq = $("rs-izq"), der = $("rs-der"), barra = $("resumen-tabs");
  if (izq && izq.classList.contains("abierto")) z.izq = acota(izq.offsetWidth, c.width * 0.8);
  if (der && der.classList.contains("abierto")) {
    if (panelEsHoja()) z.abajo = acota(der.offsetHeight, c.height * 0.92); else z.der = acota(der.offsetWidth, c.width * 0.8);
  }
  if (barra) z.arriba = acota(barra.getBoundingClientRect().bottom - c.top, c.height / 2);
  return z;
}

/** Vuelve a centrar lo seleccionado en la zona libre (tras cambiar el tamaño del panel o la orientación de la pantalla). */
function recentrarSeleccionRed() { if (redOrbital) redOrbital.centrarSeleccion(); }

function initAsaPanelDerecho() {
  const asa = $("rs-der-asa"), sec = $("view-resumen"), panel = $("rs-der");
  if (!asa || !sec || !panel) return;
  let arrastre = null;
  const fijar = (px, guardar) => {
    const hoja = panelEsHoja(), lim = limitesPanelDer(), v = Math.min(lim.max, Math.max(lim.min, px));
    sec.style.setProperty(hoja ? "--rs-der-h" : "--rs-der-w", v + "px");
    actualizarAriaAsa();
    if (guardar) guardarTamanoPanel(hoja ? PANEL_DER.claveAlto : PANEL_DER.claveAncho, v);
  };
  asa.addEventListener("pointerdown", (ev) => {
    if (ev.button > 0) return;
    ev.preventDefault();                                                 // sin selección de texto ni arrastre de la página
    arrastre = { id: ev.pointerId, hoja: panelEsHoja(), r: sec.getBoundingClientRect() };
    try { asa.setPointerCapture(ev.pointerId); } catch (e) { /* sin captura: el arrastre sigue mientras el puntero esté encima */ }
    asa.classList.add("activa"); sec.classList.add("rs-ajustando");
  });
  asa.addEventListener("pointermove", (ev) => {
    if (!arrastre || ev.pointerId !== arrastre.id) return;
    fijar(arrastre.hoja ? arrastre.r.bottom - ev.clientY : arrastre.r.right - ev.clientX, false);       // el panel está pegado al borde derecho (o al inferior)
  });
  const soltar = (ev) => {
    if (!arrastre || ev.pointerId !== arrastre.id) return;
    arrastre = null; asa.classList.remove("activa"); sec.classList.remove("rs-ajustando");
    fijar(panelEsHoja() ? panel.offsetHeight : panel.offsetWidth, true);
    recentrarSeleccionRed();
  };
  asa.addEventListener("pointerup", soltar); asa.addEventListener("pointercancel", soltar);
  asa.addEventListener("keydown", (ev) => {                              // con teclado: flechas (Mayús: más), Inicio y Fin
    const hoja = panelEsHoja(), lim = limitesPanelDer(), actual = hoja ? panel.offsetHeight : panel.offsetWidth, paso = ev.shiftKey ? 96 : 24;
    const crece = hoja ? "ArrowUp" : "ArrowLeft", decrece = hoja ? "ArrowDown" : "ArrowRight";
    let nuevo = null;
    if (ev.key === crece) nuevo = actual + paso; else if (ev.key === decrece) nuevo = actual - paso;
    else if (ev.key === "Home") nuevo = lim.min; else if (ev.key === "End") nuevo = lim.max;
    if (nuevo == null) return;
    ev.preventDefault(); fijar(nuevo, true); recentrarSeleccionRed();
  });
  asa.addEventListener("dblclick", () => {                               // doble clic: vuelve al tamaño original
    guardarTamanoPanel(PANEL_DER.claveAncho, null); guardarTamanoPanel(PANEL_DER.claveAlto, null);
    sec.style.removeProperty("--rs-der-w"); sec.style.removeProperty("--rs-der-h");
    actualizarAriaAsa(); recentrarSeleccionRed();
  });
  // al girar el iPad o cambiar la ventana, el tamaño guardado se acota a lo que cabe y lo seleccionado se vuelve a centrar. Solo si cambió el ancho: en el iPhone
  // la barra de direcciones que sube y baja cambia el alto sin parar y la red no debe moverse por eso.
  let anchoPrevio = window.innerWidth;
  window.addEventListener("resize", debounce(() => {
    const cambio = Math.abs(window.innerWidth - anchoPrevio) > 40;
    anchoPrevio = window.innerWidth;
    aplicarTamanoPanelDer();
    if (cambio && $("rs-der").classList.contains("abierto")) recentrarSeleccionRed();
  }, 200));
  aplicarTamanoPanelDer();
}

function initResumen() {
  poblarSelect($("resumen-alcance"), { nacional: true, seleccionado: "todas" });
  $("resumen-alcance")?.addEventListener("change", (e) => navegar({ vista: "resumen", alcance: e.target.value }));
  initEntidades();
  $("btn-copiar-cita")?.addEventListener("click", copiarCita);
  $("btn-csv")?.addEventListener("click", descargarCSV);
  const selTipo = $("anunciantes-tipo");
  if (selTipo) {
    selTipo.innerHTML = opcionesTipo(state.resumen.tipo);
    selTipo.addEventListener("change", (e) => { state.resumen.tipo = e.target.value; state.resumen.visibles = 15; cargarTop(state.resumen.alcance, ++state.resumen.seq); });
  }
  $("anunciantes-base")?.addEventListener("change", (e) => { state.resumen.soloBase = e.target.checked; state.resumen.visibles = 15; renderAnunciantes(); });

  // pestañas (con flechas del teclado)
  const tabs = $("resumen-tabs");
  tabs?.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) { activarTab(state.resumen.tab === b.dataset.tab && b.dataset.tab !== "red" ? "red" : b.dataset.tab); escribirHash(); return; }
    if (e.target.closest("#rs-btn-filtros")) alternarIzq();
    if (e.target.closest("#rs-btn-resumen")) alternarFlot();
  });
  initFlot();
  $("rs-izq-cerrar")?.addEventListener("click", () => alternarIzq(false));
  $("rs-der-cerrar")?.addEventListener("click", () => {
    if (state.resumen.der === "detalle") limpiarSeleccionRed(); else { activarTab("red"); escribirHash(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || state.vista !== "resumen" || (e.target.closest && e.target.closest("#rg-canvas"))) return;
    if (e.target.closest && e.target.closest("#rs-flot")) { alternarFlot(false); $("rs-btn-resumen")?.focus(); return; }       // Esc dentro de la ventana flotante: solo la cierra a ella
    if ($("rs-izq").classList.contains("abierto")) alternarIzq(false);
    else if (state.resumen.der === "detalle") limpiarSeleccionRed();
    else if (state.resumen.der) { activarTab("red"); escribirHash(); }
  });
  if (window.ResizeObserver && $("rs-stage")) new ResizeObserver(ajustarRedDeb).observe($("rs-stage"));
  initAsaPanelDerecho();

  // anunciantes: búsqueda, orden, cabeceras, detalles, "mostrar más"
  $("anunciantes-buscar")?.addEventListener("input", debounce((e) => { state.resumen.buscar = e.target.value; state.resumen.visibles = 15; renderAnunciantes(); }, 150));
  $("anunciantes-orden")?.addEventListener("change", (e) => {
    const clave = e.target.value;
    state.resumen.orden = { clave, dir: clave === "nombre" ? "asc" : "desc" };
    renderAnunciantes();
  });
  $("anunciantes-tabla")?.addEventListener("click", (e) => {
    const sort = e.target.closest("[data-sort]");
    if (sort) {
      const o = state.resumen.orden;
      state.resumen.orden = o.clave === sort.dataset.sort ? { clave: o.clave, dir: o.dir === "desc" ? "asc" : "desc" } : { clave: sort.dataset.sort, dir: sort.dataset.sort === "nombre" ? "asc" : "desc" };
      $("anunciantes-orden").value = state.resumen.orden.clave;
      renderAnunciantes();
      return;
    }
    const tog = e.target.closest("[data-toggle]");
    if (tog) {
      const k = tog.dataset.toggle;
      state.resumen.abiertos.has(k) ? state.resumen.abiertos.delete(k) : state.resumen.abiertos.add(k);
      renderAnunciantes();
      document.querySelector(`[data-toggle="${CSS.escape(k)}"]`)?.focus();
      return;
    }
    if (e.target.closest("[data-mas]")) { state.resumen.visibles += 15; renderAnunciantes(); }
  });

  $("mensajes-solo-distintos")?.addEventListener("change", renderMensajes);
  $("mensajes-sin-aisladas")?.addEventListener("change", renderMensajes);
  $("mensajes-ver-revisados")?.addEventListener("change", renderMensajes);
  const listaMensajes = $("mensajes-lista");
  listaMensajes?.addEventListener("click", clicMensajes);
  listaMensajes?.addEventListener("submit", (ev) => {
    const form = ev.target.closest(".rev-form");
    if (!form) return;
    ev.preventDefault();
    guardarRevisionMensaje(Number(form.dataset.i), form);
  });
  listaMensajes?.addEventListener("keydown", (ev) => {
    const form = ev.key === "Escape" && ev.target.closest(".rev-form");
    if (form) form.querySelector('[data-men="cerrar"]').click();
  });

  const buscar = () => { const p = $("termino-input").value.trim(); if (p) consultarTermino(p); };
  $("termino-buscar")?.addEventListener("click", buscar);
  $("termino-input")?.addEventListener("keydown", (e) => { if (e.key === "Enter") buscar(); });
}

const SECCIONES_DER = { detalle: "Detalle", mensajes: "Mensajes repetidos", entidades: "Entidades", termino: "Buscar un término", info: "Fuente y método" };

function abrirDerecho(sec) {
  const der = $("rs-der");
  if (!der || !SECCIONES_DER[sec]) return;
  state.resumen.der = sec;
  Object.keys(SECCIONES_DER).forEach((s) => { const el = $(`tab-${s}`); if (el) el.hidden = s !== sec; });
  $("rs-der-titulo").textContent = SECCIONES_DER[sec];
  der.classList.add("abierto"); der.inert = false; der.removeAttribute("aria-hidden");
  $("rs-stage").classList.add("der-abierto");
  der.querySelector(".rs-panel-cuerpo").scrollTop = 0;
  if (sec === "entidades" && !entidadesUI.datos) cargarEntidades();
  if (sec === "termino" && !state.resumen.tendenciasCargadas) cargarTendencias();
  actualizarAriaAsa();
}

function cerrarDerecho() {
  const der = $("rs-der");
  if (!der) return;
  state.resumen.der = null;
  der.classList.remove("abierto"); der.inert = true; der.setAttribute("aria-hidden", "true");
  $("rs-stage").classList.remove("der-abierto");
}

/** Cierra el detalle de un nodo y devuelve el panel a la sección que estaba abierta (o lo cierra). */
function restaurarDerecho() {
  const t = state.resumen.tab;
  if (t && t !== "red") abrirDerecho(t); else cerrarDerecho();
}

// --- Ventana flotante «Resumen» (totales y anunciantes) ---------------------
// No es un panel lateral: flota sobre la red y puede quedar abierta junto al panel derecho (mensajes repetidos, detalle de una línea o un nodo).
// Se mueve arrastrando la cabecera; su posición se recuerda en este navegador (doble clic en la cabecera: vuelve a la de inicio).
const CLAVE_FLOT = "noai_rs_flot_pos", CLAVE_FLOT_TAM = "noai_rs_flot_tam", FLOT_MIN = { w: 300, h: 180 };

function alternarFlot(abrir) {
  const f = $("rs-flot");
  if (!f) return;
  const abierto = abrir === undefined ? f.hidden : abrir;
  f.hidden = !abierto;
  $("rs-btn-resumen")?.setAttribute("aria-expanded", String(abierto));
  if (abierto) { acotarFlot(); f.querySelector(".rs-flot-cuerpo").scrollTop = 0; }
}

/** Coloca la ventana en `pos` (o donde estaba) sin que se salga de la vista: siempre queda a la vista al menos su cabecera. */
function acotarFlot(pos) {
  const f = $("rs-flot"), sec = $("view-resumen");
  if (!f || f.hidden || !sec || panelEsHoja()) return;
  const r = sec.getBoundingClientRect();
  const x = pos ? pos.x : f.offsetLeft, y = pos ? pos.y : f.offsetTop;
  if (f.offsetWidth > r.width - 8) f.style.width = Math.max(FLOT_MIN.w, r.width - 8) + "px";        // la vista se achicó: la ventana también
  if (f.offsetHeight > r.height - 8) f.style.height = Math.max(FLOT_MIN.h, r.height - 8) + "px";
  f.style.left = Math.max(0, Math.min(r.width - f.offsetWidth, x)) + "px";
  f.style.top = Math.max(0, Math.min(r.height - 44, y)) + "px";
  f.style.right = "auto";
}

function initFlot() {
  const f = $("rs-flot"), cab = $("rs-flot-cab");
  if (!f || !cab) return;
  $("rs-flot-cerrar")?.addEventListener("click", () => { alternarFlot(false); $("rs-btn-resumen")?.focus(); });
  try { const p = JSON.parse(localStorage.getItem(CLAVE_FLOT) || "null"); if (p && isFinite(p.x) && isFinite(p.y)) { f.style.left = p.x + "px"; f.style.top = p.y + "px"; f.style.right = "auto"; } } catch (e) { /* sin almacenamiento: posición de inicio */ }
  let arr = null;
  cab.addEventListener("pointerdown", (ev) => {
    if (ev.button > 0 || ev.target.closest("button") || panelEsHoja()) return;
    ev.preventDefault();
    arr = { id: ev.pointerId, dx: ev.clientX - f.offsetLeft, dy: ev.clientY - f.offsetTop };
    try { cab.setPointerCapture(ev.pointerId); } catch (e) { /* sin captura */ }
    f.classList.add("moviendo");
  });
  cab.addEventListener("pointermove", (ev) => { if (arr && ev.pointerId === arr.id) acotarFlot({ x: ev.clientX - arr.dx, y: ev.clientY - arr.dy }); });
  const soltar = (ev) => {
    if (!arr || ev.pointerId !== arr.id) return;
    arr = null; f.classList.remove("moviendo");
    try { localStorage.setItem(CLAVE_FLOT, JSON.stringify({ x: f.offsetLeft, y: f.offsetTop })); } catch (e) { /* sin almacenamiento */ }
  };
  cab.addEventListener("pointerup", soltar); cab.addEventListener("pointercancel", soltar);
  cab.addEventListener("dblclick", (ev) => {
    if (ev.target.closest("button")) return;
    f.style.left = f.style.top = f.style.right = f.style.width = f.style.height = "";
    try { localStorage.removeItem(CLAVE_FLOT); localStorage.removeItem(CLAVE_FLOT_TAM); } catch (e) { /* sin almacenamiento */ }
  });

  // Tamaño: asas en los bordes izquierdo, derecho e inferior y en las esquinas de abajo. Se recuerda en este navegador; el contenido se acomoda
  // al nuevo ancho por sí solo (container queries en styles.css).
  ["e", "w", "s", "se", "sw"].forEach((b) => {
    const a = document.createElement("div");
    a.className = `rs-flot-asa rs-flot-asa-${b}`; a.dataset.borde = b; a.setAttribute("aria-hidden", "true");
    a.title = "Arrastra para cambiar el tamaño (doble clic en la cabecera: tamaño y posición originales)";
    f.appendChild(a);
  });
  try { const t = JSON.parse(localStorage.getItem(CLAVE_FLOT_TAM) || "null"); if (t && t.w >= FLOT_MIN.w && t.h >= FLOT_MIN.h) { f.style.width = t.w + "px"; f.style.height = t.h + "px"; } } catch (e) { /* tamaño de inicio */ }
  let aj = null;
  f.addEventListener("pointerdown", (ev) => {
    const a = ev.target.closest(".rs-flot-asa");
    if (!a || ev.button > 0 || panelEsHoja()) return;
    ev.preventDefault();
    const r = $("view-resumen").getBoundingClientRect();
    aj = { id: ev.pointerId, b: a.dataset.borde, x0: ev.clientX, y0: ev.clientY, l: f.offsetLeft, t: f.offsetTop, w: f.offsetWidth, h: f.offsetHeight, W: r.width, H: r.height };
    try { a.setPointerCapture(ev.pointerId); } catch (e) { /* sin captura */ }
    f.classList.add("ajustando");
  });
  f.addEventListener("pointermove", (ev) => {
    if (!aj || ev.pointerId !== aj.id) return;
    const dx = ev.clientX - aj.x0, dy = ev.clientY - aj.y0, lim = (v, a, b) => Math.max(a, Math.min(b, v));
    let l = aj.l, w = aj.w, h = aj.h;
    if (aj.b.includes("e")) w = lim(aj.w + dx, FLOT_MIN.w, aj.W - aj.l);
    if (aj.b.includes("w")) { w = lim(aj.w - dx, FLOT_MIN.w, aj.l + aj.w); l = aj.l + aj.w - w; }
    if (aj.b.includes("s")) h = lim(aj.h + dy, FLOT_MIN.h, aj.H - aj.t);
    f.style.left = l + "px"; f.style.right = "auto"; f.style.width = w + "px"; f.style.height = h + "px";
  });
  const soltarAj = (ev) => {
    if (!aj || ev.pointerId !== aj.id) return;
    aj = null; f.classList.remove("ajustando");
    try {
      localStorage.setItem(CLAVE_FLOT_TAM, JSON.stringify({ w: f.offsetWidth, h: f.offsetHeight }));
      localStorage.setItem(CLAVE_FLOT, JSON.stringify({ x: f.offsetLeft, y: f.offsetTop }));
    } catch (e) { /* sin almacenamiento */ }
  };
  f.addEventListener("pointerup", soltarAj); f.addEventListener("pointercancel", soltarAj);
  window.addEventListener("resize", debounce(() => acotarFlot(), 150));
}

function alternarIzq(abrir) {
  const izq = $("rs-izq");
  if (!izq) return;
  const abierto = abrir === undefined ? !izq.classList.contains("abierto") : abrir;
  izq.classList.toggle("abierto", abierto); izq.inert = !abierto;
  if (abierto) izq.removeAttribute("aria-hidden"); else izq.setAttribute("aria-hidden", "true");
  $("rs-stage").classList.toggle("izq-abierto", abierto);
  $("rs-btn-filtros")?.setAttribute("aria-expanded", String(abierto));
}

function activarTab(tab) {
  if (!TABS.includes(tab)) tab = TABS[0];
  state.resumen.tab = tab;
  document.querySelectorAll("#resumen-tabs [data-tab]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tab === tab)));
  if (tab === "red") cerrarDerecho(); else abrirDerecho(tab);
  if (redOrbital) redOrbital.refrescar();         // «Mensajes repetidos» ilumina las líneas de texto en la red
}

/**
 * Carga todo lo de Conexiones para un alcance. `silencioso`: es una actualización de los mismos datos (p. ej. tras guardar un perfil), no un cambio de
 * alcance: lo que hay en pantalla se queda hasta que llegan los datos nuevos (sin pantallas de carga) y la red conserva su cámara y su selección.
 */
async function cargarResumen(alcance, { silencioso = false } = {}) {
  const R = state.resumen;
  R.alcance = alcance;
  const seq = ++R.seq;
  R.top = null; R.stats = null; R.mensajes = null; R.red = null;
  selResumen = null;                // la red nueva vuelve a avisar si restaura lo que estaba seleccionado
  if (!silencioso) { R.visibles = 15; R.abiertos = new Set(); }
  const nacional = alcance === "todas";
  $("view-resumen").setAttribute("aria-busy", "true");
  $("resumen-progress").classList.add("on");
  if (!silencioso) {
    $("resumen-kpis").innerHTML = "";
    $("resumen-lead").textContent = "";
    $("anunciantes-tabla").innerHTML = cajaEstado({ tipo: "carga", titulo: "Cargando anunciantes...", descripcion: "Consultando la Biblioteca de Anuncios de Meta. La primera vez puede tardar unos segundos.", filas: 5 });
    $("anunciantes-redes").innerHTML = "";
    $("mensajes-lista").innerHTML = cajaEstado({ tipo: "carga", titulo: "Buscando mensajes repetidos...", descripcion: "Comparando el texto de los anuncios." });
    $("red-lienzo").innerHTML = cajaEstado({ tipo: "carga", titulo: "Armando la red de pagadores...", descripcion: "Uniendo cada pagador con las páginas que paga." });
    $("red-lista").innerHTML = "";
    $("red-kpis").innerHTML = "";
  }

  await Promise.allSettled([
    cargarTop(alcance, seq),
    cargarStats(alcance, seq),
    cargarMensajes(alcance, seq),
    cargarRed(alcance, seq),
    state.mapaDatos ? Promise.resolve() : cargarMapaDatos()
  ]);
  if (seq === R.seq) {
    $("resumen-progress").classList.remove("on");
    $("view-resumen").setAttribute("aria-busy", "false");
  }
}

async function cargarTop(alcance, seq) {
  const tabla = $("anunciantes-tabla");
  try {
    const tipo = state.resumen.tipo ? `&tipo=${encodeURIComponent(state.resumen.tipo)}` : "";
    const d = await fetchApi(`/api/ads/top-gastadores?provincia=${encodeURIComponent(alcance)}&limite=6000${tipo}`, { timeout: 90000 });
    if (seq !== state.resumen.seq) return;
    state.resumen.top = d;
    renderProveniencia(d.estado);
    renderKpis(d);
    renderAnunciantes();
    const redes = $("anunciantes-redes");
    redes.innerHTML = (d.redes_de_financiadores || []).length ? `
      <div class="notice info" style="margin-top:14px"><strong>Un mismo pagador declarado detrás de varias páginas</strong> (indicador, no prueba)
        ${d.redes_de_financiadores.map((n) => `<div>${escaparHtml(n.financiador)} → ${n.paginas.map(escaparHtml).join(", ")}</div>`).join("")}
      </div>` : "";
    $("anunciantes-nota").textContent = (d.anunciantes || []).length ? (d.nota || "") + " Incluye anuncios de gobiernos, medios y empresas: Meta clasifica como «política o temas sociales» una categoría amplia." : "";
  } catch (e) {
    if (seq !== state.resumen.seq) return;
    $("resumen-fuente").textContent = "Sin conexión con el servidor.";
    errorEnCaja(tabla, `No se pudo cargar la información de anunciantes (${e.message}).`, () => cargarTop(alcance, state.resumen.seq));
  }
}

async function cargarStats(alcance, seq) {
  try {
    const d = await fetchApi(`/api/dashboard/stats?provincia=${encodeURIComponent(alcance)}`, { timeout: 90000 });
    if (seq !== state.resumen.seq) return;
    state.resumen.stats = d;
    $("resumen-lead").innerHTML = alcance === "todas" ? "" : (d.resumen_general || "");
  } catch (e) {
    if (seq !== state.resumen.seq) return;
    $("resumen-lead").textContent = "";
  }
}

async function cargarMensajes(alcance, seq) {
  const lista = $("mensajes-lista");
  try {
    // Se piden también los grupos ya revisados (van al final): la casilla «Mostrar revisados» los muestra u oculta sin volver a consultar.
    const cab = codigoEdicion() ? { "X-Edit-Token": codigoEdicion() } : undefined;
    const d = await fetchApi(`/api/ads/textos-duplicados?provincia=${encodeURIComponent(alcance)}&limite=200&revisados=true`, { timeout: 90000, headers: cab });
    if (seq !== state.resumen.seq) return;
    state.resumen.mensajes = d;
    renderMensajes();
  } catch (e) {
    if (seq !== state.resumen.seq) return;
    errorEnCaja(lista, `No se pudo cargar el análisis de mensajes repetidos (${e.message}).`, () => cargarMensajes(alcance, state.resumen.seq));
  }
}

// --- Red de pagadores -------------------------------------------------------
const TIPOS_RED = {
  pagador_compartido: "Un pagador, varias páginas",
  varios_pagadores: "Una página, varios pagadores",
  red_mixta: "Red de varios pagadores y páginas",
  tercero: "Pagado por un tercero"
};

async function cargarRed(alcance, seq) {
  const lista = $("red-lienzo");
  try {
    // max_paginas: todas las páginas con anuncios entran al grafo (antes solo las ~80 de mayor inversión: las provincias pequeñas quedaban casi vacías);
    // la vista orbital muestra más o menos según el zoom y el cursor (ver «nivel de detalle» en red-orbital.js).
    const d = await fetchApi(`/api/ads/red-pagadores?provincia=${encodeURIComponent(alcance)}&limite=40&max_paginas=6000`, { timeout: 90000 });
    if (seq !== state.resumen.seq) return;
    state.resumen.red = d;
    renderRed();
  } catch (e) {
    if (seq !== state.resumen.seq) return;
    errorEnCaja(lista, `No se pudo cargar la red de pagadores (${e.message}).`, () => cargarRed(alcance, state.resumen.seq));
  }
}

// Partido de un nodo (solo si está verificado, o si el usuario pidió incluir los pendientes)
const partidoDe = (n) => {
  const af = n.afiliacion;
  return af && af.partido && (af.verificado || filtrosGrafo.conPendientes) ? af.partido : null;
};
let coloresPartido = new Map();
const PALETA_AFIL = ["#e8590c", "#2f9e44", "#9c36b5", "#1c7ed6", "#d6336c", "#f08c00", "#0b7285"];
const PALETA_REGION = ["#4dd0e1", "#ffa94d", "#b197fc", "#8ce99a", "#ff8787", "#74c0fc", "#fcc419", "#faa2c1", "#63e6be", "#d0bfff"];
const ARISTAS = {
  pagador: { nombre: "Pagador declarado distinto de la página", chip: "Pagador distinto", corto: "pagador", color: "#ffd43b", dash: [], glifo: "━━" },
  enlace: { nombre: "Mismo enlace en los anuncios", chip: "Mismo enlace", corto: "enlace", color: "#4dd0e1", dash: [3, 4], glifo: "┅┅" },
  texto: { nombre: "Texto casi idéntico", chip: "Texto repetido", corto: "texto", color: "#c4c9d4", dash: [9, 5], glifo: "╍╍" },
  alcance: { nombre: "Provincia donde llega más", chip: "Provincia", corto: "provincia", color: "#7d8cb8", dash: [], glifo: "──" },
  partido: { nombre: "Misma organización política (unida a la página del partido)", chip: "Partido", corto: "partido", color: "#a855f7", dash: [], glifo: "══" },
  partido_prov: { nombre: "Candidatos del mismo partido en otra provincia (une los soles)", chip: "Partido entre provincias", corto: "mismo partido en otra provincia", color: "#a855f7", dash: [], glifo: "══" }
};
/**
 * Interruptores del panel «Conexiones» de los filtros: [clave, tipos de conexión que apaga o enciende].
 * «Provincia» (la unión de cada página con la provincia donde llega más) no está: es la estructura de la red y no se puede romper (siempre se dibuja).
 * «Partido» es un solo interruptor para el partido dentro de una provincia y entre provincias.
 */
const TIPOS_FILTRO = [["pagador", ["pagador"]], ["enlace", ["enlace"]], ["texto", ["texto"]], ["partido", ["partido", "partido_prov"]]];
/** Una fila de la leyenda de la red: icono y texto en columnas alineadas (texto ya escapado). */
const filtrosGrafo = { tipos: new Set(["pagador", "enlace", "texto", "alcance", "partido", "partido_prov"]), activos: false, color: "tipo", fechaIdx: 0, buscar: "", etiquetas: true, conPendientes: false, partidos: new Set() };
let ultimoGrafoRed = null;
let aplicarFiltrosRed = () => {};

// ---------------------------------------------------------------------------
// Segmentadores (filtros como los de un tablero): por provincia, por conector y por entidad. Al empezar todo está seleccionado, así que se ve
// todo; lo que se desmarca deja de dibujarse (no se atenúa). Cada segmentador guarda «todos menos estas excepciones» o «solo estas».
// ---------------------------------------------------------------------------
const SEG_NINGUNA = "ninguna";                       // conector: páginas que solo tienen la unión con su provincia
const SEG_SIN_PARTIDO = "\u0000sin-partido";          // partido: páginas sin partido registrado (o sin verificar, si no se incluyen)
const SEGMENTOS = [
  { clave: "provincia", titulo: "Provincia", todos: "Todas", buscar: true },
  { clave: "conector", titulo: "Conector", todos: "Todos", buscar: false },
  { clave: "partido", titulo: "Partido", todos: "Todos", buscar: true },
  { clave: "entidad", titulo: "Entidad", todos: "Todas", buscar: true }
];
const segmentos = { provincia: { todos: true, exc: new Set() }, conector: { todos: true, exc: new Set() }, partido: { todos: true, exc: new Set() }, entidad: { todos: true, exc: new Set() } };
let segItems = { provincia: [], conector: [], partido: [], entidad: [] };       // lo que lista cada segmentador para la red en pantalla
// Con algún segmentador filtrando: las páginas y pagadores que siguen a la vista (por id de página y por nombre), para filtrar también las
// listas de Anunciantes, Mensajes repetidos y Entidades. null = todo seleccionado (las listas no se tocan).
let segVisibles = null;
let segSincronizar = () => {};
/** ¿Los segmentadores dejan ver esta página o pagador? Basta con que coincida uno de sus ids de página o uno de sus nombres. */
const segPasa = (ids, nombres) => !segVisibles
  || [].concat(ids || []).some((id) => id != null && id !== "" && segVisibles.ids.has(String(id)))
  || [].concat(nombres || []).some((n) => n && segVisibles.nombres.has(_normBusqueda(n)));
/**
 * Lo seleccionado en la red (un nodo o una línea de texto repetido, enlace o partido) filtra la ventana «Resumen» como un filtro más: sus totales,
 * su lista y su CSV se limitan a las páginas encendidas. null = nada seleccionado. Un pagador cuenta las páginas que paga; una provincia, las páginas
 * con base en ella.
 */
let selResumen = null;      // { etiqueta, ids: Set, nombres: Set, pagadores: Set, region: string|null }
const selPasa = (a) => !selResumen
  || (a.page_id != null && selResumen.ids.has(String(a.page_id)))
  || selResumen.nombres.has(_normBusqueda(a.page_name))
  || (a.financiadores || []).some((f) => selResumen.pagadores.has(_normBusqueda(f)))
  || (!!selResumen.region && !!a.region_principal && _normBusqueda(a.region_principal.region) === selResumen.region);

/** Arma la selección de la ventana «Resumen» a partir de los nodos encendidos (las provincias de un grupo de partido no cuentan: sí sus páginas). */
function selDeNodos(nodos, etiqueta) {
  const s = { etiqueta, ids: new Set(), nombres: new Set(), pagadores: new Set(), region: null };
  nodos.forEach((n) => {
    if (!n || n.tipo === "provincia") return;
    if (n.page_id != null && n.page_id !== "") s.ids.add(String(n.page_id));
    s.nombres.add(_normBusqueda(n.nombre));
  });
  return s;
}

function fijarSelResumen(sel) {
  selResumen = sel;
  state.resumen.visibles = 15;
  if (state.resumen.top) { renderKpis(state.resumen.top); renderAnunciantes(); }
}

/** Selección de un nodo de la red: una página es ella misma; un pagador, las páginas que paga; una provincia, las páginas con base allí. */
function selDeNodo(n) {
  if (n.tipo === "pagador") {
    const s = selDeNodos([], `pagador ${n.nombre}`);
    s.pagadores.add(_normBusqueda(n.nombre));
    return s;
  }
  if (n.tipo === "provincia") { const s = selDeNodos([], `páginas con base en ${n.nombre}`); s.region = _normBusqueda(n.nombre); return s; }
  return selDeNodos([n], n.nombre);
}

/** Selección de una línea de la red: las páginas que deja encendidas (su grupo). */
function selDeArista(e) {
  const etiqueta = e.tipo === "partido" || e.tipo === "partido_prov" ? `partido ${e.partido || ""}`.trim()
    : `${e.tipo === "enlace" ? "mismo enlace" : "texto repetido"}: ${e.a.nombre} ↔ ${e.b.nombre}`;
  return selDeNodos(e.miembros && e.miembros.length ? e.miembros : [e.a, e.b], etiqueta);
}

const htmlAvisoSel = (quedan) => (selResumen
  ? `<div class="seg-aviso xsmall" role="status"><span>Selección en la red (${escaparHtml(selResumen.etiqueta)}): ${fmtNum(quedan)} ${quedan === 1 ? "anunciante" : "anunciantes"}.</span><button type="button" class="link-btn" data-sel-quitar>Quitar selección</button></div>` : "");
document.addEventListener("click", (ev) => {
  if (ev.target.closest && ev.target.closest("[data-sel-quitar]")) limpiarSeleccionRed();
});

/** Aviso de las listas mientras hay filtros: cuántas filas quedan y un botón para quitarlos. `quedan`/`total` ya filtrados por lo demás. */
const htmlAvisoSeg = (quedan, total, cosa) => (segVisibles
  ? `<div class="seg-aviso xsmall" role="status"><span>Filtros de la red: ${fmtNum(quedan)} de ${fmtNum(total)} ${cosa}.</span><button type="button" class="link-btn" data-seg-quitar>Quitar filtros</button></div>` : "");
document.addEventListener("click", (ev) => {
  if (!ev.target.closest("[data-seg-quitar]")) return;
  SEGMENTOS.forEach((d) => segReiniciar(d.clave)); segSincronizar();
});
/** Las listas se vuelven a pintar con lo que dejan ver los segmentadores (cada una comprueba si ya tiene sus datos). */
function repintarListasSeg() {
  if (state.resumen.top) renderKpis(state.resumen.top);
  renderAnunciantes(); renderMensajes();
  if ($("ent-filas")) pintarFilasEntidades();
}
let segAlcance = null;
let colorAntesDePartido = null;      // «Color por» que había antes de que el segmentador de partido lo cambiara a «Afiliación»
const segElegido = (clave, id) => { const s = segmentos[clave]; return s.todos ? !s.exc.has(id) : s.exc.has(id); };
const segMarcar = (clave, id, elegido) => { const s = segmentos[clave]; if (elegido === s.todos) s.exc.delete(id); else s.exc.add(id); };
const segCuenta = (clave) => segItems[clave].reduce((c, it) => c + (segElegido(clave, it.id) ? 1 : 0), 0);
const segCompleto = (clave) => segCuenta(clave) === segItems[clave].length;
const segReiniciar = (clave) => { segmentos[clave].todos = true; segmentos[clave].exc.clear(); };

/** Lo que lista cada segmentador para el grafo `g` (provincias y entidades por inversión; conectores en el orden de la leyenda). */
function prepararSegmentos(g) {
  const especiales = new Map();                      // id de nodo -> tipos de conexión que tiene, además de la de su provincia
  g.aristas.forEach((e) => {
    if (e.tipo === "partido_prov" || e.tipo === "alcance") return;
    [e.a, e.b].forEach((id) => { if (!especiales.has(id)) especiales.set(id, new Set()); especiales.get(id).add(e.tipo); });
  });
  const paginas = g.nodos.filter((n) => n.tipo === "pagina");
  const gasto = (n) => Number(n.gasto && n.gasto.medio) || 0;
  const porPartido = new Map();                      // partido -> páginas (solo verificados, salvo que se incluyan los pendientes)
  paginas.forEach((n) => { const p = partidoDe(n) || SEG_SIN_PARTIDO; porPartido.set(p, (porPartido.get(p) || 0) + 1); });
  segItems = {
    partido: [...porPartido.entries()].filter(([p]) => p !== SEG_SIN_PARTIDO).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "es"))
      .map(([p, c]) => ({ id: p, nombre: p, glifo: "●", color: coloresPartido.get(p) || "var(--text-2)", dato: `${fmtNum(c)} pág.` }))
      .concat([{ id: SEG_SIN_PARTIDO, nombre: "Sin partido registrado", glifo: "○", color: "var(--text-3)", dato: `${fmtNum(porPartido.get(SEG_SIN_PARTIDO) || 0)} pág.` }]),
    provincia: g.nodos.filter((n) => n.tipo === "provincia").sort((a, b) => gasto(b) - gasto(a))
      .map((n) => ({ id: n.id, nombre: n.nombre, dato: `${fmtNum(n.paginas_total != null ? n.paginas_total : n.paginas)} pág.` })),
    conector: TIPOS_FILTRO.map(([t, tipos]) => ({ id: t, nombre: ARISTAS[t].chip, glifo: ARISTAS[t].glifo, color: colorAristaVista(t), dato: fmtNum(tipos.reduce((c, k) => c + ((g.tipos || {})[k] || 0), 0)) }))
      .concat([{ id: SEG_NINGUNA, nombre: "Sin otra conexión", glifo: "·", color: "var(--text-3)", dato: `${fmtNum(paginas.filter((n) => !especiales.has(n.id)).length)} pág.` }]),
    entidad: g.nodos.filter((n) => n.tipo !== "provincia").sort((a, b) => gasto(b) - gasto(a) || a.nombre.localeCompare(b.nombre, "es"))
      .map((n) => ({ id: n.id, nombre: n.nombre, dato: fmtUsd(gasto(n)), marca: n.tipo === "pagador" ? "pagador" : "" }))
  };
  return especiales;
}

/**
 * Traduce los segmentadores a lo que lee la red: `ocultos` (nodos que no se dibujan), `tiposOcultos` (conexiones que no se dibujan) y `forzados`
 * (si queda poco a la vista, se dibuja todo sin esperar al zoom). Una página se ve si está elegida, su provincia está elegida y tiene alguno de los
 * conectores elegidos y su partido está elegido; un pagador, si está elegido y se ve alguna página a la que paga; una provincia, si está elegida y le
 * queda alguna página. El partido de un pagador no cuenta: sigue a las páginas que paga.
 */
function calcularSegmentos(g, especiales) {
  const ocultos = new Set(), tiposOcultos = new Set();
  const conTodos = segCompleto("conector"), parTodos = segCompleto("partido"), filtrando = !conTodos || !parTodos || !segCompleto("entidad") || !segCompleto("provincia");
  // conectores entre soles de los partidos desmarcados, y líneas de partido bien visibles mientras se filtra por partido
  filtrosGrafo.partidosOcultos = new Set(parTodos ? [] : segItems.partido.filter((it) => it.id !== SEG_SIN_PARTIDO && !segElegido("partido", it.id)).map((it) => it.id));
  filtrosGrafo.partidoFiltrado = !parTodos;
  // filtrando por partido, los puntos toman el color de su partido; al quitar ese filtro vuelve el color que había
  if (!parTodos && filtrosGrafo.color !== "afiliacion") { colorAntesDePartido = filtrosGrafo.color; filtrosGrafo.color = "afiliacion"; }
  else if (parTodos && colorAntesDePartido) { filtrosGrafo.color = colorAntesDePartido; colorAntesDePartido = null; }
  TIPOS_FILTRO.forEach(([t, tipos]) => { if (!segElegido("conector", t)) tipos.forEach((k) => tiposOcultos.add(k)); });
  filtrosGrafo.tipos = new Set(["alcance", ...Object.keys(ARISTAS).filter((k) => !tiposOcultos.has(k))]);
  const provDe = new Map(), tipoNodo = new Map(g.nodos.map((n) => [n.id, n.tipo]));
  g.aristas.forEach((e) => { if (e.tipo !== "alcance") return; if (tipoNodo.get(e.b) === "provincia") provDe.set(e.a, e.b); else if (tipoNodo.get(e.a) === "provincia") provDe.set(e.b, e.a); });
  const conPaginas = new Set(), visibles = [];
  g.nodos.forEach((n) => {
    if (n.tipo !== "pagina") return;
    const prov = provDe.get(n.id), tipos = especiales.get(n.id);
    const ok = segElegido("entidad", n.id) && (prov ? segElegido("provincia", prov) : segCompleto("provincia"))
      && (parTodos || segElegido("partido", partidoDe(n) || SEG_SIN_PARTIDO))
      && (conTodos || (tipos ? [...tipos].some((t) => segElegido("conector", t)) : segElegido("conector", SEG_NINGUNA)));
    if (!ok) { ocultos.add(n.id); return; }
    visibles.push(n.id); if (prov) conPaginas.add(prov);
  });
  const pagaA = new Map();
  g.aristas.forEach((e) => { if (e.tipo !== "pagador") return; const [pg, pag] = tipoNodo.get(e.a) === "pagador" ? [e.a, e.b] : [e.b, e.a]; if (!pagaA.has(pg)) pagaA.set(pg, []); pagaA.get(pg).push(pag); });
  g.nodos.forEach((n) => {
    if (n.tipo === "pagador") {
      if (!(segElegido("entidad", n.id) && segElegido("conector", "pagador") && (pagaA.get(n.id) || []).some((id) => !ocultos.has(id)))) ocultos.add(n.id);
    } else if (n.tipo === "provincia") {
      if (!segElegido("provincia", n.id) || (filtrando && !conPaginas.has(n.id))) ocultos.add(n.id);
    }
  });
  filtrosGrafo.ocultos = ocultos; filtrosGrafo.tiposOcultos = tiposOcultos;
  filtrosGrafo.forzados = filtrando && visibles.length <= 400 ? new Set(visibles) : null;
  const entidades = g.nodos.filter((n) => n.tipo !== "provincia");
  segVisibles = null;
  if (filtrando) {
    segVisibles = { ids: new Set(), nombres: new Set() };
    entidades.forEach((n) => {
      if (ocultos.has(n.id)) return;
      segVisibles.nombres.add(_normBusqueda(n.nombre));
      if (n.page_id) segVisibles.ids.add(String(n.page_id));
      (n.unificada || []).forEach((u) => { if (u.page_id) segVisibles.ids.add(String(u.page_id)); if (u.nombre) segVisibles.nombres.add(_normBusqueda(u.nombre)); });
    });
  }
  return { filtrando, visibles: entidades.filter((n) => !ocultos.has(n.id)).length, total: entidades.length };
}

const htmlSegmento = (def) => {
  const items = segItems[def.clave];
  return `<section class="rs-sec seg" data-seg="${def.clave}">
    <h3><span>${def.titulo}</span><span class="seg-res" data-seg-res></span></h3>
    ${def.buscar && items.length > 8 ? `<input type="search" class="seg-buscar" placeholder="Buscar ${def.titulo.toLowerCase()}…" aria-label="Buscar en ${def.titulo}">` : ""}
    <div class="seg-lista" role="group" aria-label="${def.titulo}">
      <label class="seg-fila seg-todo"><input type="checkbox" data-seg-todo> <span class="seg-nom">Seleccionar todo</span></label>
      ${items.map((it, i) => `<div class="seg-fila" data-i="${i}" data-q="${escaparHtml(_normBusqueda(it.nombre))}"><label><input type="checkbox" data-seg-i="${i}"> ${it.glifo ? `<span class="seg-glifo" style="color:${it.color}">${it.glifo}</span> ` : ""}<span class="seg-nom" title="${escaparHtml(it.nombre)}">${escaparHtml(it.nombre)}</span>${it.marca ? ` <span class="seg-marca">${it.marca}</span>` : ""}</label><span class="seg-dato">${escaparHtml(it.dato)}</span><button type="button" class="seg-solo" data-seg-solo="${i}" title="Dejar seleccionado solo este" aria-label="Solo ${escaparHtml(it.nombre)}">solo</button></div>`).join("")}
      <p class="seg-vacio xsmall muted" hidden>Nada coincide con la búsqueda.</p>
    </div>
  </section>`;
};

/** Pinta y conecta los tres segmentadores en `cont`. `alCambiar(clave, id, elegido)` se llama tras cada cambio, con la red ya filtrada. */
function montarSegmentos(cont, g, alCambiar) {
  const especiales = prepararSegmentos(g);
  let caja = cont.querySelector("#rg-segmentos");
  const limpia = caja.cloneNode(false); caja.replaceWith(limpia); caja = limpia;      // si se vuelve a montar (p. ej. al incluir partidos sin verificar), sin escuchas repetidas
  caja.innerHTML = `<p class="seg-estado" id="seg-estado" aria-live="polite"></p>` + SEGMENTOS.map(htmlSegmento).join("");
  const sincronizar = (inicial) => {
    const r = calcularSegmentos(g, especiales);
    let activos = 0;
    SEGMENTOS.forEach((def) => {
      const sec = caja.querySelector(`[data-seg="${def.clave}"]`), n = segCuenta(def.clave), total = segItems[def.clave].length;
      if (n < total) activos++;
      sec.querySelectorAll("input[data-seg-i]").forEach((c) => { c.checked = segElegido(def.clave, segItems[def.clave][Number(c.dataset.segI)].id); });
      const todo = sec.querySelector("input[data-seg-todo]"); todo.checked = n === total; todo.indeterminate = n > 0 && n < total;
      sec.querySelector("[data-seg-res]").textContent = n === total ? def.todos : `${fmtNum(n)} de ${fmtNum(total)}`;
      sec.classList.toggle("filtrando", n < total);
    });
    $("seg-estado").innerHTML = r.filtrando
      ? `<span>Se ${r.visibles === 1 ? "ve" : "ven"} <strong>${fmtNum(r.visibles)}</strong> de ${fmtNum(r.total)} entidades</span><button type="button" class="link-btn" id="seg-reiniciar">Quitar filtros</button>`
      : `<span>Todo seleccionado: se ven las ${fmtNum(r.total)} entidades.</span>`;
    const selColor = $("rg-color"); if (selColor && selColor.value !== filtrosGrafo.color) selColor.value = filtrosGrafo.color;
    const boton = $("rs-btn-filtros");
    if (boton) { boton.textContent = activos ? `Filtros · ${activos}` : "Filtros"; boton.classList.toggle("con-filtro", activos > 0); }
    aplicarFiltrosRed();
    if (inicial !== true || segVisibles) repintarListasSeg();      // al montar sin filtros no hace falta (y no se pisa una fila que se está editando)
  };
  segSincronizar = sincronizar;
  caja.addEventListener("change", (ev) => {
    const sec = ev.target.closest("[data-seg]"); if (!sec) return;
    const clave = sec.dataset.seg, items = segItems[clave];
    if (ev.target.matches("input[data-seg-todo]")) {
      const q = _normBusqueda((sec.querySelector(".seg-buscar") || {}).value);
      if (!q) { segmentos[clave].todos = ev.target.checked; segmentos[clave].exc.clear(); }
      else items.forEach((it) => { if (_normBusqueda(it.nombre).includes(q)) segMarcar(clave, it.id, ev.target.checked); });      // con búsqueda: solo lo que coincide
      sincronizar(); alCambiar(clave, null, ev.target.checked);
    } else if (ev.target.matches("input[data-seg-i]")) {
      const it = items[Number(ev.target.dataset.segI)];
      segMarcar(clave, it.id, ev.target.checked);
      sincronizar(); alCambiar(clave, it.id, ev.target.checked);
    }
  });
  caja.addEventListener("click", (ev) => {
    if (ev.target.closest("#seg-reiniciar")) { SEGMENTOS.forEach((d) => segReiniciar(d.clave)); sincronizar(); alCambiar(null, null, true); return; }
    const solo = ev.target.closest("[data-seg-solo]"); if (!solo) return;
    const clave = solo.closest("[data-seg]").dataset.seg, it = segItems[clave][Number(solo.dataset.segSolo)];
    segmentos[clave].todos = false; segmentos[clave].exc = new Set([it.id]);
    sincronizar(); alCambiar(clave, it.id, true);
  });
  caja.addEventListener("input", (ev) => {
    if (!ev.target.matches(".seg-buscar")) return;
    const sec = ev.target.closest("[data-seg]"), q = _normBusqueda(ev.target.value); let n = 0;
    sec.querySelectorAll(".seg-fila[data-i]").forEach((f) => { const ok = !q || f.dataset.q.includes(q); f.hidden = !ok; if (ok) n++; });
    sec.querySelector(".seg-vacio").hidden = n > 0;
    sec.querySelector(".seg-todo .seg-nom").textContent = q ? "Seleccionar lo encontrado" : "Seleccionar todo";
  });
  sincronizar(true);
}

let limpiarSeleccionRed = () => {};

// La red recuerda su encuadre y lo que tenía seleccionado: si se reconstruye (p. ej. al guardar un perfil) o se recarga la página,
// vuelve a donde estaba en vez de encuadrarlo todo y deseleccionar. Es de este alcance (nacional o una provincia) y de esta pestaña del navegador.
const CLAVE_MEMORIA_RED = "noai_red_memoria";
let memoriaRed = (() => {
  try { const m = JSON.parse(sessionStorage.getItem(CLAVE_MEMORIA_RED) || "null"); return m && typeof m === "object" && typeof m.alcance === "string" ? m : null; } catch (e) { return null; }
})();
let leerEstadoRed = () => null;      // lo fija la vista orbital: devuelve su cámara y su selección
let alcanceDeRed = null;             // alcance con el que se dibujó la red que hay en pantalla (el de state.resumen puede haber cambiado ya)

function guardarMemoriaRed() {
  const e = leerEstadoRed();
  if (e && alcanceDeRed) memoriaRed = { ...e, alcance: alcanceDeRed, detalle: state.resumen.der === "detalle" };      // detalle: el panel lateral mostraba lo seleccionado
  if (memoriaRed) { try { sessionStorage.setItem(CLAVE_MEMORIA_RED, JSON.stringify(memoriaRed)); } catch (er) { /* sin almacenamiento */ } }
}
window.addEventListener("pagehide", guardarMemoriaRed);
/** Lo recordado para la vista `vista` ("orbital") si es del alcance que se está dibujando; si no, null (se encuadra todo). */
const memoriaParaRed = (vista) => (memoriaRed && memoriaRed.alcance === state.resumen.alcance && memoriaRed.vista === vista ? memoriaRed : null);

// La red se dibuja con la vista orbital (frontend/js/red-orbital.js, sin dependencias). Si el módulo no carga o falla, se avisa en el lienzo.
let redOrbital = null;
let velocidadOrbita = sinMovimiento() ? 0 : 1;
const usarOrbital = () => !!window.RedOrbital;
// Leyenda del lienzo: se pliega con el botón «Leyenda» y la elección se recuerda.
// Sin elección guardada: abierta en pantallas grandes y plegada en las pequeñas, donde más estorba.
const leyendaAbierta = () => {
  try { const v = localStorage.getItem("noai_red_leyenda"); if (v === "1" || v === "0") return v === "1"; } catch (e) { /* sin almacenamiento */ }
  return !(window.matchMedia && window.matchMedia("(max-width: 640px)").matches);
};
const guardarLeyendaAbierta = (abierta) => { try { localStorage.setItem("noai_red_leyenda", abierta ? "1" : "0"); } catch (e) { /* sin almacenamiento */ } };

// Disposición de la red orbital: los soles sobre el mapa de Ecuador (por defecto) o compactos. La elección se recuerda en este equipo.
// Cada sol se coloca en el mismo punto que su burbuja del Mapa (la capital de la provincia) y el mapa base son las teselas de OpenStreetMap.
const disposicionEnMapa = () => { try { return localStorage.getItem("noai_red_disp") !== "compacta"; } catch (e) { return true; } };
const guardarDisposicion = (mapa) => { try { localStorage.setItem("noai_red_disp", mapa ? "mapa" : "compacta"); } catch (e) { /* sin almacenamiento */ } };
const ubicacionesProvincias = () => Object.fromEntries(provinciasEcuador.map((p) => [p.nombre, [p.lat, p.lng]]));
const teselasRed = () => urlTeselas().replace("{s}.", "");
// El mapa base de la red es el mismo de la pestaña Mapa: su filtro oscuro está definido una sola vez en styles.css (--mapa-filtro-oscuro).
const filtroTeselasRed = () => getComputedStyle(document.documentElement).getPropertyValue("--mapa-filtro-oscuro").trim() || null;

/**
 * Tipo de conexión que la red orbital ilumina extra: «texto» (las líneas grises punteadas) mientras la sección «Mensajes repetidos»
 * está seleccionada, o cuando el filtro de conexiones quedó limitado a texto repetido.
 */
const tipoDestacadoRed = () => {
  if (state.resumen.tab === "mensajes") return "texto";
  const t = filtrosGrafo.tipos;
  if (t.has("texto") && !["pagador", "enlace", "partido", "partido_prov"].some((x) => t.has(x))) return "texto";
  if (["partido", "partido_prov"].some((x) => t.has(x)) && !["pagador", "enlace", "texto"].some((x) => t.has(x))) return "partido";      // solo «partido»: sus líneas (sutiles por defecto) se iluminan
  return null;
};
/** Color de una conexión en la vista activa (la orbital usa la paleta validada para fondo oscuro). */
const colorAristaVista = (t) => (usarOrbital() ? window.RedOrbital.colorArista(t) : ARISTAS[t].color);

/** Si el escenario cambió de tamaño (ventana, vista oculta que se muestra), se vuelve a dibujar la red a su nuevo tamaño. */
function ajustarRed() {
  if (redOrbital) return;                       // la vista orbital observa su propio contenedor
  const cont = $("red-lienzo"), cv = cont && cont.querySelector("canvas");
  if (!ultimoGrafoRed || !cont || !cont.clientWidth || !cont.clientHeight) return;
  if (cv && Math.abs(Number(cv.dataset.w) - cont.clientWidth) < 40 && Math.abs(Number(cv.dataset.h) - cont.clientHeight) < 40) return;
  dibujarLienzoRed(ultimoGrafoRed, fechasDeGrafo(ultimoGrafoRed));
}
const ajustarRedDeb = debounce(ajustarRed, 250);
window.addEventListener("resize", ajustarRedDeb);

const urlHttp = (u) => (/^https?:\/\/\S+$/.test(u || "") ? u : "");

function _normBusqueda(s) {
  return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

const etiquetaArista = (e) => {
  if (e.tipo === "pagador") return `${e.anuncios} ${e.anuncios === 1 ? "anuncio" : "anuncios"} · ${fmtUsd(e.gasto.medio)}`;
  if (e.tipo === "texto") return "texto repetido";
  if (e.tipo === "enlace") return "mismo enlace";
  if (e.tipo === "partido_prov") return e.partido;
  return `${Math.round((e.pct || 0) * 100)} % del alcance`;
};

const fechasDeGrafo = (g) => [...new Set(g.aristas.map((e) => e.primero).filter(Boolean))].sort();

function htmlDetalle(n, vs) {
  const l = [];
  l.push(`<strong>${escaparHtml(n.nombre)}</strong> · ${n.tipo === "pagador" ? "pagador declarado" : "página"}`);
  if ((n.unificada || []).length > 1) {           // una entidad con varias páginas de Meta se cuenta como un solo punto
    l.push(`<span class="muted">Un solo punto: reúne ${n.unificada.length} páginas de Meta (${n.unificada.map((p) => `${escaparHtml(p.nombre)} · id ${escaparHtml(p.page_id)}`).join("; ")}).</span>`);
  }
  const g = n.gasto || {};
  l.push(`${fmtNum(n.anuncios)} ${n.anuncios === 1 ? "anuncio" : "anuncios"}${n.activos != null ? ` (${fmtNum(n.activos)} activos)` : ""} · inversión estimada ${escaparHtml(fmtUsd(g.medio))}`
    + (g.min != null ? ` <span class="muted">(rango ${escaparHtml(fmtUsd(g.min))}–${escaparHtml(fmtUsd(g.max))})</span>` : ""));
  if (n.region) l.push(`Llega sobre todo a <strong>${escaparHtml(n.region.region)}</strong> (${Math.round(n.region.pct * 100)} %)`);
  if ((n.plataformas || []).length) l.push(`Plataformas: ${n.plataformas.map(escaparHtml).join(", ")}`);
  if (n.primero) l.push(`Anuncios del ${escaparHtml(n.primero)} al ${escaparHtml(n.ultimo || n.primero)}`);
  if ((n.edades || []).length) {
    const max = Math.max(...n.edades.map((e) => e.pct)) || 1;
    const gen = n.genero || {};
    l.push(`<div style="display:flex;gap:4px;align-items:flex-end;height:44px;margin-top:6px" role="img" aria-label="Alcance por edad">${n.edades.map((e) => `<div title="${escaparHtml(e.edad)}: ${Math.round(e.pct * 100)} %" style="flex:1"><div style="background:var(--accent);height:${Math.max(2, Math.round(e.pct / max * 40))}px;border-radius:2px 2px 0 0"></div></div>`).join("")}</div>`
      + `<div style="display:flex;gap:4px;font-size:10px;color:var(--text-3)">${n.edades.map((e) => `<span style="flex:1;text-align:center">${escaparHtml(e.edad)}</span>`).join("")}</div>`
      + `<div class="muted" style="font-size:11px">Alcance por edad · hombres ${Math.round((gen.male || 0) * 100)} % · mujeres ${Math.round((gen.female || 0) * 100)} %</div>`);
  }
  if (n.texto) l.push(`<em class="muted">«${escaparHtml(n.texto)}${n.texto.length >= 200 ? "…" : ""}»</em>`);
  if (vs.length) l.push(`<strong>Conexiones</strong>:<br>${vs.map((e) => `· ${escaparHtml(ARISTAS[e.tipo].corto)} → ${escaparHtml((e.a === n ? e.b : e.a).nombre)}${(e.detalles || []).length ? ` <span class="muted">(${e.detalles.map(escaparHtml).join("; ")})</span>` : ""}`).join("<br>")}`);
  const af = n.afiliacion, fuente = af && urlHttp(af.fuente);
  const enlaceFuente = fuente ? ` · <a href="${escaparHtml(fuente)}" target="_blank" rel="noopener noreferrer">fuente</a>` : "";
  if (n.afiliacion_estado === "verificada") l.push(`Afiliación: <strong>${escaparHtml(af.afiliacion)}</strong>${enlaceFuente}`);
  else if (n.afiliacion_estado === "pendiente") l.push(`<span class="tag tag-warn">Sin verificar</span> ${escaparHtml(af.afiliacion)}${enlaceFuente} <span class="muted">(falta confirmar la fuente en afiliaciones.json)</span>`);
  else l.push(`<span class="muted">Sin afiliación registrada (Meta no la publica).</span>`);
  if (n.nombre) l.push(`<button type="button" class="btn" data-ficha data-ficha-nombre="${escaparHtml(n.nombre)}" data-ficha-id="${escaparHtml(n.page_id || "")}">✎ Validar perfil</button>`);
  if (urlHttp(n.ejemplo_link)) l.push(`<a href="${escaparHtml(n.ejemplo_link)}" target="_blank" rel="noopener noreferrer">Ver un anuncio en la Biblioteca de Meta ↗</a>`);
  return l.join("<br>");
}

function detenerRed() {
  guardarMemoriaRed();                          // antes de destruirla: su cámara y su selección pasan a la siguiente
  leerEstadoRed = () => null;
  if (redOrbital) { redOrbital.destruir(); redOrbital = null; }
}

const descargarBlob = (blob, nombre) => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = nombre;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

/** Monta la vista orbital en el escenario. Lanza si algo falla. */
function montarRedOrbital(g) {
  alcanceDeRed = state.resumen.alcance;
  const previa = memoriaParaRed("orbital");
  // Al reconstruir la red, el detalle de lo seleccionado se vuelve a mostrar si el panel ya lo mostraba o lo mostraba antes de recargar la página;
  // si hay otra sección abierta (p. ej. «Entidades») no se le quita el sitio.
  const reabrirDetalle = () => state.resumen.der === "detalle" || !!(previa && previa.detalle);
  redOrbital = window.RedOrbital.montar($("red-lienzo"), g, {
    restaurar: previa,
    cubierto: zonaCubiertaRed,            // lo que tapan los paneles: al seleccionar algo, la cámara lo centra en lo que queda libre
    // Con todo el país se dibujan las páginas más grandes de cada provincia y aparecen más al acercar el zoom o el cursor; al enfocar una
    // provincia caben todas, así que se dibujan completas.
    cupoMinimo: state.resumen.alcance === "todas" ? undefined : 400,
    filtros: filtrosGrafo,
    fechas: fechasDeGrafo(g),
    aristas: ARISTAS,
    partidoDe: (n) => partidoDe(n),
    colorPartido: (p) => coloresPartido.get(p),
    etiquetaArista,
    fmtUsd,
    tipoDestacado: tipoDestacadoRed,
    leyendaAbierta,
    alPlegarLeyenda: guardarLeyendaAbierta,
    ubicaciones: ubicacionesProvincias(),
    teselas: teselasRed(),
    filtroTeselas: filtroTeselasRed(),
    tema: document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark",      // el mapa base y los colores de la red siguen el tema
    disposicionMapa: disposicionEnMapa,
    alCambiarDisposicion: (mapa) => { guardarDisposicion(mapa); const s = $("rg-disp"); if (s) s.value = mapa ? "mapa" : "compacta"; },
    sinMovimiento: sinMovimiento(),
    // `restaurado`: la red se reconstruyó y volvió a seleccionar lo que había
    alSeleccionar: (n, vs, restaurado) => {
      fijarSelResumen(n ? selDeNodo(n) : null);
      if (!n) { if (state.resumen.der === "detalle") restaurarDerecho(); return; }
      if (restaurado && !reabrirDetalle()) return;
      mostrarDetalleNodo(n, vs);
    },
    alElegirArista: (e, restaurado) => {          // una línea de texto repetido (sus mensajes duplicados) o de mismo enlace, en el panel lateral
      fijarSelResumen(selDeArista(e));
      if (restaurado && !reabrirDetalle()) return;
      if (e.tipo === "partido" || e.tipo === "partido_prov") mostrarDetallePartido(e);
      else if (e.tipo === "enlace") mostrarDetalleEnlace(e); else mostrarDetalleTexto(e);
    }
  });
  const ctl = redOrbital;
  leerEstadoRed = () => { const e = redOrbital && redOrbital.estado(); return e ? { vista: "orbital", ...e } : null; };
  ctl.velocidad(velocidadOrbita);
  const disp = $("rg-disp"), dispCaja = $("rg-disp-caja");          // el selector de disposición solo aparece si hay ubicaciones de provincias
  if (dispCaja) dispCaja.hidden = !ctl.hayMapa;
  if (disp) disp.value = ctl.esMapa ? "mapa" : "compacta";
  aplicarFiltrosRed = () => ctl.refrescar();
  limpiarSeleccionRed = () => ctl.limpiarSeleccion();
  const sello = `${state.resumen.alcance}-${new Date().toISOString().slice(0, 10)}`;
  $("rg-png").onclick = () => { ctl.png().then((b) => b && descargarBlob(b, `noaiverdad-red-${sello}.png`)); };
  $("rg-csv").onclick = () => {
    const celda = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const nombre = new Map(g.nodos.map((n) => [n.id, n.nombre]));
    const cab = ["conexion", "origen", "destino", "anuncios", "gasto_min", "gasto_max", "primer_anuncio", "ultimo_anuncio", "detalle"];
    const oc = filtrosGrafo.ocultos || new Set(), to = filtrosGrafo.tiposOcultos || new Set();      // el CSV lleva lo que dejan ver los segmentadores
    const filas = g.aristas.filter((e) => nombre.has(e.a) && nombre.has(e.b) && !oc.has(e.a) && !oc.has(e.b) && !to.has(e.tipo)).map((e) => [e.tipo, nombre.get(e.a), nombre.get(e.b), e.anuncios ?? "", (e.gasto || {}).min ?? "", (e.gasto || {}).max ?? "", e.primero, e.ultimo, e.tipo === "alcance" ? `${Math.round((e.pct || 0) * 100)} % del alcance` : (e.detalles || []).join(" | ")].map(celda).join(","));
    descargarBlob(new Blob(["﻿" + [cab.join(",")].concat(filas).join("\r\n")], { type: "text/csv;charset=utf-8" }), `noaiverdad-red-${sello}.csv`);
  };
}

/**
 * Detalle de una provincia (sol) de la red. Dos cuentas distintas, siempre con su nombre:
 *  - «Con base aquí»: las páginas cuyos anuncios llegan sobre todo a esta provincia (lo que agrupa el sol); precio completo de sus anuncios.
 *  - «Llegan aquí»: los anuncios con al menos el 5 % de su alcance en la provincia, de páginas de cualquier provincia (lo que cuentan el
 *    mapa y el resumen); `llegan` es su fila de /api/ads/mapa (inversión prorrateada), o null si no aplica o aún no se cargó.
 */
function htmlDetalleHub(n, vs, llegan = null) {
  const paginas = vs.map((e) => (e.a === n ? e.b : e.a)).filter((x) => x.tipo === "pagina").sort((p, q) => q.gasto.medio - p.gasto.medio);
  const completo = n.anuncios_total != null;        // el backend nuevo suma TODAS las páginas con base aquí; el gráfico dibuja solo las de mayor inversión
  const base = completo
    ? `<strong>Con base aquí:</strong> ${fmtNum(n.paginas_total)} ${n.paginas_total === 1 ? "página" : "páginas"} · ${fmtNum(n.anuncios_total)} anuncios · inversión estimada ${escaparHtml(fmtUsd(n.gasto_total.medio))} <span class="muted">(precio completo de sus anuncios)</span>`
      + (n.paginas_total > n.paginas ? `<br><span class="muted">El gráfico dibuja las ${fmtNum(n.paginas)} páginas de mayor inversión.</span>` : "")
    : `${fmtNum(n.paginas)} páginas · ${fmtNum(n.anuncios)} anuncios · inversión estimada ${escaparHtml(fmtUsd(n.gasto.medio))}`;
  const alcanzan = llegan
    ? `<br><strong>Llegan aquí:</strong> ${fmtNum(llegan.anuncios)} anuncios de ${fmtNum(llegan.anunciantes)} anunciantes · inversión estimada ${escaparHtml(fmtUsd(llegan.gasto))} <span class="muted">(prorrateada por el % de alcance; páginas de cualquier provincia)</span>`
    : "";
  // Conectores: otras provincias donde un mismo partido tiene candidatos (solo los verificados, salvo que se incluyan los pendientes)
  const porPartido = new Map();
  vs.filter((e) => e.tipo === "partido_prov" && (e.verificada || filtrosGrafo.conPendientes)).forEach((e) => {
    const otra = e.a.id === n.id ? e.b : e.a;
    if (!porPartido.has(e.partido)) porPartido.set(e.partido, []);
    porPartido.get(e.partido).push(otra.nombre + (e.verificada ? "" : " (sin verificar)"));
  });
  const hermanas = porPartido.size
    ? `<br><strong>Candidatos del mismo partido en otras provincias</strong>:<br>${[...porPartido].map(([p, l]) => `· ${escaparHtml(p)} → ${l.map(escaparHtml).join(", ")}`).join("<br>")}` : "";
  return `<strong>${escaparHtml(n.nombre)}</strong> · provincia donde llegan más los anuncios de sus páginas<br>`
    + base + alcanzan + "<br>"
    + `<strong>Páginas con más inversión</strong>:<br>${paginas.slice(0, 8).map((p) => `· ${escaparHtml(p.nombre)} <span class="muted">(${escaparHtml(fmtUsd(p.gasto.medio))})</span>`).join("<br>")}`
    + (paginas.length > 8 ? `<br><span class="muted">y ${paginas.length - 8} más</span>` : "") + hermanas;
}

function renderGrafoRed(g) {
  const cont = $("rs-filtros-cuerpo");
  detenerRed();
  ultimoGrafoRed = g;
  if (!g || !g.nodos || !g.nodos.length) {
    cont.textContent = "Sin filtros: no hay conexiones para dibujar.";
    $("red-lienzo").innerHTML = cajaEstado({ tipo: "info", titulo: "Sin conexiones para dibujar", descripcion: "No hay anuncios con alcance por provincia en este alcance." });
    return;
  }
  const fechas = fechasDeGrafo(g);
  filtrosGrafo.fechaIdx = Math.max(0, fechas.length - 1);
  const af = g.afiliaciones || {};
  const todosPartidos = [...new Set(g.nodos.map((n) => n.afiliacion && n.afiliacion.partido).filter(Boolean))].sort((a, b) => a.localeCompare(b, "es"));
  const fijos = g.partidos || {}, libres = PALETA_AFIL.filter((c) => c !== "#9c36b5");
  let libre = 0;
  coloresPartido = new Map(todosPartidos.map((p) => [p, (fijos[p] && /^#[0-9a-fA-F]{6}$/.test(fijos[p].color || "")) ? fijos[p].color : libres[libre++ % libres.length]]));
  [...filtrosGrafo.partidos].forEach((p) => { if (!coloresPartido.has(p)) filtrosGrafo.partidos.delete(p); });
  const chip = (inner) => `<label class="chip" style="cursor:pointer">${inner}</label>`;
  const orbital = usarOrbital();
  cont.innerHTML = `
    <div id="rg-segmentos"></div>
    ${window.RedOrbital ? `<section class="rs-sec">
      <h3>Soles</h3>
      <label class="xsmall" id="rg-disp-caja" style="display:block">Disposición de los soles
        <select id="rg-disp" aria-label="Disposición de los soles">
          <option value="mapa" ${disposicionEnMapa() ? "selected" : ""}>Sobre el mapa de Ecuador</option>
          <option value="compacta" ${disposicionEnMapa() ? "" : "selected"}>Compacta</option>
        </select></label>
      <p class="xsmall muted">${"Cada provincia es un sol: sus páginas giran a su alrededor y cada pagador gira alrededor de la página que paga. Con poco zoom solo se dibujan las páginas de mayor inversión de cada provincia y las que tienen conexiones o afiliación; al acercar el zoom o el cursor aparecen más hasta ser todas."}</p>
    </section>` : ""}
    <section class="rs-sec">
      <h3>Afiliaciones</h3>
      <div class="rs-chips">${chip(`<input type="checkbox" id="rg-pendientes" style="width:auto;min-height:0" ${filtrosGrafo.conPendientes ? "checked" : ""}> Incluir partidos sin verificar (borde punteado)`)}</div>
    </section>
    <section class="rs-sec">
      <h3>Buscar</h3>
      <input id="red-buscar" type="search" placeholder="Buscar nombre…" aria-label="Buscar pagador o página en la red" value="${escaparHtml(filtrosGrafo.buscar)}">
    </section>
    <section class="rs-sec">
      <h3>Color por</h3>
      <select id="rg-color" aria-label="Color de los nodos">${[["tipo", "Tipo"], ["provincia", orbital ? "Provincia (las 3 con más inversión)" : "Provincia"], ["afiliacion", "Afiliación"]].map(([v, t]) => `<option value="${v}" ${filtrosGrafo.color === v ? "selected" : ""}>${t}</option>`).join("")}</select>
    </section>
    <section class="rs-sec">
      <h3>Opciones</h3>
      <div class="rs-chips">
        ${chip(`<input type="checkbox" id="rg-etiquetas" style="width:auto;min-height:0" ${filtrosGrafo.etiquetas ? "checked" : ""}> Mostrar montos en las líneas`)}
        ${chip(`<input type="checkbox" id="rg-activos" style="width:auto;min-height:0" ${filtrosGrafo.activos ? "checked" : ""}> Resaltar solo anuncios activos`)}
      </div>
      ${fechas.length > 1 ? `<label class="xsmall" style="display:flex;gap:8px;align-items:center;margin-top:8px">Anuncios iniciados hasta
        <input id="rg-fecha" type="range" min="0" max="${fechas.length - 1}" value="${fechas.length - 1}" style="flex:1"><span id="rg-fecha-v" style="font-family:var(--font-mono)">${escaparHtml(fechas[fechas.length - 1])}</span></label>` : ""}
      ${orbital ? `<label class="xsmall" style="display:flex;gap:8px;align-items:center;margin-top:8px">Velocidad de la órbita
        <input id="rg-orbita" type="range" min="0" max="3" step="0.25" value="${velocidadOrbita}" style="flex:1" title="0 = en pausa"><span id="rg-orbita-v" style="font-family:var(--font-mono)">${velocidadOrbita}×</span></label>
        <div class="rs-chips" style="margin-top:6px"><button type="button" class="btn" id="rg-reorg" title="Devuelve los sistemas a su posición inicial">Reorganizar sistemas</button></div>` : ""}
    </section>
    <section class="rs-sec">
      <h3>Exportar</h3>
      <div class="rs-chips"><button type="button" class="btn" id="rg-png">Descargar imagen</button><button type="button" class="btn" id="rg-csv">Descargar CSV</button></div>
    </section>
    <p class="xsmall muted">Afiliaciones: <strong>${af.verificada || 0}</strong> verificadas · ${af.pendiente || 0} sin verificar · ${af.sin_registro || 0} sin registro. Se editan en la sección <em>Entidades</em> o en <code>backend/afiliaciones.json</code>.</p>`;

  // la vista orbital lee los filtros en vivo (no recoloca nada); la primera vez (aún no hay red dibujada) se monta
  const redibuja = () => { if (redOrbital) redOrbital.refrescar(); else dibujarLienzoRed(g, fechas); };
  $("rg-orbita")?.addEventListener("input", (ev) => {
    velocidadOrbita = Number(ev.target.value); $("rg-orbita-v").textContent = `${velocidadOrbita}×`;
    if (redOrbital) redOrbital.velocidad(velocidadOrbita);
  });
  $("rg-reorg")?.addEventListener("click", () => { if (redOrbital) redOrbital.reorganizar(); });
  $("rg-disp")?.addEventListener("change", (ev) => { const mapa = ev.target.value === "mapa"; if (redOrbital) redOrbital.disposicion(mapa); else guardarDisposicion(mapa); });
  if (segAlcance !== state.resumen.alcance) { SEGMENTOS.forEach((d) => segReiniciar(d.clave)); segAlcance = state.resumen.alcance; }      // otro alcance: otra red, todo seleccionado
  const alCambiarSegmento = (clave, id, elegido) => {
    if (clave === "conector" && id === "texto" && elegido && redOrbital) redOrbital.destacar("texto");      // al marcar «Texto repetido», sus líneas destellan
  };
  montarSegmentos(cont, g, alCambiarSegmento);
  $("rg-etiquetas").addEventListener("change", (ev) => { filtrosGrafo.etiquetas = ev.target.checked; aplicarFiltrosRed(); });
  $("rg-activos").addEventListener("change", (ev) => { filtrosGrafo.activos = ev.target.checked; aplicarFiltrosRed(); });
  $("rg-color").addEventListener("change", (ev) => { filtrosGrafo.color = ev.target.value; redibuja(); });
  $("rg-fecha")?.addEventListener("input", (ev) => { filtrosGrafo.fechaIdx = Number(ev.target.value); $("rg-fecha-v").textContent = fechas[filtrosGrafo.fechaIdx]; aplicarFiltrosRed(); });
  $("red-buscar").addEventListener("input", (ev) => { filtrosGrafo.buscar = ev.target.value; aplicarFiltrosRed(); });
  // Incluir o no los partidos sin verificar cambia la lista del segmentador «Partido»: se vuelve a armar con todo seleccionado
  $("rg-pendientes").addEventListener("change", (ev) => {
    filtrosGrafo.conPendientes = ev.target.checked; segReiniciar("partido");
    montarSegmentos(cont, g, alCambiarSegmento);
    redibuja();
  });
  redibuja();
}

function dibujarLienzoRed(g, fechas) {
  detenerRed();
  if (usarOrbital()) {
    try { montarRedOrbital(g); return; }
    catch (e) { console.error("La vista orbital no está disponible:", e); }
  }
  $("red-lienzo").innerHTML = cajaEstado({ tipo: "error", titulo: "No se pudo dibujar la red", descripcion: "Este navegador no pudo iniciar la vista de la red (necesita canvas 2D). Prueba con otro navegador actualizado o recarga la página." });
}

function renderRed() {
  const d = state.resumen.red;
  if (!d) return;
  const g = d.grafo || { nodos: [], aristas: [], tipos: {} };
  $("red-kpis").innerHTML = "";
  renderGrafoRed(g);
  const nom = new Map(g.nodos.map((n) => [n.id, n.nombre]));
  const especiales = g.aristas.filter((e) => e.tipo !== "alcance");
  $("red-lista").innerHTML = especiales.length ? `<details><summary class="xsmall">Ver las conexiones especiales (${especiales.length})</summary>
    <ul class="xsmall" style="margin:6px 0 0;padding-left:18px">${especiales.map((e) => `<li>${escaparHtml(nom.get(e.a))} ${e.tipo === "pagador" ? "→" : "↔"} ${escaparHtml(nom.get(e.b))} <span class="muted">(${escaparHtml(ARISTAS[e.tipo].nombre)}${e.tipo === "partido_prov" && !e.verificada ? " · sin verificar" : ""})</span>${e.tipo === "pagador" ? `: ${fmtNum(e.anuncios)} anuncios, ${escaparHtml(fmtUsd(e.gasto.min))}–${escaparHtml(fmtUsd(e.gasto.max))}` : ((e.detalles || []).length ? `: ${e.detalles.map(escaparHtml).join("; ")}` : "")}${urlHttp(e.ejemplo_link) ? ` · <a href="${escaparHtml(e.ejemplo_link)}" target="_blank" rel="noopener noreferrer">ver un anuncio</a>` : ""}</li>`).join("")}</ul></details>`
    : "";
  const parcial = d.estado && d.estado.parcial ? " Muestra parcial: Meta tenía más anuncios de los que se descargan por consulta, así que pueden faltar vínculos (p. ej. textos repetidos o pagadores)." : "";
  const revisados = d.textos_revisados ? ` ${d.textos_revisados} grupo(s) de mensajes repetidos ya revisados no se dibujan (pestaña «Mensajes repetidos» → «Mostrar revisados»).` : "";
  $("red-nota").textContent = (d.nota || "") + " Las conexiones por texto o enlace indican coincidencias, no coordinación probada." + parcial + revisados;
}

// ---------------------------------------------------------------------------
// Entidades: afiliación política editable (se guarda en backend/afiliaciones.json)
// ---------------------------------------------------------------------------
const TIPOS_ENTIDAD = [["", "Sin clasificar"], ["persona", "Persona"], ["candidato", "Candidato/a"], ["partido", "Partido o movimiento"], ["institucion", "Institución"], ["gobierno", "Gobierno"], ["medio", "Medio"], ["agencia", "Agencia"], ["empresa", "Empresa"], ["otro", "Otro"]];
const FILTROS_ENTIDAD = [["todas", "Todas"], ["personas", "Personas"], ["medios", "Medios"], ["verificada", "Verificadas"], ["pendiente", "Sin verificar"], ["vacia", "Por completar"]];
const ETIQ_ESTADO = { verificada: ["Verificada", "tag-afil"], pendiente: ["Sin verificar", "tag-afil pendiente"], vacia: ["Por completar", ""] };
const entidadesUI = { datos: null, filas: [], filtro: "todas", buscar: "" };

const estadoEntidad = (f) => (f.verificado && f.afiliacion && f.fuente ? "verificada" : (f.afiliacion ? "pendiente" : "vacia"));

// «Neutral»: valor reservado de Partido para un medio que informa sin alinearse con un partido (otros medios sí lo están). Mismos valores y
// misma regla que backend/ads_library.py: solo los medios pueden ser neutrales y, sin afiliación escrita, la entrada lleva el texto habitual.
const PARTIDO_NEUTRAL = "Neutral", AFIL_NEUTRAL = "Medio neutral: sin alineación partidista", TIPOS_NEUTRALES = ["medio"];
const esNeutral = (p) => normalizar(p || "") === "neutral";
const aceptaNeutral = (tipo) => !tipo || TIPOS_NEUTRALES.includes(tipo);
const errorNeutral = (f) => (esNeutral(f.partido) && !aceptaNeutral(f.tipo) ? "«Neutral» solo se usa en medios: cambia el tipo a «Medio» o elige otro partido." : "");
/** Todos los ID de página de una entidad (una persona puede tener varias páginas): el principal y los de `page_ids`. */
const idsDeEntidad = (f) => [...new Set([f.page_id, ...(Array.isArray(f.page_ids) ? f.page_ids : [])].filter(Boolean).map(String))];
const codigoEdicion = () => { try { return sessionStorage.getItem("noai_edit_token") || ""; } catch (e) { return ""; } };

/** POST a la API (el primer origen que la tenga). Lanza un Error con `estado` si el servidor rechaza la petición. */
async function enviarApi(ruta, cuerpo) {
  let ultimo = new Error("sin origen disponible");
  for (const origen of origenesApi()) {
    try {
      const cab = { "Content-Type": "application/json" };
      if (codigoEdicion()) cab["X-Edit-Token"] = codigoEdicion();
      const res = await fetch(origen + ruta, { method: "POST", headers: cab, body: JSON.stringify(cuerpo) });
      const dato = await res.json().catch(() => ({}));
      if (!res.ok) {
        const err = new Error(typeof dato.detail === "string" ? dato.detail : `HTTP ${res.status}`);
        err.estado = res.status;
        throw err;
      }
      return dato;
    } catch (e) {
      if (e.estado && e.estado !== 404 && e.estado !== 405) throw e;
      ultimo = e;
    }
  }
  throw ultimo;
}

async function cargarEntidades() {
  const caja = $("entidades-lista");
  caja.innerHTML = cajaEstado({ tipo: "carga", titulo: "Cargando entidades...", descripcion: "Leyendo backend/afiliaciones.json y las páginas con más inversión.", filas: 4 });
  try {
    const cab = codigoEdicion() ? { "X-Edit-Token": codigoEdicion() } : undefined;
    const d = await fetchApi("/api/ads/afiliaciones?faltantes=60", { timeout: 60000, headers: cab });
    if (d.error) throw new Error(d.error);
    entidadesUI.datos = d;
    entidadesUI.filas = (d.entidades || []).map((e) => ({ ...e, nueva: false }))
      .concat((d.faltantes || []).map((f) => ({ nombre: f.nombre, page_id: f.page_id, tipo: null, afiliacion: null, partido: null, fuente: null, verificado: false, problemas: [], nueva: true, anuncios: f.anuncios, gasto_medio: f.gasto_medio })));
    pintarBaseEntidades();
  } catch (e) {
    errorEnCaja(caja, `No se pudieron cargar las entidades (${e.message}).`, cargarEntidades);
  }
}

function pintarBaseEntidades() {
  const U = entidadesUI, d = U.datos, caja = $("entidades-lista");
  const aviso = d.editable ? "" : `<div class="notice xsmall" style="margin-bottom:10px"><strong>Solo lectura.</strong> ${d.requiere_codigo
    ? `El servidor pide un código de edición: <input id="ent-codigo" type="password" placeholder="Código" style="width:160px;display:inline-block;min-height:30px"> <button type="button" class="btn" id="ent-usar-codigo">Usar código</button>`
    : "Las afiliaciones solo se pueden editar desde el mismo equipo donde corre el servidor (o configurando AFIL_EDIT_TOKEN en el backend)."}</div>`;
  const hecho = U.aviso ? `<div class="notice xsmall" role="status" style="margin-bottom:10px">${escaparHtml(U.aviso)}</div>` : "";
  U.aviso = "";
  caja.innerHTML = `${aviso}${hecho}
    <p id="ent-resumen" class="xsmall muted"></p>
    <div class="toolbar" role="group" aria-label="Filtrar entidades">
      ${FILTROS_ENTIDAD.map(([v, t]) => `<button type="button" class="chip" data-filtro="${v}" aria-pressed="${U.filtro === v}">${t}</button>`).join("")}
      <input id="ent-buscar" type="search" placeholder="Buscar nombre, partido…" aria-label="Buscar entidades" value="${escaparHtml(U.buscar)}" style="flex:1;min-width:160px;max-width:280px">
      <button type="button" class="btn" id="ent-recargar">Recargar</button>
    </div>
    <div id="ent-union" class="ent-union" hidden></div>
    <div id="ent-filas"></div>`;
  pintarFilasEntidades();
  pintarBarraUnion();
}

// --- Unificar entidades: la misma persona con otro nombre, el pagador con su segundo nombre u otra página ---------------------------
// Se marcan dos o más filas (casilla, o Shift/Ctrl + clic en el nombre) y se pulsa «Unificar»: el servidor las une en una sola entrada.
function alternarMarca(i, valor) {
  const f = entidadesUI.filas[i];
  if (!f || !(entidadesUI.datos && entidadesUI.datos.editable)) return;
  f.sel = valor === undefined ? !f.sel : !!valor;
  const form = document.querySelector(`.ent-fila[data-i="${i}"]`);
  if (form) { form.classList.toggle("ent-marcada", f.sel); const c = form.querySelector("input[data-marca]"); if (c) c.checked = f.sel; }
  pintarBarraUnion();
}

function pintarBarraUnion() {
  const barra = $("ent-union");
  if (!barra) return;
  const m = filasMarcadas();
  if (!m.length) { barra.hidden = true; barra.innerHTML = ""; return; }
  barra.hidden = false;
  const nombres = m.map(([f]) => `«${escaparHtml(f.nombre)}»`).join(", ");
  barra.innerHTML = m.length === 1
    ? `<div class="small"><strong>1 marcada:</strong> ${nombres}. Marca otra (con su casilla o con Shift + clic en su nombre) para unificarlas.</div>
       <div class="ent-union-acciones"><button type="button" class="btn" data-union="limpiar">Quitar la marca</button></div>`
    : `<div class="small"><strong>${m.length} marcadas:</strong> ${nombres}.</div>
       <div class="ent-union-acciones"><button type="button" class="btn btn-primary" data-union="abrir">Unificar…</button><button type="button" class="btn" data-union="limpiar">Quitar las marcas</button></div>`;
}

/** La fila que conviene conservar: verificada, si no con afiliación, si no la que ya tiene entrada. */
function principalSugerida(m) {
  const peso = (f) => (estadoEntidad(f) === "verificada" ? 3 : (f.afiliacion ? 2 : (f.nueva ? 0 : 1)));
  return m.map(([f], k) => [peso(f), -k, f]).sort((a, b) => b[0] - a[0] || b[1] - a[1])[0][2];
}

function abrirUnificar() {
  const barra = $("ent-union"), m = filasMarcadas();
  if (!barra || m.length < 2) return;
  const sug = principalSugerida(m);
  const etiqueta = (f) => (f.nueva ? "Nueva" : ETIQ_ESTADO[estadoEntidad(f)][0]);
  barra.innerHTML = `
    <div class="small"><strong>Unificar ${m.length} entidades en una</strong>: es la misma persona con otro nombre (por ejemplo el pagador con su segundo nombre) u otra página.</div>
    <fieldset><legend class="xsmall muted">Nombre que se conserva</legend>
      ${m.map(([f, i]) => `<label class="ent-opcion"><input type="radio" name="ent-principal" value="${i}" ${f === sug ? "checked" : ""}> ${escaparHtml(f.nombre)} <span class="xsmall muted">${etiqueta(f)}</span></label>`).join("")}
    </fieldset>
    <label class="xsmall muted" style="display:block;margin-top:8px">Nombre final (puedes corregirlo, por ejemplo con la ñ)
      <input id="ent-union-nombre" type="text" value="${escaparHtml(sug.nombre)}" style="margin-top:3px;display:block;width:100%"></label>
    <div id="ent-union-resumen" class="xsmall" style="margin-top:8px"></div>
    <div class="ent-union-acciones"><button type="button" class="btn btn-primary" data-union="confirmar">Unificar</button><button type="button" class="btn" data-union="cancelar">Cancelar</button><span id="ent-union-msg" class="ent-msg xsmall muted" role="status"></span></div>`;
  resumenUnion();
}

/** Qué pasará al confirmar (el servidor calcula lo mismo y devuelve los conflictos reales). */
function resumenUnion() {
  const radio = document.querySelector('input[name="ent-principal"]:checked'), caja = $("ent-union-resumen");
  if (!radio || !caja) return;
  const fp = entidadesUI.filas[Number(radio.value)], otras = filasMarcadas().map(([f]) => f).filter((f) => f !== fp);
  const final = ($("ent-union-nombre").value || "").trim() || fp.nombre;
  const ids = [...new Set([...idsDeEntidad(fp), ...otras.flatMap(idsDeEntidad)])];
  const vistos = new Set([normalizar(final)]), alternos = [];
  [fp.nombre, ...otrosNombresDe(fp), ...otras.flatMap((f) => [f.nombre, ...otrosNombresDe(f)])].forEach((n) => {
    const k = normalizar(n);
    if (k && !vistos.has(k)) { vistos.add(k); alternos.push(n); }
  });
  const avisos = [], mismaAfil = (f) => normalizar(f.afiliacion || "") === normalizar(fp.afiliacion || "") && normalizar(f.partido || "") === normalizar(fp.partido || "");
  if (!fp.afiliacion) {
    const o = otras.find((f) => f.afiliacion);
    if (o) avisos.push(`«${fp.nombre}» no tenía afiliación: se tomará la de «${o.nombre}» (${o.afiliacion}).`);
  } else otras.filter((f) => f.afiliacion && !mismaAfil(f)).forEach((f) => avisos.push(`«${f.nombre}» decía «${f.afiliacion}»; se conservará «${fp.afiliacion}».`));
  caja.innerHTML = `<ul>
    <li>Quedará una sola entrada: <strong>${escaparHtml(final)}</strong>${estadoEntidad(fp) === "verificada" ? " (verificada)" : ""}.</li>
    ${ids.length ? `<li>ID de página: ${escaparHtml(ids.join(" · "))}.</li>` : ""}
    ${alternos.length ? `<li>Otros nombres: ${alternos.map(escaparHtml).join(" · ")}.</li>` : ""}
    ${avisos.map((a) => `<li class="ent-error">${escaparHtml(a)}</li>`).join("")}
    <li class="muted">Se ${otras.length === 1 ? "borra la otra entrada" : `borran las otras ${otras.length} entradas`} del archivo; sus anuncios pasan a contarse como de esta entidad.</li></ul>`;
}

async function confirmarUnificar() {
  const radio = document.querySelector('input[name="ent-principal"]:checked'), msg = $("ent-union-msg"), btn = document.querySelector('[data-union="confirmar"]');
  if (!radio || !msg || !btn) return;
  const fp = entidadesUI.filas[Number(radio.value)], otras = filasMarcadas().map(([f]) => f).filter((f) => f !== fp);
  const final = ($("ent-union-nombre").value || "").trim();
  const ref = (f) => ({ nombre: f.nombre, page_id: f.page_id ? String(f.page_id) : null });
  btn.disabled = true; msg.className = "ent-msg xsmall muted"; msg.textContent = "Unificando…";
  try {
    const r = await enviarApi("/api/ads/afiliaciones/unificar", { principal: ref(fp), otras: otras.map(ref), nombre_final: final && final !== fp.nombre ? final : null });
    entidadesUI.aviso = `Unificadas en «${r.entidad.nombre}»` + ((r.conflictos || []).length ? `. Ojo: ${r.conflictos.join(" ")}` : ".");
    await cargarEntidades();                 // vuelve a leer el archivo: desaparecen las entradas absorbidas y se limpian las marcas
    refrescarPorAfiliacion();
  } catch (e) {
    msg.className = "ent-msg xsmall ent-error"; msg.textContent = e.estado ? e.message : `No se pudo unificar (${e.message})`; btn.disabled = false;
  }
}

const otrosNombresDe = (f) => (Array.isArray(f.otros_nombres) ? f.otros_nombres : []);
const filasMarcadas = () => entidadesUI.filas.map((f, i) => [f, i]).filter(([f]) => f.sel);

function htmlFilaEntidad(f, i, editable) {
  const [txt, cls] = f.nueva ? ["Nueva", ""] : ETIQ_ESTADO[estadoEntidad(f)];
  const dis = editable ? "" : "disabled";
  const otros = otrosNombresDe(f);
  const bloqueo = f.sucia ? errorNeutral(f) : "";           // «Neutral» en una entidad que no es un medio: no se puede guardar así
  return `<form class="ent-fila${f.sel ? " ent-marcada" : ""}" data-i="${i}" autocomplete="off">
    <div class="ent-cab">
      <label class="ent-marca" title="Marcar para unificar con otra entrada (también: Shift + clic en el nombre)"><input type="checkbox" data-marca ${f.sel ? "checked" : ""} ${dis} aria-label="Marcar «${escaparHtml(f.nombre)}» para unificar"></label>
      <strong class="ent-nombre">${escaparHtml(f.nombre)}</strong> <span class="tag ${cls}">${txt}</span>
      ${f.nueva ? `<span class="xsmall muted">USD ${fmtNum(f.gasto_medio)} · ${fmtNum(f.anuncios)} anuncios</span>` : ""}
      ${idsDeEntidad(f).length ? `<span class="xsmall muted" style="font-family:var(--font-mono)">${idsDeEntidad(f).length > 1 ? "ids" : "id"} ${escaparHtml(idsDeEntidad(f).join(" · "))}</span>` : ""}
      <button type="button" class="btn ent-ver-anuncios" aria-expanded="false" title="Todos los anuncios que esta entidad publica o paga">Ver anuncios</button></div>
    ${otros.length ? `<div class="ent-otros xsmall muted">También como: ${otros.map(escaparHtml).join(" · ")}</div>` : ""}
    <div class="ent-campos">
      <label>Tipo<select data-campo="tipo" ${dis}>${TIPOS_ENTIDAD.map(([v, t]) => `<option value="${v}" ${(f.tipo || "") === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <div class="ent-partido"><label>Partido<input data-campo="partido" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-expanded="false" aria-controls="ent-sug-${i}" value="${escaparHtml(f.partido || "")}" placeholder="${aceptaNeutral(f.tipo) ? "p. ej. ADN o Neutral" : "p. ej. ADN"}" title="Partido o movimiento. Un medio que informa sin alineación partidista se marca «Neutral»." ${dis}></label>
        <ul class="ent-sug" id="ent-sug-${i}" role="listbox" aria-label="Partidos sugeridos" hidden></ul></div>
      <label class="ent-ancho">Afiliación<input data-campo="afiliacion" value="${escaparHtml(f.afiliacion || "")}" placeholder="Partido, cargo o condición" ${dis}></label>
      <label class="ent-ancho">Fuente (enlace)<input data-campo="fuente" type="url" value="${escaparHtml(f.fuente || "")}" placeholder="https://…" ${dis}></label>
      <label class="ent-completa">Otros nombres<input data-campo="otros_nombres" value="${escaparHtml(otros.join("; "))}" placeholder="Otro nombre de la misma entidad (p. ej. el pagador declarado); separa varios con «;»" ${dis}></label>
      <label class="ent-ver"><input type="checkbox" data-campo="verificado" ${f.verificado ? "checked" : ""} ${dis}> Verificada</label>
      <button type="submit" class="btn btn-primary" ${editable && f.sucia && !bloqueo ? "" : "disabled"}>Guardar</button>
      <span class="ent-msg xsmall ${f.error || bloqueo ? "ent-error" : "muted"}" role="status">${escaparHtml(f.msg || bloqueo)}</span>
    </div>
    ${(f.problemas || []).length ? `<ul class="prob xsmall">${f.problemas.map((p) => `<li>${escaparHtml(p)}</li>`).join("")}</ul>` : ""}
    <div class="ent-anuncios rs-anuncios" hidden></div>
  </form>`;
}

function resumenEntidades() {
  const U = entidadesUI, reales = U.filas.filter((f) => !f.nueva), cuenta = (e) => reales.filter((f) => estadoEntidad(f) === e).length;
  const neutrales = reales.filter((f) => esNeutral(f.partido)).length;
  $("ent-resumen").innerHTML = `${reales.length} entradas en el archivo · <strong>${cuenta("verificada")}</strong> verificadas · ${cuenta("pendiente")} sin verificar · ${cuenta("vacia")} por completar${neutrales ? ` · ${neutrales} ${neutrales === 1 ? "medio neutral" : "medios neutrales"}` : ""} · ${U.filas.length - reales.length} páginas con inversión aún sin entrada`;
}

function pintarFilasEntidades() {
  const U = entidadesUI, editable = !!(U.datos && U.datos.editable), q = normalizar(U.buscar);
  cerrarSugerencias();                                       // las filas se vuelven a dibujar: la lista abierta ya no tendría campo
  const antesDeSeg = U.filas.map((f, i) => [f, i]).filter(([f]) => {
    if (U.filtro === "personas" && !["persona", "candidato"].includes(f.tipo)) return false;
    if (U.filtro === "medios" && f.tipo !== "medio") return false;
    if (["verificada", "pendiente", "vacia"].includes(U.filtro) && estadoEntidad(f) !== U.filtro) return false;
    return !q || normalizar(`${f.nombre} ${f.afiliacion || ""} ${f.partido || ""} ${f.tipo || ""} ${idsDeEntidad(f).join(" ")}`).includes(q);
  });
  // segmentadores de la red: quedan las entidades que siguen a la vista en ella (las que no tienen anuncios en la red no pasan mientras se filtra)
  const visibles = !segVisibles ? antesDeSeg : antesDeSeg.filter(([f]) => segPasa(idsDeEntidad(f), [f.nombre].concat(Array.isArray(f.otros_nombres) ? f.otros_nombres : [])));
  $("ent-filas").innerHTML = htmlAvisoSeg(visibles.length, antesDeSeg.length, "entidades") + (visibles.length ? visibles.map(([f, i]) => htmlFilaEntidad(f, i, editable)).join("")
    : cajaEstado({ tipo: "info", titulo: "Ninguna entidad coincide", descripcion: segVisibles && antesDeSeg.length ? "Ninguna entidad de esta lista pasa los filtros de la red." : "Prueba con otro filtro o quita la búsqueda." }));
  resumenEntidades();
}

const refrescarPorAfiliacion = debounce(() => {
  state.resumen.top = null; state.resumen.mensajes = null; state.resumen.red = null;
  cargarResumen(state.resumen.alcance, { silencioso: true });      // la red se vuelve a dibujar con la misma cámara y la misma selección
}, 1500);

async function guardarEntidad(i, form) {
  const f = entidadesUI.filas[i], btn = form.querySelector("button[type=submit]"), msg = form.querySelector(".ent-msg");
  btn.disabled = true; msg.className = "ent-msg xsmall muted"; msg.textContent = "Guardando…";
  try {
    const r = await enviarApi("/api/ads/afiliaciones", { nombre: f.nombre, page_id: f.page_id ? String(f.page_id) : null, page_ids: Array.isArray(f.page_ids) ? f.page_ids.map(String) : null, otros_nombres: Array.isArray(f.otros_nombres) ? f.otros_nombres : null, tipo: f.tipo || null, afiliacion: f.afiliacion || null, partido: f.partido || null, fuente: f.fuente || null, verificado: !!f.verificado });
    Object.assign(f, r.entidad, { nueva: false, sucia: false, error: false, msg: "Guardado en el servidor ✓" });
    const padre = form.parentElement, desdeFicha = !!form.closest("#ficha");
    form.outerHTML = htmlFilaEntidad(f, i, true);
    padre.querySelector(`.ent-fila[data-i="${i}"] select`)?.focus();
    if (desdeFicha) { if ($("ent-filas")) pintarFilasEntidades(); }       // la lista de Entidades muestra la misma entrada
    else if (fichaUI.i === i && !$("ficha").hidden) pintarFichaForm();    // y la ficha, si está abierta sobre ella
    else resumenEntidades();
    refrescarPorAfiliacion();
  } catch (e) {
    f.error = true; f.msg = e.estado ? e.message : `No se pudo guardar (${e.message})`;
    msg.className = "ent-msg xsmall ent-error"; msg.textContent = f.msg; btn.disabled = false;
  }
}

/**
 * Al cambiar Tipo o Partido en una fila: elegir «Neutral» deja la entidad como medio y con su afiliación habitual; si el tipo no es un medio,
 * devuelve el aviso (y la fila no se puede guardar así). Los campos que cambia se actualizan en la fila y en `f`.
 */
function ajustarNeutral(form, f, campo, ev) {
  const tipo = form.querySelector('[data-campo="tipo"]'), partido = form.querySelector('[data-campo="partido"]'), afil = form.querySelector('[data-campo="afiliacion"]');
  if (esNeutral(f.partido)) {
    if (ev.type === "change") { f.partido = PARTIDO_NEUTRAL; partido.value = PARTIDO_NEUTRAL; }       // una sola grafía (al salir del campo, no mientras se teclea)
    if (!f.tipo) { f.tipo = "medio"; tipo.value = "medio"; }
    if (aceptaNeutral(f.tipo) && !f.afiliacion) { f.afiliacion = AFIL_NEUTRAL; afil.value = AFIL_NEUTRAL; }      // con otro tipo no se rellena: solo se avisa
  } else if (campo === "partido" && f.afiliacion === AFIL_NEUTRAL) {
    f.afiliacion = null; afil.value = "";                                                              // el texto automático ya no corresponde
  }
  partido.placeholder = aceptaNeutral(f.tipo) ? "p. ej. ADN o Neutral" : "p. ej. ADN";
  return errorNeutral(f);
}

// --- Sugerencias de Partido: lista propia junto al campo, no un <datalist>. El menú nativo del navegador sale desplazado en algunos
// entornos (p. ej. el navegador integrado de la app de escritorio) y no se puede colocar; esta lista vive en la página y siempre queda pegada. ---
const NOTA_NEUTRAL = "Medio que informa sin alineación partidista";
const sug = { input: null, lista: null, items: [], activo: -1 };

/** Partidos ya guardados (sin repetidos) y, al principio, «Neutral» si la fila puede serlo. Con texto escrito, solo los que lo contienen. */
function opcionesPartido(f, texto) {
  const usados = [...new Set(entidadesUI.filas.filter((x) => !x.sucia).map((x) => x.partido).filter((p) => p && !esNeutral(p)))].sort((a, b) => a.localeCompare(b, "es"));
  const todas = [...(aceptaNeutral(f.tipo) ? [{ valor: PARTIDO_NEUTRAL, nota: NOTA_NEUTRAL }] : []), ...usados.map((valor) => ({ valor }))];
  const q = normalizar(texto);
  return !q || todas.some((o) => normalizar(o.valor) === q) ? todas : todas.filter((o) => normalizar(o.valor).includes(q));      // un valor ya elegido deja ver todas
}

function cerrarSugerencias() {
  if (!sug.lista) return;
  sug.lista.hidden = true; sug.lista.innerHTML = "";
  sug.input.setAttribute("aria-expanded", "false"); sug.input.removeAttribute("aria-activedescendant");
  sug.input = sug.lista = null; sug.items = []; sug.activo = -1;
}

function abrirSugerencias(input, texto) {
  const form = input.closest(".ent-fila"), f = form && entidadesUI.filas[Number(form.dataset.i)], lista = form && form.querySelector(".ent-sug");
  if (!f || !lista) return;
  if (sug.lista) cerrarSugerencias();
  const items = opcionesPartido(f, texto);
  if (!items.length) return;
  Object.assign(sug, { input, lista, items, activo: -1 });
  lista.innerHTML = items.map((o, k) => `<li role="option" id="${lista.id}-${k}" data-valor="${escaparHtml(o.valor)}" aria-selected="false"><span>${escaparHtml(o.valor)}</span>${o.nota ? `<small>${escaparHtml(o.nota)}</small>` : ""}</li>`).join("");
  lista.hidden = false; lista.classList.remove("arriba");
  input.setAttribute("aria-expanded", "true");
  const r = input.getBoundingClientRect(), alto = Math.min(lista.scrollHeight, 232);
  lista.classList.toggle("arriba", innerHeight - r.bottom < alto + 12 && r.top > innerHeight - r.bottom);      // sin sitio debajo y con más arriba: se abre hacia arriba
}

function moverSugerencia(delta) {
  const n = sug.items.length;
  if (!sug.lista || !n) return;
  sug.activo = sug.activo < 0 ? (delta > 0 ? 0 : n - 1) : (sug.activo + delta + n) % n;
  sug.lista.querySelectorAll("li").forEach((li, k) => {
    const on = k === sug.activo;
    li.setAttribute("aria-selected", String(on));
    if (on) { sug.input.setAttribute("aria-activedescendant", li.id); li.scrollIntoView({ block: "nearest" }); }
  });
}

function elegirSugerencia(valor) {
  const input = sug.input;
  if (!input) return;
  input.value = valor;
  cerrarSugerencias();
  input.dispatchEvent(new Event("input", { bubbles: true }));       // mismo camino que al teclear: actualiza la fila y aplica la regla de «Neutral»
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.focus();
}

const esCampoPartido = (el) => !!(el && el.matches && el.matches('input[data-campo="partido"]') && !el.disabled);

function initEntidades(caja = $("entidades-lista")) {
  if (!caja) return;
  const cambio = (ev) => {
    const campo = ev.target.dataset && ev.target.dataset.campo, form = ev.target.closest && ev.target.closest(".ent-fila");
    if (!campo || !form) return;
    const f = entidadesUI.filas[Number(form.dataset.i)];
    if (campo === "otros_nombres") f.otros_nombres = ev.target.value.split(/[;\n]+/).map((s) => s.trim()).filter(Boolean);    // lista (vacía = quitar todos)
    else f[campo] = ev.target.type === "checkbox" ? ev.target.checked : (ev.target.value.trim() || null);
    const aviso = campo === "tipo" || campo === "partido" ? ajustarNeutral(form, f, campo, ev) : errorNeutral(f);
    f.sucia = true; f.msg = aviso; f.error = !!aviso;
    form.querySelector("button[type=submit]").disabled = !!aviso;
    const msg = form.querySelector(".ent-msg");
    msg.textContent = aviso; msg.className = `ent-msg xsmall ${aviso ? "ent-error" : "muted"}`;
  };
  caja.addEventListener("input", cambio);
  caja.addEventListener("change", cambio);
  caja.addEventListener("mousedown", (ev) => { if (ev.shiftKey && ev.target.closest(".ent-nombre")) ev.preventDefault(); });    // Shift + clic no selecciona texto
  // Sugerencias de Partido (ver opcionesPartido): se abren al enfocar el campo, al hacer clic o con la flecha abajo, y se filtran al teclear.
  caja.addEventListener("focusin", (ev) => { if (esCampoPartido(ev.target) && ev.relatedTarget) abrirSugerencias(ev.target, ev.target.value); });    // con Tab; con el ratón abre el clic
  caja.addEventListener("click", (ev) => { if (esCampoPartido(ev.target) && !sug.lista) abrirSugerencias(ev.target, ev.target.value); });
  caja.addEventListener("focusout", (ev) => { if (esCampoPartido(ev.target)) cerrarSugerencias(); });
  caja.addEventListener("input", (ev) => { if (ev.isTrusted && esCampoPartido(ev.target)) abrirSugerencias(ev.target, ev.target.value); });         // solo al teclear (no al elegir una opción)
  caja.addEventListener("mousedown", (ev) => {
    const li = ev.target.closest && ev.target.closest(".ent-sug li");
    if (!li) return;
    ev.preventDefault();                                           // el campo conserva el foco
    elegirSugerencia(li.dataset.valor);
  });
  caja.addEventListener("keydown", (ev) => {
    if (!esCampoPartido(ev.target)) return;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (!sug.lista) abrirSugerencias(ev.target, ""); else moverSugerencia(ev.key === "ArrowDown" ? 1 : -1);
    } else if (ev.key === "Enter") {
      if (sug.lista && sug.activo >= 0) { ev.preventDefault(); elegirSugerencia(sug.items[sug.activo].valor); }      // elige la opción marcada en vez de guardar la fila
      else cerrarSugerencias();
    } else if (ev.key === "Escape" && sug.lista) {
      ev.preventDefault(); ev.stopPropagation();                  // cierra solo la lista: no el panel
      cerrarSugerencias();
    } else if (ev.key === "Tab") cerrarSugerencias();
  });
  caja.addEventListener("change", (ev) => {
    if (ev.target.name !== "ent-principal") return;            // en la confirmación de «Unificar»: otro nombre principal
    $("ent-union-nombre").value = entidadesUI.filas[Number(ev.target.value)].nombre;
    resumenUnion();
  });
  caja.addEventListener("input", (ev) => { if (ev.target.id === "ent-union-nombre") resumenUnion(); });
  caja.addEventListener("submit", (ev) => { const form = ev.target.closest(".ent-fila"); if (!form) return; ev.preventDefault(); guardarEntidad(Number(form.dataset.i), form); });
  caja.addEventListener("click", (ev) => {
    const union = ev.target.closest("[data-union]");
    if (union) {
      const a = union.dataset.union;
      if (a === "abrir") abrirUnificar();
      else if (a === "confirmar") confirmarUnificar();
      else if (a === "cancelar") pintarBarraUnion();                                                      // vuelve a la lista de marcadas
      else { entidadesUI.filas.forEach((f) => { f.sel = false; }); pintarFilasEntidades(); pintarBarraUnion(); }   // quitar las marcas
      return;
    }
    const marca = ev.target.closest("input[data-marca]");
    if (marca) { alternarMarca(Number(marca.closest(".ent-fila").dataset.i), marca.checked); return; }
    const nombre = ev.target.closest(".ent-nombre");
    if (nombre && (ev.shiftKey || ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); alternarMarca(Number(nombre.closest(".ent-fila").dataset.i)); return; }
    const ver = ev.target.closest(".ent-ver-anuncios");
    if (ver) {                       // todos los anuncios de la entidad (los que publica y los que paga), bajo demanda
      const form = ver.closest(".ent-fila"), lista = form.querySelector(".ent-anuncios"), f = entidadesUI.filas[Number(form.dataset.i)];
      const abrir = lista.hidden;
      lista.hidden = !abrir; ver.setAttribute("aria-expanded", String(abrir)); ver.textContent = abrir ? "Ocultar anuncios" : "Ver anuncios";
      if (abrir && !lista.dataset.listo) {
        lista.dataset.listo = "1";
        montarListaAnuncios(lista, { entidad: f.nombre, page_id: idsDeEntidad(f).join(",") }, { titulo: "Todos los anuncios de esta entidad", mostrarRol: true });
      }
      return;
    }
    const filtro = ev.target.closest("[data-filtro]");
    if (filtro) {
      entidadesUI.filtro = filtro.dataset.filtro;
      caja.querySelectorAll("[data-filtro]").forEach((b) => b.setAttribute("aria-pressed", String(b === filtro)));
      pintarFilasEntidades();
    } else if (ev.target.id === "ent-recargar") cargarEntidades();
    else if (ev.target.id === "ent-usar-codigo") {
      try { sessionStorage.setItem("noai_edit_token", $("ent-codigo").value); } catch (e) { /* sin almacenamiento */ }
      cargarEntidades();
    }
  });
  caja.addEventListener("input", debounce((ev) => { if (ev.target.id === "ent-buscar") { entidadesUI.buscar = ev.target.value; pintarFilasEntidades(); } }, 200));
}

// ---------------------------------------------------------------------------
// Ficha de entidad: tarjeta flotante, disponible en todas las pestañas. Edita la misma entrada (entidadesUI.filas) que Conexiones → Entidades.
// ---------------------------------------------------------------------------
const fichaUI = { i: null };
const nombresDeEntidad = (f) => [f.nombre, ...otrosNombresDe(f)];

/** Índice de la entrada que corresponde a un nombre o id de página (también por «otros nombres»); si no existe, crea una entrada nueva. */
function filaParaFicha(nombre, pageId) {
  const filas = entidadesUI.filas, id = pageId ? String(pageId) : "", n = normalizar(nombre || "");
  let k = id ? filas.findIndex((f) => idsDeEntidad(f).includes(id)) : -1;
  if (k < 0 && n) k = filas.findIndex((f) => nombresDeEntidad(f).some((x) => normalizar(x) === n));
  if (k < 0 && nombre) {
    filas.push({ nombre, page_id: id || null, tipo: null, afiliacion: null, partido: null, fuente: null, verificado: false, problemas: [], nueva: true });
    k = filas.length - 1;
  }
  return k;
}

function pintarFichaForm() {
  const f = entidadesUI.filas[fichaUI.i], d = entidadesUI.datos, editable = !!(d && d.editable);
  $("ficha-titulo").textContent = f ? `Validar perfil · ${f.nombre}` : "Validar perfiles";
  $("ficha-form").innerHTML = (d && !editable ? `<div class="notice xsmall" style="margin-bottom:8px"><strong>Solo lectura.</strong> Para editar, desde Conexiones → Entidades introduce el código de edición del servidor.</div>` : "")
    + (f ? htmlFilaEntidad(f, fichaUI.i, editable)
      : `<p class="xsmall muted">Busca una entidad arriba, o pulsa ✎ junto al nombre de un anuncio o de un nodo de la red.</p>`);
}

function resultadosFicha(texto) {
  const ul = $("ficha-resultados"), t = normalizar(texto);
  if (!t) { ul.hidden = true; ul.innerHTML = ""; return; }
  const r = entidadesUI.filas.map((f, i) => [f, i])
    .filter(([f]) => normalizar(`${nombresDeEntidad(f).join(" ")} ${f.afiliacion || ""} ${f.partido || ""} ${idsDeEntidad(f).join(" ")}`).includes(t)).slice(0, 8);
  ul.innerHTML = r.length
    ? r.map(([f, i]) => `<li role="option" data-i="${i}"><span>${escaparHtml(f.nombre)}</span><small>${escaparHtml(f.partido || f.afiliacion || "sin afiliación")}</small></li>`).join("")
    : `<li class="vacio">Sin coincidencias</li>`;
  ul.hidden = false;
}

function elegirEnFicha(i) {
  fichaUI.i = i;
  $("ficha-buscar").value = ""; resultadosFicha("");
  pintarFichaForm();
  if ($("ent-filas")) pintarFilasEntidades();                  // la lista refleja lo que haya a medio editar en la ficha
  $("ficha-form").querySelector("select, input:not([type=checkbox])")?.focus();
}

function cerrarFicha() {
  $("ficha").hidden = true;
  $("btn-ficha").setAttribute("aria-expanded", "false");
  $("btn-ficha").focus();
}

/** Abre la ficha. Con nombre o id de página, sobre esa entidad; sin ellos, solo con el buscador (o la última entidad vista). */
async function abrirFicha(nombre, pageId) {
  const ficha = $("ficha");
  ficha.hidden = false; ficha.classList.remove("min");
  $("ficha-min").setAttribute("aria-expanded", "true");
  $("btn-ficha").setAttribute("aria-expanded", "true");
  if (!entidadesUI.datos) {
    $("ficha-form").innerHTML = cajaEstado({ tipo: "carga", titulo: "Cargando entidades...", descripcion: "Leyendo backend/afiliaciones.json.", filas: 2 });
    await cargarEntidades();
    if (!entidadesUI.datos) { $("ficha-form").innerHTML = `<p class="xsmall ent-error">No se pudieron cargar las entidades. Comprueba que el servidor esté en marcha.</p>`; return; }
  }
  if (nombre || pageId) { elegirEnFicha(filaParaFicha(nombre, pageId)); return; }
  pintarFichaForm();
  $("ficha-buscar").focus();
}

function initFicha() {
  const ficha = $("ficha");
  if (!ficha) return;
  initEntidades($("ficha-form"));                               // mismos controles y reglas que la pestaña Entidades
  $("btn-ficha").addEventListener("click", () => { if (ficha.hidden) abrirFicha(); else cerrarFicha(); });
  $("ficha-cerrar").addEventListener("click", cerrarFicha);
  $("ficha-min").addEventListener("click", () => {
    const min = ficha.classList.toggle("min");
    $("ficha-min").setAttribute("aria-expanded", String(!min));
  });
  ficha.addEventListener("keydown", (ev) => { if (ev.key === "Escape") cerrarFicha(); });          // la lista de partidos abierta ya consumió su Escape
  $("ficha-buscar").addEventListener("input", (ev) => resultadosFicha(ev.target.value));
  $("ficha-buscar").addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    const li = $("ficha-resultados").querySelector("li[data-i]");
    if (li) elegirEnFicha(Number(li.dataset.i));
  });
  $("ficha-resultados").addEventListener("mousedown", (ev) => {
    const li = ev.target.closest("li[data-i]");
    if (li) { ev.preventDefault(); elegirEnFicha(Number(li.dataset.i)); }
  });
  document.addEventListener("click", (ev) => {                   // botón ✎ en anuncios, red de conexiones, etc.
    const b = ev.target.closest && ev.target.closest("[data-ficha]");
    if (!b) return;
    ev.preventDefault(); ev.stopPropagation();
    abrirFicha(b.dataset.fichaNombre, b.dataset.fichaId);
  }, true);
}

function renderProveniencia(estado) {
  const el = $("resumen-fuente");
  if (!estado || estado.habilitado === false || !estado.configurado) { el.textContent = (estado && estado.mensaje) || "Sin datos de la Biblioteca de Anuncios de Meta."; return; }
  if (estado.ok === false && !estado.total_nacional) { el.textContent = "Biblioteca de Anuncios de Meta: no disponible en este momento."; return; }
  el.innerHTML = `Biblioteca de Anuncios de Meta · últimos <strong>${escaparHtml(estado.dias ?? "?")} días</strong> · actualizado <strong>${escaparHtml(fmtFechaHora(estado.actualizado))}</strong>`
    + (estado.desactualizado ? ` <span class="tag tag-warn" title="${escaparHtml(estado.aviso || "")}">Datos guardados: Meta no respondió</span>` : "")
    + (estado.solo_activos ? ` · <span class="tag tag-info" title="El interruptor «Solo activos» está encendido: se muestran únicamente los anuncios que siguen circulando (sin fecha de fin).">Solo activos: ${escaparHtml(fmtNum(estado.excluidos_inactivos || 0))} anuncios terminados no se cuentan</span>` : "")
    + (estado.rango_fechas ? ` · <span class="tag tag-info" title="Hay fechas elegidas en el calendario de la barra superior: se muestran solo los anuncios que circularon entonces. Los montos son los de todo el anuncio, no solo los de esos días.">Fechas: ${escaparHtml(textoRango(estado.rango_fechas.desde, estado.rango_fechas.hasta || estado.rango_fechas.desde))} · ${escaparHtml(fmtNum(estado.excluidos_fechas || 0))} anuncios de otras fechas no se cuentan</span>` : "")
    + (estado.retirados_por_meta ? ` · <span title="Anuncios que Meta retiró (sin el descargo de responsabilidad obligatorio, por incumplir sus normas publicitarias o de una cuenta o página inhabilitada): solo queda un aviso de Meta en su lugar, así que no se cuentan en ninguna cifra, lista ni gráfico.">sin <strong>${escaparHtml(fmtNum(estado.retirados_por_meta))}</strong> anuncios retirados por Meta</span>` : "");
  const palabras = (estado.terminos || []).filter((t) => t && t !== "*");      // «*» = todos los anuncios, no una palabra buscada
  const alcanceDatos = palabras.length
    ? `Anuncios políticos y de temas sociales que llegaron a Ecuador, consultados con los términos: ${palabras.join(", ")}`
    : "Todos los anuncios políticos y de temas sociales que llegaron a Ecuador en el período (se descargan completos, no solo los que mencionan ciertas palabras)";
  $("resumen-metodo").textContent = `${alcanceDatos}. Los datos se guardan en caché ${estado.cache_min ?? "?"} min (hora del servidor). Meta publica la inversión y las impresiones como rangos; la «inversión estimada» es el punto medio de cada rango. Para una provincia cuentan los anuncios que llegan allí (al menos el 5 % de su alcance), cada uno en proporción a su porcentaje: es una estimación, no un dato reportado.`;
}

/**
 * Totales de la pestaña Anunciantes. Sin filtros de la red son los del servidor (todos los anunciantes del alcance); con filtros se suman las
 * filas que pasan los segmentadores (provincia, conector, entidad), con la misma regla que el servidor: inversión estimada = punto medio del rango.
 */
function resumenAnunciantes(d) {
  if (!segVisibles && !selResumen) return d.resumen || {};
  const filas = (d.anunciantes || []).filter((a) => segPasa(a.page_id, a.page_name) && selPasa(a));
  const suma = (f) => filas.reduce((t, a) => t + (Number(f(a)) || 0), 0);
  const gasto = suma((a) => a.gasto.medio), top5 = filas.map((a) => a.gasto.medio).sort((x, y) => y - x).slice(0, 5).reduce((t, v) => t + v, 0);
  return {
    filtrado: true, anunciantes: filas.length, anuncios: suma((a) => a.anuncios),
    gasto_medio_total: Math.round(gasto), gasto_min_total: Math.round(suma((a) => a.gasto.min)), gasto_max_total: Math.round(suma((a) => a.gasto.max)),
    concentracion_top5: gasto && filas.length >= 10 ? top5 / gasto : null
  };
}

function renderKpis(d) {
  const r = resumenAnunciantes(d);
  if (!r.anuncios) {
    $("resumen-kpis").innerHTML = r.filtrado ? `<p class="xsmall muted" style="grid-column:1/-1;margin:0">Ningún anunciante pasa ${selResumen ? "la selección y los filtros" : "los filtros"} de la red: no hay totales que mostrar.</p>` : "";
    return;
  }
  const top5 = r.concentracion_top5 != null;
  $("resumen-kpis").innerHTML = `${r.filtrado ? `<p class="xsmall kpis-filtro" style="grid-column:1/-1;margin:0">${selResumen ? `Totales de lo seleccionado en la red: <strong>${escaparHtml(selResumen.etiqueta)}</strong>${segVisibles ? " (y los filtros)" : ""}.` : "Totales de lo seleccionado en los filtros de la red."}</p>` : ""}
    <div class="kpi"><strong>${fmtNum(r.anunciantes)}</strong><span>anunciantes</span></div>
    <div class="kpi"><strong>${fmtNum(r.anuncios)}</strong><span>anuncios</span></div>
    <div class="kpi"><strong>${escaparHtml(fmtUsd(r.gasto_medio_total))}</strong><span>inversión estimada</span><small>rango ${fmtNum(r.gasto_min_total)} – ${fmtNum(r.gasto_max_total)}</small></div>
    <div class="kpi"><strong>${top5 ? Math.round(r.concentracion_top5 * 100) + " %" : "—"}</strong><span>${top5 ? "del gasto en los 5 mayores" : "concentración: muestra insuficiente"}</span></div>`;
}

// --- Tabla de anunciantes ---------------------------------------------------
function ordenarAnunciantes(lista) {
  const { clave, dir } = state.resumen.orden;
  const val = { gasto: (a) => a.gasto.medio, impresiones: (a) => a.impresiones.medio, anuncios: (a) => a.anuncios, nombre: (a) => a.page_name.toLowerCase() };
  const f = val[clave] || val.gasto;
  const signo = dir === "asc" ? 1 : -1;
  return lista.slice().sort((a, b) => {
    const x = f(a), y = f(b);
    return (typeof x === "string" ? x.localeCompare(y, "es") : x - y) * signo;
  });
}

/** Los anunciantes que se ven: la búsqueda y, en una provincia, «solo páginas con base aquí» (las demás llegan a la provincia pero su alcance principal está en otra). */
function anunciantesFiltrados(lista) {
  const q = normalizar(state.resumen.buscar);
  let r = q ? lista.filter((a) => normalizar(`${a.page_name} ${a.financiadores.join(" ")}`).includes(q)) : lista;
  if (state.resumen.soloBase && state.resumen.alcance !== "todas") {
    const n = normalizar(etiquetaAlcance(state.resumen.alcance));
    r = r.filter((a) => a.region_principal && normalizar(a.region_principal.region) === n);
  }
  state.resumen.antesDeSeg = r.length;                 // cuántos había antes de aplicar los segmentadores de la red
  if (segVisibles) r = r.filter((a) => segPasa(a.page_id, a.page_name));
  if (selResumen) r = r.filter(selPasa);
  return r;
}

function renderAnunciantes() {
  const d = state.resumen.top;
  const cont = $("anunciantes-tabla");
  if (!d) return;
  const baseWrap = $("anunciantes-base-wrap");
  if (baseWrap) baseWrap.hidden = state.resumen.alcance === "todas";
  const lista = d.anunciantes || [];
  if (!lista.length) {
    cont.innerHTML = `<div class="state"><div class="state-title">Sin anunciantes</div><p>${escaparHtml((d.estado && d.estado.mensaje) || "No hay anunciantes con alcance en esta zona en el período consultado.")}</p></div>`;
    $("anunciantes-conteo").textContent = "";
    return;
  }

  const filtrados = anunciantesFiltrados(lista);
  const ordenados = ordenarAnunciantes(filtrados);
  const visibles = ordenados.slice(0, state.resumen.visibles);
  const maxGasto = Math.max(...lista.map((a) => a.gasto.medio), 1);
  const nacional = d.alcance === "nacional";
  const { clave, dir } = state.resumen.orden;

  $("anunciantes-conteo").textContent = `${filtrados.length} de ${lista.length} anunciantes`;

  const th = (texto, k, extra = "") => `<th scope="col" class="${extra}" ${clave === k ? `aria-sort="${dir === "asc" ? "ascending" : "descending"}"` : ""}><button type="button" data-sort="${k}">${texto}</button></th>`;

  const avisoSeg = htmlAvisoSel(filtrados.length) + htmlAvisoSeg(filtrados.length, state.resumen.antesDeSeg, "anunciantes");
  if (!visibles.length) {
    cont.innerHTML = avisoSeg + ((segVisibles || selResumen) && state.resumen.antesDeSeg
      ? `<div class="state"><div class="state-title">Sin coincidencias</div><p>Ningún anunciante de esta lista pasa ${selResumen ? "la selección y los filtros" : "los filtros"} de la red${selResumen ? " (en la red pueden verse páginas que no están en esta lista del alcance)" : ""}.</p></div>`
      : `<div class="state"><div class="state-title">Sin coincidencias</div><p>Ningún anunciante coincide con «${escaparHtml(state.resumen.buscar)}».</p></div>`);
    return;
  }

  const filas = visibles.map((a) => {
    const k = String(a.page_id || a.page_name);
    const abierto = state.resumen.abiertos.has(k);
    const flags = [];
    if (nacional && a.region_principal && a.region_principal.porcentaje >= 0.9) flags.push(`<span class="tag tag-warn" title="Indicador: más del 90 % de su alcance estimado está en una sola región">Alcance concentrado en ${escaparHtml(a.region_principal.region)}</span>`);
    if (a.pagado_por_tercero) flags.push(`<span class="tag tag-warn" title="Indicador: el pagador declarado a Meta no coincide con el nombre de la página. Puede ser una agencia o una razón social distinta; no implica irregularidad.">Pagador distinto de la página</span>`);
    const region = a.region_principal ? `${escaparHtml(a.region_principal.region)} · ${Math.round(a.region_principal.porcentaje * 100)} %` : "—";
    const detalle = abierto ? `
      <tr class="row-detail"><td colspan="5">
        <dl>
          <div><dt>Pagador(es) declarado(s)</dt><dd>${a.financiadores.length ? escaparHtml(a.financiadores.join(", ")) : "No declarado"}</dd></div>
          <div><dt>Inversión (rango)</dt><dd>${escaparHtml(fmtUsd(a.gasto.min))} – ${escaparHtml(fmtNum(a.gasto.max))}</dd></div>
          <div><dt>Impresiones (rango)</dt><dd>${fmtNum(a.impresiones.min)} – ${fmtNum(a.impresiones.max)}</dd></div>
          <div><dt>Región principal</dt><dd>${region}</dd></div>
          <div><dt>Costo por mil impresiones</dt><dd>${a.costo_por_mil != null ? "USD " + a.costo_por_mil.toLocaleString("es-EC", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "No calculable (muestra pequeña)"}</dd></div>
          <div><dt>Primer / último anuncio</dt><dd>${escaparHtml(formatearFechaSafe(a.primer_anuncio))} – ${escaparHtml(formatearFechaSafe(a.ultimo_anuncio))}</dd></div>
          <div><dt>Anuncios activos</dt><dd>${a.activos} de ${a.anuncios}</dd></div>
          <div><dt>En la Biblioteca de Anuncios</dt><dd>${enlace(urlBibliotecaPagina(a.page_id), "Ver todos sus anuncios") || "—"}</dd></div>
        </dl>
      </td></tr>` : "";
    return `
      <tr>
        <td>
          <div class="cell-name">${escaparHtml(a.page_name)}</div>
          ${filaAfil(a)}
          <div class="cell-sub">${a.financiadores.length ? "Paga: " + escaparHtml(a.financiadores.join(", ")) : "Pagador no declarado"}</div>
          ${flags.length ? `<div class="cell-flags">${flags.join("")}</div>` : ""}
          <button type="button" class="row-toggle" data-toggle="${escaparHtml(k)}" aria-expanded="${abierto}">${abierto ? "Ocultar detalles" : "Ver detalles"}</button>
        </td>
        <td class="num">${a.anuncios}<div class="cell-sub">${a.activos} activos</div></td>
        <td class="num" style="min-width:150px"><div class="bar" aria-hidden="true"><span style="width:${Math.max(3, Math.round(a.gasto.medio / maxGasto * 100))}%"></span></div>${escaparHtml(fmtUsd(a.gasto.medio))}<div class="cell-sub">${fmtNum(a.gasto.min)} – ${fmtNum(a.gasto.max)}</div></td>
        <td class="num">${fmtCompacto(a.impresiones.medio)}<div class="cell-sub">${fmtCompacto(a.impresiones.min)} – ${fmtCompacto(a.impresiones.max)}</div></td>
        <td>${region}</td>
      </tr>${detalle}`;
  }).join("");

  const quedan = ordenados.length - visibles.length;
  cont.innerHTML = `${avisoSeg}
    <div class="table-wrap">
      <table class="table tabla-anunciantes">
        <caption class="visually-hidden">Anunciantes políticos en Meta</caption>
        <thead><tr>${th("Anunciante", "nombre")}${th("Anuncios", "anuncios", "num")}${th("Inversión estimada", "gasto", "num")}${th("Impresiones", "impresiones", "num")}<th scope="col">Región principal</th></tr></thead>
        <tbody>${filas}</tbody>
      </table>
    </div>
    ${quedan > 0 ? `<div class="more-row"><button type="button" class="btn" data-mas>Mostrar ${Math.min(15, quedan)} más (${quedan} restantes)</button></div>` : ""}`;
}

function urlBibliotecaPagina(pageId) {
  return pageId ? `https://www.facebook.com/ads/library/?active_status=all&ad_type=political_and_issue_ads&country=EC&view_all_page_id=${encodeURIComponent(pageId)}` : "";
}

// --- Mensajes repetidos ------------------------------------------------------
const esGrupoRevisado = (g) => !!(g.revision && g.revision.estado === "completa");

/** Formulario en línea para marcar un grupo como revisado (esperable). `i` es la posición del grupo en `state.resumen.mensajes.grupos`. */
function htmlFormRevision(g, i, motivos) {
  return `
    <form class="rev-form" id="rev-form-${i}" data-i="${i}" hidden>
      <div>
        <label class="field-label" for="rev-motivo-${i}">Motivo</label>
        <select id="rev-motivo-${i}" name="motivo" required>
          <option value="">Elige un motivo…</option>
          ${motivos.map((m) => `<option value="${escaparHtml(m.id)}">${escaparHtml(m.texto)}</option>`).join("")}
        </select>
      </div>
      <div>
        <label class="field-label" for="rev-nota-${i}">Nota: qué revisaste</label>
        <input id="rev-nota-${i}" name="nota" type="text" maxlength="500" placeholder="Opcional; obligatoria con «Otro motivo»" autocomplete="off">
      </div>
      <fieldset>
        <legend>Qué cubre</legend>
        <label class="rev-opcion"><input type="radio" name="alcance" value="mensaje" checked><span><strong>Solo este mensaje</strong> entre estas ${g.n_paginas} páginas.</span></label>
        <label class="rev-opcion"><input type="radio" name="alcance" value="paginas"><span><strong>Cualquier mensaje repetido entre estas ${g.n_paginas} páginas</strong>, también los que aparezcan después. Si se suma otra página, el grupo vuelve a mostrarse.</span></label>
      </fieldset>
      <p class="xsmall muted">Revisar no dice que el mensaje sea bueno o malo: solo que ya se miró y deja de contarse como señal. Si son la misma persona u organización, mejor únelas en Entidades.</p>
      <p class="rev-error" role="alert" hidden></p>
      <div class="rev-acciones">
        <button type="submit" class="btn btn-primary">Guardar revisión</button>
        <button type="button" class="btn" data-men="cerrar" data-i="${i}">Cancelar</button>
      </div>
    </form>`;
}

function renderMensajes() {
  const d = state.resumen.mensajes;
  const cont = $("mensajes-lista");
  if (!d) return;
  const soloDistintos = $("mensajes-solo-distintos").checked;
  const sinAisladas = !!($("mensajes-sin-aisladas") && $("mensajes-sin-aisladas").checked);
  const hayRevisados = (d.total_revisados ?? 0) > 0;
  const verRevisados = hayRevisados && !!($("mensajes-ver-revisados") && $("mensajes-ver-revisados").checked);
  if ($("mensajes-revisados-caja")) {
    $("mensajes-revisados-caja").hidden = !hayRevisados;
    $("mensajes-n-revisados").textContent = String(d.total_revisados ?? 0);
  }
  const editable = !!d.editable, motivos = d.motivos_revision || [];
  // «coincidencias»: en cuántos grupos coinciden las mismas páginas. Un backend antiguo no lo envía: no se filtra nada.
  const antesDeSeg = (d.grupos || []).map((g, i) => [g, i])
    .filter(([g]) => (verRevisados || !esGrupoRevisado(g)) && (!soloDistintos || g.financiadores_distintos) && (!sinAisladas || (g.coincidencias ?? 2) >= 2));
  const textoElegido = segElegido("conector", "texto");
  const filas = !segVisibles ? antesDeSeg : antesDeSeg.filter(([g]) => textoElegido && (g.paginas || []).some((p) => segPasa(p.page_id, p.page_name)));
  const avisoSeg = htmlAvisoSeg(filas.length, antesDeSeg.length, "grupos");
  const aviso = state.resumen.avisoMensajes ? `<div class="notice info xsmall" role="status" style="margin-bottom:10px">${escaparHtml(state.resumen.avisoMensajes)}</div>` : "";
  state.resumen.avisoMensajes = "";
  const permiso = editable || !(d.grupos || []).length ? "" : d.requiere_codigo
    ? `<div class="notice xsmall" style="margin-bottom:10px"><strong>Solo lectura.</strong> Para marcar grupos como revisados el servidor pide un código de edición: <input id="men-codigo" type="password" placeholder="Código" style="width:160px;display:inline-block;min-height:30px"> <button type="button" class="btn" data-men="usar-codigo">Usar código</button></div>`
    : `<p class="xsmall muted" style="margin:0 0 10px">Marcar grupos como revisados solo se puede desde el mismo equipo donde corre el servidor.</p>`;

  if (!filas.length) {
    const msg = (d.estado && d.estado.mensaje) ? d.estado.mensaje
      : antesDeSeg.length ? (textoElegido ? "Ningún grupo incluye páginas que pasen los filtros de la red." : "El conector «Texto repetido» está desmarcado en los filtros de la red.")
      : (soloDistintos || sinAisladas) ? "Ningún grupo cumple los filtros activos."
      : hayRevisados ? "Todos los grupos están revisados. Activa «Mostrar revisados» para verlos."
      : `No se detectaron mensajes casi idénticos entre páginas distintas (${d.analizados ?? 0} anuncios analizados).`;
    cont.innerHTML = `${aviso}${permiso}${avisoSeg}<div class="state"><div class="state-title">Sin resultados</div><p>${escaparHtml(msg)}</p></div>`;
  } else {
    cont.innerHTML = aviso + permiso + avisoSeg + filas.map(([g, i]) => {
      const rev = g.revision;
      const revisionHtml = !rev ? ""
        : rev.estado === "completa"
          ? `<div class="group-revision" role="note"><span class="tag tag-ok" title="Alguien del equipo revisó este grupo y lo dio por esperable: no cuenta como señal.">Revisado</span>${escaparHtml(rev.motivo_texto)}${rev.nota ? ` — ${escaparHtml(rev.nota)}` : ""} <span class="muted">(${escaparHtml(formatearFechaSafe(rev.revisado))})</span></div>`
          : `<div class="notice info xsmall group-revision" role="note">Este grupo comparte páginas con una revisión anterior (${escaparHtml(rev.motivo_texto)}), pero incluye páginas que esa revisión no cubría: <strong>${(rev.paginas_nuevas || []).map(escaparHtml).join(", ")}</strong>. Sigue como señal hasta que lo revises de nuevo.</div>`;
      const acciones = !editable ? ""
        : esGrupoRevisado(g) ? `<div class="group-acciones"><button type="button" class="btn" data-men="quitar" data-i="${i}">Quitar revisión</button></div>`
        : `<div class="group-acciones"><button type="button" class="btn" data-men="abrir" data-i="${i}" aria-expanded="false" aria-controls="rev-form-${i}">Marcar como revisado</button></div>${htmlFormRevision(g, i, motivos)}`;
      const parecido = g.n_textos > 1 ? `${g.n_textos} variantes · similitud ≥ ${Math.round(g.similitud_minima * 100)} %`
        : g.n_textos === 1 ? "texto idéntico" : `similitud ≥ ${Math.round(g.similitud_minima * 100)} %`;
      const dias = g.dias == null ? "" : g.dias === 0 ? " (el mismo día)" : ` (en ${g.dias} día${g.dias === 1 ? "" : "s"})`;
      // Contexto objetivo para que cada grupo se lea con sus matices; ninguno acusa a nadie.
      const etiquetas = [
        g.mismo_partido ? `<span class="tag" title="Todas estas páginas tienen verificado el mismo partido: reutilizar mensajes dentro de un partido (candidatos y su partido) es lo esperado.">Mismo partido: ${escaparHtml(g.mismo_partido)}</span>` : "",
        (g.coincidencias ?? 1) >= 3 ? `<span class="tag" title="Las mismas páginas repiten mensajes en ${g.coincidencias} grupos: un patrón, no una coincidencia aislada. Puede ser una sola persona u organización detrás de varias páginas (si lo es, únelas en Entidades) o una red coordinada.">Coinciden en ${g.coincidencias} mensajes</span>`
          : g.coincidencias === 1 ? `<span class="tag" title="Es la única vez que estas páginas repiten un mensaje: puede ser casual (por ejemplo, que ambas copien el mismo comunicado).">Coincidencia aislada</span>` : "",
        g.financiadores_distintos ? `<span class="tag" title="Los anuncios declaran pagadores distintos. Casi siempre es así (cada página declara pagar sus propios anuncios): por sí solo no indica nada. Puede haber explicaciones legítimas (un partido y sus candidatos, una agencia).">Pagadores declarados distintos</span>` : `<span class="tag" title="Los anuncios declaran el mismo pagador o ninguno: una misma entidad detrás de varias páginas.">Mismo pagador declarado</span>`,
      ].join("");
      return `
      <article class="group${esGrupoRevisado(g) ? " revisado" : ""}">
        <div class="group-text">“${escaparHtml(g.texto)}”</div>
        <div class="group-meta">
          <strong>${g.n_paginas} páginas</strong><span>${g.anuncios} anuncios</span><span>${escaparHtml(parecido)}</span>
          ${etiquetas}
        </div>
        <div class="cell-sub">${g.paginas.map((p) => `${escaparHtml(p.page_name)} (${p.anuncios})${badgeAfil(p.afiliacion)}`).join(" · ")}</div>
        <div class="cell-sub">Inversión estimada ${escaparHtml(fmtUsd(g.gasto_medio))} · ${fmtNum(g.impresiones_medias)} impresiones · ${escaparHtml(formatearFechaSafe(g.primer_anuncio))} → ${escaparHtml(formatearFechaSafe(g.ultimo_anuncio))}${dias} · ${enlace(g.ejemplo_link, "ver ejemplo")}</div>
        ${g.financiadores.length ? `<div class="cell-sub">Declaran pagar: ${escaparHtml(g.financiadores.join(", "))}</div>` : ""}
        ${revisionHtml}${acciones}
      </article>`;
    }).join("");
  }
  const retirados = d.retirados_por_meta && d.retirados_por_meta.anuncios ? ` Meta retiró además ${d.retirados_por_meta.anuncios} anuncio(s) por incumplir sus normas publicitarias (excluidos de este análisis).` : "";
  const plantillas = d.plantillas_separadas ? ` Se mantuvieron aparte ${d.plantillas_separadas} texto(s) que solo cambian un nombre o una cifra respecto a otro (plantillas, no el mismo mensaje).` : "";
  const extendidos = d.textos_muy_extendidos && d.textos_muy_extendidos.textos ? ` ${d.textos_muy_extendidos.textos} texto(s) aparecen en ${d.textos_muy_extendidos.paginas_minimas} o más páginas (avisos de la plataforma o plantillas masivas) y no se analizan.` : "";
  const sinRevisar = (d.total_grupos ?? 0) - (d.revisados_incluidos ? (d.total_revisados ?? 0) : 0);
  const cuenta = hayRevisados ? `${sinRevisar} grupo(s) sin revisar y ${d.total_revisados} revisado(s)` : `${sinRevisar} grupo(s)`;
  $("mensajes-nota").textContent = `${cuenta} entre ${d.analizados ?? 0} anuncios analizados.${retirados}${plantillas}${extendidos}`;
}

/** Vuelve a pedir los mensajes repetidos y la red (los grupos revisados dejan de dibujarse como líneas de texto). */
async function recargarTrasRevision() {
  const R = state.resumen;
  await Promise.allSettled([cargarMensajes(R.alcance, R.seq), cargarRed(R.alcance, R.seq)]);
}

async function guardarRevisionMensaje(i, form) {
  const d = state.resumen.mensajes, g = d && d.grupos[i];
  if (!g) return;
  const campos = new FormData(form);
  const motivo = String(campos.get("motivo") || ""), nota = String(campos.get("nota") || "").trim(), alcance = String(campos.get("alcance") || "mensaje");
  const error = form.querySelector(".rev-error"), boton = form.querySelector('[type="submit"]');
  const fallo = (texto) => { error.textContent = texto; error.hidden = !texto; };
  if (!motivo) return fallo("Elige un motivo.");
  if (motivo === "otro" && !nota) return fallo("Con «Otro motivo» escribe en la nota qué revisaste.");
  fallo("");
  boton.disabled = true;
  try {
    await enviarApi("/api/ads/mensajes-revisados", {
      alcance, motivo, nota, huellas: g.huellas || [], ejemplo: String(g.texto || "").slice(0, 200),
      paginas: g.paginas.map((p) => ({ nombre: p.page_name, page_id: p.page_id == null ? null : String(p.page_id) }))
    });
    const texto = ((d.motivos_revision || []).find((m) => m.id === motivo) || {}).texto || motivo;
    state.resumen.avisoMensajes = `Grupo marcado como revisado (${texto}). Deja de contarse como señal; «Mostrar revisados» lo vuelve a mostrar.`;
    await recargarTrasRevision();
  } catch (e) {
    boton.disabled = false;
    fallo(e.estado === 403 ? e.message : `No se pudo guardar la revisión (${e.message}).`);
  }
}

async function quitarRevisionMensaje(i, boton) {
  const g = state.resumen.mensajes && state.resumen.mensajes.grupos[i];
  if (!g || !g.revision) return;
  boton.disabled = true;
  try {
    await enviarApi("/api/ads/mensajes-revisados/quitar", { id: g.revision.id });
    state.resumen.avisoMensajes = "Revisión quitada: el grupo vuelve a contarse como señal.";
    await recargarTrasRevision();
  } catch (e) {
    boton.disabled = false;
    state.resumen.avisoMensajes = `No se pudo quitar la revisión (${e.message}).`;
    renderMensajes();
  }
}

/** Botones de las tarjetas de «Mensajes repetidos» (un solo oyente: la lista se vuelve a pintar con cada filtro). */
function clicMensajes(ev) {
  const b = ev.target.closest("[data-men]");
  if (!b) return;
  const i = Number(b.dataset.i), form = $(`rev-form-${i}`), abrir = document.querySelector(`[data-men="abrir"][data-i="${i}"]`);
  if (b.dataset.men === "abrir" && form) {
    form.hidden = !form.hidden;
    b.setAttribute("aria-expanded", String(!form.hidden));
    if (!form.hidden) form.querySelector("select").focus();
  } else if (b.dataset.men === "cerrar" && form) {
    form.hidden = true;
    if (abrir) { abrir.setAttribute("aria-expanded", "false"); abrir.focus(); }
  } else if (b.dataset.men === "quitar") {
    quitarRevisionMensaje(i, b);
  } else if (b.dataset.men === "usar-codigo") {
    try { sessionStorage.setItem("noai_edit_token", $("men-codigo").value); } catch (e) { /* sin almacenamiento */ }
    cargarMensajes(state.resumen.alcance, state.resumen.seq);
  }
}

// --- Cita y CSV ----------------------------------------------------------------
function textoCita() {
  const e = (state.resumen.top && state.resumen.top.estado) || {};
  const hoy = new Date().toLocaleDateString("es-EC", { day: "numeric", month: "long", year: "numeric" });
  return `NoAIVerdad. «Anuncios políticos en Meta, alcance: ${etiquetaAlcance(state.resumen.alcance)}». Datos de la Biblioteca de Anuncios de Meta (últimos ${e.dias ?? "?"} días; actualizados ${fmtFechaHora(e.actualizado) || "s/d"}). Montos e impresiones son rangos publicados por Meta; la inversión estimada es el punto medio. Consultado el ${hoy}. ${location.href}`;
}

async function copiarCita() {
  const aviso = $("resumen-aviso");
  const texto = textoCita();
  try { await navigator.clipboard.writeText(texto); aviso.textContent = "Cita copiada."; }
  catch (e) { window.prompt("Copia la cita:", texto); }
}

function descargarCSV() {
  const d = state.resumen.top;
  const aviso = $("resumen-aviso");
  if (!d || !(d.anunciantes || []).length) { aviso.textContent = "No hay datos para exportar."; return; }
  const lista = anunciantesFiltrados(d.anunciantes);            // lo mismo que se ve en la tabla (búsqueda y «solo con base aquí»)
  if (!lista.length) { aviso.textContent = "No hay anunciantes con estos filtros."; return; }
  const alcance = etiquetaAlcance(state.resumen.alcance), nacional = state.resumen.alcance === "todas";
  const cab = ["anunciante", "page_id", "pagadores_declarados", "tipo_anunciante", "partido", "anuncios", "anuncios_activos", "gasto_min", "gasto_max", "gasto_estimado",
    "impresiones_min", "impresiones_max", "impresiones_estimadas", "costo_por_mil", "region_principal", "porcentaje_region_principal", "base_en_el_alcance_consultado",
    "primer_anuncio", "ultimo_anuncio", "afiliacion", "afiliacion_estado", "alcance_consultado"];
  const filas = lista.map((a) => [
    a.page_name, a.page_id, a.financiadores.join(" | "), a.afiliacion ? (a.afiliacion.tipo || "") : "", a.afiliacion ? (a.afiliacion.partido || "") : "", a.anuncios, a.activos,
    a.gasto.min, a.gasto.max, a.gasto.medio, a.impresiones.min, a.impresiones.max, a.impresiones.medio, a.costo_por_mil,
    a.region_principal ? a.region_principal.region : "", a.region_principal ? a.region_principal.porcentaje : "",
    nacional ? "" : (a.region_principal && normalizar(a.region_principal.region) === normalizar(alcance) ? "sí" : "no (su alcance principal está en otra provincia)"),
    a.primer_anuncio, a.ultimo_anuncio, a.afiliacion ? a.afiliacion.afiliacion : "", a.afiliacion ? (a.afiliacion.verificado ? "verificada" : "sin verificar") : "", alcance]);
  descargarCsvArchivo(`noaiverdad-anunciantes-${state.resumen.alcance}-${fechaHoyIso()}.csv`, cab, filas);
  aviso.textContent = `CSV descargado (${lista.length} anunciantes${lista.length < d.anunciantes.length ? ` de ${d.anunciantes.length}, según los filtros` : ""}).`;
}

// --- Buscar un término --------------------------------------------------------
async function cargarTendencias() {
  const lista = $("termino-sugerencias");
  state.resumen.tendenciasCargadas = true;
  try {
    const data = await fetchApi(`/api/dashboard/keywords`, { timeout: 30000 });
    const kws = data.trending_keywords || [];
    lista.innerHTML = kws.length
      ? kws.map((k) => `<button type="button" class="chip" data-word="${escaparHtml(k.word)}">${escaparHtml(k.word)} <span class="muted">×${k.count}</span></button>`).join("")
      : `<span class="xsmall muted">Aún no hay palabras que se repitan en los titulares actuales.</span>`;
    lista.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => {
      $("termino-input").value = chip.dataset.word;
      consultarTermino(chip.dataset.word);
    }));
  } catch (e) {
    state.resumen.tendenciasCargadas = false;
    lista.innerHTML = `<span class="xsmall muted">No se pudieron cargar las palabras repetidas (${escaparHtml(e.message)}).</span>`;
  }
}

async function consultarTermino(palabra) {
  const box = $("termino-resultado");
  box.hidden = false;
  box.setAttribute("aria-busy", "true");
  box.innerHTML = cajaEstado({ tipo: "carga", titulo: `Buscando «${palabra}»...` });
  try {
    const data = await fetchApi(`/api/dashboard/keywords?q=${encodeURIComponent(palabra)}`, { timeout: 90000 });
    const a = data.analisis;
    if (!a) throw new Error("respuesta sin análisis");
    const dist = a.distribucion || {};
    const rel = (a.relacionados || []).map((t) => `
      <li><span class="tag">${escaparHtml(t.tipo)}</span><span>${urlSegura(t.link) ? `<a href="${escaparHtml(t.link)}" target="_blank" rel="noopener noreferrer">${escaparHtml(t.titulo)}</a>` : escaparHtml(t.titulo)}
        <span class="muted"> · ${escaparHtml(t.fuente)}${t.fecha ? " · " + escaparHtml(formatearFechaSafe(t.fecha)) : ""}</span></span></li>`).join("");
    box.innerHTML = `
      <h3>Resultados para «${escaparHtml(a.palabra)}»</h3>
      <p>${a.resumen_analisis}</p>
      <div class="pill-list"><span class="tag"><strong>${fmtNum(dist.prensa)}</strong>&nbsp;prensa</span><span class="tag"><strong>${fmtNum(dist.fact_check)}</strong>&nbsp;verificaciones</span><span class="tag"><strong>${fmtNum(dist.meta)}</strong>&nbsp;anuncios de Meta</span></div>
      ${rel ? `<ul class="result-list">${rel}</ul>` : ""}
      <p class="xsmall muted" style="margin-top:12px">Fuentes consultadas: ${(a.fuentes_consultadas || []).map(escaparHtml).join("; ")}. No consultadas aquí: ${(a.fuentes_no_consultadas || []).map(escaparHtml).join(", ")} (se consultan por provincia). Solo se cuentan coincidencias del término; el número no mide popularidad.</p>`;
  } catch (e) {
    errorEnCaja(box, `No se pudo completar la búsqueda (${e.message}).`, () => consultarTermino(palabra));
  } finally {
    box.setAttribute("aria-busy", "false");
  }
}

// ---------------------------------------------------------------------------
// Vista Comparar
// ---------------------------------------------------------------------------
function renderSelectoresComparar() {
  const cont = $("comparar-selectores");
  const alc = state.comparar.alcances;
  const campos = alc.map((a, i) => `
    <div class="field">
      <label class="field-label" for="cmp-${i}">Alcance ${"ABC"[i]}</label>
      <select id="cmp-${i}" data-i="${i}"></select>
    </div>`).join("");
  cont.innerHTML = `${campos}
    ${alc.length < 3 ? `<button type="button" class="btn" id="cmp-agregar">Agregar un tercero</button>` : `<button type="button" class="btn" id="cmp-quitar">Quitar el tercero</button>`}`;
  alc.forEach((a, i) => poblarSelect($(`cmp-${i}`), { nacional: true, seleccionado: a }));
  cont.querySelectorAll("select").forEach((s) => s.addEventListener("change", (e) => {
    const nuevo = state.comparar.alcances.slice();
    nuevo[Number(e.target.dataset.i)] = e.target.value;
    navegar({ vista: "comparar", comp: nuevo });
  }));
  $("cmp-agregar")?.addEventListener("click", () => {
    const usados = new Set(state.comparar.alcances);
    const libre = provinciasEcuador.find((p) => !usados.has(p.id)) || provinciasEcuador[0];
    navegar({ vista: "comparar", comp: [...state.comparar.alcances, libre.id] });
  });
  $("cmp-quitar")?.addEventListener("click", () => navegar({ vista: "comparar", comp: state.comparar.alcances.slice(0, 2) }));
}

async function cargarComparacion() {
  const C = state.comparar;
  const seq = ++C.seq;
  const cont = $("comparar-resultado");
  $("view-comparar").setAttribute("aria-busy", "true");
  $("comparar-progress").classList.add("on");
  cont.innerHTML = cajaEstado({ tipo: "carga", titulo: "Comparando anuncios en Meta...", descripcion: "Calculando inversión, alcance y anunciantes para cada zona.", filas: 4 });
  try {
    const d = await fetchApi(`/api/ads/comparar?provincias=${encodeURIComponent(C.alcances.join(","))}`, { timeout: 120000 });
    if (seq !== C.seq) return;
    renderComparacion(d);
  } catch (e) {
    if (seq !== C.seq) return;
    errorEnCaja(cont, `No se pudo completar la comparación (${e.message}).`, cargarComparacion);
  } finally {
    if (seq === C.seq) { $("comparar-progress").classList.remove("on"); $("view-comparar").setAttribute("aria-busy", "false"); }
  }
}

function renderComparacion(d) {
  const cont = $("comparar-resultado");
  const cols = d.columnas || [];
  if (!cols.length || !cols.some((c) => (c.resumen || {}).anuncios)) {
    cont.innerHTML = cajaEstado({ tipo: "info", titulo: "Sin datos para comparar", descripcion: escaparHtml((d.estado && d.estado.mensaje) || "La Biblioteca de Anuncios no devolvió datos.") });
    return;
  }
  const filas = [
    { t: "Anuncios", v: (c) => c.resumen.anuncios, f: fmtNum },
    { t: "Anunciantes", v: (c) => c.resumen.anunciantes, f: fmtNum },
    { t: "Anuncios activos", v: (c) => c.resumen.anuncios_activos, f: fmtNum },
    { t: "Inversión estimada", v: (c) => c.resumen.gasto_medio_total, f: fmtUsd, sub: (c) => `rango ${fmtNum(c.resumen.gasto_min_total)} – ${fmtNum(c.resumen.gasto_max_total)}` },
    { t: "Impresiones estimadas", v: (c) => c.resumen.impresiones_medias_total, f: fmtNum },
    { t: "Concentración en los 5 mayores", v: (c) => c.resumen.concentracion_top5, f: (x) => x == null ? "—" : Math.round(x * 100) + " %", barra: false, nota: "Se muestra con 10 o más anunciantes" },
    { t: "Mensajes repetidos (grupos)", v: (c) => c.mensajes_repetidos, f: fmtNum },
    { t: "Pagador distinto de la página", v: (c) => c.resumen.pagador_distinto, f: fmtNum, sub: (c) => c.resumen.anunciantes ? `${Math.round((c.resumen.pagador_distinto || 0) / c.resumen.anunciantes * 100)} % de sus anunciantes` : "" }
  ];

  const cuerpo = filas.map((fila) => {
    const valores = cols.map((c) => fila.v(c) ?? 0);
    const max = Math.max(...valores, 1);
    return `<tr><th scope="row">${escaparHtml(fila.t)}</th>${cols.map((c, i) => {
      const v = fila.v(c);
      return `<td><div class="cmp-val">${escaparHtml(fila.f(v))}${fila.sub ? `<small>${escaparHtml(fila.sub(c))}</small>` : ""}${v == null && fila.nota ? `<small>${escaparHtml(fila.nota)}</small>` : ""}</div>${fila.barra === false || v == null ? "" : `<div class="bar cmp-bar" aria-hidden="true"><span style="width:${Math.max(2, Math.round((valores[i] / max) * 100))}%"></span></div>`}</td>`;
    }).join("")}</tr>`;
  }).join("");

  const top = cols.map((c) => `
    <div>
      <h3 class="small" style="margin-bottom:8px">${escaparHtml(c.alcance)}</h3>
      <ol class="cmp-list" style="padding-left:18px">${(c.top || []).map((a) => `<li><span>${escaparHtml(a.page_name)}${badgeAfil(a.afiliacion)}</span><strong>${escaparHtml(fmtUsd(a.gasto.medio))}</strong></li>`).join("") || "<li>Sin anunciantes</li>"}</ol>
    </div>`).join("");

  const comun = (d.en_comun || []).length ? `
    <div class="cmp-section">
      <h2>Anunciantes presentes en todos los alcances</h2>
      <p class="small muted" style="margin-bottom:10px">${fmtNum(d.total_en_comun)} anunciante(s) aparecen en los ${cols.length} alcances. Se muestran los 10 con mayor inversión estimada total.</p>
      <div class="table-wrap"><table class="table">
        <thead><tr><th scope="col">Anunciante</th>${cols.map((c) => `<th scope="col" class="num">${escaparHtml(c.alcance)}</th>`).join("")}</tr></thead>
        <tbody>${d.en_comun.map((e) => `<tr><td class="cell-name">${escaparHtml(e.page_name)}${badgeAfil(e.afiliacion)}</td>${e.gasto_medio.map((g) => `<td class="num">${escaparHtml(fmtUsd(g))}</td>`).join("")}</tr>`).join("")}</tbody>
      </table></div>
    </div>` : "";

  const incluyeNacional = cols.some((c) => c.alcance === "Nacional");
  const truncados = ((d.estado && d.estado.terminos_truncados) || []).filter((t) => t && t !== "*");
  const parcial = d.estado && d.estado.parcial ? `<div class="notice info" role="note">Resultados parciales: Meta tenía más anuncios de los que se descargan${truncados.length ? ` por consulta (${escaparHtml(truncados.join(", "))})` : ""}. Los totales pueden ser mayores.</div>` : "";
  $("comparar-resultado").innerHTML = `${parcial}
    <div class="table-wrap" style="margin-top:12px">
      <table class="table cmp-table">
        <caption class="visually-hidden">Comparación de anuncios políticos de Meta</caption>
        <thead><tr><th scope="col"><span class="visually-hidden">Medida</span></th>${cols.map((c) => `<th scope="col">${escaparHtml(c.alcance)}</th>`).join("")}</tr></thead>
        <tbody>${cuerpo}</tbody>
      </table>
    </div>
    <div class="cmp-section">
      <h2>Mayores anunciantes en cada alcance</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:24px">${top}</div>
    </div>
    ${comun}
    <p class="xsmall muted" style="margin-top:24px">Las cifras son estimaciones a partir de rangos publicados por Meta (punto medio de cada rango; para una provincia, repartidas según el porcentaje de alcance de cada anuncio). Comparar totales absolutos puede reflejar el tamaño de cada provincia y no una diferencia de intensidad.${incluyeNacional ? " El total nacional incluye a las provincias." : ""}</p>`;
}

// ---------------------------------------------------------------------------
// Inicio
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initSinCne();
  initSoloActivos();
  initFechas();
  initTutorial();
  initPanel();
  initResumen();
  initFicha();
  initMap();
  initNav();
  sincronizarPanel();
  renderIntro();

  const ruta = leerHash();
  state.hashAplicado = null;
  // Conexiones empieza sin provincia de enfoque: al recargar se descarta la que quedó en la URL (un enlace con provincia abierto de cero sí se respeta),
  // salvo que la red tuviera guardada su vista (cámara y selección) en ese alcance: entonces se conserva para poder volver a ella.
  if (ruta.vista === "resumen" && cargaDeNuevo() && !(memoriaRed && memoriaRed.alcance === ruta.alcance)) ruta.alcance = "todas";
  // Mapa: con la URL sin provincia se recupera la selección guardada; con recarga (o URL vacía) también el encuadre que tenía.
  const g = leerMapaGuardado(), hashVacio = !location.hash || /^#\/?mapa\/?$/.test(location.hash);
  if (g && ruta.vista !== "mapa" && cargaDeNuevo()) state.mapaPendiente = g;       // recarga en otra pestaña: el Mapa lo recupera cuando se abra
  if (g && ruta.vista === "mapa" && !ruta.provincia && hashVacio) {
    if (g.prov && provinciaPorId(g.prov)) ruta.provincia = g.prov;
    if (seccionDelMapa(g.seccion)) ruta.seccion = g.seccion;
    if (PERIODOS[g.periodo]) ruta.periodo = g.periodo;
  }
  const restaurarEncuadre = !!g && ruta.vista === "mapa" && (hashVacio || cargaDeNuevo()) && (!ruta.provincia || ruta.provincia === g.prov);
  if (ruta.vista !== "mapa" || ruta.provincia) navegar(ruta, { historial: false });
  else { mostrarVista("mapa"); escribirHash(true); }
  if (restaurarEncuadre) state.map.setView([g.lat, g.lng], g.zoom, { animate: false });
  state.map.on("moveend", debounce(guardarMapa, 400));
});
