import json
import os
import re
import requests
import logging
import xml.etree.ElementTree as ET
import unicodedata
import time
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Tuple
import firebase_store
from ads_library import AdLibraryClient
from x_service import XClient

# Configurar logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _anio_de_fecha(value: str) -> str:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
    return match.group(1) if match else ""


def _texto_normalizado(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(char for char in value if unicodedata.category(char) != "Mn")


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _fecha_a_datetime(valor: Any) -> datetime:
    """Convierte fechas RFC 2822 (RSS) o ISO 8601 a datetime con zona; las ilegibles quedan al final al ordenar."""
    texto = str(valor or "").strip()
    if not texto:
        return _EPOCH
    try:
        dt = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            return _EPOCH
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _limpiar_titulo(titulo: str, fuente: str) -> str:
    """Google News añade ' - Medio' al final del título; se quita porque la fuente ya se muestra aparte."""
    if fuente and titulo.endswith(f" - {fuente}"):
        return titulo[: -len(fuente) - 3].strip()
    return titulo.strip()


def _con_cache(nombre: str, ttl: int = 600):
    """Cachea (10 min por defecto) el resultado de una fuente por provincia/término para cuidar las cuotas de las APIs."""
    def decorador(fn):
        def envoltura(self, provincia: str):
            clave = (nombre, str(provincia).strip().lower())
            hit = self._cache_fuentes.get(clave)
            ahora = time.time()
            if hit and ahora - hit[0] < ttl:
                return hit[1]
            resultado = fn(self, provincia)
            if resultado:  # no se cachean resultados vacíos: así se reintenta pronto
                self._cache_fuentes[clave] = (ahora, resultado)
            return resultado
        envoltura.__name__ = fn.__name__
        envoltura.__doc__ = fn.__doc__
        return envoltura
    return decorador


# Medios locales por provincia (backend/medios_locales.json): alimentan la pestaña «Prensa local» del Mapa.
RUTA_MEDIOS_LOCALES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "medios_locales.json")
_MEDIOS_LOCALES_CACHE: Dict[str, Any] = {"mtime": None, "datos": {}}
_QUERY_ELECTORAL = "(elecciones OR candidato OR candidata OR candidatura OR alcaldía OR prefectura OR concejal OR campaña OR CNE)"
_UA_NAVEGADOR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def _medios_locales(provincia: str) -> List[Dict[str, Any]]:
    """Medios registrados para una provincia (se relee el archivo si cambia); lista vacía si no hay o no se puede leer."""
    try:
        mtime = os.path.getmtime(RUTA_MEDIOS_LOCALES)
        if _MEDIOS_LOCALES_CACHE["mtime"] != mtime:
            with open(RUTA_MEDIOS_LOCALES, encoding="utf-8") as f:
                _MEDIOS_LOCALES_CACHE.update(mtime=mtime, datos=json.load(f).get("provincias", {}))
    except (OSError, ValueError):
        return []
    por_nombre = {_texto_normalizado(k): v for k, v in _MEDIOS_LOCALES_CACHE["datos"].items()}
    return list(por_nombre.get(_texto_normalizado(provincia), []))


_ELECTORAL_ESTRICTO = re.compile(r"(?<![a-z0-9])(eleccion\w*|electoral\w*|candidat\w+|precandidat\w+|alcald\w+|prefect\w+|concejal\w*|campana|cne|voto|votar|votacion|sufragio|seccional\w*|urna\w*|papeleta\w*)(?![a-z0-9])")


def _es_electoral_estricto(texto: str) -> bool:  # noqa: D401
    """Más estricto que TERMINOS_ELECTORALES (que incluye «política», «seguridad»…): para canales RSS de medios que publican de todo, incluso noticias internacionales."""
    return bool(_ELECTORAL_ESTRICTO.search(_texto_normalizado(texto)))


_EXTRANJERO = re.compile(r"(?<![a-z0-9])(estados unidos|ee ?uu|trump|alaska|paraguay|venezuela|espana|mexico|colombia|peru|argentina|chile|brasil|bolivia|honduras|nicaragua|cuba|israel|gaza|ucrania|rusia|china|europa|texas|california|florida)(?![a-z0-9])")


def _es_electoral_local(texto: str) -> bool:
    """Electoral (estricto) y que no trate de otro país salvo que nombre a Ecuador: los medios locales también publican elecciones y política internacionales."""
    t = _texto_normalizado(texto)
    if not _ELECTORAL_ESTRICTO.search(t):
        return False
    return not (_EXTRANJERO.search(t) and "ecuador" not in t)


def _menciona_localidad(texto: str, localidades: List[str]) -> bool:
    """¿El texto nombra alguna de las localidades (sin tildes ni mayúsculas, como palabra completa)? Sin lista, siempre sí."""
    if not localidades:
        return True
    t = _texto_normalizado(texto)
    return any(re.search(r"(?<![a-z0-9])" + re.escape(_texto_normalizado(loc)) + r"(?![a-z0-9])", t) for loc in localidades)


PROVINCIA_LOCALIDADES = {
    "Azuay": ["Azuay", "Cuenca", "Gualaceo"],
    "Bolívar": ["Bolívar Ecuador", "Guaranda", "San Miguel Bolívar"],
    "Cañar": ["Cañar", "Azogues", "La Troncal"],
    "Carchi": ["Carchi", "Tulcán", "Montúfar"],
    "Chimborazo": ["Chimborazo", "Riobamba", "Alausí"],
    "Cotopaxi": ["Cotopaxi", "Latacunga", "La Maná"],
    "El Oro": ["El Oro Ecuador", "Machala", "Santa Rosa El Oro"],
    "Esmeraldas": ["Esmeraldas Ecuador", "Quinindé", "Atacames"],
    "Galápagos": ["Galápagos", "Puerto Ayora", "San Cristóbal Galápagos"],
    "Guayas": ["Guayas", "Guayaquil", "Durán"],
    "Imbabura": ["Imbabura", "Ibarra", "Otavalo"],
    "Loja": ["Loja Ecuador", "Catamayo", "Macará"],
    "Los Ríos": ["Los Ríos Ecuador", "Babahoyo", "Quevedo"],
    "Manabí": ["Manabí", "Portoviejo", "Manta"],
    "Morona Santiago": ["Morona Santiago", "Macas", "Gualaquiza"],
    "Napo": ["Napo Ecuador", "Tena", "Archidona"],
    "Orellana": ["Orellana Ecuador", "El Coca", "Francisco de Orellana"],
    "Pastaza": ["Pastaza Ecuador", "Puyo", "Mera"],
    "Pichincha": ["Pichincha", "Quito", "Cayambe"],
    "Santa Elena": ["Santa Elena Ecuador", "Salinas", "La Libertad Ecuador"],
    "Santo Domingo de los Tsáchilas": ["Santo Domingo Ecuador", "Santo Domingo de los Tsáchilas", "La Concordia"],
    "Sucumbíos": ["Sucumbíos", "Lago Agrio", "Nueva Loja"],
    "Tungurahua": ["Tungurahua", "Ambato", "Baños Ecuador"],
    "Zamora Chinchipe": ["Zamora Chinchipe", "Zamora Ecuador", "Yantzaza"],
}
TERMINOS_ELECTORALES = [
    "elecciones", "elección", "electoral", "CNE", "votación", "voto", "votar",
    "sufragio", "candidato", "candidata", "candidatos", "candidatas",
    "candidatura", "campaña", "presidencial", "consulta popular", "referéndum",
    "escrutinio", "papeleta", "urna", "segunda vuelta", "precandidato",
    "precandidata", "Consejo Nacional Electoral", "elecciones 2027", "política",
    "político", "presidente de Ecuador", "gobierno de Ecuador", "Asamblea Nacional",
    "asambleísta", "alcalde", "prefecto", "Noboa", "reforma", "seguridad",
]

class UnifiedFeedService:
    """
    Servicio unificado que consulta de manera concurrente fuentes REALES:
    prensa (GNews, Google News y CNE), verificaciones (Google Fact Check), Bluesky público, YouTube (RSS de
    canales ecuatorianos), Reddit (RSS público), anuncios políticos de Meta (Biblioteca de Anuncios) y, si hay
    financiamiento, X (API oficial).

    Si una fuente no está configurada o no devuelve resultados, entrega una lista vacía y un estado explicativo en
    `estados`. Nunca inventa contenido.
    """

    GNEWS_URL = "https://gnews.io/api/v4/search"
    FACT_CHECK_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

    # sección -> campo de la respuesta
    CAMPOS = {
        "noticias": "tiempo_real",
        "verificaciones": "verificaciones",
        "tweets": "tweets_recientes",
        "bluesky": "bluesky_posts",
        "youtube": "youtube_videos",
        "reddit": "reddit_posts",
        "meta_ads": "meta_ads",
        "prensa_local": "prensa_local",
    }
    # Reddit se consulta solo bajo demanda: no se pregunta por las 24 provincias en cada ciclo de recolección.
    SECCIONES_FEED_COMPLETO = ("noticias", "verificaciones", "tweets", "bluesky", "youtube", "meta_ads")

    def __init__(self):
        self.gnews_api_key = ""
        self.fact_check_api_key = ""
        self.bluesky_handle = ""
        self.bluesky_app_password = ""
        self._reddit_rss_cache = {}
        self._reddit_rss_lock = threading.Lock()
        self._youtube_channel_cache = {}
        self._youtube_cache_expiry = 0
        self._cache_fuentes: Dict[tuple, tuple] = {}
        self.ads_library = AdLibraryClient()
        self.x_client = XClient()
        self.reload_api_keys()
        self.scraper = None

    # --- Interruptores heredados (los usa el colector) -------------------------------------------
    @property
    def META_INTEGRATION_ENABLED(self) -> bool:
        return self.ads_library.habilitado

    @property
    def meta_api_enabled(self) -> bool:
        return self.ads_library.configurado

    @property
    def x_api_enabled(self) -> bool:
        return self.x_client.configurado

    @staticmethod
    def _clave(keys: Dict[str, str], nombre: str) -> str:
        """El entorno local (.env.local) tiene prioridad; si no hay, se usa la clave guardada en Firebase."""
        return os.getenv(nombre, "").strip() or keys.get(nombre, "")

    def reload_api_keys(self) -> Dict[str, bool]:
        """Recarga las credenciales: entorno local primero, Firebase (/config/api_keys) después. Nunca llegan al frontend."""
        keys = firebase_store.get_api_keys()
        self.gnews_api_key = self._clave(keys, "GNEWS_API_KEY")
        self.fact_check_api_key = self._clave(keys, "GOOGLE_FACT_CHECK_API_KEY")
        self.bluesky_handle = self._clave(keys, "BLUESKY_HANDLE")
        self.bluesky_app_password = self._clave(keys, "BLUESKY_APP_PASSWORD")
        if hasattr(self, "ads_library"):
            self.ads_library.reload_token(force=True)
        disponibles = {name: bool(value) for name, value in keys.items()}
        disponibles["GNEWS_API_KEY"] = bool(self.gnews_api_key)
        disponibles["GOOGLE_FACT_CHECK_API_KEY"] = bool(self.fact_check_api_key)
        return disponibles

    # ------------------------------------------------------------------
    # Feed por sección / completo
    # ------------------------------------------------------------------
    def _estado_lista(self, items: list, configurado: bool, vacio: str) -> Dict[str, Any]:
        estado = {"configurado": configurado, "ok": configurado, "total": len(items),
                  "mensaje": "" if items else vacio}
        if items and all((i.get("ambito") or i.get("alcance")) == "nacional" for i in items):
            estado["aviso"] = "No hay resultados específicos de esta provincia; se muestran resultados a nivel nacional."
        return estado

    def _cargar(self, provincia: str, seccion: str) -> Tuple[list, Dict[str, Any]]:
        """Descarga una sección y devuelve (items, estado)."""
        if seccion == "noticias":
            items = self.obtener_noticias_reales(provincia)
            return items, self._estado_lista(items, True, "No se encontraron noticias recientes para esta provincia en GNews, Google News ni el CNE.")
        if seccion == "prensa_local":
            medios = _medios_locales(provincia)
            if not medios:
                return [], {"configurado": False, "ok": False, "total": 0,
                            "mensaje": "Aún no hay medios locales registrados para esta provincia (se pueden añadir en backend/medios_locales.json). "
                                       "La pestaña «Prensa» sí incluye cobertura nacional sobre ella."}
            items = self.obtener_prensa_local(provincia)
            estado = self._estado_lista(items, True, "Los medios locales registrados no publicaron notas electorales recientes (últimos 90 días) que se pudieran leer.")
            nombres = ", ".join(dict.fromkeys(m["medio"] for m in medios))
            estado["aviso"] = (f"Medios locales consultados: {nombres}. Se muestran sus notas electorales de los últimos 90 días (por su canal RSS y por Google News); "
                               "no se leen medios sin sitio web ni lo que solo publican en redes sociales.")
            return items, estado
        if seccion == "verificaciones":
            if not self.fact_check_api_key:
                return [], {"configurado": False, "ok": False, "total": 0,
                            "mensaje": "Falta GOOGLE_FACT_CHECK_API_KEY (en backend/.env.local o en Firebase /config/api_keys) para ver verificaciones."}
            items = self.obtener_verificaciones_con_rating(provincia)
            estado = self._estado_lista(items, True, "Google Fact Check no tiene revisiones que coincidan con esta provincia.")
            if items:
                estado["aviso"] = ("Cobertura parcial: se buscan por palabras clave (provincia + elecciones) en Google Fact Check, que solo indexa las "
                                   "verificaciones que los medios marcan con formato ClaimReview. Pocos resultados no significan que no existan más.")
            return items, estado
        if seccion == "tweets":
            if not self.x_client.configurado:
                return [], {"configurado": False, "ok": False, "total": 0,
                            "mensaje": "X está desactivado: la API oficial es de pago y aún no hay financiamiento."}
            return self.x_client.buscar(provincia)
        if seccion == "bluesky":
            items = self.obtener_posts_bluesky(provincia)
            return items, self._estado_lista(items, True, "Bluesky no devolvió publicaciones electorales que mencionen esta provincia.")
        if seccion == "youtube":
            items = self.obtener_videos_youtube(provincia)
            estado = self._estado_lista(items, True, "No hay videos electorales recientes en los canales ecuatorianos monitoreados.")
            if items:
                estado["aviso"] = "Videos electorales recientes de canales ecuatorianos (Ecuavisa, Teleamazonas, Primicias, TC y Ecuador TV). Son canales nacionales: no se filtran por provincia."
            return items, estado
        if seccion == "reddit":
            items = self.obtener_posts_reddit(provincia)
            return items, self._estado_lista(items, True, "Reddit no devolvió conversaciones públicas electorales sobre esta provincia.")
        if seccion == "meta_ads":
            return self.obtener_anuncios_meta_con_estado(provincia)
        raise ValueError(f"Sección desconocida: {seccion}")

    def _respuesta_vacia(self, provincia: str) -> Dict[str, Any]:
        res: Dict[str, Any] = {"provincia": provincia, "meta_estado": None, "estados": {}}
        for campo in self.CAMPOS.values():
            res[campo] = []
        return res

    def obtener_feed_por_seccion(self, provincia: str, seccion: str) -> Dict[str, Any]:
        """Obtiene únicamente la sección solicitada (noticias, verificaciones, tweets, bluesky, youtube, reddit, meta_ads)."""
        seccion_lower = (seccion or "").lower().strip()
        if seccion_lower not in self.CAMPOS:
            return self.obtener_feed_completo(provincia)

        res = self._respuesta_vacia(provincia)
        items, estado = self._cargar(provincia, seccion_lower)
        res[self.CAMPOS[seccion_lower]] = items
        res["estados"][seccion_lower] = estado
        res["meta_estado"] = estado if seccion_lower == "meta_ads" else None
        return res

    def obtener_feed_completo(self, provincia: str) -> Dict[str, Any]:
        """Consulta en paralelo todas las secciones salvo Reddit (que se pide bajo demanda)."""
        res = self._respuesta_vacia(provincia)
        with ThreadPoolExecutor(max_workers=len(self.SECCIONES_FEED_COMPLETO)) as executor:
            futuros = {s: executor.submit(self._cargar, provincia, s) for s in self.SECCIONES_FEED_COMPLETO}
            for seccion, futuro in futuros.items():
                try:
                    items, estado = futuro.result()
                except Exception as e:
                    logger.error("[Feed] Error en sección '%s': %s", seccion, type(e).__name__)
                    items, estado = [], {"configurado": True, "ok": False, "mensaje": "Error inesperado al consultar esta fuente."}
                res[self.CAMPOS[seccion]] = items
                res["estados"][seccion] = estado
        res["estados"]["reddit"] = {"configurado": True, "ok": True, "total": 0, "omitido": True,
                                    "mensaje": "Reddit se consulta bajo demanda."}
        res["meta_estado"] = res["estados"].get("meta_ads")
        return res

    def obtener_videos_youtube(self, provincia: str) -> List[Dict[str, Any]]:
        """Collect recent election-related uploads from major Ecuadorian news channels via public YouTube RSS."""
        channels = {
            "Ecuavisa": "UCRUV3nUNSc-xpBrTwQOCQQg",
            "Teleamazonas": "UCCwRtme3lumNRQXMO2EvCvw",
            "Primicias": "UCe6Gi8_PZp9gcEZb5hTCPdQ",
            "TC Televisión": "UCMDsWeFwRQ5BRzNLFzpc-ew",
            "Ecuador TV": "UCfXVS_zw_XmAx8iIiia1IkA",
        }
        now = time.time()
        if now >= self._youtube_cache_expiry:
            videos = []
            headers = {"User-Agent": "Mozilla/5.0 (compatible; NoAIVerdad/1.0)"}
            for name, channel_id in channels.items():
                try:
                    feed = requests.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}, headers=headers, timeout=8)
                    feed.raise_for_status()
                    root = ET.fromstring(feed.content)
                    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
                    for entry in root.findall("atom:entry", ns):
                        title = entry.findtext("atom:title", "", ns)
                        video_id = entry.findtext("yt:videoId", "", ns)
                        published = entry.findtext("atom:published", "", ns)
                        if not video_id:
                            continue
                        videos.append({"titulo": title, "url": f"https://www.youtube.com/watch?v={video_id}", "fecha": published, "fuente": name, "canal": name, "anio": _anio_de_fecha(published)})
                except Exception as exc:
                    logger.info("[YouTube RSS] No se pudo consultar %s: %s", name, exc)
            self._youtube_channel_cache = videos
            # No guardar el vacío como si fuera válido durante 15 minutos: un
            # bloqueo temporal de RSS no debe ocultar videos provinciales.
            self._youtube_cache_expiry = now + (900 if videos else 30)
        # Los canales publican de todo: solo se devuelven los videos cuyo título trata temas electorales.
        return [v for v in self._youtube_channel_cache if self._es_electoral(v.get("titulo", ""))]

    @staticmethod
    def _es_electoral(texto: str) -> bool:
        t = _texto_normalizado(texto)
        return any(
            re.search(r"(?<![a-z0-9])" + re.escape(_texto_normalizado(termino)) + r"(?![a-z0-9])", t)
            for termino in TERMINOS_ELECTORALES
        )

    def obtener_posts_reddit(self, provincia: str) -> List[Dict[str, Any]]:
        """Busca conversaciones públicas de Reddit con consultas locales amplias."""
        provincia = str(provincia or "").strip()
        if not provincia:
            return []

        cache_key = _texto_normalizado(provincia)
        now = time.time()
        with self._reddit_rss_lock:
            cached = self._reddit_rss_cache.get(cache_key)
            if cached and cached["expires_at"] > now:
                return list(cached["posts"])

        localidades = next(
            (values for nombre, values in PROVINCIA_LOCALIDADES.items()
             if _texto_normalizado(nombre) == cache_key),
            [provincia],
        )
        # Reddit RSS puede interpretar de forma restrictiva comillas, OR y
        # paréntesis. Usar frases sencillas mejora la cobertura y además
        # permite incluir asuntos electorales discutidos sin nombrar la ciudad
        # en el título. La provincia se conserva como foco de búsqueda.
        consultas = list(dict.fromkeys(
            f"{localidad} {tema}"
            for localidad in localidades
            for tema in (
                "elecciones Ecuador", "politica Ecuador", "CNE Ecuador",
                "candidatos Ecuador", "presidente Ecuador",
            )
        ))
        consultas.extend([
            f"elecciones Ecuador {provincia}",
            f"elecciones Ecuador {provincia} 2027",
            f"politica ecuatoriana {provincia}",
        ])
        consultas = list(dict.fromkeys(consultas))
        headers = {
            "User-Agent": "NoAIVerdad/1.0 (public Reddit RSS reader)",
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml",
        }
        posts_por_url = {}
        election_terms = [
            "eleccion", "electoral", "cne", "candidat", "campan", "vot",
            "sufrag", "urna", "papeleta", "prefect", "alcald", "concej",
            "politic", "president", "noboa", "asamblea", "referendum",
            "consulta popular", "escrutinio", "debate electoral",
        ]
        def buscar_rss(query: str):
            try:
                response = requests.get(
                    "https://www.reddit.com/search.rss",
                    params={"q": query, "sort": "new", "limit": 100},
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()
                root = ET.fromstring(response.content)
                namespace = "{http://www.w3.org/2005/Atom}"
                encontrados = []
                for entry in root.findall(f"{namespace}entry"):
                    title_node = entry.find(f"{namespace}title")
                    link_node = entry.find(f"{namespace}link")
                    date_node = entry.find(f"{namespace}updated")
                    if date_node is None:
                        date_node = entry.find(f"{namespace}published")
                    summary_node = entry.find(f"{namespace}content")
                    if summary_node is None:
                        summary_node = entry.find(f"{namespace}summary")
                    titulo = (title_node.text or "").strip() if title_node is not None else ""
                    url = link_node.get("href", "") if link_node is not None else ""
                    fecha = (date_node.text or "").strip() if date_node is not None else ""
                    summary = (summary_node.text or "").strip() if summary_node is not None else ""
                    if not titulo or not url or urlparse(url).hostname not in {"reddit.com", "www.reddit.com", "old.reddit.com"}:
                        continue
                    normalized_text = _texto_normalizado(f"{titulo} {summary}")
                    if not any(term in normalized_text for term in election_terms):
                        continue
                    categories = entry.findall(f"{namespace}category")
                    subreddit = next((item.get("term", "") for item in categories if item.get("term", "").startswith("r/")), "Reddit")
                    clean_summary = re.sub(r"<[^>]*>", " ", summary)
                    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()
                    encontrados.append({
                        "titulo": titulo,
                        "text": clean_summary,
                        "url": url,
                        "fecha": fecha,
                        "fuente": subreddit,
                        "anio": _anio_de_fecha(fecha),
                        "alcance": "provincial",
                        "provincia": provincia,
                    })
                return encontrados
            except Exception as exc:
                logger.info("[Reddit RSS] Falló consulta '%s': %s", query, exc)
                return []

        with ThreadPoolExecutor(max_workers=8) as executor:
            for encontrados in executor.map(buscar_rss, consultas):
                for post in encontrados:
                    posts_por_url.setdefault(post["url"], post)

        posts = sorted(posts_por_url.values(), key=lambda post: post.get("fecha", ""), reverse=True)[:100]
        with self._reddit_rss_lock:
            self._reddit_rss_cache[cache_key] = {
                "posts": posts,
                "expires_at": time.time() + (600 if posts else 60),
            }
        logger.info("[Reddit RSS] %s publicaciones públicas electorales para %s.", len(posts), provincia)
        return posts

    # =========================================================================
    # 1. NOTICIAS EN TIEMPO REAL (GNews API + Google News RSS en vivo)
    # =========================================================================
    @_con_cache("noticias")
    def obtener_noticias_reales(self, provincia: str) -> List[Dict[str, Any]]:
        noticias = []

        # Intento A: GNews API si existe clave configurada
        if self.gnews_api_key:
            try:
                query = f"elecciones {provincia} Ecuador"
                params = {
                    "q": query,
                    "lang": "es",
                    "country": "ec",
                    "max": 10,
                    "apikey": self.gnews_api_key
                }
                logger.info(f"[GNews API] Consultando noticias reales: '{query}'...")
                resp = requests.get(self.GNEWS_URL, params=params, timeout=7)
                if resp.status_code == 200:
                    articles = resp.json().get("articles", [])
                    for art in articles:
                        title = art.get("title")
                        url = art.get("url")
                        if not title or not url or url == "#":
                            continue
                        source_name = art.get("source", {}).get("name") or urlparse(url).hostname or ""
                        noticias.append({
                            "titulo": title,
                            "url": url,
                            "fecha": art.get("publishedAt", ""),
                            "fuente": source_name,
                            "anio": _anio_de_fecha(art.get("publishedAt", "")),
                        })
            except Exception as e:
                logger.error(f"[GNews API] Error: {e}")

        # Combinar GNews con búsquedas locales de Google News para ampliar la
        # cobertura y evitar que todas las provincias compartan los mismos 10 titulares.
        noticias.extend(self._obtener_google_news_rss(provincia))

        # Deduplicar fuentes combinadas sin descartar titulares antiguos válidos.
        merged = []
        seen = set()
        for item in noticias:
            identity = str(item.get("url") or item.get("titulo") or "").strip().lower()
            if identity and identity not in seen:
                seen.add(identity)
                merged.append(item)
        noticias = merged

        # El CNE es una fuente primaria y se añade a la prensa agregada.
        known_urls = {item.get("url") for item in noticias if item.get("url")}
        noticias.extend(item for item in self._obtener_cne_rss() if item.get("url") not in known_urls)

        for item in noticias:
            item["titulo"] = _limpiar_titulo(item.get("titulo", ""), item.get("fuente", ""))
        # Orden real por fecha (las fechas llegan en formatos distintos: RFC 2822 de RSS e ISO 8601 de GNews).
        noticias.sort(key=lambda n: _fecha_a_datetime(n.get("fecha")), reverse=True)
        return noticias

    @_con_cache("prensa_local")
    def obtener_prensa_local(self, provincia: str) -> List[Dict[str, Any]]:
        """Notas electorales de los medios locales de la provincia: Google News restringido a su sitio (`site:`) y, si lo tienen, su canal RSS."""
        medios = _medios_locales(provincia)
        headers = {"User-Agent": _UA_NAVEGADOR}

        def por_google_news(m: Dict[str, Any]) -> List[Dict[str, Any]]:
            q = f"{_QUERY_ELECTORAL} site:{m['sitio']} when:90d"
            try:
                resp = requests.get("https://news.google.com/rss/search", params={"q": q, "hl": "es-419", "gl": "EC", "ceid": "EC:es-419"}, headers=headers, timeout=9)
                resp.raise_for_status()
                out = []
                for item in ET.fromstring(resp.content).findall(".//item")[:50]:
                    titulo, link, fecha = item.findtext("title", ""), item.findtext("link", ""), item.findtext("pubDate", "")
                    fuente_gn = item.find("source").text if item.find("source") is not None else ""
                    if not titulo or not link or not _es_electoral_local(titulo) or not _menciona_localidad(titulo, m.get("localidades") or []):
                        continue
                    out.append({"titulo": _limpiar_titulo(_limpiar_titulo(titulo, fuente_gn), m["sitio"].split("/")[0]), "url": link, "fecha": fecha,
                                "fuente": m["medio"], "anio": _anio_de_fecha(fecha), "ambito": "local", "provincia": provincia})
                return out
            except Exception as exc:
                logger.info("[Prensa local] Google News falló para %s (%s): %s", m["medio"], provincia, exc)
                return []

        def por_rss(m: Dict[str, Any]) -> List[Dict[str, Any]]:
            """Canal RSS del medio y, si se indica «busquedas», el RSS de su buscador (WordPress: /?s=término&feed=rss2), que llega más atrás que el canal."""
            partes = urlparse(m["feed"])
            urls = [m["feed"]] + [f"{partes.scheme}://{partes.netloc}/?s={quote(t)}&feed=rss2" for t in m.get("busquedas") or []]

            def leer(url: str) -> List[Dict[str, Any]]:
                try:
                    resp = requests.get(url, headers={"User-Agent": "NoAIVerdad/1.0"}, timeout=8)
                    resp.raise_for_status()
                    salida = []
                    for item in ET.fromstring(resp.content).findall(".//item")[:60]:
                        titulo, link, fecha = item.findtext("title", ""), item.findtext("link", ""), item.findtext("pubDate", "")
                        resumen = re.sub(r"<[^>]+>", " ", item.findtext("description", "") or "")
                        texto = f"{titulo} {resumen}"
                        if titulo and link and _es_electoral_local(texto) and _menciona_localidad(texto, m.get("localidades") or []):
                            salida.append({"titulo": titulo.strip(), "url": link, "fecha": fecha, "fuente": m["medio"], "anio": _anio_de_fecha(fecha),
                                           "ambito": "local", "provincia": provincia})
                    return salida
                except Exception as exc:
                    logger.info("[Prensa local] RSS falló para %s (%s): %s", m["medio"], provincia, exc)
                    return []

            with ThreadPoolExecutor(max_workers=min(6, len(urls))) as ex:
                return [n for lista in ex.map(leer, urls) for n in lista]

        tareas = [(por_rss, m) for m in medios if m.get("feed")] + [(por_google_news, m) for m in medios if m.get("sitio") and m.get("gnews", True)]
        if not tareas:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(tareas))) as executor:
            resultados = list(executor.map(lambda t: t[0](t[1]), tareas))
        vistos, notas = set(), []
        for lista in resultados:                       # el RSS va primero: trae el enlace directo al medio, no el de Google News
            for n in lista:
                clave = _texto_normalizado(n["titulo"])[:90]
                if clave and clave not in vistos:
                    vistos.add(clave)
                    notas.append(n)
        notas.sort(key=lambda n: _fecha_a_datetime(n.get("fecha")), reverse=True)
        return notas[:60]

    def _obtener_cne_rss(self) -> List[Dict[str, Any]]:
        """Fetch official CNE newsroom posts through the site's WordPress RSS feed."""
        for rss_url in ("https://www.cne.gob.ec/category/noticias/feed/", "https://www.cne.gob.ec/feed/"):
            try:
                response = requests.get(rss_url, headers={"User-Agent": "NoAIVerdad/1.0"}, timeout=8)
                if response.status_code != 200:
                    continue
                root = ET.fromstring(response.content)
                result = []
                for item in root.findall(".//item")[:30]:
                    title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    pub_date = item.findtext("pubDate", "")
                    if title and link:
                        result.append({"titulo": title, "url": link, "fecha": pub_date, "fuente": "CNE Ecuador", "anio": _anio_de_fecha(pub_date)})
                if result:
                    return result
            except Exception as exc:
                logger.info("[CNE RSS] No se pudo consultar el feed: %s", exc)
        return []

    def _obtener_google_news_rss(self, provincia: str) -> List[Dict[str, Any]]:
        """Busca titulares electorales en las principales localidades provinciales."""
        localidades = PROVINCIA_LOCALIDADES.get(provincia, [provincia])
        queries = list(dict.fromkeys(
            query
            for localidad in localidades
            for query in (
                f"elecciones 2027 {localidad} Ecuador",
                f"elecciones {localidad} Ecuador",
                f"CNE {localidad} elecciones",
                f"candidatos {localidad} elecciones Ecuador",
            )
        ))
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

        def buscar(q: str):
            try:
                rss_url = "https://news.google.com/rss/search"
                logger.info("[Google News RSS] Consulta local %s: '%s'.", provincia, q)
                resp = requests.get(rss_url, params={"q": q, "hl": "es-419", "gl": "EC", "ceid": "EC:es-419"}, headers=headers, timeout=8)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                result = []
                for item in root.findall(".//item")[:10]:
                    title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    pub_date = item.findtext("pubDate", "")
                    source_elem = item.find("source")
                    fuente = source_elem.text if source_elem is not None else "Google News"
                    if title and link:
                        result.append({
                            "titulo": title, "url": link, "fecha": pub_date,
                            "fuente": fuente, "anio": _anio_de_fecha(pub_date),
                            "alcance": "provincial", "provincia": provincia,
                        })
                return result
            except Exception as e:
                logger.info("[Google News RSS] Falló '%s' para %s: %s", q, provincia, e)
                return []

        with ThreadPoolExecutor(max_workers=5) as executor:
            feeds = executor.map(buscar, queries)
            noticias_rss = [item for feed in feeds for item in feed]

        unique = {}
        for item in noticias_rss:
            identity = (item.get("titulo") or "").strip().casefold()
            if identity:
                unique.setdefault(identity, item)
        result = list(unique.values())
        result.sort(key=lambda item: item.get("fecha", ""), reverse=True)
        return result[:80]

    # =========================================================================
    # 2. INFORMACIÓN CÍVICA Y VERIFICACIONES (Google Fact Check Tools API)
    #    Incluye la clasificación original (textualRating) para advertencias en la UI.
    # =========================================================================
    @_con_cache("verificaciones")
    def obtener_verificaciones_con_rating(self, provincia: str) -> List[Dict[str, Any]]:
        """Revisiones reales de Google Fact Check. Sin API key devuelve lista vacía (nunca simula registros)."""
        if not self.fact_check_api_key:
            return []

        verificaciones: List[Dict[str, Any]] = []
        vistos = set()
        for q in [f"{provincia} elecciones Ecuador", f"Ecuador elecciones {provincia}", "Ecuador elecciones"]:
            ambito = "nacional" if q == "Ecuador elecciones" else "provincial"
            try:
                params = {"query": q, "languageCode": "es", "pageSize": 100, "key": self.fact_check_api_key}
                logger.info(f"[Google Fact Check] Consultando revisiones: '{q}'...")
                resp = requests.get(self.FACT_CHECK_URL, params=params, timeout=7)
                if resp.status_code != 200:
                    continue
                for claim in resp.json().get("claims", []):
                    reviews = claim.get("claimReview") or []
                    rev = reviews[0] if reviews else {}
                    url = rev.get("url", "")
                    if not claim.get("text") or not url or not (rev.get("publisher") or {}).get("name") or url in vistos:
                        continue
                    vistos.add(url)
                    fecha_rev = rev.get("reviewDate", "")
                    fecha_claim = claim.get("claimDate", "")
                    verificaciones.append({
                        "text": claim.get("text", ""),
                        "claimant": claim.get("claimant", ""),
                        "title": rev.get("title", ""),
                        "url": url,
                        "publisher": (rev.get("publisher") or {}).get("name", ""),
                        "textualRating": rev.get("textualRating", ""),
                        "reviewDate": fecha_rev,
                        "claimDate": fecha_claim,
                        "anio": (fecha_rev or fecha_claim)[:4],
                        "ambito": ambito,
                    })
            except Exception as e:
                logger.error(f"[Google Fact Check] Error: {type(e).__name__}")

        verificaciones.sort(key=lambda v: _fecha_a_datetime(v.get("reviewDate") or v.get("claimDate")), reverse=True)
        return verificaciones

    # =========================================================================
    # 3. PUBLICACIONES EN X (API OFICIAL v2, ver x_service.py)
    # =========================================================================
    def obtener_tweets_reales(self, provincia: str) -> List[Dict[str, Any]]:
        return self.x_client.buscar(provincia)[0]

    # =========================================================================
    # 4. PUBLICACIONES EN BLUESKY (POSTS REALES VÍA AT PROTOCOL SEARCH API)
    # =========================================================================
    BLUESKY_SEARCH_POSTS_API = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"

    @_con_cache("bluesky")
    def obtener_posts_bluesky(self, provincia: str) -> List[Dict[str, Any]]:
        """
        Consulta publicaciones REALES que mencionan la provincia o ciudades locales.
        Usa la API pública oficial de búsqueda de Bluesky, sin consultas nacionales genéricas.
        - CERO perfiles genéricos, CERO datos sintéticos.
        """
        # Variar los términos temáticos por provincia/localidad permite ampliar
        # los resultados sin rellenar cada feed con las mismas menciones nacionales.
        localidades = PROVINCIA_LOCALIDADES.get(provincia, [provincia])
        temas = [
            "elecciones", "electoral", "CNE", "candidatos", "votación",
            "campaña electoral", "consulta popular", "elecciones 2027",
        ]
        queries = list(dict.fromkeys(
            f'"{localidad}" {tema}'
            for localidad in localidades
            for tema in temas
        ))
        localidades_normalizadas = [_texto_normalizado(value) for value in localidades]
        terminos_electorales_normalizados = [_texto_normalizado(value) for value in TERMINOS_ELECTORALES]
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        seen_uris = set()
        posts_bluesky = []
        since = datetime.now(timezone.utc).strftime("%Y-01-01T00:00:00Z")

        def buscar(q: str):
            try:
                resp = requests.get(
                    self.BLUESKY_SEARCH_POSTS_API,
                    params={"q": q, "limit": 100, "sort": "latest", "since": since},
                    headers=headers,
                    timeout=8,
                )
                if resp.status_code != 200:
                    logger.warning("[Bluesky Public API] HTTP %d para consulta '%s'.", resp.status_code, q)
                    return q, []
                return q, resp.json().get("posts", [])
            except Exception:
                logger.warning("[Bluesky Public API] Error consultando '%s'.", q)
                return q, []

        # Consultas paralelas: amplían cobertura sin sumar hasta 8 timeouts en serie.
        with ThreadPoolExecutor(max_workers=4) as executor:
            for q, posts_raw in executor.map(buscar, queries):
                logger.info("[Bluesky Public API] Procesando '%s' (%d resultados).", q, len(posts_raw))
                for p in posts_raw:
                    uri = p.get("uri", "")
                    if not uri or uri in seen_uris:
                        continue
                    seen_uris.add(uri)

                    rec = p.get("record", {})
                    text = rec.get("text", "")
                    if not text or len(text) < 8:
                        continue
                    texto_local = _texto_normalizado(text)
                    if not any(
                        re.search(r"(?<![a-z0-9])" + re.escape(localidad) + r"(?![a-z0-9])", texto_local)
                        for localidad in localidades_normalizadas
                    ):
                        continue
                    if not any(
                        re.search(r"(?<![a-z0-9])" + re.escape(termino) + r"(?![a-z0-9])", texto_local)
                        for termino in terminos_electorales_normalizados
                    ):
                        continue

                    auth = p.get("author", {})
                    post_handle = auth.get("handle", "")
                    if not post_handle:
                        continue
                    display_name = auth.get("displayName") or post_handle
                    rkey = uri.split("/")[-1]
                    post_url = f"https://bsky.app/profile/{post_handle}/post/{rkey}"
                    date_str = rec.get("createdAt") or p.get("indexedAt") or ""
                    posts_bluesky.append({
                        "text": text,
                        "author": {
                            "name": display_name,
                            "handle": f"@{post_handle}",
                            "avatar": auth.get("avatar", "")
                        },
                        "date": date_str,
                        "link": post_url,
                        "stats": {
                            "likes": p.get("likeCount", 0),
                            "reposts": p.get("repostCount", 0),
                            "replies": p.get("replyCount", 0),
                            "quotes": p.get("quoteCount", 0)
                        },
                        "anio": _anio_de_fecha(date_str),
                        "alcance": "provincial",
                        "ambito": "provincial",
                    })
        posts_bluesky.sort(key=lambda post: post.get("date", ""), reverse=True)
        return posts_bluesky[:200]

    # =========================================================================
    # 5. ANUNCIOS POLÍTICOS EN META (Biblioteca de Anuncios - Graph API ads_archive)
    # =========================================================================
    def obtener_anuncios_meta_con_estado(self, provincia: str):
        """
        Anuncios políticos y de temas sociales de Meta (Facebook / Instagram) cuyo alcance
        incluye la provincia, con quién pagó, rango de inversión e impresiones.
        Devuelve (anuncios, estado). Sin token o ante un error devuelve lista vacía y un
        estado explicativo; nunca datos sintéticos.
        """
        try:
            return self.ads_library.por_provincia(provincia)
        except Exception as e:
            logger.error(f"[Meta Ad Library] Error inesperado: {type(e).__name__}")
            return [], {"configurado": self.ads_library.configurado, "ok": False,
                        "mensaje": "Error inesperado consultando la Biblioteca de Anuncios de Meta."}

    def obtener_anuncios_meta(self, provincia: str) -> List[Dict[str, Any]]:
        return self.obtener_anuncios_meta_con_estado(provincia)[0]
