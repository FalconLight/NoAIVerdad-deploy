/**
 * Despliegue público de showcase (Netlify). Solo actúa en un dominio publicado; en localhost, la red local o file:// no hace nada.
 *
 *  · Modo debug como base: nadie necesita cuenta para usar la app (el botón «Iniciar sesión» sigue siendo opcional).
 *  · Los datos se piden al propio dominio (/api/...). Netlify los reenvía al backend desde el servidor (netlify/edge-functions/api-proxy.js),
 *    así que el navegador nunca conoce la dirección del backend ni el código que lo protege.
 * Se carga antes de js/app-config.js, que respeta lo que se fije aquí.
 */
(function () {
  var h = location.hostname;
  var local = location.protocol === "file:" || h === "" || ["localhost", "127.0.0.1", "[::1]"].indexOf(h) !== -1 || location.port === "3000";
  if (local) return;
  window.NOAI_CONFIG = Object.assign({}, window.NOAI_CONFIG || {}, { requireLogin: false, showcase: true });
  window.API_URL = location.origin;
})();
