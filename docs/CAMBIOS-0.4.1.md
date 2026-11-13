# NoAIVerdad beta 0.4.0 — cambios de la sesión del 2026-11-05

Documento de traspaso: para retomar el trabajo en la sesión inicial y reportar los cambios con git.
La lista de archivos y las cifras salen de comparar, archivo por archivo, esta carpeta con el zip original
(`NoAIVerdad-Beta-v0.4.0.zip`); el detalle funcional, del código y de lo que se pidió en la sesión.

## Resumen para pegar en el reporte

- **Meta Ad Library carga.** Faltaba `app/backend/.env.local` (integración apagada por defecto y sin token). Ese archivo no se versiona.
- **«Validar perfiles»:** icono nuevo en la barra superior que abre una ficha flotante para editar la afiliación de una entidad desde cualquier pestaña.
- **Memoria de vista:** el Mapa y la red «Conexiones» conservan zoom y selección al recargar (p. ej. tras guardar un perfil).
- **Red más legible:** líneas de mensajes repetidos casi invisibles hasta seleccionarlas o activar su filtro; leyenda en columnas, colapsable y en mayúsculas; filtros unificados.
- **Todas las provincias en la vista nacional** (antes las pequeñas desaparecían) y **nivel de detalle por zoom** para que no se sature; dibujo mucho más rápido.
- **Anuncios retirados por Meta** (sin descargo de responsabilidad) fuera del mapa, la red, las listas y las cifras.
- **Modo red local:** `INICIAR NoAIVerdad (red local).bat` abre la app a otros dispositivos de la misma red, sin pedir cuenta.
- **iPhone/iPad (también Chrome en iOS):** el mapa base de «Conexiones» ya se ve (alternativa sin `ctx.filter`).
- **Panel lateral de «Conexiones» ajustable** (asa para arrastrar) y la selección se centra para no quedar tapada.
- **Datos:** 7 entradas nuevas en `afiliaciones.json`, añadidas desde la app durante las pruebas; sus fuentes ya las revisó el usuario (no son código).

## Cómo ver los cambios con git

El repositorio se creó al final de la sesión (la carpeta no era un repo). Los cambios están en el segundo commit; los posteriores solo ajustan este documento:

1. `e519286` — `Base: NoAIVerdad beta 0.4.0 (zip original, sin ads_snapshot.json)`: el estado del zip tal cual.
2. `fae3bf6` — `Cambios de la sesión del 2026-11-05`: todo lo descrito aquí, más este documento y el `.gitignore`.
3. Un commit posterior que solo corrige este documento: las fuentes de las 7 entradas nuevas ya las revisó el usuario, y las referencias de git pasan a usar los hashes de arriba.

```bash
git log --oneline
git show --stat fae3bf6
git diff e519286 fae3bf6 -- app/frontend/js/app.js
```

Los archivos del proyecto usan saltos de línea CRLF; git (con `core.autocrlf=true`, como en GitHub Desktop) los guarda como LF y
avisa «CRLF will be replaced by LF». Es normal y no cambia el contenido. Para llevar estos cambios a otro repositorio:
`git format-patch -1 fae3bf6` genera un parche del segundo commit (las rutas empiezan por `app/`).

## Archivos tocados (zip original → ahora)

| Archivo | Líneas + / − | Qué cambia |
|---|---|---|
| `app/frontend/js/app.js` | +454 / −51 | Ficha, memoria de mapa y red, filtros, leyendas, panel ajustable, centrado de la selección |
| `app/frontend/js/red-orbital.js` | +296 / −51 | Red orbital: líneas tenues, nivel de detalle, rendimiento, memoria de cámara, alternativa para iOS, centrado |
| `app/frontend/css/styles.css` | +81 / −6 | Estilos de ficha, leyenda en columnas, asa del panel, panel inferior en móvil |
| `app/frontend/index.html` | +33 / −2 | Botón y sección de la ficha, asa `#rs-der-asa`, textos de ayuda (ⓘ y Método), CSP |
| `app/frontend/js/app-config.js` | +26 / −6 | Entrada sin cuenta en localhost con `?debug=1` y automática en la red local |
| `app/frontend/js/afiliaciones-check.js` | +2 / −1 | Dirección de la API cuando la página se abre por la red local |
| `app/backend/ads_library.py` | +46 / −6 | Filtro de anuncios retirados por Meta; provincias garantizadas en la red nacional |
| `app/backend/main.py` | +1 / −1 | Tope de `max_paginas` en `/api/ads/red-pagadores`: 300 → 6000 |
| `app/launcher.py` | +67 / −4 | Modo red local (`0.0.0.0`), direcciones para otros dispositivos, aviso si el puerto ya lo usa NoAIVerdad |
| `INICIAR NoAIVerdad (red local).bat` | nuevo | Pone `NOAIVERDAD_RED=1` y llama al `.bat` de siempre (que no se modificó) |
| `app/backend/afiliaciones.json` | +70 / 0 | 7 entradas nuevas (datos) |
| `CAMBIOS.md`, `.gitignore` | nuevos | Este documento y las exclusiones |

## Detalle por tema

### 1. Meta Ad Library
- Sin `app/backend/.env.local` la integración arranca **apagada** y sin token (`ads_library.py`). Se creó ese archivo con
  `META_INTEGRATION_ENABLED=true` y la línea `META_AD_LIBRARY_TOKEN=`; el token lo pegó el usuario. Nunca se copió ni se versiona.
- No hubo cambios de código para esto; el `.bat` original sigue idéntico al del zip.

### 2. «Validar perfiles» (ficha)
- `index.html`: botón de solo icono `#btn-ficha` (tooltip «Validar perfiles») en la barra superior y sección flotante `#ficha`.
- `app.js`: `fichaUI`, `filaParaFicha`, `abrirFicha`, `initFicha`. Edita los datos de afiliación de la entidad (los campos de `afiliaciones.json`).
- Tras guardar, `refrescarPorAfiliacion` recarga **en silencio** (`cargarResumen(alcance, { silencioso })`) y se mantiene la vista.

### 3. Memoria de vista (mapa y red)
- **Mapa (Leaflet):** `guardarMapa` / `leerMapaGuardado` guardan en `localStorage["noai_mapa"]` la provincia, sección, periodo, centro y zoom.
  Al recargar se restaura esa vista en lugar de encuadrar todo el país (`conservarEncuadre`).
- **Red «Conexiones»:** `memoriaRed` (en `sessionStorage["noai_red_memoria"]`, por pestaña) guarda alcance, cámara y selección.
  `red-orbital.js` expone `estado()` y `restaurar`; al volver a abrir el detalle (`reabrirDetalle`) la selección y el zoom siguen donde estaban.
  Una selección restaurada no se re-centra (`restaurado`), para no mover la cámara.

### 4. Red «Conexiones»: lectura visual
- Líneas de mensajes repetidos (tipo `texto`) **muy tenues**; recuperan su fuerza solo al seleccionar una o al activar su filtro.
- Leyenda en **columnas** (iconos y texto alineados, menos espacio entre grupos), en mayúsculas con Inter; se quitó «Sol» y «(pulsa la línea)».
  Las explicaciones de tamaño y anillo pasaron a la ayuda ⓘ («Cómo leer el gráfico», «Qué se dibuja según el zoom»).
- **Un solo trazo** (doble continuo) para las conexiones de partido, dentro y entre provincias.
- Ambas leyendas (mapa y red) son **colapsables** y comparten diseño; la del mapa recuerda su estado (`noai_mapa_leyenda`).
- Filtros: `TIPOS_FILTRO` reúne `partido` y `partido_prov` en un único filtro «partido». El filtro de **provincia se eliminó**:
  el vínculo con la provincia no se puede romper (`aristaViva` es siempre verdadero para `alcance`).

### 5. Cobertura de provincias en la vista nacional
- Causa: la red nacional se recortaba a las páginas de mayor inversión y las provincias pequeñas se quedaban sin nodos.
- Arreglo: `_grafo_red(..., garantizar_provincias=True)` en la vista nacional (`PAGINAS_POR_PROVINCIA_GARANTIZADAS = 2`) y
  el frontend pide `max_paginas=6000`; por eso `main.py` sube el tope de 300 a 6000. La densidad se controla ahora en el cliente (punto 6).

### 6. Nivel de detalle por zoom y rendimiento (`red-orbital.js`)
- Con poco zoom solo se ven las páginas grandes; al acercar aparecen más. Provincias pequeñas: siempre completas.
  Constantes: `LOD_K0 = 0.43` (zoom que encuadra el país), `LOD_CUPO_MIN = 12` páginas por provincia con ese zoom, además de las **fijas**;
  `actualizarVisibilidad` / `lodRank` / `cupoLOD` hacen el reparto y `visA` suaviza la aparición.
- **Lente del cursor:** `LENTE_PX = 80` px alrededor del cursor muestra hasta `LENTE_MAX = 30` páginas ocultas (las de mayor inversión).
- Selección por clic, rótulos y navegación con teclado solo consideran lo visible.
- Rendimiento (medido en el navegador integrado con 2.304 nodos): de ~109 ms a ~8–20 ms por fotograma, con nodos como sprites (`esfera`),
  descarte fuera de pantalla, aristas en lotes (`Path2D`) y repintado pasivo limitado.

### 7. Anuncios retirados por Meta
- Meta deja un aviso en lugar del texto cuando retira un anuncio sin descargo. `_PLACEHOLDER_SIN_DESCARGO` cubre 3 variantes
  (inglés y dos en español); `_retirado_por_meta()` solo acepta textos de ≤ 300 caracteres (`_LARGO_MAX_AVISO`).
- `_derivar` marca `_retirado`; `obtener_nacional()` los quita del mapa, la red, las listas y las cifras y publica
  `estado["retirados_por_meta"]` y `total_nacional`. La copia en disco (snapshot) los conserva.
- Se avisa en ⓘ (`renderProveniencia`), en la leyenda del mapa y en la página Método.

### 8. Modo red local
- `INICIAR NoAIVerdad (red local).bat` → `NOAIVERDAD_RED=1` → `launcher.py` (`RED_LOCAL`, o `--red`) escucha en `0.0.0.0` (web 3000 y API 8000)
  e imprime las direcciones `http://<ip>:3000/` para otros dispositivos. Sin esa variable sigue en `127.0.0.1`, como antes.
- `app-config.js` (`esHostDeRedLocal`): en el puerto 3000 y con IP privada (10.x, 192.168.x, 172.16–31.x, 100.64–127.x, 169.254.x) o nombre
  local (`.local`, `.lan`, `.home`…), la app entra **sin cuenta**; `?debug=0` fuerza el acceso con cuenta. En localhost sigue haciendo falta `?debug=1`.
  Un dominio publicado nunca entra por aquí. No depende del almacenamiento del navegador.
- `obtenerBackendUrl` (`app.js`) y `afiliaciones-check.js` apuntan a `<host>:8000` cuando la página viene de la red local; la CSP permite `connect-src http://*:8000`.
- Desde otro dispositivo la app es **de solo lectura**: guardar afiliaciones solo se acepta desde el propio equipo, salvo que se defina `AFIL_EDIT_TOKEN`
  (`_puede_editar_afiliaciones`, comportamiento que ya existía).
- La primera vez Windows pregunta si Python puede usar la red: se permite solo en redes privadas. No se tocó el firewall ni ningún ajuste del sistema.
- El lanzador distingue «puerto 3000 ocupado por otro programa» de «NoAIVerdad ya está abierto en otra ventana» (`es_web_noaiverdad`, `responde_en`).

### 9. iPhone / iPad (todos los navegadores de iOS usan WebKit, también Chrome)
- Síntoma: el mapa de Ecuador de fondo en «Conexiones» no se veía (el mapa principal sí).
- Causa: WebKit no implementa `ctx.filter` en el canvas, que se usaba para oscurecer las teselas de OpenStreetMap.
- Arreglo: `SOPORTA_FILTRO` detecta la función; si falta, `aplicarFiltroManual` aplica el mismo filtro **píxel a píxel** al cargar cada tesela
  (`pasosDeFiltro` / `pasosActuales`). La caché de teselas queda acotada (160, descarta 50).
- Para probarlo en escritorio: abrir con `?sinfiltro=1` (o `window.NOAI_SIN_FILTRO_CANVAS = true`).

### 10. Panel lateral ajustable y selección centrada
- Asa `#rs-der-asa` (role `separator`) dentro de `#rs-der`. En pantallas anchas ajusta el **ancho**; en móvil (≤ 640 px, panel inferior) la **altura**.
  Variables CSS `--rs-der-w` / `--rs-der-h`; mínimo 300 px de ancho o 150 px de alto; máximo `min(ancho − 200, 1000)` px o el 92 % del alto.
- Se mueve con el puntero, con el teclado (flechas, Inicio/Fin) y el doble clic vuelve al tamaño original. Se recuerda en `localStorage`
  (`noai_rs_der_ancho`, `noai_rs_der_alto`). Durante el arrastre `.rs-ajustando` desactiva las transiciones.
- Al seleccionar algo, la vista se centra en la zona **no cubierta** por el panel (`zonaCubiertaRed`, `recentrarSeleccionRed`,
  `ctl.centrarSeleccion` / `centrarEnLibre` en la red orbital, `centrarSeleccionClasica` / `centrarEn` en la clásica). También al redimensionar el panel.

## Datos
- `app/backend/afiliaciones.json`: 7 entradas nuevas con fuente y fecha 2026-11-05 (Lisette Naranjo Herdoíza, Alejandro Lara, Christian Meléndez,
  Wilman Rodrigo Rodríguez Berrú, Natalia Escobar, Christian Lozada y Alcaldía Ciudadana de Quinindé). Se añadieron desde la propia app mientras se
  probaba. Las fuentes (campo `fuente`) las revisó el usuario; el archivo pasó de 44 a 51 entradas.

## Lo que NO está en el repositorio (ver `.gitignore`)
- `app/backend/.env.local`: contiene el token de Meta.
- `app/backend/data/ads_snapshot.json`: ≈45 MB, la app lo regenera (cambió de tamaño respecto al zip). Está cerca del aviso de 50 MB de GitHub.
- `app/.venv/` y `__pycache__/`: los crea el `.bat`.

## Verificación
- **Hecho:** navegador integrado en escritorio, móvil (375×812) y tableta (768×1024); modo clásico y orbital; teclado, doble clic y persistencia del panel;
  entrada sin cuenta en la red local con Chrome sin ventana (con `?debug=0` vuelve a pedir cuenta); cabeceras CORS de la API con `curl`;
  filtro manual de iOS contra el nativo (diferencia máxima 3/255, media ≈ 1).
- **No hecho:** pruebas en un iPhone o iPad reales; el proyecto no tiene pruebas automáticas, así que no se ejecutó ninguna.
- **Observado, sin investigar:** el rótulo de fuente de ⓘ a veces dice «Datos guardados: Meta no respondió» (el refresco en segundo plano falla y se usa el snapshot local).
- `app/VERSION.txt` no se cambió (sigue «beta 0.4.0 · 2026-11-05 · d58f7fd»).

## Cómo probar rápido
- Normal: `INICIAR NoAIVerdad.bat` → `http://localhost:3000/?debug=1`.
- Red local: `INICIAR NoAIVerdad (red local).bat` y abrir desde otro dispositivo la dirección `http://<ip-del-equipo>:3000/` que imprime la consola.
- Borrar la memoria de vista: en la consola del navegador, `localStorage.removeItem("noai_mapa")` y `sessionStorage.removeItem("noai_red_memoria")`.
