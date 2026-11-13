/* Aplica el tema guardado (o el del sistema) antes de pintar, para evitar parpadeos. Archivo externo por el CSP. */
(function () {
  try {
    var t = localStorage.getItem("noai_theme");
    if (!t) t = (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
  } catch (e) { document.documentElement.setAttribute("data-theme", "dark"); }
})();
