import asyncio
import hmac
import html
import logging
import os
import re
import threading
import unicodedata
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Asegurar que el directorio backend está en sys.path
_DIR_ACTUAL = os.path.dirname(os.path.abspath(__file__))
import sys
if _DIR_ACTUAL not in sys.path:
    sys.path.insert(0, _DIR_ACTUAL)

# Cargar variables de entorno si existen (.env)
load_dotenv()
# Secretos locales (fuera de git): sobrescriben a .env, p. ej. META_AD_LIBRARY_TOKEN, GNEWS_API_KEY, X_BEARER_TOKEN
load_dotenv(os.path.join(_DIR_ACTUAL, ".env.local"), override=True)

from meta_service import UnifiedFeedService
import firebase_store
from news_collector import refresh_all

logger = logging.getLogger(__name__)

_collector_task = None

# --- Despliegue público (showcase) ---
# NOAI_SOLO_LECTURA: true deja solo las consultas GET a las rutas de datos que usa la app. Todo lo demás (escrituras de
#   afiliaciones y revisiones, /docs, /openapi.json, diagnósticos, la raíz con el estado de los servicios) responde 404/403.
#   Además las respuestas se marcan como cacheables 5 minutos en la CDN y no se permite CORS desde otros sitios.
_SOLO_LECTURA = os.getenv("NOAI_SOLO_LECTURA", "").strip().lower() in ("1", "true", "yes", "si", "sí")
_RUTAS_DE_DATOS = re.compile(r"^/api/(ads/(mapa|comparar|top-gastadores|red-pagadores|afiliaciones|anuncios|textos-duplicados(/par)?|enlaces/par)"
                             r"|dashboard/(stats|keywords)|noticias)/?$")


async def _scheduled_collection_loop():
    interval = max(900, int(os.getenv("NEWS_REFRESH_INTERVAL_SECONDS", "21600")))
    print(f"[Firebase collector] Recolección de noticias cada {interval} segundos.", flush=True)
    while True:
        try:
            result = await asyncio.to_thread(refresh_all, unified_service)
            print(f"[Firebase collector] Ciclo terminado: {result}", flush=True)
        except Exception:
            logger.exception("Falló el ciclo del colector programado.")
        await asyncio.sleep(interval)


def _calentar_anuncios():
    """Descarga los anuncios de Meta al arrancar (tarda decenas de segundos): así la primera visita ya los encuentra en caché."""
    try:
        unified_service.ads_library.obtener_nacional()
        unified_service.ads_library.precalcular()           # y la comparación de textos (mensajes repetidos y red), que tarda unos segundos
    except Exception:
        logger.exception("No se pudo calentar la caché de anuncios de Meta.")


@asynccontextmanager
async def lifespan(_app):
    global _collector_task
    threading.Thread(target=_calentar_anuncios, name="ads-library-calentar", daemon=True).start()
    if firebase_store.initialize():
        _collector_task = asyncio.create_task(_scheduled_collection_loop())
    else:
        print("[Firebase collector] Sin credenciales Admin; la recolección programada está desactivada.", flush=True)
    try:
        yield
    finally:
        if _collector_task:
            _collector_task.cancel()
            try:
                await _collector_task
            except asyncio.CancelledError:
                pass
            _collector_task = None


async def _filtro_cne(sin_cne: bool = Query(False, description="Excluye de todas las respuestas los anuncios del CNE (autoridad electoral)")):
    """Activa el filtro global del CNE para esta petición (async: así el valor llega a los endpoints sincrónicos)."""
    from ads_library import SIN_CNE
    SIN_CNE.set(sin_cne)


async def _filtro_activos(solo_activos: bool = Query(False, description="Deja solo los anuncios que siguen activos (sin fecha de fin) en todas las respuestas")):
    """Activa el filtro global «solo activos» para esta petición (igual que el del CNE)."""
    from ads_library import SOLO_ACTIVOS
    SOLO_ACTIVOS.set(solo_activos)


_FECHA = r"^\d{4}-\d{2}-\d{2}$"


async def _filtro_fechas(fecha_desde: Optional[str] = Query(None, pattern=_FECHA, description="Deja solo los anuncios que circularon desde este día (AAAA-MM-DD) en todas las respuestas"),
                         fecha_hasta: Optional[str] = Query(None, pattern=_FECHA, description="Deja solo los anuncios que circularon hasta este día (AAAA-MM-DD); igual que fecha_desde = un solo día")):
    """Activa el rango de fechas global para esta petición (igual que el del CNE). Si llegan invertidas, se ordenan."""
    from ads_library import RANGO_FECHAS
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        fecha_desde, fecha_hasta = fecha_hasta, fecha_desde
    RANGO_FECHAS.set((fecha_desde, fecha_hasta))


# Inicializar aplicación FastAPI
app = FastAPI(
    dependencies=[Depends(_filtro_cne), Depends(_filtro_activos), Depends(_filtro_fechas)],
    title="NoAIVerdad - Backend",
    description="API para el monitoreo cívico de desinformación electoral en Ecuador por provincia: prensa (GNews, "
                "Google News, CNE), verificaciones, Bluesky, YouTube, Reddit y anuncios políticos de Meta. "
                "Sin datos simulados. Un colector opcional guarda los resultados en Firebase.",
    version="6.0.0",
    lifespan=lifespan,
    docs_url=None if _SOLO_LECTURA else "/docs",
    redoc_url=None if _SOLO_LECTURA else "/redoc",
    openapi_url=None if _SOLO_LECTURA else "/openapi.json",
)

# Configuración de CORS middleware
_cors_env = os.getenv("CORS_ORIGINS", "*").strip()
_allow_origins = ["*"] if _cors_env == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _guardia_despliegue(request: Request, call_next):
    """Cierra el backend en el despliegue público (NOAI_SOLO_LECTURA): solo se consultan las rutas de datos de la app y archivos estáticos."""
    from fastapi.responses import JSONResponse
    if _SOLO_LECTURA:
        if request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": "Esta versión pública es de solo lectura."}, status_code=403)
        es_estatico = (
            request.url.path == "/"
            or any(request.url.path.startswith(p) for p in ("/css", "/js", "/data", "/docs", "/assets", "/favicon.ico"))
            or request.url.path.endswith((".html", ".png", ".jpg", ".svg", ".json", ".geojson", ".ico"))
        )
        if not _RUTAS_DE_DATOS.match(request.url.path) and not es_estatico:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        respuesta = await call_next(request)
        if respuesta.status_code == 200:
            # caché compartida en la CDN: muchas visitas al showcase = pocas ejecuciones del backend. Los anuncios salen de la copia incluida
            # y solo cambian con un nuevo despliegue (que vacía la caché de Vercel): un día en la CDN. Las noticias en vivo, una hora.
            if request.url.path.startswith("/api/noticias"):
                respuesta.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600, stale-while-revalidate=3600"
            elif request.url.path.startswith("/api/"):
                respuesta.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
        return respuesta
    return await call_next(request)

# Inicializar servicio unificado
unified_service = UnifiedFeedService()

PROVINCIAS = {
    "azuay": "Azuay", "bolivar": "Bolívar", "canar": "Cañar", "carchi": "Carchi", "chimborazo": "Chimborazo",
    "cotopaxi": "Cotopaxi", "el_oro": "El Oro", "esmeraldas": "Esmeraldas", "galapagos": "Galápagos",
    "guayas": "Guayas", "imbabura": "Imbabura", "loja": "Loja", "los_rios": "Los Ríos", "manabi": "Manabí",
    "morona_santiago": "Morona Santiago", "napo": "Napo", "orellana": "Orellana", "pastaza": "Pastaza",
    "pichincha": "Pichincha", "santa_elena": "Santa Elena", "santo_domingo": "Santo Domingo de los Tsáchilas",
    "sucumbios": "Sucumbíos", "tungurahua": "Tungurahua", "zamora_chinchipe": "Zamora Chinchipe",
}


def nombre_provincia(valor: Optional[str]) -> Optional[str]:
    """Acepta el nombre o el identificador del selector (p. ej. 'zamora_chinchipe'). None = nivel nacional."""
    if not valor or not valor.strip():
        return None
    limpio = valor.strip()
    if limpio.lower() in ("todas", "ecuador", "ecuador (todas)"):
        return None
    return PROVINCIAS.get(limpio.lower(), limpio.replace("_", " "))


def miles(n: Any) -> str:
    """Formato es-EC de miles: 36434 -> '36.434'."""
    return f"{int(n or 0):,}".replace(",", ".")


def _norm(texto: Any) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@app.get("/")
def read_root():
    """Ruta raíz para verificación de estado del servidor."""
    return {
        "sistema": "NoAIVerdad API v6.0",
        "estado": "Activo",
        "servicios": {
            "noticias": True,
            "cne": True,
            "youtube_rss": True,
            "reddit_rss": True,
            "bluesky_publico": True,
            "google_fact_check": bool(unified_service.fact_check_api_key),
            "x_api": unified_service.x_client.configurado,
            "meta_ad_library": unified_service.ads_library.configurado,
            "meta_habilitado": unified_service.ads_library.habilitado,
            "firebase_colector": _collector_task is not None,
        },
        "documentacion": "/docs"
    }


@app.get("/api/ads/diagnostico")
def diagnostico_biblioteca_anuncios():
    """Prueba mínima de la Biblioteca de Anuncios de Meta: interruptor, token, versión de API y cobertura de Ecuador."""
    return unified_service.ads_library.diagnostico()


@app.get("/api/x/diagnostico")
def diagnostico_x():
    """Estado de la integración con la API de X (sin gastar créditos)."""
    return unified_service.x_client.diagnostico()


@app.get("/api/ads/mapa")
def metricas_mapa():
    """Impresiones, inversión, anuncios y anunciantes estimados por provincia (alimenta el mapa)."""
    return unified_service.ads_library.metricas_por_provincia()


@app.get("/api/ads/comparar")
def comparar_alcances(provincias: str = Query(..., description="De 2 a 3 alcances separados por coma; 'todas' = nacional")):
    """Compara anuncios políticos de Meta entre provincias (o contra el total nacional)."""
    partes = [p for p in provincias.split(",") if p.strip()][:3]
    if len(partes) < 2:
        raise HTTPException(status_code=400, detail="Indica al menos dos alcances separados por coma.")
    return unified_service.ads_library.comparar([nombre_provincia(p) for p in partes])


@app.get("/api/ads/top-gastadores")
def top_gastadores_meta(provincia: Optional[str] = Query(None), limite: int = Query(10, ge=1, le=6000), sin_cne: bool = Query(False),
                        tipo: Optional[str] = Query(None, max_length=120, description="Tipo de anunciante: candidatos, instituciones, medios, agencias, otros, sin_clasificar (varios, separados por comas)")):
    """Anunciantes políticos de Meta con mayor inversión estimada (nacional o por provincia)."""
    return unified_service.ads_library.top_gastadores(nombre_provincia(provincia), limite, sin_cne, tipo)


@app.get("/api/ads/red-pagadores")
def red_pagadores_meta(provincia: Optional[str] = Query(None), limite: int = Query(15, ge=1, le=100), sin_cne: bool = Query(False),
                       max_paginas: int = Query(80, ge=0, le=6000)):
    """Vínculos pagador -> página (pagador declarado distinto de la página) y redes de pagadores compartidos."""
    return unified_service.ads_library.red_pagadores(nombre_provincia(provincia), limite, sin_cne, max_paginas)


_ORIGEN_LOCAL = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")


def _puede_editar_afiliaciones(request: Request) -> bool:
    """
    Escribir afiliaciones solo se permite (a) con el código AFIL_EDIT_TOKEN si está configurado, o (b) si no lo está,
    desde el mismo equipo del servidor y desde una página local. Evita que otro sitio web escriba en el archivo.
    """
    if _SOLO_LECTURA:                                     # despliegue público: nadie edita, ni siquiera con código
        return False
    token = os.getenv("AFIL_EDIT_TOKEN", "")
    if token:
        return hmac.compare_digest(request.headers.get("x-edit-token", ""), token)
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost") or request.headers.get("x-forwarded-for"):
        return False
    origen = request.headers.get("origin")
    return not origen or bool(_ORIGEN_LOCAL.match(origen))


class AfiliacionEntrada(BaseModel):
    nombre: str
    page_id: Optional[str] = None
    page_ids: Optional[List[str]] = None      # todos los ID de página de la entidad (una persona puede tener varias páginas); None = conservar los actuales
    otros_nombres: Optional[List[str]] = None  # otros nombres de la misma entidad (el pagador declarado, otra grafía…); None = conservar los actuales
    tipo: Optional[str] = None
    afiliacion: Optional[str] = None
    partido: Optional[str] = None             # «Neutral» (solo medios) marca un medio que informa sin alineación partidista
    fuente: Optional[str] = None
    verificado: bool = False


class EntidadRef(BaseModel):
    nombre: Optional[str] = None
    page_id: Optional[str] = None


class UnificarEntrada(BaseModel):
    principal: EntidadRef                     # la entrada que se conserva
    otras: List[EntidadRef]                   # las que pasan a ser la principal (nombre y/o ID de página)
    nombre_final: Optional[str] = None        # opcional: nuevo nombre de la entrada unificada (p. ej. con la ñ)


@app.post("/api/ads/afiliaciones/unificar")
def unificar_afiliaciones_meta(entrada: UnificarEntrada, request: Request):
    """Une varias entradas de afiliaciones.json en una (la misma persona con otro nombre, otra página o el pagador con otro nombre)."""
    if not _puede_editar_afiliaciones(request):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar afiliaciones desde aquí (solo el equipo del servidor, o con el código de edición).")
    try:
        return unified_service.ads_library.unificar_afiliaciones(entrada.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ads/afiliaciones")
def afiliaciones_meta(request: Request, faltantes: int = Query(15, ge=0, le=100)):
    """Contenido y estado de backend/afiliaciones.json (para revisarlo o editarlo) y páginas con inversión que aún no están en el archivo."""
    resultado = unified_service.ads_library.afiliaciones_estado(faltantes)
    resultado["editable"] = _puede_editar_afiliaciones(request)
    resultado["requiere_codigo"] = bool(os.getenv("AFIL_EDIT_TOKEN"))
    return resultado


@app.post("/api/ads/afiliaciones")
def guardar_afiliacion_meta(entrada: AfiliacionEntrada, request: Request):
    """Crea o actualiza una entrada de afiliación y la guarda en backend/afiliaciones.json."""
    if not _puede_editar_afiliaciones(request):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar afiliaciones desde aquí (solo el equipo del servidor, o con el código de edición).")
    try:
        return unified_service.ads_library.guardar_afiliacion(entrada.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ads/anuncios")
def anuncios_meta(alcance: Optional[str] = Query(None, description="Provincia: los anuncios que llegan a ella (al menos el 5 % de su alcance); vacío o 'todas' = todo el país"),
                  pagina: Optional[str] = Query(None, max_length=200),
                  page_id: Optional[str] = Query(None, max_length=400, description="Uno o varios ID de página de Meta, separados por comas"),
                  pagador: Optional[str] = Query(None, max_length=200), region: Optional[str] = Query(None, max_length=80),
                  entidad: Optional[str] = Query(None, max_length=200),
                  solo_terceros: bool = Query(False, description="Con pagador: solo anuncios donde el pagador declarado es distinto de la página"),
                  orden: str = Query("recientes", description="recientes | inversion | impresiones"),
                  desde: int = Query(0, ge=0), limite: int = Query(25, ge=1, le=100), sin_cne: bool = Query(False),
                  dias: int = Query(0, ge=0, le=730, description="Solo anuncios activos o que terminaron en los últimos N días; 0 = sin límite"),
                  tipo: Optional[str] = Query(None, max_length=120, description="Tipo de anunciante: candidatos, instituciones, medios, agencias, otros, sin_clasificar (varios, separados por comas)"),
                  completo: bool = Query(False, description="Incluye el alcance de cada anuncio por provincia (para exportar)")):
    """
    Todos los anuncios que llegan a una provincia (`alcance`), de una página, de un pagador, de las páginas con base en una
    provincia (`region`, lo que suma el sol de la red) o de una entidad, paginados y con las mismas reglas que el resto de la API.
    """
    try:
        return unified_service.ads_library.anuncios(nombre_provincia(alcance), pagina, page_id, pagador, region, entidad, solo_terceros,
                                                    orden, desde, limite, sin_cne, dias, tipo, completo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ads/textos-duplicados")
def textos_duplicados_meta(request: Request, provincia: Optional[str] = Query(None), limite: int = Query(10, ge=1, le=200), sin_cne: bool = Query(False),
                           revisados: bool = Query(False, description="Incluir (al final) los grupos que el equipo ya revisó; por defecto se omiten")):
    """Mensajes de anuncios casi idénticos publicados por páginas distintas (indicador de posible coordinación)."""
    resultado = unified_service.ads_library.textos_duplicados(nombre_provincia(provincia), limite, sin_cne=sin_cne, revisados=revisados)
    resultado["editable"] = _puede_editar_afiliaciones(request)          # marcar grupos como revisados se protege igual que editar afiliaciones
    resultado["requiere_codigo"] = bool(os.getenv("AFIL_EDIT_TOKEN"))
    return resultado


@app.get("/api/ads/textos-duplicados/par")
def textos_duplicados_par(pagina_a: str = Query(..., max_length=200), pagina_b: str = Query(..., max_length=200),
                          provincia: Optional[str] = Query(None), sin_cne: bool = Query(False)):
    """Los mensajes repetidos entre dos páginas, con cada anuncio (texto, fechas y su propio enlace a la Biblioteca de Meta) para verlos lado a lado."""
    return unified_service.ads_library.textos_duplicados(nombre_provincia(provincia), 200, sin_cne=sin_cne, revisados=True, entre=(pagina_a, pagina_b))


@app.get("/api/ads/enlaces/par")
def enlaces_par(pagina_a: str = Query(..., max_length=200), pagina_b: str = Query(..., max_length=200),
                provincia: Optional[str] = Query(None), sin_cne: bool = Query(False)):
    """Los enlaces que comparten dos páginas, con los anuncios de cada una que los llevan, para verlos lado a lado (línea «mismo enlace» de la red)."""
    return unified_service.ads_library.enlaces_par(pagina_a, pagina_b, nombre_provincia(provincia), sin_cne=sin_cne)


class PaginaRevisada(BaseModel):
    nombre: str
    page_id: Optional[str] = None


class RevisionEntrada(BaseModel):
    alcance: str                              # «mensaje» (solo ese texto entre esas páginas) o «paginas» (cualquier mensaje repetido entre ellas)
    paginas: List[PaginaRevisada]
    huellas: Optional[List[str]] = None       # los textos revisados (campo «huellas» del grupo); obligatorio con alcance «mensaje»
    ejemplo: Optional[str] = None
    motivo: str
    nota: Optional[str] = None


class QuitarRevisionEntrada(BaseModel):
    id: str


@app.post("/api/ads/mensajes-revisados")
def guardar_revision_meta(entrada: RevisionEntrada, request: Request):
    """Marca un grupo de mensajes repetidos como revisado (esperable) y lo guarda en backend/mensajes_revisados.json."""
    if not _puede_editar_afiliaciones(request):
        raise HTTPException(status_code=403, detail="No tienes permiso para marcar mensajes como revisados desde aquí (solo el equipo del servidor, o con el código de edición).")
    try:
        return unified_service.ads_library.guardar_revision(entrada.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ads/mensajes-revisados/quitar")
def quitar_revision_meta(entrada: QuitarRevisionEntrada, request: Request):
    """Quita una revisión: los grupos que cubría vuelven a mostrarse como señal."""
    if not _puede_editar_afiliaciones(request):
        raise HTTPException(status_code=403, detail="No tienes permiso para quitar revisiones desde aquí (solo el equipo del servidor, o con el código de edición).")
    try:
        return unified_service.ads_library.quitar_revision(entrada.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/noticias")
def obtener_noticias_y_tweets_por_provincia(
    provincia: str = Query(
        ...,
        description="Nombre de la provincia de Ecuador a consultar (ej: Pichincha, Guayas, Azuay)"
    ),
    seccion: str = Query(
        None,
        description="Sección a consultar bajo demanda (noticias, verificaciones, tweets, bluesky, youtube, reddit, meta_ads)"
    )
):
    """
    `GET /api/noticias?provincia={nombre}&seccion={seccion}`.
    Cada respuesta incluye `estados`: por sección, si está configurada, si respondió bien y un mensaje
    cuando no hay resultados. Nunca contiene datos simulados.
    """
    if not provincia or not provincia.strip():
        raise HTTPException(status_code=400, detail="El parámetro 'provincia' es obligatorio.")

    provincia_limpia = nombre_provincia(provincia) or provincia.strip()

    try:
        if seccion:
            return unified_service.obtener_feed_por_seccion(provincia_limpia, seccion)
        return unified_service.obtener_feed_completo(provincia_limpia)
    except Exception as e:
        return {
            "provincia": provincia_limpia,
            "tiempo_real": [],
            "verificaciones": [],
            "tweets_recientes": [],
            "bluesky_posts": [],
            "youtube_videos": [],
            "reddit_posts": [],
            "meta_ads": [],
            "estados": {},
            "error": True,
            "mensaje": f"Error obteniendo datos para {provincia_limpia} ({type(e).__name__})."
        }


# =============================================================================
# DASHBOARD
# =============================================================================
@app.get("/api/dashboard/stats")
def obtener_estadisticas_dashboard(provincia: Optional[str] = Query(None)):
    """
    Métricas del dashboard, todas calculadas con datos reales.
    - Provincia: conteo por fuente + resumen de anuncios de Meta con alcance en esa provincia.
    - Nacional: resumen de anuncios políticos de Meta y alcance estimado por provincia
      (las demás fuentes se consultan por provincia, no a nivel nacional).
    """
    nombre = nombre_provincia(provincia)
    ads = unified_service.ads_library
    ahora = datetime.now().isoformat(timespec="seconds")

    if nombre and _SOLO_LECTURA:
        # Despliegue público: sin consultas en vivo a noticias, Bluesky ni YouTube (gastan el tiempo de la función en cada visita).
        # Solo el resumen de anuncios de Meta, que sale de la copia incluida.
        gasto = ads.top_gastadores(nombre, 1)
        r = gasto.get("resumen") or {}
        n = html.escape(nombre)
        resumen = (
            f"En <strong>{n}</strong> hay <span class='summary-highlight'>{r['anuncios']} anuncios políticos de Meta</span> con alcance en la provincia, "
            f"de <strong>{r.get('anunciantes', 0)} anunciantes</strong>."
            if r.get("anuncios") else f"No hay anuncios políticos de Meta con alcance en <strong>{n}</strong> para los filtros elegidos."
        )
        return {
            "provincia": nombre,
            "alcance": "provincia",
            "datos_demostrativos": False,
            "total_publicaciones": r.get("anuncios", 0),
            "distribucion_fuentes": {"meta_ads": r.get("anuncios", 0)},
            "estados": {"meta_ads": gasto.get("estado") or {}},
            "resumen_anuncios": r or None,
            "resumen_general": resumen,
            "timestamp": ahora,
        }

    if nombre:
        feed = unified_service.obtener_feed_completo(nombre)
        cuentas = {
            "prensa_tiempo_real": len(feed["tiempo_real"]),
            "fact_checks": len(feed["verificaciones"]),
            "redes_sociales_x": len(feed["tweets_recientes"]),
            "bluesky_feed": len(feed["bluesky_posts"]),
            "youtube_videos": len(feed["youtube_videos"]),
            "meta_ads": len(feed["meta_ads"]),
        }
        total = sum(cuentas.values())
        gasto = ads.top_gastadores(nombre, 1)
        r = gasto.get("resumen") or {}
        n = html.escape(nombre)
        resumen = (
            f"En <strong>{n}</strong> se encontraron <span class='summary-highlight'>{total} publicaciones</span> "
            f"en las fuentes consultadas: {cuentas['prensa_tiempo_real']} noticias, {cuentas['fact_checks']} verificaciones, "
            + (f"{cuentas['redes_sociales_x']} de X, " if unified_service.x_client.configurado else "")
            + f"{cuentas['bluesky_feed']} de Bluesky, {cuentas['youtube_videos']} videos de YouTube y {cuentas['meta_ads']} anuncios políticos de Meta"
            + (f" (de {r['anuncios']} con alcance en la provincia)." if r.get("anuncios") else ".")
        )
        return {
            "provincia": nombre,
            "alcance": "provincia",
            "datos_demostrativos": False,
            "total_publicaciones": total,
            "distribucion_fuentes": cuentas,
            "estados": feed.get("estados", {}),
            "resumen_anuncios": r or None,
            "resumen_general": resumen,
            "timestamp": ahora,
        }

    # Nacional: solo se resume lo que existe a nivel nacional (anuncios de Meta)
    gasto = ads.top_gastadores(None, 1)
    estado = gasto.get("estado") or {}
    r = gasto.get("resumen")
    por_provincia = ads.alcance_por_provincia()
    top = por_provincia[:6]
    resto = por_provincia[6:]
    if resto:
        top.append({
            "provincia": "Otras provincias",
            "impresiones": sum(f["impresiones"] for f in resto),
            "anuncios": sum(f["anuncios"] for f in resto),
            "porcentaje": round(sum(f["porcentaje"] for f in resto), 1),
        })

    if r:
        resumen = (
            f"Se analizaron <span class='summary-highlight'>{r['anuncios']} anuncios políticos</span> de "
            f"<strong>{r['anunciantes']} anunciantes</strong> en la Biblioteca de Anuncios de Meta, con una inversión estimada de "
            f"<strong>USD {miles(r['gasto_medio_total'])}</strong> y unas {miles(r['impresiones_medias_total'])} impresiones. "
            "Meta publica rangos, no cifras exactas. Selecciona una provincia para ver noticias, verificaciones, Bluesky y YouTube."
        )
    else:
        resumen = html.escape(estado.get("mensaje") or "No hay datos de anuncios disponibles.")

    return {
        "provincia": "Ecuador (Todas)",
        "alcance": "nacional",
        "datos_demostrativos": False,
        "total_publicaciones": r["anuncios"] if r else 0,
        "distribucion_fuentes": None,
        "top_provincias_cobertura": [
            {"provincia": f["provincia"], "publicaciones": f["anuncios"], "impresiones": f["impresiones"], "porcentaje": f["porcentaje"]}
            for f in top
        ],
        "estados": {"meta_ads": estado},
        "resumen_anuncios": r,
        "resumen_general": resumen,
        "timestamp": ahora,
    }


STOP_WORDS = {
    "que", "las", "los", "por", "para", "con", "del", "una", "uno", "como", "mas", "más",
    "sus", "este", "esta", "estos", "estas", "sobre", "entre", "hasta", "desde", "cada",
    "todo", "toda", "todos", "todas", "pero", "sino", "donde", "cuando", "quien", "quienes",
    "bien", "hace", "hacen", "hacer", "ser", "sido", "estar", "está", "están",
    "hubo", "hay", "tiene", "tienen", "tenía", "dijo", "dicen", "decir", "ante", "tras",
    "sin", "año", "años", "2026", "2027", "2025", "2024", "ecuador", "elecciones", "noticias",
    "provincia", "tiempo", "real", "también", "según", "será", "serán", "puede", "pueden",
}


def extraer_palabras_tendencia_reales() -> List[Dict[str, Any]]:
    """Palabras más repetidas en los titulares nacionales actuales. Solo cuentan las que aparecen 2 o más veces."""
    try:
        noticias = unified_service.obtener_noticias_reales("Ecuador")
    except Exception as e:
        print(f"Error generando tendencias: {type(e).__name__}")
        return []
    textos = " ".join(n.get("titulo", "") for n in noticias)
    tokens = re.findall(r'\b[a-zA-ZáéíóúñÁÉÍÓÚÑ]{4,}\b', textos)
    conteo = Counter(t.capitalize() for t in tokens if t.lower() not in STOP_WORDS)
    return [{"word": w, "count": c} for w, c in conteo.most_common(8) if c >= 2]


@app.get("/api/dashboard/keywords")
def obtener_analisis_palabras_clave(q: Optional[str] = Query(None), provincia: Optional[str] = Query(None)):
    """
    Buscador de palabras clave. Solo cuenta coincidencias reales del término (sin tildes, palabra completa) en:
    titulares de prensa, verificaciones de Google Fact Check y texto de anuncios políticos de Meta ya descargados.
    X, Bluesky, YouTube y Reddit no se consultan aquí (se consultan por provincia).
    """
    tendencias = extraer_palabras_tendencia_reales()
    termino = q.strip() if (q and isinstance(q, str)) else ""
    if not termino:
        return {"trending_keywords": tendencias, "analisis": None}

    patron = re.compile(r"\b" + re.escape(_norm(termino)) + r"\b")
    seguro = html.escape(termino)

    prensa = [n for n in unified_service.obtener_noticias_reales(termino)
              if patron.search(_norm(n.get("titulo", "") + " " + n.get("fuente", "")))]
    facts = [f for f in unified_service.obtener_verificaciones_con_rating(termino)
             if patron.search(_norm(f.get("text", "") + " " + f.get("title", "") + " " + f.get("claimant", "")))]
    meta = unified_service.ads_library.buscar_texto(termino)

    relacionados = (
        [{"tipo": "Prensa", "titulo": n["titulo"], "fuente": n.get("fuente", ""), "link": n.get("url", ""), "fecha": n.get("fecha", "")}
         for n in prensa[:5]]
        + [{"tipo": "Verificación", "titulo": f.get("title") or f.get("text", ""), "fuente": f.get("publisher", ""),
            "link": f.get("url", ""), "fecha": f.get("reviewDate", "")} for f in facts[:3]]
        + [{"tipo": "Anuncio Meta", "titulo": (a["text"] or "(sin texto)")[:160], "fuente": a["page_name"],
            "link": a["link"], "fecha": a["date"]} for a in meta["anuncios"][:3]]
    )
    total = len(prensa) + len(facts) + meta["total"]
    en_tendencia = next((t for t in tendencias if t["word"].lower() == termino.lower()), None)

    if total == 0:
        resumen = (f"No se encontraron menciones de '<strong>{seguro}</strong>' en los titulares de prensa, verificaciones "
                   "ni anuncios de Meta consultados.")
    else:
        resumen = (f"'<strong>{seguro}</strong>' aparece en <span class='summary-highlight'>{total} resultado(s)</span>: "
                   f"{len(prensa)} titulares de prensa, {len(facts)} verificaciones y {meta['total']} anuncios de Meta"
                   + (f" ({meta['paginas']} páginas, inversión estimada USD {miles(meta['gasto_medio'])})" if meta["total"] else "")
                   + ".")

    return {
        "trending_keywords": tendencias,
        "analisis": {
            "palabra": termino,
            "menciones_totales": total,
            "frecuencia_en_titulares": en_tendencia["count"] if en_tendencia else None,
            "distribucion": {"prensa": len(prensa), "fact_check": len(facts), "meta": meta["total"], "x_twitter": None, "bluesky": None},
            "fuentes_consultadas": ["Titulares de prensa (GNews / Google News / CNE)", "Google Fact Check", "Texto de anuncios políticos de Meta"],
            "fuentes_no_consultadas": ["X", "Bluesky", "YouTube", "Reddit"],
            "resumen_analisis": resumen,
            "relacionados": relacionados,
        }
    }


# Servir frontend estático si existe
_DIR_RAIZ = os.path.dirname(_DIR_ACTUAL)
_FRONTEND_DIR = os.path.join(_DIR_RAIZ, "frontend")
_PUBLIC_DIR = os.path.join(_DIR_RAIZ, "public")
_static_dir = _PUBLIC_DIR if os.path.isdir(_PUBLIC_DIR) else (_FRONTEND_DIR if os.path.isdir(_FRONTEND_DIR) else None)
if _static_dir:
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    print(f"Iniciando NoAIVerdad Backend en http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)
