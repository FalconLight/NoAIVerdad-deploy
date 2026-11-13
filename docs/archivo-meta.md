# Archivo histórico de anuncios de Meta

Conserva en disco, sin límite de tiempo, los anuncios políticos de Ecuador tal como los devuelve la Biblioteca de Anuncios de Meta, para
poder volver a cargarlos en esta o en futuras versiones aunque la app ya no los muestre.

## Por qué hace falta

- **Los 120 días son un límite de la app, no de Meta.** La app solo pide a Meta los anuncios que circularon en los últimos
  `AD_LIBRARY_DAYS` días (120 por defecto). Meta conserva los anuncios políticos unos 7 años, así que nada se borra en Meta a los 120
  días; lo que pasa es que la app deja de verlos.
- Aun así conviene tener copia propia: el token de acceso vence (el actual, el 2026-12-26), el acceso a la API se puede perder, y cuando
  Meta retira un anuncio sustituye su texto por un aviso estándar: el texto original ya no se puede recuperar.
- La copia de la app (`backend/data/ads_snapshot.json`) guarda una versión resumida (un solo texto por anuncio, sin campos extra) y se
  reemplaza entera en cada descarga. El archivo guarda la **respuesta cruda** de Meta y solo crece.

## Qué guarda y cómo

Carpeta del archivo: la de `AD_LIBRARY_ARCHIVO_DIR` (en `backend/.env.local`); si no está definida, `backend/data/archivo`.
En este equipo: `D:\Users\Usuario\Documents\YO\MEDIAHACK II\NoAIVerdad-datos\archivo-meta` (fuera de las carpetas de cada versión, para
que no dependa de ninguna).

```
manifest.json                 esquema, país, total, cada mes (anuncios, bytes, sha256), meses capturados y bitácora de capturas
anuncios/AAAA-MM.jsonl.gz     una línea JSON por anuncio (gzip). El mes es el de inicio del anuncio; sin fecha: sin-fecha.jsonl.gz
```

Cada línea:

```json
{"id": "…", "visto_primero": "2026-11-10T02:10:00", "visto_ultimo": "2026-11-10T02:10:00", "origen": "meta-api",
 "raw": { …respuesta de Meta: page_id, page_name, bylines, fechas, textos, spend, impressions, delivery_by_region,
          demographic_distribution, estimated_audience_size, publisher_platforms, languages, ad_creative_link_captions… },
 "versiones": [{"hasta": "…", "ad_creative_bodies": ["texto anterior"]}]}
```

Reglas:

- **Solo añade o actualiza; nunca borra.** Un anuncio visto otra vez actualiza sus cifras (los rangos de gasto e impresiones cambian
  mientras circula) pero no pierde campos.
- Si el texto de un anuncio cambia (por ejemplo, Meta lo retira y pone su aviso), el texto anterior queda en `versiones`.
- `ad_snapshot_url` nunca se pide ni se guarda: Meta incrusta en ella el token. **El archivo no contiene ningún token ni clave**; son
  datos públicos de la Biblioteca de Anuncios.
- El formato es JSON por líneas comprimido con gzip: se puede leer con cualquier lenguaje sin este programa.

## Cómo se llena

1. **Sola, con cada descarga de la app** (a partir de la 0.6): cada vez que el servidor renueva los anuncios (una vez por hora) los
   fusiona en el archivo. Así lo que salga de la ventana de 120 días ya quedó guardado. Se apaga con `AD_LIBRARY_ARCHIVAR=false`.
2. **A mano, con la herramienta** (también para versiones anteriores, que no archivan solas):

Desde `backend/`, con el Python que tiene las dependencias (`.venv`):

```
python tools\archivo_meta.py capturar                      baja lo que falte, mes a mes hacia atrás, y refresca los últimos 120 días
python tools\archivo_meta.py capturar --desde 2025-01-01   solo hasta esa fecha
python tools\archivo_meta.py capturar --forzar             vuelve a bajar también los meses ya completos
python tools\archivo_meta.py estado                        cuántos anuncios hay y de qué meses
python tools\archivo_meta.py verificar                     comprueba cada archivo contra el manifiesto (sha256 y cuentas)
python tools\archivo_meta.py exportar D:\copias\archivo-meta.zip
python tools\archivo_meta.py importar D:\copias\archivo-meta.zip
python tools\archivo_meta.py snapshot --salida D:\copias\ads_historico.json --desde 2026-01-01
python tools\archivo_meta.py sqlite D:\copias\anuncios-meta.sqlite        base de datos SQLite con todo el archivo
python tools\archivo_meta.py csv D:\copias\anuncios-meta-csv              las mismas tablas en CSV
```

`capturar`:

- Pide a Meta todos los anuncios políticos y de temas sociales de Ecuador (búsqueda «*», activos e inactivos) que circularon en cada mes,
  del mes actual hacia atrás. Para al llegar a `--desde` (por defecto, hace 7 años) o tras 12 meses seguidos sin anuncios.
- **Es reanudable**: cada mes que termina sin errores queda marcado como completo y no se vuelve a bajar. Si se corta (límite de
  consultas de Meta, red, token vencido), se ejecuta el mismo comando otra vez y continúa. Lo bajado de un mes interrumpido no se pierde.
- Los meses que tocan los últimos 120 días se bajan siempre, porque esos anuncios siguen cambiando.
- Va despacio a propósito (1,5 s entre consultas) y lee en cada respuesta qué parte de la cuota de la hora lleva gastada: al pasar del
  75 % hace una pausa. Un fallo de red se reintenta cinco veces con esperas crecientes. Si Meta limita el ritmo espera 5, 10, 15… minutos
  y, si sigue, se detiene con un mensaje. Mientras corre, otro servidor de NoAIVerdad que use el mismo token puede mostrar «No se pudo
  actualizar con Meta» y seguir con su última copia: es normal y se arregla solo.
- Si una página de resultados pesa demasiado la pide más pequeña (hasta de un anuncio en uno). Si un solo anuncio no cabe, lo guarda sin
  su reparto por edad (y, si aun así no cabe, sin su reparto por región); los ids de esos anuncios quedan en `manifest.json`, en la
  ventana de su mes (`campos_reducidos`).
- Al reanudar no repite los meses recientes que se bajaron hace menos de 12 horas.
- En este equipo hay un lanzador que la ejecuta en segundo plano y deja el avance en `captura.log`:
  `D:\Users\Usuario\Documents\YO\MEDIAHACK II\NoAIVerdad-datos\reanudar-captura.cmd` (doble clic).
- Usa el token de `backend/.env.local`. El resto de comandos no llama a Meta.

Conviene ejecutar `capturar` de vez en cuando mientras la versión en uso no archive sola (la 0.5 no lo hace), y siempre antes de que
venza el token.

## Base de datos estándar (SQLite) y CSV

El archivo en sí es JSON por líneas, pensado para no perder nada. Para consultarlo o analizarlo con otras herramientas se exporta a:

- **SQLite** (`sqlite <ruta>`): un solo archivo `.sqlite`, formato de base de datos estándar, libre y sin servidor. Lo abren DB Browser
  for SQLite, DBeaver, Python (`sqlite3`), R, Excel y Power BI (con el controlador ODBC de SQLite), y se puede cargar tal cual en
  PostgreSQL o MySQL. Con `--sin-raw` no incluye la respuesta original de Meta en cada fila (queda más pequeño).
- **CSV** (`csv <carpeta>`): las mismas tablas como archivos `.csv` en UTF-8 (Excel y Power BI los abren directamente).

Las dos salidas aceptan `--desde` y `--hasta` (fecha de inicio del anuncio) y se generan de nuevo, completas, cada vez: la fuente sigue
siendo el archivo. Tablas:

| Tabla | Una fila por | Columnas |
|---|---|---|
| `anuncios` | anuncio | `id`, `page_id`, `page_name`, `pagador`, `inicio`, `fin`, `creado`, `activo`, `moneda`, `gasto_min`, `gasto_max`, `impresiones_min`, `impresiones_max`, `audiencia_min`, `audiencia_max`, `texto`, `titulo`, `textos`, `plataformas`, `idiomas`, `enlace`, `retirado_por_meta`, `versiones_de_texto`, `visto_primero`, `visto_ultimo`, `origen` (y `raw_json` en SQLite) |
| `anuncio_regiones` | anuncio y región | `anuncio_id`, `region`, `porcentaje` (0 a 1) |
| `anuncio_demografia` | anuncio, edad y género | `anuncio_id`, `edad`, `genero`, `porcentaje` (0 a 1) |
| `anuncio_versiones` | texto anterior de un anuncio | `anuncio_id`, `hasta`, `texto` |
| `info` (solo SQLite) | dato de la exportación | `clave`, `valor` |

`gasto`, `impresiones` y `audiencia` son los rangos que publica Meta (mínimo y máximo), no cifras exactas. `region` es el nombre tal como
lo da Meta (incluye regiones de otros países con porcentajes mínimos); la app las reduce a las 24 provincias al cargar.

Ejemplo (inversión mínima y máxima por página en 2026):

```sql
SELECT page_name, COUNT(*) AS anuncios, SUM(gasto_min) AS gasto_min, SUM(gasto_max) AS gasto_max
FROM anuncios WHERE inicio >= '2026-01-01' AND retirado_por_meta = 0
GROUP BY page_id ORDER BY gasto_max DESC LIMIT 20;
```

## Cómo volver a cargar los datos (carga manual)

La app carga una copia en su propio formato. Se genera desde el archivo y se le indica al servidor que la use sin llamar a Meta:

1. Generar la copia con el período que se quiera ver:

   ```
   python tools\archivo_meta.py snapshot --salida D:\copias\ads_historico.json --desde 2026-01-01 --hasta 2026-11-10
   ```

   (`--dias 365` en lugar de `--desde` toma los últimos N días.)

2. Arrancar el backend con estas variables (en `backend/.env.local` o en el entorno):

   ```
   AD_LIBRARY_SNAPSHOT=D:\copias\ads_historico.json
   AD_LIBRARY_SOLO_COPIA=true
   ```

   En modo «solo copia» el servidor sirve esa copia tal cual, **sin token y sin llamar nunca a Meta**; no importa de cuántos días sea. La
   app avisa de que son datos guardados y de qué fecha.

Para versiones futuras con otro formato interno: lean directamente `anuncios/*.jsonl.gz` (campo `raw`); es la respuesta original de Meta.

Para llevar el archivo a otro equipo: `exportar` hace un solo `.zip`; `importar` lo **fusiona** con el archivo que haya (no borra nada, y
de cada anuncio queda la captura más reciente).

## Límites conocidos

- El gasto y las impresiones son rangos de Meta y el archivo guarda **el último valor visto** de cada anuncio (más las versiones de
  texto); no guarda la evolución diaria de las cifras.
- Meta devuelve en cada mes los anuncios que **circularon** ese mes, aunque empezaran antes; cada anuncio se guarda una sola vez, en el
  archivo del mes en que empezó.
- La fecha más antigua que acepta la API es 2018-05-07.
- La app no se ha probado con cientos de miles de anuncios a la vez: una copia de varios años puede ser lenta o no caber en memoria.
  Para verla en la app conviene generar la copia por períodos (un año, una campaña).
- El archivo no se sube a git (`backend/data/` está ignorado y la carpeta de datos está fuera del repositorio): hay que copiarlo aparte
  (`exportar`) para tener respaldo.
- Unir páginas de una misma entidad, afiliaciones y revisiones de mensajes no viven en el archivo: siguen en `afiliaciones.json` y
  `mensajes_revisados.json`.
