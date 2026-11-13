/**
 * Configuración de la aplicación (se carga justo después del modal de acceso y antes de Firebase).
 *
 * requireLogin: true  -> la app exige crear cuenta o iniciar sesión (Firebase) antes de usarse (diseño original del equipo).
 *               false -> el acceso es opcional: la app funciona sin cuenta y el botón "Iniciar sesión" abre el formulario.
 * Nota: es un control de interfaz, no de seguridad. Los datos del colector en Firebase sí están protegidos por sus reglas
 * (database.rules.json). Los endpoints del backend local no piden sesión.
 */
window.NOAI_CONFIG = Object.assign({ requireLogin: true }, window.NOAI_CONFIG || {});

// Modo debug: omite el acceso obligatorio sin crear cuenta.
//  · En localhost solo con ?debug=1 en la dirección (queda activo en esa pestaña; ?debug=0 lo desactiva).
//  · En la red local no hace falta el parámetro: una página servida por «INICIAR NoAIVerdad (red local).bat» (puerto 3000) y abierta por la dirección
//    privada del equipo (192.168.x.x, 10.x.x.x, 172.16–31.x.x, 100.64–127.x.x de Tailscale o 169.254.x.x) o por su nombre («mi-pc», «mi-pc.local»,
//    «mi-pc.lan») entra sin cuenta. Quien abre ese archivo ya decidió compartir la app en su red; con ?debug=0 se vuelve a pedir la cuenta.
//  · Un dominio publicado (puerto 80 o 443, o cualquier dirección de Internet) nunca entra aquí.
// No depende del almacenamiento del navegador: si no se puede escribir (modo privado de algunos móviles), vale lo que diga la dirección.
function esHostDeRedLocal(host) {
  if (location.port !== "3000") return false;
  var m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (m) {
    var a = +m[1], b = +m[2];
    return a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31) || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254);
  }
  return /\.(local|lan|home|internal|localdomain|home\.arpa|fritz\.box)$/i.test(host) || host.indexOf(".") === -1;
}

(function () {
  var enRedLocal = esHostDeRedLocal(location.hostname);
  var local = ["localhost", "127.0.0.1", "[::1]"].indexOf(location.hostname) !== -1 || enRedLocal;
  if (!local) return;
  var p = null, guardado = null;
  try { p = new URLSearchParams(location.search).get("debug"); }
  catch (e) { var m = /[?&]debug=([01])(?:&|$)/.exec(location.search); p = m ? m[1] : null; }      // navegadores sin URLSearchParams
  try {
    if (p === "1" || p === "0") sessionStorage.setItem("noai_debug", p);
    guardado = sessionStorage.getItem("noai_debug");
  } catch (e) { /* sin almacenamiento */ }
  var debug = p === "1" || (p !== "0" && guardado !== "0" && (guardado === "1" || enRedLocal));
  if (debug) window.NOAI_CONFIG.requireLogin = false;
})();

if (window.NOAI_CONFIG.requireLogin === false) {
  var overlay = document.getElementById("modal-auth-overlay");
  if (overlay) overlay.classList.remove("active");
}
