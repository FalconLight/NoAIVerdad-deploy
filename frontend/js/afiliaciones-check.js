/* Página temporal para revisar backend/afiliaciones.json. Solo lectura: no escribe nada. */
(function () {
  "use strict";

  var host = location.hostname;
  var API = (host === "localhost" || host === "127.0.0.1" || host === "") ? "http://localhost:" + (location.port === "3600" ? 8600 : 8000)
    : (location.port === "3000" ? location.protocol + "//" + host + ":8000" : location.origin);      // puerto 3000: red local, los datos están en el puerto 8000 de ese equipo
  var $ = function (id) { return document.getElementById(id); };
  var datos = null;
  var filtro = "todas";
  var etiquetas = { verificada: "Verificada", pendiente: "Sin verificar", vacia: "Por completar" };

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k === "class") n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }

  function norm(s) {
    return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function urlSegura(u) { return /^https?:\/\/\S+$/.test(u || "") ? u : ""; }

  function copiar(texto, boton) {
    var anterior = boton.textContent;
    var listo = function () { boton.textContent = "Copiado"; setTimeout(function () { boton.textContent = anterior; }, 1200); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(texto).then(listo, function () { boton.textContent = "No se pudo copiar"; });
    else boton.textContent = "No se pudo copiar";
  }

  function limpia(e) {
    var o = {};
    ["nombre", "page_id", "page_ids", "otros_nombres", "tipo", "afiliacion", "partido", "fuente", "verificado", "actualizado"].forEach(function (k) {
      if ((k === "page_ids" || k === "otros_nombres") && !Array.isArray(e[k])) return;      // solo si la entidad tiene varias páginas u otros nombres
      o[k] = e[k] === undefined ? null : e[k];
    });
    return o;
  }

  /* Todos los ID de página de una entrada: el principal y los de page_ids. */
  function idsDe(e) {
    var ids = [e.page_id].concat(Array.isArray(e.page_ids) ? e.page_ids : []).filter(Boolean).map(String);
    return ids.filter(function (v, i) { return ids.indexOf(v) === i; });
  }

  function tarjetas() {
    var r = datos.resumen || {};
    var defs = [
      ["todas", "Entradas", r.total, ""], ["verificada", "Verificadas", r.verificadas, "ok"], ["pendiente", "Sin verificar", r.pendientes, "warn"],
      ["vacia", "Por completar", r.vacias, ""], ["problemas", "Con problemas", r.con_problemas, "bad"]
    ];
    var cont = $("resumen");
    cont.textContent = "";
    defs.forEach(function (d) {
      var b = el("button", { type: "button", class: "card " + d[3], "aria-pressed": String(filtro === d[0]) }, [el("strong", { text: String(d[2] || 0) }), el("span", { text: d[1] })]);
      b.addEventListener("click", function () { filtro = d[0]; tarjetas(); pintar(); });
      cont.appendChild(b);
    });
    cont.hidden = false;
  }

  function filtradas() {
    var q = norm($("buscar").value);
    return datos.entidades.filter(function (e) {
      if (filtro === "problemas" ? !e.problemas.length : (filtro !== "todas" && e.estado !== filtro)) return false;
      return !q || norm([e.nombre, e.afiliacion, e.fuente, e.tipo].concat(idsDe(e)).join(" ")).indexOf(q) !== -1;
    });
  }

  function pintar() {
    var lista = filtradas();
    var tb = $("filas");
    tb.textContent = "";
    lista.forEach(function (e) {
      var fuente = urlSegura(e.fuente);
      var tr = el("tr", {}, [
        el("td", {}, [el("span", { class: "tag " + e.estado, text: etiquetas[e.estado] })]),
        el("td", {}, [el("strong", { text: e.nombre || "(sin nombre)" }), el("div", { class: "muted mono", text: idsDe(e).length ? (idsDe(e).length > 1 ? "ids " : "id ") + idsDe(e).join(" · ") : "sin page_id" })]
          .concat(Array.isArray(e.otros_nombres) && e.otros_nombres.length ? [el("div", { class: "muted", text: "También como: " + e.otros_nombres.join(" · ") })] : [])),
        el("td", { text: e.tipo || "—" }),
        el("td", { text: e.afiliacion || "—" }),
        el("td", { class: "mono", text: e.partido || "—" }),
        el("td", {}, [fuente ? el("a", { href: fuente, target: "_blank", rel: "noopener noreferrer", text: fuente.replace(/^https?:\/\//, "").slice(0, 40) }) : el("span", { class: "muted", text: e.fuente ? e.fuente : "—" })]),
        el("td", { class: "mono", text: e.actualizado || "—" }),
        el("td", {}, e.problemas.length ? [el("ul", { class: "prob" }, e.problemas.map(function (p) { return el("li", { text: p }); }))] : [el("span", { class: "muted", text: "—" })])
      ]);
      tb.appendChild(tr);
    });
    if (!lista.length) tb.appendChild(el("tr", {}, [el("td", { colspan: "8", class: "muted", text: "Ninguna entrada coincide." })]));
    $("conteo").textContent = lista.length + " de " + datos.entidades.length + " entradas";
  }

  function faltantes() {
    var tb = $("faltantes");
    tb.textContent = "";
    (datos.faltantes || []).forEach(function (f) {
      var b = el("button", { type: "button", class: "btn", text: "Copiar entrada" });
      b.addEventListener("click", function () {
        copiar(JSON.stringify({ nombre: f.nombre, page_id: f.page_id, tipo: null, afiliacion: null, fuente: null, verificado: false, actualizado: null }, null, 2), b);
      });
      tb.appendChild(el("tr", {}, [
        el("td", { text: f.nombre }), el("td", { class: "mono", text: String(f.page_id || "—") }), el("td", { text: String(f.anuncios) }),
        el("td", { class: "mono", text: "USD " + Number(f.gasto_medio).toLocaleString("es-EC") }), el("td", {}, [b])
      ]));
    });
    if (!(datos.faltantes || []).length) tb.appendChild(el("tr", {}, [el("td", { colspan: "5", class: "muted", text: "Todas las páginas con más inversión ya tienen una entrada." })]));
  }

  function campos() {
    var ul = $("campos");
    ul.textContent = "";
    var c = datos.campos || {};
    Object.keys(c).forEach(function (k) { ul.appendChild(el("li", {}, [el("code", { text: k }), " — " + c[k]])); });
    if (datos.leeme) ul.appendChild(el("li", { class: "muted", text: datos.leeme }));
  }

  function cargar() {
    $("estado").hidden = false;
    $("estado").textContent = "Cargando…";
    fetch(API + "/api/ads/afiliaciones?faltantes=25").then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (d) {
      if (d.error) throw new Error(d.error);
      datos = d;
      $("archivo").textContent = d.archivo;
      $("estado").hidden = true;
      $("contenido").hidden = false;
      tarjetas(); pintar(); faltantes(); campos();
    }).catch(function (e) {
      $("estado").textContent = "No se pudo cargar (" + e.message + "). ¿Está el backend en " + API + "?";
    });
  }

  $("buscar").addEventListener("input", pintar);
  $("recargar").addEventListener("click", cargar);
  $("copiar-json").addEventListener("click", function () { copiar(JSON.stringify(filtradas().map(limpia), null, 2), $("copiar-json")); });
  cargar();
})();
