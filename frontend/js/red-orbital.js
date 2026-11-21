/* Red orbital: vista del grafo de pagadores como sistemas orbitales (canvas 2D, sin dependencias).
 *
 *  - Cada provincia es un "sol"; sus páginas giran en pistas concéntricas y cada pagador es una luna de la página que paga.
 *  - El diseño se calcula una sola vez; después solo hay movimiento orbital (sin física viva que "explote" al arrastrar).
 *  - Arrastrar una página o un pagador lo estira con resistencia y vuelve a su órbita; arrastrar una provincia mueve todo su sistema.
 *  - Los filtros del panel (tipos, fecha, activos, partido, búsqueda) resaltan y atenúan: nunca ocultan. La unión de cada página con su
 *    provincia («alcance») no se atenúa con ninguno: es la estructura de la red.
 *  - Color: contexto en azul; la señal (pagador y sus vínculos) en naranja. La paleta categórica son las ranuras 1-3 del método
 *    dataviz (azul, naranja, aqua), validadas sobre el fondo oscuro con `validate_palette.js --mode dark --pairs all`. El texto repetido va
 *    en gris (gris claro en el tema oscuro, casi negro en el claro), a petición del equipo, para no confundirse con el color de ningún partido;
 *    se distingue de la unión con la provincia (gris medio, continua) por el tono y por su punteado, que es el canal secundario.
 *  - Las líneas de texto repetido se pueden pulsar (opciones.alElegirArista): la app muestra en el panel lateral los mensajes que las unen.
 *  - Los nombres vienen de la API (no son de fiar): todo el DOM se arma con textContent (helper h), nunca con innerHTML.
 *
 *  Uso:  const ctl = RedOrbital.montar(contenedor, grafo, opciones);
 *  Disposición «Mapa»: cada sol se coloca en la capital de su provincia (opciones.ubicaciones) sobre un mapa base de OpenStreetMap que se
 *  dibuja en el mismo lienzo (opciones.teselas); donde los sistemas se solapan se separan un poco y una línea punteada marca la capital.
 *
 *  opciones: { filtros, fechas, partidoDe(nodo), colorPartido(partido), aristas, etiquetaArista(arista), fmtUsd, sinMovimiento,
 *              tipoDestacado(), leyendaAbierta(), alPlegarLeyenda(abierta), ubicaciones: {provincia: [lat, lng]},
 *              teselas: "https://…/{z}/{x}/{y}.png", filtroTeselas: "<filtro CSS del mapa base>", disposicionMapa(), alCambiarDisposicion(mapa),
 *              alSeleccionar(nodo|null, aristasDelNodo, restaurado), alElegirArista(arista con sus extremos a y b, restaurado),
 *              restaurar: lo que devolvió estado() de la instancia anterior (cámara y selección),
 *              cupoMinimo: páginas por provincia que se dibujan con poco zoom (el resto aparece al acercar; ver «nivel de detalle»),
 *              cubierto(): lo que tapan los paneles sobre el lienzo, { izq, der, arriba, abajo } en px: al seleccionar algo la cámara lo centra en lo que queda libre,
              alcanceOtras(): { activo, umbral } — al seleccionar una página se dibujan líneas a las demás provincias donde llega (nodo.regiones) desde ese umbral }
 *  controlador: { refrescar, ajustar, limpiarSeleccion, centrarSeleccion, reorganizar, velocidad, disposicion, estado, png, destruir }
 */
(function () {
  "use strict";

  // Dos temas (el de la app: data-theme). El oscuro es el original; el claro usa un mapa base claro, rótulos oscuros con halo claro y mezcla «multiply»
  // en lugar de «lighter» (sumar luz solo se ve sobre fondo oscuro). Se elige al montar (opciones.tema) y la app vuelve a montar la red si cambia el tema.
  const TEMAS = {
    oscuro: { fondo: "#0b0f1a", degradado: ["#131a2e", "#080b14"], halo: "rgba(11,15,26,.92)", chip: "rgba(11,15,26,.9)", atrib: "rgba(240,239,236,.78)", anillo: "rgba(255,255,255,.5)",
      mezcla: "lighter", aclarar: 255, filtro: null, alcance: 1, caliente: 0.98,
      pal: { tinta: "#f0efec", tinta2: "#c3c2b7", tinta3: "#898781", c1: "#3987e5", c2: "#d95926", c3: "#199e70", texto: "#c4c9d4", sol: "#9ec5f4", pista: "#86b6ef" } },
    claro: { fondo: "#f8fafc", degradado: ["#f4f7fb", "#e2e8f2"], halo: "rgba(248,250,252,.94)", chip: "rgba(248,250,252,.92)", atrib: "rgba(51,65,85,.85)", anillo: "rgba(15,23,42,.4)",
      mezcla: "multiply", aclarar: 0, alcance: 0.55, caliente: 0.72, filtro: "grayscale(0.7) brightness(1.05) contrast(0.9)",
      pal: { tinta: "#0f172a", tinta2: "#334155", tinta3: "#64748b", c1: "#2563c9", c2: "#c2410c", c3: "#0f766e", texto: "#27272a", sol: "#1d5fa8", pista: "#3b6aa8" } }
  };
  let TEMA = TEMAS.oscuro, FONDO = TEMA.fondo, MEZCLA = TEMA.mezcla;
  const PAL = Object.assign({}, TEMA.pal);
  const COLOR_ARISTA = { pagador: PAL.c2, texto: PAL.texto, enlace: PAL.c1, partido: "#a855f7", partido_prov: "#a855f7", alcance: PAL.tinta3 };
  /** Aplica un tema a las paletas del módulo (y descarta lo dibujado con el anterior: esferas y teselas filtradas). */
  function aplicarTema(nombre) {
    TEMA = nombre === "claro" ? TEMAS.claro : TEMAS.oscuro; FONDO = TEMA.fondo; MEZCLA = TEMA.mezcla;
    Object.assign(PAL, TEMA.pal);
    Object.assign(COLOR_ARISTA, { pagador: PAL.c2, texto: PAL.texto, enlace: PAL.c1, alcance: PAL.tinta3 });
    esferas.clear(); teselas.clear(); mezclaMemo.clear();
  }
  const CLICABLES = new Set(["texto", "enlace", "partido", "partido_prov"]);      // vínculos que se pueden pulsar: texto repetido, mismo enlace y partido
  const PUNTEADO = { pagador: [], texto: [9, 5], enlace: [3, 4], partido: [], partido_prov: [], alcance: [] };
  const colorArista = (t) => COLOR_ARISTA[t] || PAL.tinta3;
  const ETIQ = { provincia: "Provincia", pagina: "Página", pagador: "Pagador" };
  const HEX = /^#[0-9a-f]{6}$/i;
  const TAU = Math.PI * 2;
  const LENTE_PX = 80;      // radio (px) alrededor del cursor dentro del cual se rotulan (y se muestran) los nodos cuando el zoom es bajo
  const LENTE_MAX = 30;     // y a lo sumo cuántas páginas ocultas aparecen a la vez bajo el cursor (las de mayor inversión)
  const LOD_CUPO_MIN = 12;  // páginas por provincia que se dibujan con el zoom de referencia (las provincias con menos, completas), además de las fijas
  const LOD_K0 = 0.43;      // zoom de referencia: el que encuadra todo el país en una pantalla normal

  // ---------- utilidades
  /** Constructor de DOM: los textos se insertan como texto (nunca como HTML). */
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.style.cssText = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    kids.flat().forEach((c) => { if (c != null && c !== false) el.append(c); });
    return el;
  }
  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  function hash(s) { let x = 2166136261; for (let i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 16777619); } return ((x >>> 0) % 100000) / 100000; }
  const rgbDe = (c) => { const v = parseInt(c.slice(1), 16); return [v >> 16, (v >> 8) & 255, v & 255]; };
  const rgba = (c, a) => { const [r, g, b] = rgbDe(c); return `rgba(${r},${g},${b},${a})`; };
  const mezclaMemo = new Map();      // el degradado de cada nodo pide los mismos tonos en cada cuadro: se calculan una sola vez
  const mezcla = (c, t, a = [255, 255, 255]) => {
    const k = c + "|" + t + "|" + a[0]; let v = mezclaMemo.get(k); if (v) return v;
    const [r, g, b] = rgbDe(c); v = `rgb(${Math.round(r + (a[0] - r) * t)},${Math.round(g + (a[1] - g) * t)},${Math.round(b + (a[2] - b) * t)})`;
    mezclaMemo.set(k, v); return v;
  };
  const aclarar = (c, t) => { const [r, g, b] = rgbDe(c), f = (v) => Math.round(v + (TEMA.aclarar - v) * t).toString(16).padStart(2, "0"); return "#" + f(r) + f(g) + f(b); };      // hacia el blanco (tema oscuro) o hacia el negro (claro)
  const suave = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  const omega = (R) => Math.min(0.55, 0.16 * Math.pow(40 / R, 1.5));      // más lejos, más lento (tipo Kepler)

  // ---------- mapa: los sistemas pueden colocarse sobre la geografía de Ecuador
  // Coordenadas de mundo = píxeles de Web Mercator a un zoom de referencia (Z0) menos el centro del país. Así la cámara de la red
  // equivale a una vista de teselas de OpenStreetMap: zoom del mapa = Z0 + log2(k). Las teselas se oscurecen una vez al cargarlas.
  const Z0 = 8.6, LADO_TESELA = 256, CENTRO_MAPA = [-1.7, -78.4];
  const mercator = (lat, lng) => {
    const s = LADO_TESELA * Math.pow(2, Z0), sen = Math.sin(clamp(lat, -85, 85) * Math.PI / 180);
    return [(lng + 180) / 360 * s, (0.5 - Math.log((1 + sen) / (1 - sen)) / (4 * Math.PI)) * s];
  };
  const ORIGEN = mercator(CENTRO_MAPA[0], CENTRO_MAPA[1]);
  const aMundo = (lat, lng) => { const p = mercator(lat, lng); return [p[0] - ORIGEN[0], p[1] - ORIGEN[1]]; };
  // El mapa base debe verse igual que en la pestaña «Mapa» (Leaflet): la app pasa su mismo filtro oscuro (opciones.filtroTeselas, que sale de
  // la variable CSS --mapa-filtro-oscuro) y aquí se aplica una sola vez a cada tesela al cargarla. FILTRO_BASE solo es el valor de reserva.
  const FILTRO_BASE = "invert(1) hue-rotate(180deg) grayscale(0.85) brightness(0.78) contrast(0.95)";
  let FILTRO_TESELAS = FILTRO_BASE;
  // Hay lienzos que no saben filtrar (ctx.filter): todos los de iPhone y iPad, también Chrome, porque Apple obliga a usar su motor (WebKit). En ellos el mismo
  // filtro oscuro se aplica píxel a píxel (aplicarFiltroManual) al cargar cada tesela, y el mapa base se ve igual. `?sinfiltro=1` en la dirección fuerza ese camino (pruebas).
  const FORZAR_SIN_FILTRO = !!window.NOAI_SIN_FILTRO_CANVAS || /[?&]sinfiltro=1(?:&|$)/.test(location.search);
  const SOPORTA_FILTRO = (() => {
    if (FORZAR_SIN_FILTRO) return false;
    try {
      if (!("filter" in document.createElement("canvas").getContext("2d"))) return false;
      const c = document.createElement("canvas"); c.width = c.height = 1; const y = c.getContext("2d");
      y.filter = "invert(1)"; y.fillStyle = "#000"; y.fillRect(0, 0, 1, 1);
      return y.getImageData(0, 0, 1, 1).data[0] > 200;                       // a veces la propiedad existe pero no hace nada: negro invertido debe dar blanco
    } catch (e) { return false; }
  })();

  /** Los pasos de un filtro CSS (invert, grayscale, sepia, saturate, hue-rotate, brightness, contrast), en orden: cada uno es una matriz 3×3 `m` o `a·v + b` por canal. */
  function pasosDeFiltro(texto) {
    const pasos = [], re = /([a-z-]+)\(\s*([^)]*?)\s*\)/gi; let m;
    while ((m = re.exec(texto || ""))) {
      const f = m[1].toLowerCase(), crudo = m[2];
      let v = parseFloat(crudo); if (!isFinite(v)) v = f === "hue-rotate" ? 0 : 1;
      if (/%\s*$/.test(crudo)) v /= 100;
      if (f === "invert") pasos.push({ a: 1 - 2 * v, b: v });
      else if (f === "brightness") pasos.push({ a: v, b: 0 });
      else if (f === "contrast") pasos.push({ a: v, b: 0.5 * (1 - v) });
      else if (f === "grayscale") {
        const s = 1 - Math.min(1, Math.max(0, v));
        pasos.push({ m: [0.2126 + 0.7874 * s, 0.7152 - 0.7152 * s, 0.0722 - 0.0722 * s, 0.2126 - 0.2126 * s, 0.7152 + 0.2848 * s, 0.0722 - 0.0722 * s, 0.2126 - 0.2126 * s, 0.7152 - 0.7152 * s, 0.0722 + 0.9278 * s] });
      } else if (f === "sepia") {
        const s = 1 - Math.min(1, Math.max(0, v));
        pasos.push({ m: [0.393 + 0.607 * s, 0.769 - 0.769 * s, 0.189 - 0.189 * s, 0.349 - 0.349 * s, 0.686 + 0.314 * s, 0.168 - 0.168 * s, 0.272 - 0.272 * s, 0.534 - 0.534 * s, 0.131 + 0.869 * s] });
      } else if (f === "saturate") {
        pasos.push({ m: [0.213 + 0.787 * v, 0.715 - 0.715 * v, 0.072 - 0.072 * v, 0.213 - 0.213 * v, 0.715 + 0.285 * v, 0.072 - 0.072 * v, 0.213 - 0.213 * v, 0.715 - 0.715 * v, 0.072 + 0.928 * v] });
      } else if (f === "hue-rotate") {
        const u = (/[a-z]+$/i.exec(crudo) || [""])[0].toLowerCase(), rad = u === "rad" ? v : u === "grad" ? v * Math.PI / 200 : u === "turn" ? v * 2 * Math.PI : v * Math.PI / 180;
        const c = Math.cos(rad), s = Math.sin(rad);
        pasos.push({ m: [0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928,
          0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140, 0.072 - c * 0.072 - s * 0.283,
          0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072] });
      }
    }
    return pasos;
  }
  /** Aplica esos pasos a los píxeles RGBA de una imagen (Uint8ClampedArray), recortando a 0–1 después de cada uno, como hace el navegador. */
  function aplicarFiltroManual(d, pasos) {
    const n = pasos.length;
    for (let i = 0; i < d.length; i += 4) {
      let r = d[i] / 255, g = d[i + 1] / 255, b = d[i + 2] / 255;
      for (let s = 0; s < n; s++) {
        const p = pasos[s];
        if (p.m) { const m = p.m, nr = m[0] * r + m[1] * g + m[2] * b, ng = m[3] * r + m[4] * g + m[5] * b; b = m[6] * r + m[7] * g + m[8] * b; r = nr; g = ng; }
        else { r = r * p.a + p.b; g = g * p.a + p.b; b = b * p.a + p.b; }
        r = r < 0 ? 0 : r > 1 ? 1 : r; g = g < 0 ? 0 : g > 1 ? 1 : g; b = b < 0 ? 0 : b > 1 ? 1 : b;
      }
      d[i] = r * 255; d[i + 1] = g * 255; d[i + 2] = b * 255;                // el Uint8ClampedArray redondea solo
    }
  }
  let pasosEnUso = null;      // los pasos del filtro vigente (se calculan una vez por filtro)
  const pasosActuales = () => {
    if (!pasosEnUso || pasosEnUso.texto !== FILTRO_TESELAS) { let p = pasosDeFiltro(FILTRO_TESELAS); if (!p.length) p = pasosDeFiltro(FILTRO_BASE); pasosEnUso = { texto: FILTRO_TESELAS, pasos: p }; }
    return pasosEnUso.pasos;
  };
  const teselas = new Map();            // "plantilla|z/x/y" -> { img, cv (ya oscurecida), listo, error, t0, uso }; compartida entre montajes
  let usoTeselas = 0;
  function teselaDe(plantilla, z, x, y, cb) {
    const k = plantilla + "|" + z + "/" + x + "/" + y; let t = teselas.get(k);
    if (t && t.error && performance.now() - t.t0 > 30000) { teselas.delete(k); t = null; }       // tras un fallo, se reintenta pasados 30 s
    if (t) { t.uso = ++usoTeselas; return t; }
    t = { img: new Image(), cv: null, listo: false, error: false, t0: 0, uso: ++usoTeselas };
    t.img.crossOrigin = "anonymous";                     // sin esto el lienzo quedaría "contaminado" y no se podría exportar la imagen
    t.img.onload = () => {
      const c = document.createElement("canvas"); c.width = c.height = LADO_TESELA; const x2 = c.getContext("2d");
      if (SOPORTA_FILTRO) x2.filter = FILTRO_TESELAS;
      x2.drawImage(t.img, 0, 0, LADO_TESELA, LADO_TESELA);
      if (!SOPORTA_FILTRO) {              // sin ctx.filter (iPhone, iPad): el mismo filtro, píxel a píxel
        try { const px = x2.getImageData(0, 0, LADO_TESELA, LADO_TESELA); aplicarFiltroManual(px.data, pasosActuales()); x2.putImageData(px, 0, 0); }
        catch (e) { t.error = true; t.img = null; t.t0 = performance.now(); cb.error(); return; }          // lienzo contaminado: sin mapa base
      }
      t.cv = c; t.img = null; t.listo = true; t.t0 = performance.now(); cb.carga();
    };
    t.img.onerror = () => { t.error = true; t.t0 = performance.now(); cb.error(); };
    t.img.src = plantilla.replace("{z}", z).replace("{x}", x).replace("{y}", y);
    teselas.set(k, t);
    if (teselas.size > 160) [...teselas.entries()].sort((a, b) => a[1].uso - b[1].uso).slice(0, 50).forEach(([kk]) => teselas.delete(kk));      // cada tesela son 256 KB de lienzo: en un iPhone la memoria es poca
    return t;
  }

  const brillos = new Map();
  function brillo(hex) {
    let s = brillos.get(hex); if (s) return s;
    s = document.createElement("canvas"); s.width = s.height = 128;
    const x = s.getContext("2d"), gr = x.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, rgba(hex, 0.7)); gr.addColorStop(0.22, rgba(hex, 0.32)); gr.addColorStop(0.55, rgba(hex, 0.1)); gr.addColorStop(1, rgba(hex, 0));
    x.fillStyle = gr; x.fillRect(0, 0, 128, 128); brillos.set(hex, s); return s;
  }

  /**
   * Esfera ya dibujada (mismo degradado y mismo contorno oscuro que dibujarNodo) para los nodos medianos: con miles de páginas es mucho más barato
   * estampar una imagen que crear un degradado por nodo y por cuadro. Radio de la esfera = 25 px de 64; el contorno ocupa el resto.
   */
  const esferas = new Map();
  function esfera(hex) {
    let s = esferas.get(hex); if (s) return s;
    s = document.createElement("canvas"); s.width = s.height = 64;
    const x = s.getContext("2d"), R = 25, c = 32, gr = x.createRadialGradient(c - R * 0.35, c - R * 0.4, R * 0.08, c, c, R * 1.05);
    gr.addColorStop(0, mezcla(hex, 0.6)); gr.addColorStop(0.5, hex); gr.addColorStop(1, mezcla(hex, 0.45, [0, 0, 0]));
    x.beginPath(); x.arc(c, c, R, 0, TAU); x.fillStyle = gr; x.fill(); x.lineWidth = R * 0.5; x.strokeStyle = FONDO; x.stroke();
    esferas.set(hex, s); return s;
  }

  function montar(cont, g, op) {
    op = op || {};
    aplicarTema(op.tema === "light" ? "claro" : "oscuro");
    const filtroMapa = TEMA.filtro || op.filtroTeselas || FILTRO_BASE;           // claro: mapa base claro y algo apagado; oscuro: el filtro oscuro de la pestaña Mapa
    if (filtroMapa !== FILTRO_TESELAS) { FILTRO_TESELAS = filtroMapa; teselas.clear(); }      // las teselas ya cargadas se filtraron con otro filtro
    const F = op.filtros || { tipos: new Set(), activos: false, color: "tipo", fechaIdx: 0, buscar: "", etiquetas: true, conPendientes: false, partidos: new Set() };
    const fechas = op.fechas || [];
    const RM = !!op.sinMovimiento;
    const usd = op.fmtUsd || ((v) => "$" + Math.round(v || 0).toLocaleString("es-EC"));
    const defArista = (t) => (op.aristas && op.aristas[t]) || { corto: t, nombre: t, glifo: "──", dash: PUNTEADO[t] || [] };
    const partidoDe = (n) => (op.partidoDe ? op.partidoDe(n.raw) : null);
    const colorDePartido = (p) => (op.colorPartido && op.colorPartido(p)) || null;
    const FUENTE = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";

    // ---------- modelo
    const nodos = [], porId = new Map();
    (g.nodos || []).forEach((n) => {
      const o = { id: n.id, raw: n, nombre: String(n.nombre || n.id), nq: norm(n.nombre || n.id), tipo: n.tipo, gm: Number(n.gasto && n.gasto.medio) || 0,
        aristas: [], kids: [], parent: null, depth: 0, tracks: [], grupo: null, rank: -1, ext: 0, r: 0, spin: 1, orb: null, ang: 0,
        bx: 0, by: 0, bx0: 0, by0: 0, tgt: null, ox: 0, oy: 0, vx: 0, vy: 0, wx: 0, wy: 0, sx: -1e4, sy: -1e4,
        ph: hash(String(n.id)) * TAU, lab: false, labPrev: false, _fs: null };
      nodos.push(o); porId.set(o.id, o);
    });
    const aristas = [], vistos = new Set(), paralelas = new Map();
    (g.aristas || []).forEach((e) => {
      const A = porId.get(e.a), B = porId.get(e.b); if (!A || !B || A === B) return;
      const par = A.id < B.id ? A.id + "\u0000" + B.id : B.id + "\u0000" + A.id;
      const k = par + "\u0000" + e.tipo + (e.tipo === "partido_prov" ? "\u0000" + e.partido : ""); if (vistos.has(k)) return; vistos.add(k);       // un conector por partido y par de soles
      const npar = e.tipo === "partido_prov" ? (paralelas.get(par) || 0) : 0; if (e.tipo === "partido_prov") paralelas.set(par, npar + 1);      // los de un mismo par se abren en abanico
      const E = { a: A, b: B, tipo: e.tipo, raw: e, i: aristas.length, esp: e.tipo !== "alcance", len: 100, cx: 0, cy: 0, dib: false, labPrev: false, par: npar };
      aristas.push(E); A.aristas.push(E); B.aristas.push(E);
    });
    // los vínculos "partido" solo existen cuando ambos extremos tienen ese partido visible (igual que la vista clásica); los conectores entre soles
    // («partido_prov») solo si tienen candidatos verificados en sus dos extremos, o si se incluyen los partidos sin verificar
    const aristaVisible = (E) => (E.tipo === "partido" ? (partidoDe(E.a) === E.raw.partido && partidoDe(E.b) === E.raw.partido)
      : E.tipo === "partido_prov" ? !!(E.raw.verificada || F.conPendientes) : true);
    const otro = (E, n) => (E.a === n ? E.b : E.a);
    const vecinos = (n) => { const s = new Set(); n.aristas.forEach((E) => { if (aristaVisible(E)) s.add(otro(E, n)); }); return s; };

    const maxProv = Math.max(1, ...nodos.filter((n) => n.tipo === "provincia").map((n) => n.gm));
    const maxOtro = Math.max(1, ...nodos.filter((n) => n.tipo !== "provincia").map((n) => n.gm));
    nodos.forEach((n) => {
      const t = Math.sqrt(n.gm / (n.tipo === "provincia" ? maxProv : maxOtro));
      n.r = n.tipo === "provincia" ? 12 + 12 * t : n.tipo === "pagador" ? 5.5 + 3.5 * t : 3.6 + 7.4 * t;      // tamaño = inversión estimada
    });
    nodos.filter((n) => n.tipo !== "provincia").sort((a, b) => b.gm - a.gm).forEach((n, i) => { n.rank = i; });
    const provincias = nodos.filter((n) => n.tipo === "provincia").sort((a, b) => b.gm - a.gm);

    // ---------- alcance en otras provincias (solo con una página seleccionada)
    // La unión «alcance» de siempre sigue siendo la estructura (la página orbita la provincia donde llega más). Al pulsar una página se añaden,
    // solo mientras está seleccionada, líneas hacia las demás provincias donde llegan sus anuncios (n.raw.regiones: [[provincia, fracción], …]).
    const solPorNombre = new Map(provincias.map((p) => [norm(p.nombre), p]));
    const umbralAlc = () => (op.alcanceOtras ? Number(op.alcanceOtras().umbral) || 0 : 0.02);
    const alcanceOn = () => !op.alcanceOtras || op.alcanceOtras().activo !== false;
    /** Provincias secundarias de una página: [{ p: sol, v: fracción }] sin la principal (ya está unida) y por encima del umbral. */
    function otrasProvincias(n) {
      if (!n || n.tipo !== "pagina" || !alcanceOn() || !Array.isArray(n.raw.regiones)) return [];
      const u = umbralAlc(), principal = n.parent && n.parent.tipo === "provincia" ? n.parent : null, out = [];
      n.raw.regiones.forEach(([nombre, v]) => { const p = solPorNombre.get(norm(nombre)); if (p && p !== principal && v >= u) out.push({ p, v }); });
      return out;
    }

    // grupos: componentes unidos por pagador / texto / enlace que reúnen al menos 2 páginas (una pista, no una prueba)
    const GRP = new Set(["pagador", "texto", "enlace"]);
    const uf = new Map(nodos.map((n) => [n, n]));
    const raizUf = (x) => { while (uf.get(x) !== x) { uf.set(x, uf.get(uf.get(x))); x = uf.get(x); } return x; };
    aristas.forEach((E) => { if (GRP.has(E.tipo)) uf.set(raizUf(E.a), raizUf(E.b)); });
    const comp = new Map();
    nodos.forEach((n) => { if (n.tipo === "provincia" || !n.aristas.some((E) => GRP.has(E.tipo))) return; const r = raizUf(n); if (!comp.has(r)) comp.set(r, []); comp.get(r).push(n); });
    const grupos = [...comp.values()].filter((ns) => ns.filter((n) => n.tipo !== "pagador").length >= 2)
      .map((ns) => ({ nodos: ns, gm: ns.reduce((s, n) => s + n.gm, 0) })).sort((a, b) => b.gm - a.gm);
    grupos.forEach((gp, i) => {
      gp.n = i + 1; gp.nodos.forEach((n) => { n.grupo = gp; });
      // el halo lleva el color del vínculo que une al grupo: naranja si comparten pagador, gris si repiten texto, azul si comparten enlace
      const tipos = new Set(); gp.nodos.forEach((n) => n.aristas.forEach((E) => { if (GRP.has(E.tipo) && gp.nodos.includes(E.a) && gp.nodos.includes(E.b)) tipos.add(E.tipo); }));
      gp.color = tipos.has("pagador") ? COLOR_ARISTA.pagador : tipos.has("texto") ? COLOR_ARISTA.texto : COLOR_ARISTA.enlace;
    });

    // ---------- árbol orbital: provincia (sol) -> página donde llega más -> pagador que la paga
    const raices = provincias.slice();
    const colocados = new Set(raices);
    const mejor = (p, q) => p.gm > q.gm || (p.gm === q.gm && p.id < q.id);
    function crecer(frontera) {
      while (frontera.length) {
        const cand = new Map();
        frontera.forEach((p) => p.aristas.forEach((E) => {
          const c = otro(E, p);
          if (E.tipo === "partido" || colocados.has(c) || (p.tipo === "provincia" && E.tipo !== "alcance")) return;
          const cur = cand.get(c); if (!cur || mejor(p, cur)) cand.set(c, p);
        }));
        cand.forEach((p, c) => { c.parent = p; c.depth = p.depth + 1; p.kids.push(c); colocados.add(c); });
        frontera = [...cand.keys()];
      }
    }
    crecer(raices.slice());
    nodos.filter((n) => !colocados.has(n)).sort((a, b) => b.gm - a.gm || (a.id < b.id ? -1 : 1)).forEach((n) => {
      if (colocados.has(n)) return; colocados.add(n); raices.push(n); crecer([n]);       // huérfanos: forman su propio sistema
    });
    const porProfundidad = nodos.slice().sort((a, b) => a.depth - b.depth);
    raices.forEach((r, i) => { r.spin = i % 2 ? 1 : -1; });
    porProfundidad.forEach((n) => { if (n.parent) n.spin = -n.parent.spin; });

    /** Reparte los hijos de p en pistas concéntricas sin que se solapen sus huellas (nodo + lunas) al girar. */
    function planearOrbitas(p) {
      const ks = p.kids.slice().sort((a, b) => (b.ext - a.ext) || (b.gm - a.gm) || (a.id < b.id ? -1 : 1));
      if (!ks.length) { p.ext = p.r; return; }
      let interior = p.r + (p.tipo === "provincia" ? 8 : 4), i = 0, tk = 0;
      while (i < ks.length) {
        const f0 = ks[i].ext + 1.2, R = interior + f0 + 1.2;
        const need = (a, b) => 2 * Math.asin(Math.min(1, (a.ext + b.ext + 3.6) / (2 * R)));
        const items = [ks[i]]; let pares = 0;
        for (let j = i + 1; j < ks.length; j++) {
          const total = pares + need(items[items.length - 1], ks[j]) + need(ks[j], items[0]);
          if (total > TAU) break;
          pares += need(items[items.length - 1], ks[j]); items.push(ks[j]);
        }
        const s = items.length > 1 ? TAU / (pares + need(items[items.length - 1], items[0])) : 1;
        let a = hash(p.id + "#" + tk) * TAU;
        items.forEach((c, idx) => { c.orb = { R, a0: a, w: omega(R) * p.spin }; c.ang = a; if (idx < items.length - 1) a += need(c, items[idx + 1]) * s; });
        p.tracks.push(R); interior = R + f0; i += items.length; tk++;
      }
      p.ext = Math.max(p.r, interior);
    }
    for (let d = Math.max(...nodos.map((n) => n.depth)); d >= 0; d--) nodos.filter((n) => n.depth === d).forEach(planearOrbitas);
    // puesto de cada página por inversión dentro de su provincia: las 2 primeras de cada una llevan nombre aunque se vea todo el país
    nodos.forEach((n) => { n.rankProv = 99; });
    provincias.forEach((p) => p.kids.filter((c) => c.tipo === "pagina").sort((a, b) => b.gm - a.gm || (a.id < b.id ? -1 : 1)).forEach((c, i) => { c.rankProv = i; }));

    // ---------- nivel de detalle (qué nodos se dibujan según el zoom)
    // Con poco zoom solo se dibujan los «fijos» (provincias, pagadores y páginas con alguna conexión especial o con afiliación: son lo que se investiga)
    // y las páginas más grandes (mayor inversión) de cada provincia; al acercar la cámara aparecen más, de mayor a menor inversión, hasta ser todas.
    // Además aparecen las que rodean al cursor, la búsqueda, el partido filtrado y todo lo que esté seleccionado.
    nodos.forEach((n) => {
      n.lodRank = -1; n.visT = 1; n.visA = 1;
      n.fijo = n.tipo !== "pagina" || n.aristas.some((E) => E.tipo !== "alcance") || n.raw.afiliacion_estado !== "sin_registro";
    });
    const paginasLOD = [];            // las páginas que pueden quedar ocultas (no fijas), cada una con su puesto por inversión dentro de su provincia
    provincias.forEach((p) => p.kids.filter((c) => c.tipo === "pagina" && !c.fijo).sort((a, b) => b.gm - a.gm || (a.id < b.id ? -1 : 1)).forEach((c, i) => { c.lodRank = i; paginasLOD.push(c); }));
    const CUPO_MIN = Math.max(1, Number(op.cupoMinimo) || LOD_CUPO_MIN);      // páginas por provincia que se dibujan con el zoom de referencia
    const cupoLOD = (k) => Math.max(CUPO_MIN, Math.round(CUPO_MIN * Math.pow(k / LOD_K0, 2)));      // crece con el cuadrado del zoom: la densidad en pantalla se mantiene

    /** Posición de los sistemas: empaquetado en espiral + relajación (atracción por vínculos entre sistemas, sin solaparse). */
    function colocarSistemas() {
      const S = raices.slice().sort((a, b) => b.ext - a.ext).map((r) => ({ r, rad: r.ext + 12, x: 0, y: 0 })), puestos = [];
      S.forEach((s, i) => {
        if (i > 0) {
          let ang = hash(String(s.r.id)) * TAU;
          for (let t = 0; t < 20000; t++) {
            ang += 0.16; const rad = 4 + ang * 3.2, x = Math.cos(ang) * rad, y = Math.sin(ang) * rad;
            if (puestos.every((p) => Math.hypot(x - p.x, y - p.y) >= p.rad + s.rad)) { s.x = x; s.y = y; break; }
          }
        }
        puestos.push(s);
      });
      const de = new Map(S.map((s) => [s.r, s])), raizDe = (n) => { while (n.parent) n = n.parent; return n; }, pares = new Map();
      aristas.forEach((E) => {
        if (!E.esp || E.tipo === "partido" || E.tipo === "partido_prov") return;           // el partido no acerca los sistemas: la disposición sigue la geografía y los demás vínculos
        const ra = raizDe(E.a), rb = raizDe(E.b); if (ra === rb) return;
        const k = ra.id < rb.id ? ra.id + "|" + rb.id : rb.id + "|" + ra.id; if (!pares.has(k)) pares.set(k, { a: de.get(ra), b: de.get(rb), n: 0 }); pares.get(k).n++;
      });
      for (let it = 0; it < 260; it++) {
        pares.forEach((l) => {
          const dx = l.b.x - l.a.x, dy = l.b.y - l.a.y, d = Math.hypot(dx, dy) || 1, obj = l.a.rad + l.b.rad;
          if (d > obj) { const f = (d - obj) * Math.min(0.06, 0.015 * l.n); l.a.x += dx / d * f; l.a.y += dy / d * f; l.b.x -= dx / d * f; l.b.y -= dy / d * f; }
        });
        S.forEach((s) => { s.x *= 0.996; s.y *= 0.996; });
        for (let i = 0; i < S.length; i++) for (let j = i + 1; j < S.length; j++) {
          const a = S[i], b = S[j], dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1e-6, min = a.rad + b.rad;
          if (d < min) { const f = (min - d) / 2, ux = dx / d, uy = dy / d; a.x -= ux * f; a.y -= uy * f; b.x += ux * f; b.y += uy * f; }
        }
      }
      const cx = S.reduce((s, q) => s + q.x, 0) / S.length, cy = S.reduce((s, q) => s + q.y, 0) / S.length;
      S.forEach((s) => { s.r.pos = { compacto: [s.x - cx, s.y - cy] }; });
    }
    colocarSistemas();

    /**
     * Disposición geográfica: cada sol se acerca a la capital de su provincia (opciones.ubicaciones: nombre -> [lat, lng], los mismos
     * puntos del Mapa) y, donde los sistemas se solapan, se separan sin alejarse más de lo necesario (como un cartograma de Dorling).
     * Devuelve false si no hay ninguna ubicación conocida.
     */
    function colocarMapa() {
      const ub = {}; Object.entries(op.ubicaciones || {}).forEach(([k, v]) => { if (Array.isArray(v) && isFinite(v[0]) && isFinite(v[1])) ub[norm(k)] = v; });
      const S = raices.map((r) => {
        const u = r.tipo === "provincia" ? ub[norm(r.nombre)] : null, a = u ? aMundo(u[0], u[1]) : null, rad = r.ext + 14;
        return { r, rad, m: rad * rad, a, x: a ? a[0] : 0, y: a ? a[1] : 0 };
      });
      const con = S.filter((s) => s.a), sin = S.filter((s) => !s.a);
      if (!con.length) return false;
      if (sin.length) {                  // sistemas sin ubicación conocida: en columna, a la derecha del mapa
        const xmax = Math.max(...con.map((s) => s.a[0] + s.rad)), paso = 2 * Math.max(...sin.map((s) => s.rad)) + 10;
        sin.forEach((s, i) => { s.x = xmax + 140 + s.rad; s.y = (i - (sin.length - 1) / 2) * paso; });
      }
      for (let it = 0; it < 600; it++) {
        const tira = it < 520 ? 0.05 : 0;            // las últimas pasadas solo separan
        con.forEach((s) => { s.x += (s.a[0] - s.x) * tira; s.y += (s.a[1] - s.y) * tira; });
        for (let i = 0; i < S.length; i++) for (let j = i + 1; j < S.length; j++) {
          const a = S[i], b = S[j], dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1e-6, min = a.rad + b.rad;
          if (d < min) { const f = min - d, ux = dx / d, uy = dy / d, wa = b.m / (a.m + b.m), wb = 1 - wa; a.x -= ux * f * wa; a.y -= uy * f * wa; b.x += ux * f * wb; b.y += uy * f * wb; }
        }
      }
      S.forEach((s) => { s.r.pos.mapa = [s.x, s.y]; s.r.anc = s.a; });       // anc: la capital real (en mundo), para la línea punteada
      return true;
    }
    const hayMapa = colocarMapa();
    const plantillaTeselas = op.teselas || null;
    let mapaOn = hayMapa && (op.disposicionMapa ? !!op.disposicionMapa() : true);      // true: los soles están sobre el mapa
    let mapaA = mapaOn ? 1 : 0;                                                         // opacidad del mapa base (se anima al cambiar)
    const posRaiz = (r) => r.pos[mapaOn ? "mapa" : "compacto"] || r.pos.compacto;
    raices.forEach((r) => { const p = posRaiz(r); r.bx = r.bx0 = p[0]; r.by = r.by0 = p[1]; });

    // ---------- DOM: lienzo, controles de zoom, leyenda, tooltip
    const st = { hover: null, hoverE: null, sel: null, selE: null, grupoE: null, speed: RM ? 0 : 1, kb: -1 };       // hoverE / selE: la conexión bajo el puntero y la pulsada
    let W = 0, H = 0, DPR = 1, fondo = null, clock = 0, tscale = 1, drag = null, down = null, pointer = null, pointerIn = false, sucio = true, ajustado = false, raf = 0, ultimo = performance.now();
    let animCam = null, zoomTxt = "", muerto = false, camTocada = false;      // camTocada: la persona ya movió la cámara (no se reencuadra sola)
    const cam = { k: 1, x: 0, y: 0 };
    const rest = op.restaurar || null;      // vista de una instancia anterior de esta misma red (cámara y selección): ver estado()
    const aX = (x) => x * cam.k + cam.x, aY = (y) => y * cam.k + cam.y, mX = (sx) => (sx - cam.x) / cam.k, mY = (sy) => (sy - cam.y) / cam.k;

    const cv = h("canvas", { id: "rg-canvas", tabindex: "0", role: "img", style: "display:block;width:100%;height:100%;cursor:grab;touch-action:none",
      "aria-label": `Red de ${nodos.length} nodos y ${aristas.length} conexiones entre pagadores, páginas y provincias. Usa las flechas para recorrer los nodos.` });
    const ctx = cv.getContext("2d");
    const zoomInfo = h("span", null, "1.0×");
    const visInfo = h("strong", null, String(nodos.length));      // «X de N» nodos: cuántos se dibujan con este zoom (nivel de detalle)
    let visTxt = "";
    const caja = h("div", { class: "rs-zoom" }, ...[["+", "Acercar", "in"], ["−", "Alejar", "out"], ["⤢", "Ajustar a la pantalla", "reset"]].map(([t, lb, k]) =>
      h("button", { type: "button", class: "btn rg-z", "data-z": k, "aria-label": lb, title: lb,
        style: "min-height:0;width:36px;height:36px;padding:0",
        onclick: () => { if (k === "reset") ajustar(); else zoomPor(k === "in" ? 1.3 : 1 / 1.3, W / 2, H / 2); } }, t)));
    // botones del mapa (arriba de los de zoom): «Mapa» alterna entre los soles sobre el mapa y la disposición compacta; «Galápagos» viaja a las islas
    const estiloBtn = "min-height:0;height:36px;padding:0 10px;font-weight:700";
    const btnMapa = h("button", { type: "button", class: "btn rg-mapa", "aria-pressed": String(mapaOn), hidden: !hayMapa, style: estiloBtn,
      title: "Pone cada sol en la capital de su provincia, sobre el mapa de Ecuador", onclick: () => aplicarDisposicion(!mapaOn, true) }, "Mapa");
    const btnGal = h("button", { type: "button", class: "btn rg-gal", hidden: true, style: estiloBtn, title: "Ir a las islas Galápagos (están lejos, en el océano)",
      onclick: () => { const n = raices.find((r) => norm(r.nombre) === "galapagos"); if (n) irA(n, 1.1); } }, "Galápagos");
    caja.prepend(btnMapa, btnGal);
    const atrib = h("a", { class: "rs-atrib", href: "https://www.openstreetmap.org/copyright", target: "_blank", rel: "noopener noreferrer", hidden: true }, "© OpenStreetMap");
    const leyenda = h("div", { class: "rs-leyenda xsmall" });
    let leyAbierta = op.leyendaAbierta ? !!op.leyendaAbierta() : true;       // la leyenda se puede plegar para dejar más espacio a la red
    const tip = h("div", { class: "ro-tip", role: "tooltip", hidden: true });
    const vivo = h("div", { class: "visually-hidden", "aria-live": "polite" });
    cont.replaceChildren(cv, caja, leyenda, atrib, tip, vivo);
    let teselasOk = 0, teselasMal = 0, mapaSinTeselas = false;
    const cbTeselas = {
      carga() { teselasOk++; sucio = true; if (mapaSinTeselas) { mapaSinTeselas = false; pintarLeyenda(); } },
      error() { teselasMal++; if (!teselasOk && teselasMal >= 6 && !mapaSinTeselas) { mapaSinTeselas = true; pintarLeyenda(); } }
    };
    function actualizarBotonesMapa() {
      btnMapa.setAttribute("aria-pressed", String(mapaOn));
      btnGal.hidden = !(hayMapa && mapaOn && raices.some((r) => norm(r.nombre) === "galapagos"));
      atrib.hidden = !(mapaOn && plantillaTeselas);
    }
    /** Cambia entre soles sobre el mapa y disposición compacta; con `animar` los sistemas viajan y el mapa aparece o se desvanece. */
    function aplicarDisposicion(mapa, animar) {
      if (mapa && !hayMapa) return;
      mapaOn = !!mapa;
      raices.forEach((r) => {
        const p = posRaiz(r); r.bx0 = p[0]; r.by0 = p[1];
        if (animar && !RM) r.tgt = [p[0], p[1]]; else { r.bx = p[0]; r.by = p[1]; r.tgt = null; }
      });
      if (!animar || RM) mapaA = mapaOn ? 1 : 0;
      actualizarBotonesMapa(); pintarLeyenda(); camTocada = false; ajustar(animar && !RM ? 900 : 0); sucio = true;
      if (op.alCambiarDisposicion) op.alCambiarDisposicion(mapaOn);
    }
    actualizarBotonesMapa();

    // ---------- filtros: resaltan, no ocultan
    const fechaMax = () => (fechas.length > 1 ? fechas[F.fechaIdx] : null);
    function aristaViva(E) {
      if (E.tipo === "alcance") return true;        // página → provincia: es lo que ordena la red; ningún filtro la atenúa
      if (!F.tipos.has(E.tipo)) return false;
      const fm = fechaMax(); if (fm && E.raw.primero && E.raw.primero > fm) return false;
      if (F.activos) {
        const ok = E.tipo === "pagador" ? E.raw.activos > 0 : [E.a, E.b].filter((x) => x.tipo === "pagina").every((x) => x.raw.activos > 0);
        if (!ok) return false;
      }
      return true;
    }
    const coincide = (n, q) => !q || n.nq.includes(q);

    // ---------- color
    const top3 = provincias.slice(0, 3).map((p) => p.nombre);
    const SERIES = [PAL.c1, PAL.c2, PAL.c3];
    const provDe = (n) => { let r = n; while (r.parent) r = r.parent; return r.tipo === "provincia" ? r.nombre : null; };
    function colorNodo(n) {
      if (F.color === "provincia") {
        const i = top3.indexOf(provDe(n)); return i >= 0 ? SERIES[i] : (n.tipo === "provincia" ? PAL.sol : PAL.tinta3);
      }
      if (n.tipo === "provincia") return PAL.sol;
      if (F.color === "afiliacion") {
        const p = partidoDe(n); if (p) return colorDePartido(p) || PAL.tinta2;
        return n.raw.afiliacion_estado === "sin_registro" ? PAL.tinta3 : PAL.tinta2;
      }
      return n.tipo === "pagador" ? PAL.c2 : PAL.c1;
    }
    const colorDeArista = (E) => (E.tipo === "partido" || E.tipo === "partido_prov" ? (colorDePartido(E.raw.partido) || COLOR_ARISTA[E.tipo]) : colorArista(E.tipo));

    /** Refleja leyAbierta en la leyenda (botón, resumen y cuerpo) sin reconstruirla. */
    function aplicarLeyenda() {
      leyenda.classList.toggle("plegada", !leyAbierta);
      const t = leyenda.querySelector(".rs-ley-toggle"), cuerpo = leyenda.querySelector(".rs-ley-cuerpo"), resumen = leyenda.querySelector(".rs-ley-resumen");
      if (t) { t.setAttribute("aria-expanded", String(leyAbierta)); t.title = leyAbierta ? "Ocultar la leyenda" : "Mostrar la leyenda"; }
      if (cuerpo) cuerpo.hidden = !leyAbierta;
      if (resumen) resumen.hidden = !leyAbierta;
    }
    function alternarLeyenda() { leyAbierta = !leyAbierta; aplicarLeyenda(); if (op.alPlegarLeyenda) op.alPlegarLeyenda(leyAbierta); }

    function pintarLeyenda() {
      const par = (c, t, glifo) => h("span", { class: "rs-ley-par" }, h("span", { class: "rs-ley-ic", style: "color:" + c }, glifo || "●"), h("span", null, t));     // icono y texto en columnas alineadas
      const col = (titulo, items) => {                                  // una columna de la leyenda: subtítulo y un elemento por línea
        const it = items.filter(Boolean);
        return it.length ? h("div", { class: "rs-ley-col" }, h("div", { class: "rs-ley-sub" }, titulo), ...it.map((x) => h("div", { class: "rs-ley-it" }, x))) : null;
      };
      const visibles = aristas.filter(aristaVisible);
      let colores;
      if (F.color === "afiliacion") {
        const oc = F.ocultos && F.ocultos.size ? F.ocultos : null;      // solo los partidos de lo que los filtros dejan a la vista
        const partidos = [...new Set(nodos.filter((n) => !(oc && oc.has(n.id))).map(partidoDe).filter(Boolean))].sort();
        colores = [...partidos.map((p) => par(colorDePartido(p) || PAL.tinta2, p)), par(PAL.tinta2, "afiliación sin partido"), par(PAL.tinta3, "sin registro")];
      } else if (F.color === "provincia") {
        colores = [...top3.map((p, i) => par(SERIES[i], p)), par(PAL.tinta3, "otras provincias")];
      } else colores = [par(PAL.sol, "provincia", "◉"), par(PAL.c1, "página"), par(PAL.c2, "pagador", "◆")];
      const tipos = [...new Set(visibles.map((E) => (E.tipo === "partido_prov" ? "partido" : E.tipo)))].filter((t) => t !== "alcance");      // el partido dentro y entre provincias comparte una sola entrada
      const toggle = h("button", { type: "button", class: "rs-ley-toggle", "aria-controls": "rs-ley-cuerpo", "aria-expanded": String(leyAbierta), onclick: alternarLeyenda },
        h("span", { class: "rs-ley-chev", "aria-hidden": "true" }, "▾"), "Leyenda");
      leyenda.replaceChildren(
        h("div", { class: "rs-ley-cab" }, toggle, h("span", { class: "rs-ley-resumen", title: "Con poco zoom solo se dibujan las páginas de mayor inversión de cada provincia y las que tienen conexiones o afiliación; al acercar el zoom o el cursor aparecen más." },
          visInfo, " nodos · ", h("strong", null, String(visibles.length)), " conexiones · ", h("strong", null, String(grupos.length)), " grupos · zoom ", zoomInfo)),
        // tres columnas, una idea por línea (mismo esquema que la leyenda del mapa de provincias)
        h("div", { class: "rs-ley-cols rs-ley-cuerpo", id: "rs-ley-cuerpo" },
          col("Nodos", [...colores,
            mapaOn && mapaSinTeselas ? h("span", null, "mapa base no disponible (sin conexión)") : null]),
          col("Grupos (halo)", [
            grupos.some((g) => g.color === COLOR_ARISTA.pagador) ? par(COLOR_ARISTA.pagador, "pagador en común", "◌") : null,
            grupos.some((g) => g.color === COLOR_ARISTA.texto) ? par(COLOR_ARISTA.texto, "texto repetido", "◌") : null,
            grupos.some((g) => g.color === COLOR_ARISTA.enlace) ? par(COLOR_ARISTA.enlace, "mismo enlace", "◌") : null]),
          col("Conexiones", [...tipos.map((t) => par(colorArista(t), defArista(t).corto,defArista(t).glifo || "──")),
            alcanceOn() && nodos.some((n) => Array.isArray(n.raw.regiones) && n.raw.regiones.length > 1) ? par(PAL.c3, "otras provincias (al elegir una página)", "━━") : null])));
      aplicarLeyenda();
    }

    // ---------- cámara
    function zoomPor(f, cx, cy) {
      const k = clamp(cam.k * f, 0.15, 9), r = k / cam.k; animCam = null; camTocada = true;
      cam.x = cx - (cx - cam.x) * r; cam.y = cy - (cy - cam.y) * r; cam.k = k; sucio = true;
    }
    function irACamara(k, x, y, dur) {
      if (!dur || RM) { cam.k = k; cam.x = x; cam.y = y; animCam = null; sucio = true; return; }
      animCam = { t0: performance.now(), dur, de: { k: cam.k, x: cam.x, y: cam.y }, a: { k, x, y } };
    }
    function ajustar(dur = 600) {
      if (!W || !H) return;
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      // sobre el mapa se encuadra el país continental: Galápagos queda lejos, en el océano (hay un botón para ir allí)
      let lista = mapaOn ? raices.filter((r) => norm(r.nombre) !== "galapagos") : raices; if (!lista.length) lista = raices;
      lista.forEach((r) => { const p = posRaiz(r); x0 = Math.min(x0, p[0] - r.ext); x1 = Math.max(x1, p[0] + r.ext); y0 = Math.min(y0, p[1] - r.ext); y1 = Math.max(y1, p[1] + r.ext); });
      const arriba = W < 700 ? 56 : 68, abajo = W < 700 ? 56 : 28, lado = 24;
      const k = clamp(Math.min((W - 2 * lado) / (x1 - x0), (H - arriba - abajo) / (y1 - y0)), 0.15, 2.4);
      irACamara(k, W / 2 - k * (x0 + x1) / 2, arriba + (H - arriba - abajo) / 2 - k * (y0 + y1) / 2, dur);
      camTocada = false;
    }
    /**
     * Pone un punto del mundo en el centro de la parte del lienzo que no tapan los paneles ni la barra de arriba (opciones.cubierto(): { izq, der, arriba, abajo } en px),
     * con el zoom `k`. Así lo seleccionado no queda debajo del panel de detalle, ni a un lado en pantallas anchas ni debajo de la hoja en móviles.
     */
    function centrarEnLibre(wx, wy, k = cam.k, dur = 650) {
      const c = (op.cubierto && op.cubierto()) || {}, izq = c.izq || 0, der = c.der || 0, arr = c.arriba || 0, aba = c.abajo || 0;
      const cx = izq + Math.max(40, W - izq - der) / 2, cy = arr + Math.max(40, H - arr - aba) / 2;
      camTocada = true;
      irACamara(k, cx - k * wx, cy - k * wy, dur);
    }
    function irA(n, k = Math.max(cam.k, 2)) { centrarEnLibre(n.wx, n.wy, k); }
    /**
     * Encuadra un conjunto de nodos en la parte libre del lienzo. Con `conZoom` la cámara se aleja lo necesario para que quepan todos
     * (y se acerca hasta 2× si están muy juntos); sin él solo se centra.
     */
    function encuadrarNodos(ns, conZoom = true, dur = 650) {
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      ns.forEach((n) => { x0 = Math.min(x0, n.wx); x1 = Math.max(x1, n.wx); y0 = Math.min(y0, n.wy); y1 = Math.max(y1, n.wy); });
      if (x1 < x0) return;
      let k = cam.k;
      // abajo está la leyenda (plegada o abierta): el encuadre deja libre su alto, hasta un cuarto del lienzo
      const PIE = Math.min(H * 0.25, leyenda && !leyenda.hidden ? leyenda.getBoundingClientRect().height + 12 : 40);
      if (conZoom) {
        const c = (op.cubierto && op.cubierto()) || {}, MARCO = 80;       // margen para los nombres y el giro de las órbitas
        const lw = Math.max(60, W - (c.izq || 0) - (c.der || 0) - 2 * MARCO), lh = Math.max(60, H - (c.arriba || 0) - (c.abajo || 0) - 2 * MARCO - PIE);
        k = clamp(Math.min(lw / Math.max(1, x1 - x0), lh / Math.max(1, y1 - y0), Math.max(cam.k, 2)), 0.15, 9);
      }
      centrarEnLibre((x0 + x1) / 2, (y0 + y1) / 2 + PIE / 2 / k, k, dur);
    }
    /**
     * El grupo de una conexión pulsada: todas las conexiones del mismo tipo que comparten con ella algún texto (o enlace) y las páginas que unen.
     * Es lo que queda encendido mientras el resto de la red se atenúa.
     */
    function grupoDeArista(E) {
      const as = new Set([E]), ns = new Set([E.a, E.b]), oc = F.ocultos;
      if (E.tipo === "partido" || E.tipo === "partido_prov") {       // una línea de partido equivale a filtrar por él: todas sus páginas y sus líneas
        const p = E.raw.partido;
        for (const X of aristas) {
          if ((X.tipo !== "partido" && X.tipo !== "partido_prov") || X.raw.partido !== p || !aristaVisible(X)) continue;
          if (oc && (oc.has(X.a.id) || oc.has(X.b.id))) continue;
          as.add(X); ns.add(X.a); ns.add(X.b);
        }
        for (const n of nodos) if (n.tipo !== "provincia" && partidoDe(n) === p && !(oc && oc.has(n.id))) ns.add(n);
        return { aristas: as, nodos: ns, partido: p };
      }
      const det = new Set(E.raw.detalles || []);
      if (det.size) for (const X of aristas) {
        if (X === E || X.tipo !== E.tipo || !(X.raw.detalles || []).some((d) => det.has(d))) continue;
        if (oc && (oc.has(X.a.id) || oc.has(X.b.id))) continue;
        as.add(X); ns.add(X.a); ns.add(X.b);
      }
      return { aristas: as, nodos: ns };
    }
    /**
     * Si la red se reconstruye (p. ej. al guardar un perfil) o la página se recarga, la cámara vuelve a donde estaba en vez de encuadrar todo.
     * Se guarda el centro en coordenadas del mundo y el zoom (no el desplazamiento en píxeles), así sigue valiendo si cambió el tamaño de la ventana.
     * No se restaura si la persona nunca movió la cámara (se reencuadra sola) ni si la disposición (mapa o compacta) es otra.
     */
    function restaurarCamara() {
      if (!rest || !rest.tocada || !!rest.mapa !== mapaOn || !isFinite(rest.k) || !isFinite(rest.cx) || !isFinite(rest.cy)) return false;
      const k = clamp(rest.k, 0.15, 9);
      cam.k = k; cam.x = W / 2 - k * rest.cx; cam.y = H / 2 - k * rest.cy; animCam = null; camTocada = true; sucio = true;
      return true;
    }

    // ---------- movimiento: órbitas jerárquicas, arrastre con resistencia y retorno elástico
    const comets = [];
    aristas.forEach((E) => {
      if (!E.esp || E.tipo === "partido" || E.tipo === "partido_prov") return;
      if (E.tipo === "pagador") comets.push({ E, t: Math.random(), v: 26 + Math.random() * 14, dir: E.a.tipo === "pagador" ? 1 : -1 });      // el flujo va del pagador a la página
      else comets.push({ E, t: Math.random(), v: 24 + Math.random() * 12, dir: 1 }, { E, t: Math.random(), v: 24 + Math.random() * 12, dir: -1 });
    });
    const RESIST = 11, MAXARR = 70, K_EL = 80, C_EL = 9;
    const escala = () => clamp(Math.pow(cam.k, 0.65), 0.5, 1.9);      // los nodos crecen menos que el zoom (las letras y los nodos no se vuelven enormes), pero ya no se amontonan al alejar
    const focoNodo = () => st.hover || st.sel;
    const conjuntoFoco0 = (n) => { if (!n._fs) { const s = new Set([n]); vecinos(n).forEach((v) => s.add(v)); if (n.grupo) n.grupo.nodos.forEach((v) => s.add(v)); n._fs = s; } return n._fs; };

    const conjuntoFoco = (n) => {
      const base = conjuntoFoco0(n); if (n !== st.sel) return base;
      const otras = otrasProvincias(n); if (!otras.length) return base;
      const s = new Set(base); otras.forEach((o) => s.add(o.p)); return s;
    };
    function radioNodo(n) {
      let r = n.r * escala(); const f = focoNodo();
      if (f) { if (n === f) r *= 1.15; else if (conjuntoFoco(f).has(n)) r *= 1.05; else r *= 0.7; }
      return r;
    }
    function acierto(x, y) {         // gana el vecino más cercano en proporción a su tamaño; el área mínima es de ~24 px
      let mejorN = null, bd = Infinity;
      for (const n of nodos) {
        if (n.visA < 0.5) continue;                              // lo que no se dibuja (nivel de detalle) no se puede señalar
        const lim = Math.max(radioNodo(n) + 4, 12), d = Math.hypot(n.sx - x, n.sy - y); if (d <= lim && d / lim < bd) { mejorN = n; bd = d / lim; }
      }
      return mejorN;
    }
    const distSeg = (px, py, x1, y1, x2, y2) => {
      const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy, t = l2 ? clamp(((px - x1) * dx + (py - y1) * dy) / l2, 0, 1) : 0;
      return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
    };
    /** La conexión pulsable (CLICABLES) más cercana al punto, a menos de ~9 px de su curva; la curva se recorre en 20 tramos. Los nodos tienen prioridad (ver acierto). */
    function aciertoArista(x, y) {
      if (!op.alElegirArista) return null;
      const TOL = 9; let mejor = null, bd = TOL;
      for (const E of aristas) {
        if (!E.dib || !CLICABLES.has(E.tipo) || !aristaViva(E)) continue;
        const A = E.a, B = E.b;
        if (x < Math.min(A.sx, B.sx, E.cx) - TOL || x > Math.max(A.sx, B.sx, E.cx) + TOL || y < Math.min(A.sy, B.sy, E.cy) - TOL || y > Math.max(A.sy, B.sy, E.cy) + TOL) continue;
        let p = [A.sx, A.sy];
        for (let i = 1; i <= 20; i++) {
          const q = qAt(E, i / 20), d = distSeg(x, y, p[0], p[1], q[0], q[1]);
          if (d < bd) { bd = d; mejor = E; }
          p = q;
        }
      }
      return mejor;
    }
    function actualizar(dt) {
      if (pointerIn && !drag && st.kb < 0) {
        const n = pointer ? acierto(pointer[0], pointer[1]) : null;
        const e = n || pan || !pointer ? null : aciertoArista(pointer[0], pointer[1]);      // un nodo tiene prioridad; con la cámara arrastrándose no se destaca ninguna línea
        if (n !== st.hover || e !== st.hoverE) { st.hover = n; st.hoverE = e; cv.style.cursor = n ? "grab" : e ? "pointer" : ""; mostrarTip(); sucio = true; }
      }
      const objetivo = (drag || st.hover || st.hoverE) ? 0.03 : (st.sel || st.selE ? 0.5 : 1);        // bajo el puntero la órbita casi se detiene: la línea no se escapa del clic
      tscale += (objetivo - tscale) * (1 - Math.exp(-dt * 5));
      const adt = dt * tscale * st.speed;
      if (adt) nodos.forEach((n) => { if (n.parent) n.ang += n.orb.w * adt; });
      const mapaObj = mapaOn ? 1 : 0;                     // el mapa base aparece o se desvanece con suavidad
      if (mapaA !== mapaObj) { mapaA += (mapaObj - mapaA) * (1 - Math.exp(-dt * (RM ? 60 : 3))); if (Math.abs(mapaObj - mapaA) < 0.004) mapaA = mapaObj; sucio = true; }
      raices.forEach((r) => {
        if (!r.tgt || (drag && drag.n === r)) return;
        const k = 1 - Math.exp(-dt * 4); r.bx += (r.tgt[0] - r.bx) * k; r.by += (r.tgt[1] - r.by) * k;
        if (Math.hypot(r.tgt[0] - r.bx, r.tgt[1] - r.by) < 0.2) { r.bx = r.tgt[0]; r.by = r.tgt[1]; r.tgt = null; }
      });
      if (drag && drag.listo) {          // el nodo sigue al cursor con inercia; la distancia se "frena" (banda elástica)
        const n = drag.n, tx = drag.cx - drag.gx, ty = drag.cy - drag.gy, k = 1 - Math.exp(-dt * RESIST);
        if (!n.parent) { n.bx += (tx - n.bx) * k; n.by += (ty - n.by) * k; }
        else {
          const P = n.parent, sx = P.wx + n.orb.R * Math.cos(n.ang), sy = P.wy + n.orb.R * Math.sin(n.ang);
          const dx = tx - sx, dy = ty - sy, m = Math.hypot(dx, dy) || 1e-6, ms = MAXARR * Math.tanh(m / MAXARR);
          n.ox += (dx * ms / m - n.ox) * k; n.oy += (dy * ms / m - n.oy) * k; n.vx = n.vy = 0;
        }
      }
      let mov = false;
      if (mapaOn) raices.forEach((r) => {                // sobre el mapa los soles tienden a volver a su sitio (la ubicación significa algo)
        if (r.tgt || (drag && drag.n === r)) return;
        const k = 1 - Math.exp(-dt * 1.4); r.bx += (r.bx0 - r.bx) * k; r.by += (r.by0 - r.by) * k;
        if (Math.abs(r.bx0 - r.bx) + Math.abs(r.by0 - r.by) > 0.3) mov = true;
      });
      nodos.forEach((n) => {             // al soltar, el nodo regresa a su órbita como un muelle amortiguado
        if (!n.parent || (drag && drag.n === n) || !(n.ox || n.oy || n.vx || n.vy)) return;
        n.vx += (-K_EL * n.ox - C_EL * n.vx) * dt; n.vy += (-K_EL * n.oy - C_EL * n.vy) * dt; n.ox += n.vx * dt; n.oy += n.vy * dt; mov = true;
        if (Math.hypot(n.ox, n.oy) < 0.02 && Math.hypot(n.vx, n.vy) < 0.05) n.ox = n.oy = n.vx = n.vy = 0;
      });
      for (let i = 0; i < raices.length; i++) for (let j = i + 1; j < raices.length; j++) {       // los sistemas no se atraviesan
        const a = raices[i], b = raices[j], dx = b.bx - a.bx, dy = b.by - a.by, d = Math.hypot(dx, dy) || 1e-6, min = a.ext + b.ext + 12;
        if (d < min) {
          const push = (min - d) * 0.5 * Math.min(1, dt * 6), ux = dx / d, uy = dy / d, ad = drag && drag.n === a, bd = drag && drag.n === b;
          if (!ad) { a.bx -= ux * push * (bd ? 2 : 1); a.by -= uy * push * (bd ? 2 : 1); }
          if (!bd) { b.bx += ux * push * (ad ? 2 : 1); b.by += uy * push * (ad ? 2 : 1); }
          mov = true;
        }
      }
      porProfundidad.forEach((n) => {
        if (!n.parent) { n.wx = n.bx; n.wy = n.by; }
        else { const P = n.parent; n.wx = P.wx + n.orb.R * Math.cos(n.ang) + n.ox; n.wy = P.wy + n.orb.R * Math.sin(n.ang) + n.oy; }
      });
      if (!RM) comets.forEach((c) => { c.t += c.dir * (c.v / Math.max(30, c.E.len)) * dt; if (c.t > 1) c.t -= 1; if (c.t < 0) c.t += 1; });
      if (st.hover || st.hoverE) moverTip();
      return mov;
    }

    // ---------- dibujo
    const polvo = Array.from({ length: 140 }, (_, i) => ({ u: hash("u" + i), v: hash("v" + i), a: 0.05 + hash("a" + i) * 0.12, ph: hash("p" + i) * 6.28, s: 0.5 + hash("s" + i) * 0.9 }));
    const ordenDibujo = [...nodos.filter((n) => n.tipo === "provincia"), ...nodos.filter((n) => n.tipo === "pagina"), ...nodos.filter((n) => n.tipo !== "provincia" && n.tipo !== "pagina")];
    const medidas = new Map();
    function medir(t, font) { const k = font + "|" + t; let w = medidas.get(k); if (w == null) { ctx.font = font; w = ctx.measureText(t).width; medidas.set(k, w); } return w; }
    const solapa = (a, b) => a[0] < b[0] + b[2] + 2 && a[0] + a[2] + 2 > b[0] && a[1] < b[1] + b[3] + 2 && a[1] + a[3] + 2 > b[1];
    const qAt = (E, t) => { const u = 1 - t; return [u * u * E.a.sx + 2 * u * t * E.cx + t * t * E.b.sx, u * u * E.a.sy + 2 * u * t * E.cy + t * t * E.b.sy]; };

    /** Mapa base: teselas de OpenStreetMap oscurecidas, en las mismas coordenadas de la cámara (pan y zoom son los de la red). */
    function dibujarMapaBase() {
      if (!plantillaTeselas) return;
      const z = clamp(Math.round(Z0 + Math.log2(cam.k)), 4, 13), lado = LADO_TESELA * Math.pow(2, Z0 - z), n = Math.pow(2, z);      // lado: tamaño de una tesela en unidades de mundo
      const tx0 = Math.max(0, Math.floor((mX(0) + ORIGEN[0]) / lado)), tx1 = Math.min(n - 1, Math.floor((mX(W) + ORIGEN[0]) / lado));
      const ty0 = Math.max(0, Math.floor((mY(0) + ORIGEN[1]) / lado)), ty1 = Math.min(n - 1, Math.floor((mY(H) + ORIGEN[1]) / lado));
      if ((tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 90) return;
      const ahora = performance.now(), tam = lado * cam.k + 0.6;      // +0,6 px de solape para que no se vean costuras
      ctx.imageSmoothingEnabled = true;
      for (let ty = ty0; ty <= ty1; ty++) for (let tx = tx0; tx <= tx1; tx++) {
        const sx = aX(tx * lado - ORIGEN[0]), sy = aY(ty * lado - ORIGEN[1]);
        const t = teselaDe(plantillaTeselas, z, tx, ty, cbTeselas);
        if (!t.listo) {                                 // mientras llega: la tesela de un nivel menos, ya cargada (más borrosa, pero sin huecos)
          for (let up = 1; up <= 3 && z - up >= 3; up++) {
            const pt = teselas.get(plantillaTeselas + "|" + (z - up) + "/" + (tx >> up) + "/" + (ty >> up));
            if (pt && pt.listo) { const sub = LADO_TESELA / (1 << up); ctx.globalAlpha = mapaA; ctx.drawImage(pt.cv, (tx - ((tx >> up) << up)) * sub, (ty - ((ty >> up) << up)) * sub, sub, sub, sx, sy, tam, tam); break; }
          }
          continue;
        }
        const a = RM ? 1 : clamp((ahora - t.t0) / 350, 0, 1); if (a < 1) sucio = true;
        ctx.globalAlpha = mapaA * a; ctx.drawImage(t.cv, sx, sy, tam, tam);
      }
      ctx.globalAlpha = 1;
    }

    // Iluminado extra de un tipo de conexión (p. ej. «texto» con la sección «Mensajes repetidos» abierta): lo pide la app con
    // opciones.tipoDestacado() o un destello temporal (destacar). Al activarse lanza un pulso de ondas sobre esas conexiones.
    let destAnt = null, destT0 = -99, forzado = null;
    /** ¿La conexión es del tipo iluminado? El filtro «partido» cubre también los conectores entre soles (partido_prov). */
    const coincideDest = (E, d) => !!d && (E.tipo === d || (d === "partido" && E.tipo === "partido_prov"));
    const tipoDest = () => (forzado && clock < forzado.hasta ? forzado.tipo : (op.tipoDestacado ? op.tipoDestacado() : null)) || null;

    /**
     * Qué nodos se dibujan ahora (nivel de detalle). `visT` es lo que corresponde (1 o 0) y `visA` se le acerca poco a poco, así que los nodos aparecen y
     * desaparecen con suavidad al mover el zoom o el cursor. Se dibujan: lo fijo, las páginas más grandes de cada provincia que permite el zoom
     * (cupoLOD), las que rodean al cursor (las de mayor inversión, hasta LENTE_MAX), lo seleccionado y su entorno, la búsqueda y el partido filtrado.
     * `snap`: sin transición (primer cuadro y pruebas).
     */
    let ultClockVis = 0, animVis = false, visInicial = true;
    function actualizarVisibilidad(snap) {
      const k = cam.k, cupo = cupoLOD(k), kk = snap ? 1 : 1 - Math.exp(-clamp(clock - ultClockVis, 0, 0.1) * 9);
      ultClockVis = clock;
      const forz = st.sel ? conjuntoFoco(st.sel) : (st.selE && st.grupoE ? st.grupoE.nodos : null), q = norm(F.buscar);
      let lente = null;
      if (pointerIn && pointer && !drag && !pan && cupo < paginasLOD.length) {
        const cerca = [], r2 = LENTE_PX * LENTE_PX;
        for (const n of paginasLOD) { if (n.lodRank >= cupo) { const dx = n.sx - pointer[0], dy = n.sy - pointer[1]; if (dx * dx + dy * dy < r2) cerca.push(n); } }
        lente = new Set(cerca.sort((a, b) => a.lodRank - b.lodRank).slice(0, LENTE_MAX));
      }
      animVis = false;
      const ocultos = F.ocultos && F.ocultos.size ? F.ocultos : null, forzados = F.forzados || null;      // segmentadores: lo excluido no se dibuja
      porProfundidad.forEach((n) => {               // los padres antes que sus hijos
        let t = 1;
        if (ocultos && ocultos.has(n.id)) t = 0;
        else if (n.tipo === "pagina") {
          t = (n.lodRank < cupo || (forzados && forzados.has(n.id)) || n === st.hover || (forz && forz.has(n)) || (q && coincide(n, q)) || (F.partidos.size && F.partidos.has(partidoDe(n))) || (lente && lente.has(n))) ? 1 : 0;
        } else if (n.tipo === "pagador") t = n.parent ? n.parent.visT : 1;
        n.visT = t;
        n.visA = snap || Math.abs(t - n.visA) < 0.01 ? t : n.visA + (t - n.visA) * kk;
        if (n.visA !== t) animVis = true;
      });
    }

    function dibujarNodo(n, fs, q, extra) {
      const col = colorNodo(n), r = radioNodo(n), x = n.sx, y = n.sy, prov = n.tipo === "provincia", pagr = n.tipo === "pagador", va = n.visA;
      let alfa = 1;
      if (q && !coincide(n, q)) alfa = Math.min(alfa, 0.16);
      if (fs && !fs.has(n)) alfa = Math.min(alfa, 0.2);
      if (F.partidos.size && !F.partidos.has(partidoDe(n))) alfa = Math.min(alfa, prov ? 0.5 : 0.15);
      const pt = partidoDe(n), pc = pt && colorDePartido(pt), pend = n.raw.afiliacion_estado === "pendiente", verif = n.raw.afiliacion_estado === "verificada";
      // Las páginas comunes y pequeñas se dibujan sin degradado ni brillo (con cientos a la vez, cada degradado cuesta): un punto con zoom bajo o una
      // esfera ya dibujada con zoom medio. Las especiales (afiliación, enfocadas, buscadas, resaltadas) y las grandes, completas.
      if (n.tipo === "pagina" && !pc && !verif && !pend && n !== st.sel && n !== st.hover && !(extra && extra.set.has(n)) && !(q && coincide(n, q))) {
        if (r < 3.4) { ctx.globalAlpha = alfa * va; ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, Math.max(1, r - 0.3), 0, TAU); ctx.fill(); ctx.globalAlpha = 1; return; }
        if (r < 5.5) { const d = r * 2.56; ctx.globalAlpha = alfa * va; ctx.drawImage(esfera(col), x - d / 2, y - d / 2, d, d); ctx.globalAlpha = 1; return; }
      }
      if (alfa === 1) {
        const pulso = RM ? 1 : 1 + 0.05 * Math.sin(clock * 1.6 + n.ph), gs = r * (prov ? 4.6 : pagr ? 4.2 : 3) * pulso * (q && coincide(n, q) ? 1.4 : 1);
        ctx.globalCompositeOperation = MEZCLA; ctx.globalAlpha = (prov ? 0.5 : pagr ? 0.55 : 0.38) * va;
        ctx.drawImage(brillo(col), x - gs, y - gs, gs * 2, gs * 2);
        if (extra && extra.set.has(n)) {                // extremo de una conexión iluminada: resplandor extra del color del vínculo
          const g2 = r * 5.5; ctx.globalAlpha = 0.3 * extra.p * va; ctx.drawImage(brillo(extra.col), x - g2, y - g2, g2 * 2, g2 * 2);
        }
        ctx.globalCompositeOperation = "source-over";
      }
      ctx.globalAlpha = alfa * va;
      const gr = ctx.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.08, x, y, r * 1.05);
      gr.addColorStop(0, mezcla(col, 0.6)); gr.addColorStop(0.5, col); gr.addColorStop(1, mezcla(col, 0.45, [0, 0, 0]));
      ctx.beginPath();
      if (pagr) { ctx.moveTo(x, y - r * 1.2); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r * 1.2); ctx.lineTo(x - r, y); ctx.closePath(); } else ctx.arc(x, y, r, 0, TAU);
      ctx.fillStyle = gr; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = FONDO; ctx.stroke();           // anillo de 2 px del color de la superficie
      if (prov) { ctx.beginPath(); ctx.arc(x, y, r * 1.22, 0, TAU); ctx.strokeStyle = TEMA.anillo; ctx.lineWidth = 1; ctx.stroke(); }
      if (pc || verif || pend) {          // anillo: partido verificado (su color), verificada sin partido (gris), pendiente (punteado)
        ctx.beginPath(); ctx.arc(x, y, r + 3.8, 0, TAU); ctx.lineWidth = 2;
        ctx.strokeStyle = pc || PAL.tinta2; if (pend && !pc) ctx.setLineDash([3, 2]); ctx.stroke(); ctx.setLineDash([]);
      }
      ctx.globalAlpha = 1;
    }

    function dibujar() {
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over"; ctx.setLineDash([]);
      ctx.fillStyle = fondo; ctx.fillRect(0, 0, W, H);
      if (mapaA > 0.004) dibujarMapaBase();
      // con una conexión pulsada (texto o enlace repetido) el foco es su grupo: lo demás se atenúa igual que al seleccionar una entidad
      const f = focoNodo(), gE = !f && st.selE ? st.grupoE : null, fs = f ? conjuntoFoco(f) : (gE ? gE.nodos : null), q = norm(F.buscar), k = cam.k;
      const MARGEN = 48;         // lo que queda fuera de la pantalla (más este margen) no se dibuja; las provincias (soles) sí siempre: su brillo es grande
      nodos.forEach((n) => { n.sx = aX(n.wx); n.sy = aY(n.wy); });
      actualizarVisibilidad(visInicial); visInicial = false;      // qué nodos corresponden con este zoom (usa las posiciones recién calculadas)
      let nVis = 0;
      nodos.forEach((n) => { if (n.visA > 0.5) nVis++; n.vp = (n.tipo === "provincia" && n.visA > 0.02) || (n.visA > 0.02 && n.sx > -MARGEN && n.sx < W + MARGEN && n.sy > -MARGEN && n.sy < H + MARGEN); });
      const tVis = nVis < nodos.length ? nVis + " de " + nodos.length : String(nodos.length);
      if (tVis !== visTxt) { visTxt = tVis; visInfo.textContent = tVis; }
      const dest = tipoDest();
      if (dest !== destAnt) { if (dest) destT0 = clock; destAnt = dest; }       // al activarse, el pulso de ondas empieza de nuevo
      const pulsoD = RM ? 1 : 0.8 + 0.2 * Math.sin(clock * 3.4), colDest = dest ? colorArista(dest) : null;
      const nodosDest = new Set(), resaltadas = [];                              // extremos y conexiones del tipo iluminado

      if (!RM && mapaA < 0.98) polvo.forEach((d) => {  // polvo: profundidad muy sutil (parallax); desaparece sobre el mapa
        const x = (((d.u * (W + 40) + cam.x * 0.25) % (W + 40)) + (W + 40)) % (W + 40) - 20, y = (((d.v * (H + 40) + cam.y * 0.25) % (H + 40)) + (H + 40)) % (H + 40) - 20;
        ctx.globalAlpha = d.a * (1 - mapaA) * (0.65 + 0.35 * Math.sin(clock * 0.7 + d.ph)); ctx.fillStyle = PAL.tinta2; ctx.fillRect(x, y, d.s, d.s);
      });
      ctx.globalAlpha = 1;

      if (mapaA > 0.03) {                               // sol desplazado para no solapar: línea punteada hasta la capital real de su provincia
        ctx.lineWidth = 1;
        raices.forEach((r) => {
          if (!r.anc || r.visA < 0.3) return;
          const ax = aX(r.anc[0]), ay = aY(r.anc[1]); if (Math.hypot(r.sx - ax, r.sy - ay) < 12) return;
          ctx.setLineDash([3, 3]); ctx.strokeStyle = rgba(PAL.sol, 0.4 * mapaA); ctx.beginPath(); ctx.moveTo(r.sx, r.sy); ctx.lineTo(ax, ay); ctx.stroke();
          ctx.setLineDash([]); ctx.fillStyle = rgba(PAL.sol, 0.75 * mapaA); ctx.beginPath(); ctx.arc(ax, ay, 2.6, 0, TAU); ctx.fill();
        });
      }

      ctx.lineWidth = 1;                                // pistas orbitales: hairlines sólidas y recesivas
      nodos.forEach((n) => {
        if (!n.tracks.length || (n.parent && k < 1.5) || n.visA < 0.3) return;
        // en un sol solo se dibujan las órbitas que ya tienen algún nodo a la vista (las de más afuera aparecen al acercar el zoom)
        let hasta = Infinity;
        if (n.tipo === "provincia") { hasta = 0; for (const c of n.kids) if (c.visA > 0.3 && c.orb && c.orb.R > hasta) hasta = c.orb.R; }
        const enSis = fs && fs.has(n); ctx.strokeStyle = rgba(PAL.pista, (n.parent ? 0.06 : 0.08) * (fs && !enSis ? 0.4 : 1) + (enSis ? 0.07 : 0));
        n.tracks.forEach((R) => { if (R <= hasta + 0.5) { ctx.beginPath(); ctx.arc(n.sx, n.sy, R * k, 0, TAU); ctx.stroke(); } });
      });

      ctx.globalCompositeOperation = MEZCLA;         // halos de grupo (un lavado de ~15 %)
      grupos.forEach((gp) => {
        const sutil = gp.color === COLOR_ARISTA.texto || gp.color === COLOR_ARISTA.enlace;
        const txtTenue = sutil && dest !== (gp.color === COLOR_ARISTA.texto ? "texto" : "enlace") && !(fs && gp.nodos.some((n) => fs.has(n))) ? 0.3 : 1;   // texto repetido y mismo enlace: halo sutil hasta que se filtra o se enfoca
        const a = (fs && !gp.nodos.some((n) => fs.has(n)) ? 0.35 : 1) * txtTenue;
        const refuerzo = dest && gp.color === colDest;                            // el halo del grupo iluminado crece y respira
        gp.nodos.forEach((n) => {
          if (n.visA < 0.3) return;
          const rad = (n.r * 2.4 + 38) * Math.sqrt(k) * (refuerzo ? 1.1 : 1), gr = ctx.createRadialGradient(n.sx, n.sy, 0, n.sx, n.sy, rad);
          gr.addColorStop(0, rgba(gp.color, Math.min(0.3, 0.2 * a * (refuerzo ? 1.25 * pulsoD : 1)))); gr.addColorStop(1, rgba(gp.color, 0));      // iluminado: apenas más que en reposo (el texto repetido se sumaba hasta deslumbrar)
          ctx.fillStyle = gr; ctx.fillRect(n.sx - rad, n.sy - rad, rad * 2, rad * 2);
        });
      });
      ctx.globalCompositeOperation = "source-over";

      const chips = [];                                 // conexiones: curvas con halo; el punteado distingue el tipo (canal secundario)
      const lotes = new Map();                          // uniones página → provincia por opacidad: se trazan juntas (ver más abajo)
      aristas.forEach((E) => {
        E.dib = false; if (!aristaVisible(E) || (F.tiposOcultos && F.tiposOcultos.has(E.tipo))) return;
        if (F.partidosOcultos && F.partidosOcultos.size && (E.tipo === "partido" || E.tipo === "partido_prov") && F.partidosOcultos.has(E.raw.partido)) return;
        // fuera de la pantalla (la caja de sus dos extremos no toca la vista, con margen para el arco) no se calcula ni se traza
        if (Math.max(E.a.sx, E.b.sx) < -80 || Math.min(E.a.sx, E.b.sx) > W + 80 || Math.max(E.a.sy, E.b.sy) < -80 || Math.min(E.a.sy, E.b.sy) > H + 80) { E.lab = false; return; }
        // si uno de sus extremos no se dibuja (nivel de detalle), la conexión tampoco; mientras aparece, lo hace con él (en pasos de 0,25: así se agrupan)
        const vE = Math.min(E.a.visA, E.b.visA);
        if (vE < 0.02) { E.lab = false; return; }
        const vq = vE >= 0.98 ? 1 : Math.max(0.15, Math.round(vE * 4) / 4);
        // las conexiones especiales tienen un arco mínimo: así se ven aunque las dos páginas orbiten pegadas
        const A = E.a, B = E.b, dx = B.sx - A.sx, dy = B.sy - A.sy, len = Math.hypot(dx, dy) || 1, prov = E.tipo === "partido_prov";
        // los conectores entre soles son largos: arco suave, y los de un mismo par (varios partidos) se abren en abanico
        const bend = prov ? (E.par % 2 ? 1 : -1) * (Math.min(60, Math.max(len * 0.1, 14)) + 14 * Math.floor(E.par / 2))
          : (E.i % 2 ? 1 : -1) * Math.min(70, E.esp ? Math.max(len * 0.2, 16) : len * 0.08);
        E.cx = (A.sx + B.sx) / 2 - dy / len * bend; E.cy = (A.sy + B.sy) / 2 + dx / len * bend; E.len = len / k; E.dib = true;
        const viva = aristaViva(E), caliente = f && (A === f || B === f), col = colorDeArista(E), dash = defArista(E.tipo).dash || [];
        let al = prov ? 0.55 : E.tipo === "partido" ? 0.62 : E.esp ? 0.82 : 0.15; if (!viva) al = 0.05;      // partido: líneas sutiles incluso activadas
        if (F.partidos.size && !(prov ? F.partidos.has(E.raw.partido) : (F.partidos.has(partidoDe(A)) || F.partidos.has(partidoDe(B))))) al *= 0.2;
        if (q && !coincide(A, q) && !coincide(B, q)) al *= 0.3;
        const enGrupo = !!gE && gE.aristas.has(E);                                  // repite el mismo texto (o enlace) que la conexión pulsada
        if (fs) al = caliente ? TEMA.caliente : (gE ? (enGrupo ? al : al * 0.12) : (fs.has(A) && fs.has(B) ? al : al * 0.15));
        const elegida = st.selE === E, sobre = st.hoverE === E;                     // la conexión pulsada y la que está bajo el puntero
        // con una entidad enfocada, de las conexiones de partido solo queda la suya (la que la une a su partido); las demás, entre soles
        // o de otras páginas, casi desaparecen y no se rotulan: con las provincias de su alcance encendidas competían con ella
        const partidoAjeno = f && f.tipo !== "provincia" && (E.tipo === "partido" || prov) && !caliente && !elegida && !sobre;
        if (partidoAjeno) al = Math.min(al, 0.05);
        if (E.tipo === "alcance" && !caliente && !elegida && !sobre) {              // son cientos: un solo trazo por cada opacidad, en vez de uno por unión
          const clave = (al * vq).toFixed(4); let lote = lotes.get(clave); if (!lote) { lote = new Path2D(); lotes.set(clave, lote); }
          lote.moveTo(A.sx, A.sy); lote.quadraticCurveTo(E.cx, E.cy, B.sx, B.sy); E.lab = false; return;
        }
        // texto repetido y mismo enlace: líneas sutiles de fondo; solo se vuelven notorias al elegirlas, al pasar el puntero, al enfocar uno de sus nodos o al filtrar por su tipo
        const tenue = (E.tipo === "texto" || E.tipo === "enlace") && !(dest === E.tipo || elegida || sobre || caliente || enGrupo);
        // partido: también línea de fondo, pero más visible que la del texto repetido; se activa al filtrar por «partido», al elegir un partido, al pasar el puntero o al enfocar uno de sus nodos
        const esPart = E.tipo === "partido" || prov;
        const tenueP = esPart && !(dest === "partido" || F.partidos.size > 0 || F.partidoFiltrado || elegida || sobre || caliente || enGrupo);
        if (tenue) al *= 0.25;
        if (tenueP) al = Math.min(al, 0.38);
        if (viva && (elegida || sobre)) al = 0.98; else if (viva && enGrupo) al = Math.max(al, 0.85);
        al *= vq;
        // pagador: el grosor sube con el número de anuncios; texto/enlace/partido no traen conteo y se dibujan siempre bien visibles
        const w = (E.tipo === "pagador" ? 1.3 + Math.min(1.5, Math.log10(1 + (E.raw.anuncios || 1))) : prov ? (tenueP ? 1 : 1.4) : E.tipo === "partido" ? (tenueP ? 1 : 1.6) : tenue ? 0.9 : E.esp ? 2.2 : 0.8) * (caliente ? 1.5 : 1) * (elegida ? 1.5 : sobre ? 1.3 : 1);
        const porTipo = coincideDest(E, dest) && viva && (!gE || enGrupo), resaltada = porTipo || (viva && (elegida || sobre || enGrupo)), grosor = resaltada ? w + (esPart || !(viva && (elegida || sobre || enGrupo)) ? 0.4 : 0.9) : w;
        if (porTipo) { nodosDest.add(A); nodosDest.add(B); if (!esPart) resaltadas.push(E); }       // partido: sin pulso de ondas (son cientos de líneas)
        ctx.beginPath(); ctx.moveTo(A.sx, A.sy); ctx.quadraticCurveTo(E.cx, E.cy, B.sx, B.sy);
        ctx.globalCompositeOperation = MEZCLA; ctx.lineCap = "round";
        // Iluminar todo un tipo (p. ej. «texto» con «Mensajes repetidos» abierto) da a esas líneas el mismo resplandor leve que al partido; las tres
        // capas que "respiran" quedan para la conexión elegida, la que está bajo el puntero y su grupo (igual en texto, enlace y pagador).
        const leve = esPart || !(viva && (elegida || sobre || enGrupo));
        if (resaltada && leve && !esPart) al = Math.min(al, 0.62 * vq);           // misma opacidad que una línea de partido iluminada: las de texto se superponen por decenas y se sumaban
        if (resaltada) {
          if (!leve) {
            ctx.strokeStyle = rgba(col, al * 0.07 * pulsoD); ctx.lineWidth = grosor * 12; ctx.stroke();
            ctx.strokeStyle = rgba(col, al * 0.16 * pulsoD); ctx.lineWidth = grosor * 6.5; ctx.stroke();
          }
          ctx.strokeStyle = rgba(col, al * (leve ? 0.2 : 0.34)); ctx.lineWidth = grosor * (leve ? 2.4 : 3.2); ctx.stroke();
        } else if (E.esp && E.tipo !== "partido" && !prov && viva && al > 0.3) { ctx.strokeStyle = rgba(col, al * 0.22); ctx.lineWidth = w * 4; ctx.stroke(); }
        ctx.setLineDash(dash); ctx.strokeStyle = rgba(resaltada && !leve ? aclarar(col, 0.4) : col, Math.min(1, resaltada && !leve ? al * 1.15 : al)); ctx.lineWidth = grosor; ctx.stroke();
        ctx.setLineDash([]); ctx.globalCompositeOperation = "source-over";
        // montos: con un nodo enfocado solo se rotulan sus conexiones y las de su grupo (el resto no compite por la atención)
        if (E.esp && E.tipo !== "partido" && !tenue && !partidoAjeno && viva && (F.etiquetas || caliente) && (!fs || caliente || (gE ? enGrupo : (fs.has(A) && fs.has(B))))) chips.push({ E, prio: (caliente ? 0 : 1) - (E.labPrev ? 0.3 : 0) });
        E.lab = false;
      });
      if (lotes.size) {
        ctx.globalCompositeOperation = MEZCLA; ctx.lineCap = "round"; ctx.setLineDash([]); ctx.lineWidth = 0.8;
        lotes.forEach((lote, clave) => { ctx.strokeStyle = rgba(colorArista("alcance"), Math.min(1, Number(clave) * TEMA.alcance)); ctx.stroke(lote); });
        ctx.globalCompositeOperation = "source-over";
      }

      // con una página seleccionada, una línea casi imperceptible hacia cada otra provincia donde llega: lo que se lee es el % junto a cada sol
      const chipsAlc = [];
      if (st.sel && st.sel.tipo === "pagina" && st.sel.visA > 0.3) {
        const n = st.sel, otras = otrasProvincias(n), atenuar = st.hover && st.hover !== n && !otras.some((o) => o.p === st.hover) ? 0.35 : 1;
        const principal = n.parent && n.parent.tipo === "provincia" ? n.parent : null;
        if (principal && n.raw.region) chipsAlc.push({ p: principal, v: n.raw.region.pct, principal: true });
        const aparece = RM ? 1 : clamp((clock - (st.selT || 0)) / 0.6, 0, 1), col = PAL.c3;      // las líneas se trazan desde la página en 0,6 s
        ctx.globalCompositeOperation = MEZCLA; ctx.lineCap = "round";
        otras.forEach(({ p, v }, i) => {
          const dx = p.sx - n.sx, dy = p.sy - n.sy, len = Math.hypot(dx, dy) || 1, bend = (i % 2 ? 1 : -1) * Math.min(90, len * 0.16);
          const cx = (n.sx + p.sx) / 2 - dy / len * bend, cy = (n.sy + p.sy) / 2 + dx / len * bend;
          const w = 0.8, al = (0.1 + 0.2 * Math.sqrt(v)) * atenuar;
          // curva parcial (de la página hacia la provincia) mientras aparece
          const t = suave(aparece), pts = [];
          for (let j = 0; j <= 24; j++) { const u = t * j / 24, m = 1 - u; pts.push([m * m * n.sx + 2 * m * u * cx + u * u * p.sx, m * m * n.sy + 2 * m * u * cy + u * u * p.sy]); }
          ctx.beginPath(); pts.forEach(([x, y], j) => (j ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
          ctx.strokeStyle = rgba(col, al); ctx.lineWidth = w; ctx.stroke();
          if (aparece >= 1) chipsAlc.push({ p, v });
        });
        ctx.globalCompositeOperation = "source-over";
      }

      if (!RM) {                                        // cometas: dirección del flujo (del pagador a la página)
        ctx.globalCompositeOperation = MEZCLA;
        comets.forEach((c) => {
          const E = c.E; if (!E.dib || !aristaViva(E) || (fs && !(fs.has(E.a) && fs.has(E.b)))) return;
          const gr = coincideDest(E, dest), col = gr ? aclarar(colorDeArista(E), 0.2) : colorDeArista(E), N = gr ? 11 : 9;     // en lo iluminado, cometas más grandes y de cola más larga
          const tenueC = E.tipo === "texto" && !gr && st.selE !== E && st.hoverE !== E && !(gE && gE.aristas.has(E)) && !(f && (E.a === f || E.b === f)) ? 0.25 : 1;   // texto repetido sin enfocar: cometas apagados
          for (let i = 0; i < N; i++) {
            const u = c.t - c.dir * (gr ? 0.22 : 0.12) * (i / N); if (u < 0 || u > 1) continue;
            const p = qAt(E, u), a = 1 - i / N; ctx.fillStyle = rgba(col, 0.9 * a * a * tenueC); ctx.beginPath(); ctx.arc(p[0], p[1], (1 + 1.6 * a) * escala() * (gr ? 1.25 : 1), 0, TAU); ctx.fill();
          }
        });
        ctx.globalCompositeOperation = "source-over";
      }

      if (!RM && dest && resaltadas.length) {           // pulso de ondas al activarse: llama la atención sin mover la cámara
        const u = (clock - destT0) / 2.8;
        if (u >= 0 && u < 1) {
          ctx.globalCompositeOperation = MEZCLA; ctx.lineWidth = 2;
          resaltadas.forEach((E) => {
            const p = qAt(E, 0.5);
            for (let j = 0; j < 2; j++) {
              const uu = u - j * 0.22; if (uu <= 0) continue;
              ctx.strokeStyle = rgba(aclarar(colDest, 0.35), Math.pow(1 - uu, 1.6) * 0.75);
              ctx.beginPath(); ctx.arc(p[0], p[1], (6 + uu * 90) * escala(), 0, TAU); ctx.stroke();
            }
          });
          ctx.globalCompositeOperation = "source-over";
        }
      }

      const extra = dest ? { set: nodosDest, col: colDest, p: pulsoD } : null;
      ordenDibujo.forEach((n) => { if (n.vp) dibujarNodo(n, fs, q, extra); });

      nodos.forEach((n) => { n.labPrev = n.lab; n.lab = false; });        // etiquetas selectivas, sin solaparse, con histéresis
      const cands = [];
      // «lente»: con zoom bajo no caben los nombres de todo, pero al acercar el cursor se rotula lo que lo rodea (hasta donde haya sitio)
      const lente = pointerIn && pointer && !drag && !pan && k < 1.7 ? pointer : null;
      const conPct = new Set(chipsAlc.map((c) => c.p));
      nodos.forEach((n) => {
        if (!n.vp || n.visA < 0.6 || (fs && !fs.has(n)) || (q && !coincide(n, q))) return;         // lo que está fuera de la pantalla o aún no se ve no se rotula
        let pr;
        if (f && n === f) pr = -4; else if (q && coincide(n, q)) pr = -3;
        else if (conPct.has(n)) pr = -2.6;                                          // una provincia con su % del alcance siempre lleva su nombre
        else if (fs && fs.has(n)) pr = -2;
        else if (st.selE && (n === st.selE.a || n === st.selE.b)) pr = -1.9;                // las dos páginas de la conexión pulsada siempre llevan su nombre
        else if (nodosDest.has(n)) pr = -1.6;                                       // se ve quién está detrás del vínculo iluminado
        else if (F.partidos.size && F.partidos.has(partidoDe(n))) pr = -1;
        else if (n.tipo === "provincia") pr = 0; else if (n.tipo === "pagador") pr = 1;
        else pr = n.rank < 10 ? 2 + n.rank * 0.05 : (n.rankProv < 2 ? 2.4 + n.rankProv * 0.1 : (k > 1.7 ? 4 : 99));      // 10 mayores del país y 2 mayores de cada provincia
        if (pr >= 99 && lente) { const d = Math.hypot(n.sx - lente[0], n.sy - lente[1]); if (d < LENTE_PX) pr = 0.5 + 1.4 * d / LENTE_PX; }
        if (pr > -2.5 && (n.sx < 2 || n.sx > W - 2 || n.sy < 2 || n.sy > H - 2)) return;
        if (pr < 99) cands.push({ n, pr: pr - (n.labPrev ? 0.3 : 0) });
      });
      cands.sort((a, b) => a.pr - b.pr);
      ctx.textBaseline = "middle"; ctx.textAlign = "left"; ctx.lineJoin = "round"; ctx.lineWidth = 3.4; ctx.strokeStyle = TEMA.halo;
      // las zonas que tapan los controles del lienzo (zoom, leyenda, atribución) cuentan como ocupadas: ahí no se pone ninguna etiqueta
      const rc = cv.getBoundingClientRect();
      const puestos = [caja, leyenda, atrib].filter((e) => e && !e.hidden).map((e) => {
        const b = e.getBoundingClientRect(); return [b.left - rc.left - 3, b.top - rc.top - 3, b.width + 6, b.height + 6];
      }).filter((b) => b[2] > 8 && b[3] > 8);
      // el % del alcance va encima de cada sol unido a la página seleccionada: su sitio se reserva antes de rotular, así ningún nombre
      // (tampoco el de esa provincia) queda debajo de la etiqueta; los nombres buscan otra posición (derecha, izquierda o debajo)
      chipsAlc.forEach((c) => {
        c.fz = Math.round(11 + 9 * Math.sqrt(c.v)); c.alto = c.fz + 9;
        c.texto = (c.v * 100 >= 10 ? Math.round(c.v * 100) : (c.v * 100).toFixed(1)) + " %";
        const w = medir(c.texto, "700 " + c.fz + "px " + FUENTE) + 12;
        c.x = c.p.sx; c.y = c.p.sy - radioNodo(c.p) - c.alto / 2 - 6; c.caja = [c.x - w / 2, c.y - c.alto / 2, w, c.alto];
        puestos.push(c.caja);
      });
      cands.forEach(({ n, pr }) => {
        const prov = n.tipo === "provincia", font = (prov || pr < -1.5 ? "650 " : "500 ") + (prov ? 12.5 : 11.5) + "px " + FUENTE;
        const texto = trunc(n.nombre, prov ? 30 : 26), tw = medir(texto, font), r = radioNodo(n);
        // posiciones posibles: a la derecha, a la izquierda, debajo y encima (se prueba primero la que ya tenía, para que no salte)
        const pos = [[n.sx + r + 5, n.sy], [n.sx - r - 5 - tw, n.sy], [n.sx - tw / 2, n.sy + r + 10], [n.sx - tw / 2, n.sy - r - 10]];
        const orden = [n.labPos != null ? n.labPos : 0, 0, 1, 2, 3].filter((v, i, a) => a.indexOf(v) === i);
        let elegida = -1, caja2 = null;
        for (const i of orden) {
          const [px, py] = pos[i]; if (px < 4 || px + tw > W - 4 || py < 10 || py > H - 10) continue;
          const c = [px - 2, py - 8, tw + 4, 16];
          if (!puestos.some((b) => solapa(c, b))) { elegida = i; caja2 = c; break; }
        }
        if (elegida < 0) {                                                        // solo el nodo enfocado y las coincidencias de búsqueda se dibujan siempre
          if (pr > -2.5) return;
          elegida = 0; caja2 = [pos[0][0] - 2, pos[0][1] - 8, tw + 4, 16];
        }
        n.labPos = elegida; const [bx, by] = pos[elegida];
        puestos.push(caja2); n.lab = true; ctx.font = font; ctx.strokeText(texto, bx, by); ctx.fillStyle = (prov || pr < -1.5) ? PAL.tinta : PAL.tinta2; ctx.fillText(texto, bx, by);
      });
      ctx.font = "600 11px " + FUENTE; ctx.textAlign = "center";           // montos sobre las conexiones especiales
      chips.sort((a, b) => a.prio - b.prio).forEach(({ E }) => {
        if (!op.etiquetaArista) return;
        const p = qAt(E, 0.5), texto = op.etiquetaArista(E.raw), w = medir(texto, ctx.font) + 8, caja2 = [p[0] - w / 2, p[1] - 8, w, 16];
        if (puestos.some((b) => solapa(caja2, b))) return;
        puestos.push(caja2); E.lab = true; ctx.fillStyle = TEMA.chip; ctx.fillRect(caja2[0], caja2[1], w, 16);
        ctx.fillStyle = PAL.tinta; ctx.fillText(texto, p[0], p[1]);
      });
      for (const E of aristas) E.labPrev = E.lab;
      // el % del alcance junto a cada sol unido a la página seleccionada (la principal en gris claro, las demás en el color de sus líneas)
      // el tamaño de la etiqueta crece con el %: es lo que debe notarse (las líneas apenas se ven)
      chipsAlc.forEach(({ principal, fz, alto, texto, x, y, caja: c }) => {
        ctx.font = "700 " + fz + "px " + FUENTE;
        ctx.fillStyle = principal ? PAL.tinta2 : PAL.c3; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(c[0], c[1], c[2], alto, alto / 2) : ctx.rect(c[0], c[1], c[2], alto); ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = FONDO; ctx.stroke();
        ctx.fillStyle = FONDO; ctx.fillText(texto, x, y + 0.5);
      });
      ctx.textAlign = "left";

      const s = st.sel;                                 // selección: anillo + pulso
      if (s) {
        const r = radioNodo(s) + 6; ctx.strokeStyle = PAL.tinta; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(s.sx, s.sy, r, 0, TAU); ctx.stroke();
        if (!RM) { const u = (clock % 2.2) / 2.2; ctx.globalAlpha = (1 - u) * 0.5; ctx.beginPath(); ctx.arc(s.sx, s.sy, r + u * 22, 0, TAU); ctx.stroke(); ctx.globalAlpha = 1; }
      }
      if (st.hover && st.hover !== s) { ctx.strokeStyle = "rgba(240,239,236,.7)"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(st.hover.sx, st.hover.sy, radioNodo(st.hover) + 5, 0, TAU); ctx.stroke(); }
      const z = k.toFixed(1) + "×"; if (z !== zoomTxt) { zoomTxt = z; zoomInfo.textContent = z; }
    }

    // ---------- tooltip y anuncios para lectores de pantalla
    function mostrarTip() {
      const n = st.hover;
      if (!n && st.hoverE) {                          // una conexión pulsable bajo el puntero: qué une y que se puede pulsar
        const E = st.hoverE;
        tip.replaceChildren(h("div", { class: "t" }, E.a.nombre + " ↔ " + E.b.nombre), h("div", { class: "v" }, defArista(E.tipo).nombre),
          h("div", { class: "s" }, E.raw.partido && E.tipo !== "texto" && E.tipo !== "enlace" ? "Clic para ver solo las páginas de " + E.raw.partido
            : E.tipo === "enlace" ? "Clic para ver el enlace que comparten estas páginas" : "Clic para ver los mensajes repetidos entre estas páginas"));
        tip.hidden = false; moverTip(); return;
      }
      if (!n) { tip.hidden = true; return; }
      const lineas = [h("div", { class: "t" }, n.nombre), h("div", { class: "v" }, "Inversión estimada " + usd(n.gm)),
        h("div", { class: "s" }, ETIQ[n.tipo] + (n.tipo === "provincia" ? " · " + (n.raw.paginas || n.kids.length) + " páginas" : n.raw.anuncios ? " · " + n.raw.anuncios + " anuncios" : ""))];
      const pg = [...vecinos(n)].filter((v) => v.tipo === "pagador"); if (n.tipo === "pagina" && pg.length) lineas.push(h("div", { class: "s" }, "Pagado por: " + pg.map((x) => x.nombre).join(", ")));
      if (n.grupo) lineas.push(h("div", { class: "s" }, "Grupo " + n.grupo.n + " · páginas enlazadas por pagador o texto"));
      tip.replaceChildren(...lineas); tip.hidden = false; moverTip();
    }
    function moverTip() {
      const n = st.hover; if ((!n && !st.hoverE) || tip.hidden) return;
      const [x, y] = n && st.kb >= 0 ? [n.sx, n.sy] : (pointer || (n ? [n.sx, n.sy] : [W / 2, H / 2])), w = tip.offsetWidth, hh = tip.offsetHeight;
      let tx = x + 16, ty = y + 14; if (tx + w > W - 8) tx = x - w - 16; if (ty + hh > H - 8) ty = y - hh - 14;
      tip.style.transform = `translate(${Math.max(4, tx)}px, ${Math.max(4, ty)}px)`;
    }
    const anunciar = (t) => { vivo.textContent = t; };

    // ---------- selección (el panel de detalle lo pinta la app)
    // `restaurado`: la selección se vuelve a poner al reconstruir la red (la app decide si refresca el panel de detalle; no se anuncia)
    function seleccionar(n, restaurado = false) {
      st.sel = n; st.selE = null; st.grupoE = null; sucio = true; st.selT = clock;
      if (op.alSeleccionar) op.alSeleccionar(n ? n.raw : null, n ? n.aristas.filter(aristaVisible).map((E) => Object.assign({}, E.raw, { a: E.a.raw, b: E.b.raw })) : [], restaurado);
      if (n && !restaurado) {
        anunciar(`${ETIQ[n.tipo]} ${n.nombre}. Inversión estimada ${usd(n.gm)}. ${vecinos(n).size} conexiones.`);
        // si la página llega a otras provincias, se encuadran la página y esos soles para que se vean sus líneas
        const otras = otrasProvincias(n);
        if (otras.length) encuadrarNodos([n, ...otras.map((o) => o.p)]); else centrarEnLibre(n.wx, n.wy);
      }
    }

    /**
     * Una conexión pulsada (texto repetido o mismo enlace): quedan encendidas ella y las demás que repiten lo mismo, sus páginas llevan nombre, el resto
     * de la red se atenúa, la cámara encuadra todas esas páginas y la app muestra lo que las une en el panel lateral (`grupo`: sus nombres).
     */
    function elegirArista(E, restaurado = false) {
      st.sel = null; st.selE = E; st.grupoE = grupoDeArista(E); sucio = true;
      if (op.alElegirArista) op.alElegirArista(Object.assign({}, E.raw, { a: E.a.raw, b: E.b.raw, grupo: [...st.grupoE.nodos].map((n) => n.nombre), miembros: [...st.grupoE.nodos].map((n) => n.raw) }), restaurado);
      if (!restaurado) {
        const n = st.grupoE.nodos.size;
        anunciar(st.grupoE.partido ? `Partido ${st.grupoE.partido}: ${n} nodos resaltados.` : `${defArista(E.tipo).nombre}: ${E.a.nombre} y ${E.b.nombre}${n > 2 ? `, y ${n - 2} ${n === 3 ? "página más" : "páginas más"}` : ""}.`);
        encuadrarNodos(st.grupoE.nodos);      // todas las páginas donde se repite, en lo que el panel no tapa
      }
    }

    // ---------- interacción
    const posDe =(ev) => { const r = cv.getBoundingClientRect(); return [(ev.clientX - r.left) * W / (r.width || 1), (ev.clientY - r.top) * H / (r.height || 1)]; };
    const toques = new Map(); let pinch = null, pan = null;
    cv.addEventListener("wheel", (ev) => {              // rueda o pellizco del panel táctil: acerca o aleja alrededor del cursor
      ev.preventDefault();
      const dy = ev.deltaY * (ev.deltaMode === 1 ? 16 : 1), p = posDe(ev);
      zoomPor(Math.exp(-dy * (ev.ctrlKey ? 0.01 : 0.0015)), p[0], p[1]);
    }, { passive: false });
    cv.addEventListener("pointerenter", () => { pointerIn = true; });
    cv.addEventListener("pointerleave", () => { pointerIn = false; if (!drag && st.kb < 0 && (st.hover || st.hoverE)) { st.hover = null; st.hoverE = null; tip.hidden = true; sucio = true; } });
    cv.addEventListener("pointerdown", (ev) => {
      if (ev.button > 0) return;
      const p = posDe(ev), n = acierto(p[0], p[1]), e = n ? null : aciertoArista(p[0], p[1]); pointer = p; toques.set(ev.pointerId, p);
      try { cv.setPointerCapture(ev.pointerId); } catch (_) { /* sin captura */ }
      if (toques.size === 2) {                            // dos dedos: pellizco
        const [p1, p2] = [...toques.values()]; pinch = { d: Math.hypot(p1[0] - p2[0], p1[1] - p2[1]) || 1, k: cam.k };
        drag = null; pan = null; down = null; return;
      }
      down = { x: ev.clientX, y: ev.clientY, n, e, moved: false };
      if (n) {
        drag = { n, id: ev.pointerId, gx: mX(p[0]) - n.wx, gy: mY(p[1]) - n.wy, cx: mX(p[0]), cy: mY(p[1]), listo: false }; n.tgt = null;
        cv.style.cursor = "grabbing";
      } else pan = { p, x: cam.x, y: cam.y };
      animCam = null; sucio = true;
    });
    cv.addEventListener("pointermove", (ev) => {
      const p = posDe(ev); pointer = p; sucio = true;
      if (toques.has(ev.pointerId)) toques.set(ev.pointerId, p);
      if (pinch && toques.size === 2) {
        const [p1, p2] = [...toques.values()], d = Math.hypot(p1[0] - p2[0], p1[1] - p2[1]) || 1;
        zoomPor((pinch.k * d / pinch.d) / cam.k, (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2); return;
      }
      if (down && Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 4) down.moved = true;
      if (drag && ev.pointerId === drag.id) { drag.cx = mX(p[0]); drag.cy = mY(p[1]); if (down && down.moved) drag.listo = true; }
      else if (pan) { cam.x = pan.x + p[0] - pan.p[0]; cam.y = pan.y + p[1] - pan.p[1]; camTocada = true; cv.style.cursor = "grabbing"; }
    });
    function soltar(ev) {
      toques.delete(ev.pointerId); if (toques.size < 2) pinch = null;
      if (drag && ev.pointerId === drag.id) { if (mapaOn && !drag.n.parent) drag.n.tgt = [drag.n.bx0, drag.n.by0]; drag = null; }      // sobre el mapa, el sol vuelve a su provincia

      if (down && ev.type === "pointerup" && !down.moved) {                                    // un clic simple: selecciona (o limpia en el fondo)
        if (down.e && !down.n) elegirArista(down.e); else seleccionar(down.n || null);
      }
      down = null; pan = null; cv.style.cursor = st.hover ? "grab" : st.hoverE ? "pointer" : ""; sucio = true;
    }
    cv.addEventListener("pointerup", soltar); cv.addEventListener("pointercancel", soltar);
    const ordenTeclado = nodos.filter((n) => n.tipo !== "provincia").sort((a, b) => b.gm - a.gm).concat(provincias);
    cv.addEventListener("keydown", (ev) => {
      const t = ev.key;
      if (t === "Escape") { st.kb = -1; st.hover = null; tip.hidden = true; seleccionar(null); return; }
      if (t === "+" || t === "=") { zoomPor(1.3, W / 2, H / 2); return; }
      if (t === "-") { zoomPor(1 / 1.3, W / 2, H / 2); return; }
      if (!/^Arrow(Right|Left|Up|Down)$/.test(t) || !ordenTeclado.length) return;
      ev.preventDefault();
      const orden = ordenTeclado.filter((n) => n.visA > 0.5 || n === st.sel);      // solo lo que se está dibujando
      if (!orden.length) return;
      const i = st.sel ? orden.indexOf(st.sel) : -1, sig = orden[(i + (t === "ArrowRight" || t === "ArrowDown" ? 1 : orden.length - 1)) % orden.length];
      seleccionar(sig);
    });

    // ---------- bucle
    function resize() {
      const w = cont.clientWidth, hh = cont.clientHeight; if (!w || !hh) return;
      const W0 = W, H0 = H;
      DPR = Math.min(2, window.devicePixelRatio || 1); W = w; H = hh; cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
      fondo = ctx.createRadialGradient(W * 0.5, H * 0.45, 0, W * 0.5, H * 0.45, Math.max(W, H) * 0.75); fondo.addColorStop(0, TEMA.degradado[0]); fondo.addColorStop(1, TEMA.degradado[1]);
      if (!ajustado) { ajustado = true; if (!restaurarCamara()) ajustar(0); }
      else if (W0 && (Math.abs(W - W0) > 0.08 * W0 || Math.abs(H - H0) > 0.08 * H0)) {
        // la ventana cambió de tamaño: sin cámara movida se reencuadra; si ya la movieron, se conserva el punto central
        if (!camTocada) ajustar(0); else { cam.x += (W - W0) / 2; cam.y += (H - H0) / 2; }
      }
      sucio = true;
    }
    const ro = window.ResizeObserver ? new ResizeObserver(resize) : null; if (ro) ro.observe(cont); else window.addEventListener("resize", resize);
    const t0 = performance.now(); let entrada = rest ? 1 : 0; cv.style.opacity = rest ? "1" : "0";      // al reconstruirla con la vista anterior no hay fundido: el cambio no parpadea
    actualizar(0); resize(); pintarLeyenda();

    function cuadro(ahora) {
      if (muerto) return;
      raf = requestAnimationFrame(cuadro);
      if (!cv.isConnected) { destruir(); return; }
      const dt = Math.min(0.05, (ahora - ultimo) / 1000); ultimo = ahora;
      if (document.hidden || !cont.clientWidth || !cont.clientHeight) return;       // vista oculta: no se gasta CPU
      clock += dt;
      if (animCam) {
        const u = clamp((performance.now() - animCam.t0) / animCam.dur, 0, 1), e = suave(u);
        cam.k = animCam.de.k + (animCam.a.k - animCam.de.k) * e; cam.x = animCam.de.x + (animCam.a.x - animCam.de.x) * e; cam.y = animCam.de.y + (animCam.a.y - animCam.de.y) * e;
        if (u >= 1) animCam = null; sucio = true;
      }
      const mov = actualizar(dt);
      if (entrada < 1) { entrada = RM ? 1 : Math.min(1, (performance.now() - t0) / 900); cv.style.opacity = String(entrada); sucio = true; }
      // con "reducir movimiento" solo se vuelve a dibujar cuando algo cambia; con miles de nodos, la animación de fondo (órbitas y cometas)
      // se repinta a ~30 cuadros por segundo (el movimiento sigue a la misma velocidad) y lo que pide el usuario, a todos
      const urgente = sucio || mov || drag || animVis, pasivo = !RM && (st.speed > 0 || comets.length);      // animVis: algún nodo aparece o desaparece
      if (urgente || (pasivo && !(nodos.length > 800 && ahora - ultDibujo < 30))) { dibujar(); sucio = false; ultDibujo = ahora; }
    }
    let ultDibujo = 0;
    raf = requestAnimationFrame(cuadro);

    function destruir() { muerto = true; cancelAnimationFrame(raf); if (ro) ro.disconnect(); else window.removeEventListener("resize", resize); if (api.actual === ctl) api.actual = null; }

    const ctl = {
      /** Los filtros se leen en vivo; esto solo pide repintar y reconstruye la leyenda (colores, partidos, tipos visibles). */
      refrescar() { nodos.forEach((n) => { n._fs = null; }); if (st.selE) st.grupoE = grupoDeArista(st.selE); pintarLeyenda(); sucio = true; },
      /** Destello temporal: ilumina extra las conexiones de ese tipo durante `ms` milisegundos (no hace nada con "reducir movimiento"). */
      destacar(tipo, ms = 3500) { if (RM) return; forzado = { tipo, hasta: clock + ms / 1000 }; sucio = true; },
      ajustar, destruir,
      limpiarSeleccion() { seleccionar(null); },
      seleccionarId(id) { const n = porId.get(id); if (n) seleccionar(n); return !!n; },      // elegir una entidad desde fuera
      reiniciarLineas() { st.selT = clock; sucio = true; },
      /** Vuelve a centrar lo seleccionado en la parte libre (la app lo pide al cambiar el tamaño del panel o la orientación de la pantalla). Sin zoom nuevo. */
      centrarSeleccion() {
        if (st.sel) centrarEnLibre(st.sel.wx, st.sel.wy, cam.k, 450);
        else if (st.selE) encuadrarNodos(st.grupoE ? st.grupoE.nodos : [st.selE.a, st.selE.b], false, 450);
      },
      reorganizar() { raices.forEach((r) => { r.tgt = [r.bx0, r.by0]; }); nodos.forEach((n) => { n.ox = n.oy = n.vx = n.vy = 0; }); ajustar(); },
      velocidad(v) { st.speed = RM ? 0 : clamp(Number(v) || 0, 0, 4); sucio = true; },
      /**
       * La vista actual (cámara y selección) para pasarla como `opciones.restaurar` al volver a montar esta misma red: { k, cx, cy, tocada, mapa, sel, selE }.
       * Es null si la red nunca llegó a tener tamaño (vista oculta desde el principio): no hay nada que conservar.
       */
      estado() {
        if (!W || !H) return null;
        const c = animCam ? { k: animCam.a.k, x: animCam.a.x, y: animCam.a.y } : cam;      // con un viaje de cámara en curso, el destino
        return { k: c.k, cx: (W / 2 - c.x) / c.k, cy: (H / 2 - c.y) / c.k, tocada: camTocada, mapa: mapaOn,
          sel: st.sel ? st.sel.id : null, selE: st.selE ? { tipo: st.selE.tipo, a: st.selE.a.id, b: st.selE.b.id } : null };
      },
      /** Soles sobre el mapa (true) o disposición compacta (false). Sin ubicaciones de provincias no hace nada. */
      disposicion(mapa) { aplicarDisposicion(!!mapa, true); },
      get hayMapa() { return hayMapa; },
      get esMapa() { return mapaOn; },
      png() {
        return new Promise((res) => {
          dibujar();
          if (mapaOn && plantillaTeselas) {       // la imagen exportada lleva la atribución del mapa
            ctx.setTransform(DPR, 0, 0, DPR, 0, 0); ctx.font = "10px " + FUENTE; ctx.textAlign = "right"; ctx.textBaseline = "alphabetic";
            ctx.fillStyle = TEMA.atrib; ctx.fillText("© OpenStreetMap contributors", W - 8, H - 8); ctx.textAlign = "left";
          }
          try { cv.toBlob((b) => res(b), "image/png"); } catch (e) { res(null); }      // un lienzo contaminado (mapa sin CORS) no se puede exportar
          sucio = true;                                                              // la atribución se dibujó encima: que el siguiente cuadro repinte la escena limpia
        });
      },
      irA(id) { const n = porId.get(id); if (n) { seleccionar(n); irA(n); } },
      /** Solo para pruebas y depuración. */
      _: { nodos, aristas, raices, grupos, cam, st, dibujar, actualizarVisibilidad }
    };
    api.actual = ctl;
    if (rest && (rest.sel || rest.selE)) {          // lo que estaba seleccionado vuelve a estarlo (si sigue en la red)
      const n = rest.sel ? porId.get(rest.sel) : null;
      const E = !n && rest.selE ? aristas.find((x) => x.tipo === rest.selE.tipo && ((x.a.id === rest.selE.a && x.b.id === rest.selE.b) || (x.a.id === rest.selE.b && x.b.id === rest.selE.a))) : null;
      if (n) seleccionar(n, true);
      else if (E) elegirArista(E, true);
      else if (op.alSeleccionar) op.alSeleccionar(null, [], true);      // ya no está en la red: la app cierra su detalle
    }
    return ctl;
  }

  // `_filtro`: solo para pruebas (comparar el filtro manual con el nativo)
  const api = { montar, colorArista, COLORES: PAL, actual: null, _filtro: { soportaFiltro: SOPORTA_FILTRO, pasosDeFiltro, aplicarFiltroManual } };
  window.RedOrbital = api;
})();
