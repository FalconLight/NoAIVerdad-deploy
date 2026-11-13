/**
 * Modo demo para presentaciones en vivo: reproduce el guion del showcase (docs/guion-capturas-showcase.md, tomas C01 a C05)
 * sobre la app real, paso a paso, con un cursor visible y un rótulo por ejemplo.
 *
 * Se activa abriendo la web con ?demo=1 (o con Ctrl+Alt+D). Teclas, también las de un presentador inalámbrico:
 *   →, Espacio, AvPág, Intro   siguiente paso
 *   ←, RePág                   repetir el paso anterior
 *   1 a 5                      ir al inicio del ejemplo 1 a 5
 *   R                          volver al principio (deja la app limpia)
 *   H                          mostrar u ocultar el rótulo
 *   X                          salir del modo demo (la app queda como esté, para seguir a mano)
 *
 * No guarda nada: no edita entidades ni marca grupos como revisados. Solo pulsa botones y mueve la red como lo haría una persona.
 * Usa los mismos eventos que el ratón (pointer, click, input), así que todo lo que se ve lo pinta el código normal de la app.
 */
(() => {
  "use strict";
  const PROV_RED = "Pichincha";        // C01: provincia a la que se acerca la red
  const PROV_FILTRO = "Manabí";        // C04: provincia con prensa local (la de la diapositiva)

  const traza = [];       // lo último que hizo la demo (NoAIDemo.traza en la consola, por si algo se atasca)
  const marca = (m) => { traza.push(Math.round(performance.now()) + " " + m); if (traza.length > 60) traza.shift(); };
  const espera = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (id) => document.getElementById(id);
  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  /** Un cuadro de animación; si el navegador frena requestAnimationFrame (ventana tapada o en segundo plano), sigue con un temporizador. */
  const cuadro = (fn) => { let hecho = false; const ir = () => { if (hecho) return; hecho = true; fn(performance.now()); }; requestAnimationFrame(ir); setTimeout(ir, 40); };
  const suave = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  async function hasta(fn, ms = 8000) {           // espera a que algo exista (datos, panel, lista) sin colgarse si nunca llega
    const t0 = performance.now();
    for (;;) { let v = null; try { v = fn(); } catch (e) { v = null; } if (v) return v; if (performance.now() - t0 > ms) return null; await espera(80); }
  }

  // ---------- interfaz: cursor, rótulo y aviso
  const css = `
  html.demo-on, html.demo-on * { cursor: none !important; }
  #demo-cursor { position: fixed; left: 0; top: 0; z-index: 2147483646; pointer-events: none; width: 30px; height: 30px; transform: translate(-100px,-100px);
    filter: drop-shadow(0 2px 4px rgba(0,0,0,.55)); transition: opacity .25s; }
  #demo-cursor .anillo { position: absolute; left: -16px; top: -16px; width: 32px; height: 32px; border-radius: 50%; border: 3px solid #ffd23f; opacity: 0; }
  #demo-cursor.clic .anillo { animation: demo-onda .55s ease-out; }
  @keyframes demo-onda { from { transform: scale(.3); opacity: 1; } to { transform: scale(1.9); opacity: 0; } }
  #demo-rotulo { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); z-index: 2147483645; pointer-events: none;
    max-width: min(880px, calc(100vw - 32px)); padding: 12px 20px; border-radius: 14px; background: rgba(12,14,20,.86); color: #fff;
    font: 600 19px/1.35 system-ui, sans-serif; box-shadow: 0 8px 28px rgba(0,0,0,.35); text-align: center; transition: opacity .3s; backdrop-filter: blur(6px); }
  #demo-rotulo small { display: block; font-weight: 500; font-size: 14px; opacity: .78; margin-top: 3px; }
  #demo-rotulo .paso { position: absolute; right: 12px; top: 6px; font: 600 11px system-ui, sans-serif; opacity: .5; }
  #demo-rotulo.oculto { opacity: 0; }
  #demo-rotulo.apartado { opacity: .12; }
  #demo-rotulo.ocupado::after { content: ""; position: absolute; left: 20px; right: 20px; bottom: 5px; height: 2px; border-radius: 2px;
    background: linear-gradient(90deg, transparent, #ffd23f, transparent); background-size: 200% 100%; animation: demo-barra 1.1s linear infinite; }
  @keyframes demo-barra { from { background-position: 100% 0; } to { background-position: -100% 0; } }
  .demo-foco { outline: 3px solid #ffd23f !important; outline-offset: 2px; border-radius: 6px; transition: outline-color .3s; }`;

  let raiz = null, cursor = null, rotulo = null, activo = false, ocupado = false, indice = 0, rotuloVisible = true;
  const pos = { x: -100, y: -100 };

  function montarUI() {
    if (raiz) return;
    const st = document.createElement("style"); st.id = "demo-estilos"; st.textContent = css; document.head.appendChild(st);
    cursor = document.createElement("div"); cursor.id = "demo-cursor";
    cursor.innerHTML = `<span class="anillo"></span><svg width="30" height="30" viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.6-7.9L21 10.6z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    rotulo = document.createElement("div"); rotulo.id = "demo-rotulo"; rotulo.setAttribute("aria-live", "polite");
    document.body.append(cursor, rotulo);
    raiz = st;
    pos.x = window.innerWidth / 2; pos.y = window.innerHeight * 0.6; pintarCursor();
  }
  function desmontarUI() {
    [raiz, cursor, rotulo].forEach((e) => e && e.remove()); raiz = cursor = rotulo = null;
    document.documentElement.classList.remove("demo-on");
    document.querySelectorAll(".demo-foco").forEach((e) => e.classList.remove("demo-foco"));
  }
  /** El rótulo se aparta (casi transparente) cuando el cursor pasa por debajo: no tapa el botón que se va a pulsar. */
  const pintarCursor = () => {
    if (!cursor) return;
    cursor.style.transform = `translate(${pos.x - 3}px,${pos.y - 2}px)`;
    if (rotulo) { const r = rotulo.getBoundingClientRect(); rotulo.classList.toggle("apartado", pos.x > r.left - 50 && pos.x < r.right + 50 && pos.y > r.top - 60 && pos.y < r.bottom + 30); }
  };
  function decir(titulo, sub, numero = true) {
    if (!rotulo) return;
    rotulo.innerHTML = `${numero ? `<span class="paso">${indice + 1}/${PASOS.length}</span>` : ""}${titulo}${sub ? `<small>${sub}</small>` : ""}`;
    rotulo.classList.toggle("oculto", !rotuloVisible);
  }

  // ---------- movimiento y clics
  /** Lleva el cursor a (x, y) con una curva suave; `alPasar(x, y)` se llama en cada cuadro (para el hover de la red). */
  function mover(x, y, dur, alPasar) {
    const x0 = pos.x, y0 = pos.y, d = Math.hypot(x - x0, y - y0);
    dur = dur || Math.min(1100, 380 + d * 0.9);
    return new Promise((res) => {
      const t0 = performance.now();
      const paso = (t) => {
        const u = Math.min(1, (t - t0) / dur), e = suave(u);
        pos.x = x0 + (x - x0) * e; pos.y = y0 + (y - y0) * e; pintarCursor();
        if (alPasar) alPasar(pos.x, pos.y);
        if (u < 1) cuadro(paso); else res();
      };
      cuadro(paso);
    });
  }
  function onda() { if (!cursor) return; cursor.classList.remove("clic"); void cursor.offsetWidth; cursor.classList.add("clic"); }
  const centro = (el) => { const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
  /** Mueve el cursor a un elemento, se detiene un momento (el público ve dónde) y lo pulsa con un clic normal. */
  async function pulsar(el, { pausa = 650, hacer } = {}) {
    marca("pulsar " + (el ? el.id || el.className || el.tagName : "(nada)"));
    if (!el) return false;
    el.scrollIntoView({ block: "nearest", inline: "nearest" });
    await espera(60);
    const [x, y] = centro(el);
    await mover(x, y);
    el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true, clientX: x, clientY: y }));
    await espera(pausa);
    onda();
    if (hacer) hacer(); else el.click();
    await espera(250);
    return true;
  }
  async function escribir(input, texto, ms = 110) {
    if (!input) return;
    await pulsar(input, { pausa: 350, hacer: () => input.focus() });
    input.value = "";
    for (const ch of texto) { input.value += ch; input.dispatchEvent(new Event("input", { bubbles: true })); await espera(ms); }
  }
  async function desplazar(el, dy, dur = 1400) {
    if (!el) return;
    const y0 = el.scrollTop, t0 = performance.now();
    await new Promise((res) => {
      const paso = (t) => { const u = Math.min(1, (t - t0) / dur); el.scrollTop = y0 + dy * suave(u); if (u < 1) cuadro(paso); else res(); };
      cuadro(paso);
    });
  }
  /** El primer ancestro que de verdad tiene barra de desplazamiento. */
  function contenedorScroll(el) {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (/(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 10) return e;
    }
    return null;
  }

  // ---------- la red (lienzo): mismos eventos de puntero que el ratón
  const red = () => window.RedOrbital && window.RedOrbital.actual;
  const lienzo = () => $("rg-canvas");
  function aPantalla(sx, sy) {
    const cv = lienzo(), r = cv.getBoundingClientRect(), W = cv.clientWidth || r.width;
    const f = r.width / (W || 1);
    return [r.left + sx * f, r.top + sy * f];
  }
  function puntero(tipo, x, y) {
    const cv = lienzo(); if (!cv) return;
    cv.dispatchEvent(new PointerEvent(tipo, { bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 77, pointerType: "mouse", isPrimary: true, button: 0, buttons: tipo === "pointerdown" ? 1 : 0 }));
  }
  const sobreLienzo = (x, y) => document.elementFromPoint(x, y) === lienzo();
  /** Parte del lienzo que no tapan los paneles abiertos: ahí se centra lo que se quiere mostrar. */
  function zonaLibre() {
    const r = lienzo().getBoundingClientRect();
    let izq = r.left, der = r.right, arr = r.top + 70, aba = r.bottom - 60;
    for (const id of ["rs-izq", "rs-der", "rs-flot"]) {
      const p = $(id); if (!p || p.hidden || !p.offsetParent) continue;
      const q = p.getBoundingClientRect(); if (q.width < 30 || q.height < 30 || getComputedStyle(p).visibility === "hidden") continue;
      if (q.left > r.left + r.width / 2) der = Math.min(der, q.left); else if (q.right < r.left + r.width / 2) izq = Math.max(izq, q.right);
    }
    return { izq, der, arr, aba, cx: (izq + der) / 2, cy: (arr + aba) / 2, w: der - izq, h: aba - arr, r };
  }
  /** Viaje de cámara suave: deja el punto del mundo (wx, wy) en el centro de la zona libre con zoom k. */
  function camara(wx, wy, k, dur = 1800) {
    const c = red(); if (!c) return Promise.resolve();
    const cam = c._.cam, z = zonaLibre(), f = z.r.width / (lienzo().clientWidth || z.r.width);
    const cx = (z.cx - z.r.left) / f, cy = (z.cy - z.r.top) / f;
    const de = { k: cam.k, x: cam.x, y: cam.y }, a = { k, x: cx - k * wx, y: cy - k * wy };
    return new Promise((res) => {
      const t0 = performance.now();
      const paso = (t) => {
        const u = Math.min(1, (t - t0) / dur), e = suave(u);
        cam.k = de.k + (a.k - de.k) * e; cam.x = de.x + (a.x - de.x) * e; cam.y = de.y + (a.y - de.y) * e;
        try { c._.dibujar(); } catch (err) { /* el siguiente cuadro de la red lo pinta */ }
        if (u < 1) cuadro(paso); else res();
      };
      cuadro(paso);
    });
  }
  /** Encuadra un conjunto de nodos de la red en la zona libre. */
  function encuadrar(ns, margen = 1.5, dur) {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    ns.forEach((n) => { const e = n.ext || 30; x0 = Math.min(x0, n.wx - e); x1 = Math.max(x1, n.wx + e); y0 = Math.min(y0, n.wy - e); y1 = Math.max(y1, n.wy + e); });
    const z = zonaLibre(), f = z.r.width / (lienzo().clientWidth || z.r.width);
    const k = Math.max(0.2, Math.min(7, Math.min(z.w / f / ((x1 - x0) * margen), z.h / f / ((y1 - y0) * margen))));
    return camara((x0 + x1) / 2, (y0 + y1) / 2, k, dur);
  }
  /** Pasa el cursor por un nodo (se ve su nombre en la etiqueta flotante de la red). */
  async function pasarPorNodo(n, quieto = 1100) {
    let [x, y] = aPantalla(n.sx, n.sy);
    await mover(x, y, null, (px, py) => puntero("pointermove", px, py));
    [x, y] = aPantalla(n.sx, n.sy); pos.x = x; pos.y = y; pintarCursor(); puntero("pointermove", x, y);      // la órbita se frena bajo el puntero: un ajuste final
    await espera(quieto);
  }
  async function pulsarNodo(n) {
    await pasarPorNodo(n, 600);
    const [x, y] = aPantalla(n.sx, n.sy); pos.x = x; pos.y = y; pintarCursor();
    onda(); puntero("pointerdown", x, y); await espera(70); puntero("pointerup", x, y);
    await espera(300);
    if (red() && red()._.st.sel !== n) red().irA(n.id);      // si la órbita lo movió justo en el clic, se selecciona igual
  }
  const medio = (E) => [0.25 * E.a.sx + 0.5 * E.cx + 0.25 * E.b.sx, 0.25 * E.a.sy + 0.5 * E.cy + 0.25 * E.b.sy];
  async function pulsarArista(E) {
    for (let intento = 0; intento < 4; intento++) {
      let [x, y] = aPantalla(...medio(E));
      await mover(x, y, intento ? 350 : null, (px, py) => puntero("pointermove", px, py));
      await espera(450);
      [x, y] = aPantalla(...medio(E)); pos.x = x; pos.y = y; pintarCursor(); puntero("pointermove", x, y);
      await espera(500);
      [x, y] = aPantalla(...medio(E));
      onda(); puntero("pointerdown", x, y); await espera(70); puntero("pointerup", x, y);
      await espera(350);
      if (red() && red()._.st.selE) return true;
    }
    return false;
  }
  function soltarPuntero() { const cv = lienzo(); if (cv) cv.dispatchEvent(new PointerEvent("pointerleave", { bubbles: false, pointerId: 77 })); }

  // ---------- estado de la app
  async function irAConexiones() {
    if (!$("view-resumen") || !$("view-resumen").classList.contains("active")) { await pulsar($("nav-resumen")); }
    await hasta(() => red() && red()._.nodos.length && lienzo() && lienzo().clientWidth);
  }
  const pulsado = (b) => b && (b.getAttribute("aria-checked") === "true" || b.getAttribute("aria-pressed") === "true");
  async function cerrarPaneles() {
    document.querySelectorAll(".demo-foco").forEach((e) => e.classList.remove("demo-foco"));
    if ($("ficha") && !$("ficha").hidden) $("ficha-cerrar").click();
    if ($("fechas-panel") && !$("fechas-panel").hidden) $("btn-fechas").click();
    const abierta = document.querySelector("#resumen-tabs .rs-btn[aria-pressed='true']"); if (abierta) abierta.click();
    if ($("rs-izq") && $("rs-izq").classList.contains("abierto")) $("rs-btn-filtros").click();
    if (red()) red().limpiarSeleccion();
    soltarPuntero();
  }
  /** Deja la app como pide el guion: Conexiones, todo el país, sin filtros, CNE oculto, sin tutorial. Sin animaciones. */
  async function limpiar() {
    if ($("tutorial-overlay") && !$("tutorial-overlay").hidden) $("tuto-cerrar").click();
    if (location.hash.indexOf("#/resumen/todas") !== 0) { location.hash = "#/resumen/todas/red"; }
    marca("limpiar"); await irAConexiones(); marca("conexiones");
    await cerrarPaneles(); marca("paneles");
    if (pulsado($("btn-solo-activos"))) $("btn-solo-activos").click();
    if (!pulsado($("btn-sin-cne"))) $("btn-sin-cne").click();
    if (typeof state !== "undefined" && state.fechas && state.fechas.desde) {        // fechas: «Todo el período»
      $("btn-fechas").click();
      const todo = await hasta(() => document.querySelector("#fechas-panel [data-fp='todo']:not([disabled])"), 1500);
      if (todo) todo.click(); else $("btn-fechas").click();
    }
    marca("fechas ok"); $("rs-btn-filtros").click();                                       // segmentadores: «Quitar filtros» si hay alguno
    const reiniciar = await hasta(() => $("seg-reiniciar"), 800);
    if (reiniciar) reiniciar.click();
    await espera(150);
    if ($("rs-izq").classList.contains("abierto")) $("rs-btn-filtros").click();
    marca("segmentadores ok"); await hasta(() => red() && red()._.nodos.length, 15000);
    await espera(400);
    if (red()) red().ajustar(0); marca("limpio");
  }

  // ---------- búsquedas en los datos de la red
  const nodosDe = (tipo) => (red() ? red()._.nodos.filter((n) => n.tipo === tipo) : []);
  const provincia = (nombre) => nodosDe("provincia").find((n) => norm(n.nombre) === norm(nombre));
  /** Páginas que cuelgan de una provincia (sus esferas) en la red. */
  const paginasDe = (p) => red()._.nodos.filter((n) => n.tipo === "pagina" && (n.parent === p || (n.parent && n.parent.parent === p)));
  /**
   * La línea de texto repetido que se muestra en los ejemplos 2 y 3. El guion pide no elegir un grupo que se lea como acusación:
   * primero una línea entre dos páginas de la red de cinco páginas que cita la diapositiva (repiten mensajes de entidades públicas);
   * si no está en la red, la línea entre las páginas con más texto repetido.
   */
  const RED_CINCO = ["pulsodigital", "dpolitik", "datanews", "el emprendedor", "agencia de publicidad y marketing en quito"];
  const deLaRed = (n) => RED_CINCO.some((x) => norm(n.nombre).includes(x));
  function aristaTexto() {
    const A = red() ? red()._.aristas.filter((E) => E.tipo === "texto") : [];
    const grado = new Map(); A.forEach((E) => { grado.set(E.a, (grado.get(E.a) || 0) + 1); grado.set(E.b, (grado.get(E.b) || 0) + 1); });
    const orden = (lista) => lista.sort((x, y) => (grado.get(y.a) + grado.get(y.b)) - (grado.get(x.a) + grado.get(x.b)))[0] || null;
    return orden(A.filter((E) => deLaRed(E.a) && deLaRed(E.b))) || orden(A);
  }

  // ---------- el guion
  const PASOS = [
    { t: "NoAIVerdad", s: "Anuncios políticos en Meta, de todo Ecuador, en una sola red", async run() {
      await limpiar();
      const fit = document.querySelector(".rg-z[data-z='reset']");
      if (fit) await pulsar(fit, { pausa: 500 });
    } },
    // C01 · La red de pagadores
    { t: "Ejemplo 1 · La red de pagadores", s: `Acercamos a ${PROV_RED}: soles = provincias, esferas = páginas, rombos = pagadores`, async run() {
      await irAConexiones(); await cerrarPaneles();
      const p = provincia(PROV_RED); if (!p) return;
      await pasarPorNodo(p, 500);
      soltarPuntero();
      await encuadrar([p], 1.25, 2400);
    } },
    { t: "Ejemplo 1 · La red de pagadores", s: "Cada esfera es una página que pagó anuncios políticos", async run() {
      const p = provincia(PROV_RED); if (!p) return;
      const z = zonaLibre();
      const vis = paginasDe(p).filter((n) => { const [x, y] = aPantalla(n.sx, n.sy); return x > z.izq + 40 && x < z.der - 40 && y > z.arr + 20 && y < z.aba - 20 && sobreLienzo(x, y); })
        .sort((a, b) => b.gm - a.gm).slice(0, 3);
      for (const n of vis) await pasarPorNodo(n, 1300);
    } },
    { t: "Ejemplo 1 · La red de pagadores", s: "Una página y quien paga sus anuncios: se resaltan sus conexiones y se abre su detalle", async run() {
      const p = provincia(PROV_RED); if (!p) return;
      const conPagador = paginasDe(p).filter((n) => n.aristas.some((E) => E.tipo === "pagador")).sort((a, b) => b.gm - a.gm);
      const n = conPagador[0] || paginasDe(p).sort((a, b) => b.gm - a.gm)[0]; if (!n) return;
      await pulsarNodo(n);
      soltarPuntero();
    } },
    { t: "Ejemplo 1 · La red de pagadores", s: "Con la lista de todos sus anuncios", async run() {
      const det = await hasta(() => $("red-detalle") && $("red-detalle").textContent.trim().length > 20 && $("red-detalle"), 4000);
      const sc = det && contenedorScroll(det); if (!sc) return;
      const [x, y] = centro(sc); await mover(x, y);
      await desplazar(sc, Math.min(420, sc.scrollHeight - sc.clientHeight), 1800);
    } },
    // C02 · Mensajes repetidos
    { t: "Ejemplo 2 · El mismo texto, en páginas distintas", s: "Mensajes repetidos: las líneas grises unen páginas que publicaron el mismo texto", async run() {
      await cerrarPaneles();
      await pulsar($("tabbtn-mensajes"));
      await hasta(() => $("mensajes-lista") && $("mensajes-lista").querySelector("article.group"), 15000);
      if (red()) red().destacar("texto", 5000);
      const E = aristaTexto(); if (E) await encuadrar([E.a, E.b], 2.2, 2000);
    } },
    // C03 · Lado a lado
    { t: "Ejemplo 3 · Lado a lado, con la fuente a un clic", s: "Clic en una línea de texto repetido", async run() {
      if (!$("tabbtn-mensajes") || !pulsado($("tabbtn-mensajes"))) await pulsar($("tabbtn-mensajes"));
      const E = aristaTexto(); if (!E) return;
      await encuadrar([E.a, E.b], 2.2, 900);
      await pulsarArista(E);
      soltarPuntero();
    } },
    { t: "Ejemplo 3 · Lado a lado, con la fuente a un clic", s: "Los dos anuncios en columnas, con las palabras distintas marcadas, y el enlace al original en Meta", async run() {
      const det = await hasta(() => $("red-detalle") && $("red-detalle").querySelector("mark.dif, a[href*='facebook.com/ads/library']") && $("red-detalle"), 5000);
      if (!det) return;
      const mark = det.querySelector("mark.dif");
      if (mark) { mark.scrollIntoView({ block: "center", behavior: "smooth" }); await espera(500); const [x, y] = centro(mark); await mover(x, y); await espera(1600); }
      const link = det.querySelector("a[href*='facebook.com/ads/library']");
      if (link) {
        link.scrollIntoView({ block: "center", behavior: "smooth" }); await espera(500);
        const [x, y] = centro(link); await mover(x, y); link.classList.add("demo-foco");
      }
    } },
    // C04 · Filtros y Mapa
    { t: "Ejemplo 4 · Una provincia, unas fechas, lo activo", s: `Filtros → Provincia → solo ${PROV_FILTRO}`, async run() {
      await cerrarPaneles();
      if (red()) red().ajustar(700);
      await pulsar($("rs-btn-filtros"));
      const sec = await hasta(() => document.querySelector("#rs-izq [data-seg='provincia']"), 4000); if (!sec) return;
      const buscar = sec.querySelector(".seg-buscar");
      if (buscar) await escribir(buscar, PROV_FILTRO.slice(0, 4));
      const fila = [...sec.querySelectorAll(".seg-fila[data-i]")].find((f) => !f.hidden && f.dataset.q === norm(PROV_FILTRO));
      if (!fila) return;
      fila.scrollIntoView({ block: "nearest" });
      const [x, y] = centro(fila); await mover(x, y); fila.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); await espera(500);
      await pulsar(fila.querySelector("[data-seg-solo]"));
      if (buscar) { buscar.value = ""; buscar.dispatchEvent(new Event("input", { bubbles: true })); }
      await espera(400);
      await pulsar($("rs-btn-filtros"), { pausa: 300 });                 // cerrar el panel: se ve la red de esa provincia
      await espera(500); if (red()) red().ajustar(900);
    } },
    { t: "Ejemplo 4 · Una provincia, unas fechas, lo activo", s: "Fechas: últimos 7 días", async run() {
      await pulsar($("btn-fechas"));
      const atajo = await hasta(() => document.querySelector("#fechas-panel [data-atajo='6']"), 3000);
      await pulsar(atajo);
      await pulsar(await hasta(() => document.querySelector("#fechas-panel [data-fp='aplicar']:not([disabled])"), 2000));
      await hasta(() => red() && red()._.nodos.length, 15000); await espera(600);
    } },
    { t: "Ejemplo 4 · Una provincia, unas fechas, lo activo", s: "Solo activos: quien anuncia ahora mismo en esa provincia", async run() {
      if (!pulsado($("btn-solo-activos"))) await pulsar($("btn-solo-activos"));
      await espera(1500); await hasta(() => red() && red()._.nodos.length, 15000);
      if (red()) red().ajustar(900);
    } },
    { t: "Ejemplo 4 · Mapa", s: `${PROV_FILTRO}: su prensa, su prensa local y las verificaciones`, async run() {
      await pulsar($("nav-mapa"));
      const capa = await hasta(() => {
        if (typeof state === "undefined" || !state.map) return null;
        let c = null; state.map.eachLayer((l) => { const tt = l.getTooltip && l.getTooltip(); if (tt && norm(String(tt.getContent())).includes(norm(PROV_FILTRO)) && l.getElement && l.getElement()) c = l; });
        return c;
      }, 6000);
      if (!capa) return;
      state.map.invalidateSize();
      await espera(400);
      const el = capa.getElement(), [x, y] = centro(el);
      await mover(x, y); capa.openTooltip(); await espera(700);
      onda(); capa.fire("click"); await espera(300);
      const sc = await hasta(() => $("sidebar-content") && $("sidebar-content").textContent.trim().length > 40 && $("sidebar-content"), 8000);
      const caja = sc && (contenedorScroll(sc) || sc);
      if (caja) { await espera(800); const [cx, cy] = centro(caja); await mover(cx, cy); await desplazar(caja, Math.min(600, caja.scrollHeight - caja.clientHeight), 2600); }
    } },
    // C05 · Validar perfiles
    { t: "Ejemplo 5 · Afiliación política: solo con fuente", s: "Validar perfiles: tipo, partido, la fuente y si está verificada", async run() {
      await pulsar($("nav-resumen"));
      await hasta(() => red() && red()._.nodos.length && lienzo() && lienzo().clientWidth);
      await pulsar($("btn-ficha"));
      const filas = await hasta(() => typeof entidadesUI !== "undefined" && entidadesUI.filas.length && entidadesUI.filas, 10000);
      if (!filas) return;
      const f = filas.find((x) => x.verificado && x.partido && x.fuente && /candidat|partido|movimiento/i.test(`${x.tipo || ""}`))
        || filas.find((x) => x.verificado && x.partido && x.fuente) || filas.find((x) => x.verificado);
      if (!f) return;
      const palabras = String(f.nombre).split(/\s+/).filter((w) => w.length > 2);
      await escribir($("ficha-buscar"), palabras.slice(0, 2).join(" ") || f.nombre);
      await espera(500);
      const li = [...document.querySelectorAll("#ficha-resultados li[data-i]")].find((l) => entidadesUI.filas[Number(l.dataset.i)] === f)
        || document.querySelector("#ficha-resultados li[data-i]");
      if (li) await pulsar(li, { hacer: () => li.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })) });
      await espera(500);
      const marca = document.querySelector("#ficha-form input[type=checkbox]");
      if (marca) { const [x, y] = centro(marca); await mover(x, y); (marca.closest("label") || marca).classList.add("demo-foco"); }
    } },
    { t: "Gracias", s: "NoAIVerdad · datos de la Biblioteca de Anuncios de Meta", async run() {
      await cerrarPaneles();
      if (red()) red().ajustar(1200);
      await mover(window.innerWidth - 60, window.innerHeight - 140);
    } }
  ];

  // ---------- control
  async function ejecutar(i) {
    if (ocupado || !activo) return;
    indice = Math.max(0, Math.min(PASOS.length - 1, i));
    const p = PASOS[indice];
    ocupado = true; decir(p.t, p.s); rotulo && rotulo.classList.add("ocupado");
    marca("paso " + (indice + 1));
    try { await p.run(); } catch (e) { console.warn("[demo] paso", indice + 1, e); }
    ocupado = false; rotulo && rotulo.classList.remove("ocupado");
  }
  let siguiente = 0;       // el paso que toca con la próxima tecla
  async function avanzar() { if (ocupado) return; if (siguiente >= PASOS.length) return; const i = siguiente; siguiente++; await ejecutar(i); }
  async function repetir() { if (ocupado) return; const i = Math.max(0, siguiente - 1); siguiente = i + 1; await ejecutar(i); }
  /** Teclas 1 a 5: empieza de nuevo el ejemplo N (por si hay que repetirlo o saltarse uno). */
  async function saltar(n) {
    if (ocupado) return;
    const i = PASOS.findIndex((p) => p.t.indexOf(`Ejemplo ${n} `) === 0); if (i < 0) return;
    siguiente = i; await avanzar();
  }
  async function reiniciar() { if (ocupado) return; siguiente = 0; indice = 0; decir("Modo demo listo", "→ o Espacio para empezar · 1–5 salta a un ejemplo · R reinicia · H oculta el rótulo · X sale", false); await limpiar(); }

  function activar() {
    if (activo) return;
    activo = true; montarUI(); document.documentElement.classList.add("demo-on");
    reiniciar();
  }
  function salir() { activo = false; ocupado = false; soltarPuntero(); desmontarUI(); }

  window.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey && ev.altKey && (ev.key === "d" || ev.key === "D")) { ev.preventDefault(); activo ? salir() : activar(); return; }
    if (!activo || ev.ctrlKey || ev.altKey || ev.metaKey) return;
    const k = ev.key;
    const enCampo = ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName) && ev.isTrusted;
    if (enCampo && !/^Page/.test(k)) return;                // si la persona escribe a mano en un campo, la demo no le roba las teclas
    let hecho = true;
    if (k === "ArrowRight" || k === " " || k === "PageDown" || k === "Enter") avanzar();
    else if (k === "ArrowLeft" || k === "PageUp") repetir();
    else if (k === "r" || k === "R") reiniciar();
    else if (/^[1-5]$/.test(k)) saltar(Number(k));
    else if (k === "h" || k === "H") { rotuloVisible = !rotuloVisible; rotulo && rotulo.classList.toggle("oculto", !rotuloVisible); }
    else if (k === "x" || k === "X") salir();
    else hecho = false;
    if (hecho) { ev.preventDefault(); ev.stopPropagation(); }
  }, true);

  const pedido = /[?&]demo(=1|=true|&|$)/.test(location.search);
  if (pedido) {
    const empezar = () => hasta(() => window.RedOrbital && typeof state !== "undefined", 20000).then(activar);
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", empezar); else empezar();
  }
  window.NoAIDemo = { activar, salir, reiniciar, avanzar, repetir, PASOS, traza, saltar };
})();
