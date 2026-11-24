"""
Cliente de la Biblioteca de Anuncios de Meta (Graph API `ads_archive`).

Trae anuncios de tipo POLITICAL_AND_ISSUE_ADS que alcanzaron Ecuador y los
normaliza. Los datos son reales: si no hay token o la API falla, devuelve una
lista vacía junto con un estado explicativo; nunca inventa anuncios.

Notas de diseño:
- La API exige un término de búsqueda: por defecto se usa «*», que devuelve
  TODOS los anuncios políticos y de temas sociales de Ecuador del período (se
  pagina hasta agotarlos; AD_LIBRARY_TERMS puede fijar otras palabras). El
  resultado se cachea, se sirve de inmediato aunque esté vencido y se renueva
  en segundo plano; la última descarga completa queda en una copia local. El
  filtro por provincia se hace después con `delivery_by_region`, que indica el
  porcentaje del alcance de cada anuncio por región.
- `spend` e `impressions` llegan como rangos, no como cifras exactas.
- `ad_snapshot_url` NO se solicita ni se reenvía: Meta incrusta el access token
  en esa URL. El enlace público se arma con el id del anuncio.
- Los mensajes de error se limpian para que el token nunca aparezca en logs ni
  en las respuestas de la API.
"""
import collections
import contextvars
import difflib
import gzip
import hashlib
import itertools
import json
import logging
import os
import sys
import tempfile
import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from functools import lru_cache
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    import firebase_store  # credenciales guardadas en Firebase (/config/api_keys); opcional
except ImportError:  # pragma: no cover
    firebase_store = None

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/{version}/ads_archive"
LIBRARY_URL = "https://www.facebook.com/ads/library/?id={ad_id}"

CORE_FIELDS = [
    "id", "page_id", "page_name", "bylines",
    "ad_creation_time", "ad_delivery_start_time", "ad_delivery_stop_time",
    "ad_creative_bodies", "ad_creative_link_titles",
    "currency", "spend", "impressions", "publisher_platforms",
]
# Solo disponibles para POLITICAL_AND_ISSUE_ADS.
POLITICAL_FIELDS = ["delivery_by_region", "demographic_distribution", "estimated_audience_size"]

# «*» es la búsqueda de TODOS los anuncios políticos y de temas sociales de Ecuador del período. Buscar por palabras (elecciones, candidato, alcalde…)
# solo encontraba una parte: las pruebas del 2026-11-05 hallaron más de 10 mil anuncios y diez palabras traían menos de 4 mil, y los anuncios
# locales que no usan esas palabras (Galápagos, municipios, candidatos de provincia) quedaban fuera. AD_LIBRARY_TERMS puede fijar otras palabras.
DEFAULT_TERMS = "*"

# Texto que Meta pone en lugar de un anuncio retirado (inglés y español), ya normalizado.
_PLACEHOLDER_RETIRADO = re.compile(
    r"(we later disabled|advertising standards|was removed because|normas publicitarias|"
    r"estandares de publicidad|cuenta o pagina que inhabilitamos)"
)
# Aviso de Meta en los anuncios que corrieron sin el descargo obligatorio («pagado por»): lo comparten miles de páginas y no es un mensaje de ninguna.
# Hasta ahora solo lo libraba del análisis tener 7 palabras (menos que el mínimo): bastaba que Meta añadiera una palabra para armar grupos de mil páginas.
_PLACEHOLDER_SIN_DESCARGO = re.compile(r"(ran without a required disclaimer|se publico sin (el|un) descargo de responsabilidad)")
# Los avisos de Meta son frases cortas (la más larga mide ~100 caracteres): un anuncio largo que solo cite esas palabras no es un aviso.
_LARGO_MAX_AVISO = 300


def _retirado_por_meta(texto: Any) -> bool:
    """
    ¿Meta puso su aviso estándar en lugar del anuncio? Pasa cuando lo retira por no llevar el descargo «pagado por» obligatorio, por incumplir sus
    normas publicitarias o porque la cuenta o página que lo publicó fue inhabilitada. El anuncio real ya no existe: solo queda el aviso (el mismo en
    miles de páginas), sin mensaje ni anunciante útiles, y por eso no cuenta en el mapa, la red, las listas ni las cifras.
    """
    if not isinstance(texto, str) or not texto or len(texto) > _LARGO_MAX_AVISO:
        return False
    limpio = _norm_texto_directo(texto)
    return bool(_PLACEHOLDER_RETIRADO.search(limpio) or _PLACEHOLDER_SIN_DESCARGO.search(limpio))

def _leer_copia_compacta(ruta: str) -> Optional[Dict[str, Any]]:
    """
    Lee una copia compacta (`*.jsonl.gz`, la escribe `archivo_meta.escribir_snapshot`): primera línea con los datos de la copia ({guardado,
    terminos, dias…}) y después un anuncio por línea, con la demografía en ternas [edad, género, porcentaje]. Sirve para períodos largos (cientos
    de miles de anuncios): se lee línea a línea, sin tener nunca el JSON entero en memoria, y los textos que se repiten en miles de anuncios
    (claves, páginas, provincias, tramos de edad) se guardan una sola vez. La demografía se queda en ternas: ocupa menos de la mitad.
    """
    unico = sys.intern
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        copia = json.loads(f.readline() or "{}")
        if not isinstance(copia, dict):
            return None
        ads: List[Dict[str, Any]] = []
        for linea in f:
            if not linea.strip():
                continue
            ad = {unico(k): (unico(v) if isinstance(v, str) and k in _CAMPOS_REPETIDOS else v) for k, v in json.loads(linea).items()}
            ad["demografia"] = [(unico(str(d[0])), unico(str(d[1])), d[2]) if isinstance(d, list) else d for d in ad.get("demografia") or []]
            ad["regiones"] = [{"region": unico(str(r["region"])), "porcentaje": r["porcentaje"]} for r in ad.get("regiones") or []]
            ad["plataformas"] = [unico(str(p)) for p in ad.get("plataformas") or []]
            ads.append(ad)
    copia["ads"] = ads
    return copia if ads else None


_CAMPOS_REPETIDOS = {"page_name", "page_id", "financiador", "moneda", "fuente"}

_TOKEN_RE = re.compile(r"(access_token=)[^&\s'\")]+", re.IGNORECASE)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _norm_texto_directo(s: str) -> str:
    """Sin caché: para los textos largos de los anuncios, que casi nunca se repiten y llenarían la caché de los nombres."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(provincia|province)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_norm_texto = lru_cache(maxsize=262144)(_norm_texto_directo)


def _norm(texto: Any) -> str:
    """Minúsculas, sin tildes ni signos, sin la palabra 'provincia/province'. Con caché: los mismos nombres se normalizan miles de veces."""
    return _norm_texto(texto if isinstance(texto, str) else str(texto or ""))


# --- Comparación de los textos de los anuncios (mensajes repetidos) ---
MIN_PALABRAS_TEXTO = 8        # los textos más cortos son genéricos («Conoce más», «Inscríbete aquí») y dan falsos positivos
MAX_PAGINAS_POR_TEXTO = 40    # el mismo texto en tantas páginas es un aviso de la plataforma o una plantilla masiva, no una coincidencia entre pocas
MAX_ANUNCIOS_POR_PAGINA_DETALLE = 15      # anuncios de cada página que se detallan (con su enlace) al ver un mensaje repetido entre dos páginas

# Lo que no es parte del mensaje y no debe pesar al comparar: enlaces (cada página pone el suyo, con seguimiento), #hashtags y @menciones.
# Hay que quitarlos ANTES de normalizar: _norm convierte «https://a.b/c» en las palabras «https a b c» y ya no se reconocen.
_RUIDO_EN_TEXTO = re.compile(r"(?:https?://|www\.)\S+|[#@][\w.]+", re.IGNORECASE)
_PALABRA_O_FIN_DE_FRASE = re.compile(r"[\w'’]+|[.!?¡¿:;\n]")
_FIN_DE_FRASE = {".", "!", "?", "¡", "¿", ":", ";", "\n"}


def _sin_ruido(texto: Any) -> str:
    return _RUIDO_EN_TEXTO.sub(" ", texto if isinstance(texto, str) else str(texto or ""))


def _texto_comparable(texto: Any) -> str:
    """El texto de un anuncio tal como se compara: sin enlaces, hashtags ni menciones, sin tildes ni signos y en minúsculas."""
    return _norm_texto_directo(_sin_ruido(texto))


def _es_dato(tokens: List[str], desde: int, texto: List[str]) -> bool:
    """
    ¿Son todo cifras o nombres propios? Es lo que se cambia en una plantilla («Conoce la historia de X»). Un nombre propio es una palabra con
    mayúscula inicial que NO abre una frase: la mayúscula de «Una»/«La» o «Continuamos»/«Supervisamos» al empezar no dice que sea un nombre.
    """
    if not tokens:
        return False
    for k, t in enumerate(tokens):
        previo = texto[desde + k - 1] if desde + k else ""
        if any(c.isdigit() for c in t) or (t[:1].isupper() and previo and previo not in _FIN_DE_FRASE):
            continue
        # Una cifra distinta ya es otro dato aunque la palabra que la acompaña abra la frase («VIERNES 23» / «LUNES 12»).
        return any(any(c.isdigit() for c in x) for x in tokens) and all(any(c.isdigit() for c in x) or x[:1].isupper() for x in tokens)
    return True


def _sustituye_datos(texto_a: Any, texto_b: Any) -> bool:
    """
    ¿Son la misma plantilla con otro nombre propio o cifra en el mismo lugar («Conoce la historia de Kelly…» / «…de Gabriela…», «700 mil cupos» /
    «800 mil cupos»)? Entonces no son el mismo mensaje aunque casi todas sus palabras coincidan. No cuenta lo que solo se agrega o se quita (una
    firma, un hashtag), ni el mismo nombre más corto o más largo («Andrés» / «Andrés Esteban Vázquez») o con una errata.
    """
    ta = _PALABRA_O_FIN_DE_FRASE.findall(_sin_ruido(texto_a))
    tb = _PALABRA_O_FIN_DE_FRASE.findall(_sin_ruido(texto_b))
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        izq, der = ta[i1:i2], tb[j1:j2]
        if not (_es_dato(izq, i1, ta) and _es_dato(der, j1, tb)):
            continue
        x, y = _norm_texto_directo(" ".join(izq)), _norm_texto_directo(" ".join(der))
        if not any(c.isdigit() for c in x + y) and (x in y or y in x or difflib.SequenceMatcher(None, x, y).ratio() >= 0.85):
            continue
        return True
    return False


# Las 24 provincias de Ecuador (sin tildes, como las normaliza _norm). Meta también reporta regiones de otros países.
_PROVINCIAS_EC = {
    "azuay": "Azuay", "bolivar": "Bolívar", "canar": "Cañar", "carchi": "Carchi", "chimborazo": "Chimborazo",
    "cotopaxi": "Cotopaxi", "el oro": "El Oro", "esmeraldas": "Esmeraldas", "galapagos": "Galápagos",
    "guayas": "Guayas", "imbabura": "Imbabura", "loja": "Loja", "los rios": "Los Ríos", "manabi": "Manabí",
    "morona santiago": "Morona Santiago", "napo": "Napo", "orellana": "Orellana", "pastaza": "Pastaza",
    "pichincha": "Pichincha", "santa elena": "Santa Elena",
    "santo domingo de los tsachilas": "Santo Domingo de los Tsáchilas", "sucumbios": "Sucumbíos",
    "tungurahua": "Tungurahua", "zamora chinchipe": "Zamora Chinchipe",
}


_CANONICAS = frozenset(_PROVINCIAS_EC.values())


def _nombre_region(region: str) -> str:
    """Nombre de región de Meta -> nombre canónico de provincia (une 'Bolivar'/'Bolívar', 'Morona-Santiago', etc.)."""
    if region in _CANONICAS:             # los anuncios ya guardan solo provincias, con su nombre canónico
        return region
    limpio = re.sub(r"\s+Province$", "", str(region or "")).strip()
    return _PROVINCIAS_EC.get(_norm(limpio), limpio)


def _derivar(ad: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deja en el anuncio solo las provincias de Ecuador (con su nombre canónico) y lo que se calcula una sola vez en lugar de repetirlo en cada
    consulta: `_prov` (alcance por provincia, con la clave normalizada) y `_fuera` (fracción del alcance fuera de las 24 provincias: Meta
    también lista unas 200 regiones de otros países con un porcentaje mínimo) y `_retirado` (Meta puso su aviso en lugar del anuncio: ver
    `_retirado_por_meta`). Es idempotente; las claves con «_» no se guardan en disco ni se envían.
    """
    if "_prov" in ad:
        if "_retirado" not in ad:
            ad["_retirado"] = _retirado_por_meta(ad.get("text"))
        return ad
    ad["_retirado"] = _retirado_por_meta(ad.get("text"))
    prov: Dict[str, float] = {}
    fuera = 0.0
    for r in ad.get("regiones") or []:
        nombre = _nombre_region(r["region"])
        if nombre and _norm(nombre) in _PROVINCIAS_EC:
            prov[nombre] = prov.get(nombre, 0.0) + r["porcentaje"]
        else:
            fuera += r["porcentaje"]
    ad["regiones"] = sorted(({"region": n, "porcentaje": p} for n, p in prov.items()), key=lambda r: -r["porcentaje"])
    ad["_prov"] = {_norm(n): p for n, p in prov.items()}
    ad["_fuera"] = fuera
    return ad


_SUFIJOS_LEGALES = {"s", "a", "sa", "sas", "cia", "ltda", "ltd", "c", "l"}


@lru_cache(maxsize=131072)
def _norm_entidad_texto(s: str) -> str:
    return " ".join(t for t in _norm_texto(s).split() if t not in _SUFIJOS_LEGALES)


def _norm_entidad(texto: Any) -> str:
    """Nombre de página/financiador sin tildes, mayúsculas ni sufijos legales (S.A.S, Cía. Ltda.)."""
    return _norm_entidad_texto(texto if isinstance(texto, str) else str(texto or ""))


def _misma_entidad(a: Any, b: Any) -> bool:
    """
    ¿Son el mismo nombre (sin tildes ni mayúsculas) o uno contiene al otro? También lo son dos nombres que afiliaciones.json agrupa
    en una misma entidad (p. ej. el pagador «Hernán Vladimir Salcedo Loor» y la página «Hernán Salcedo Loor»).
    """
    na, nb = _norm_entidad(a), _norm_entidad(b)
    if not na or not nb:
        return False
    if na == nb or (len(na) >= 4 and na in nb) or (len(nb) >= 4 and nb in na):
        return True
    eq = _equivalencias()
    return na in eq and eq.get(nb) == eq[na]


# Archivo de afiliaciones curado a mano. Es una constante (y no una ruta calculada en cada función) para poder probar con una copia.
RUTA_AFILIACIONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "afiliaciones.json")


def _ids_de(entrada: Dict[str, Any]) -> List[str]:
    """
    Todos los ID de página de una entrada de afiliaciones: el principal (`page_id`) y los de `page_ids`. Una misma persona
    puede tener varias páginas de Meta; todas comparten la afiliación de la entrada.
    """
    extra = entrada.get("page_ids") if isinstance(entrada.get("page_ids"), list) else []
    ids: List[str] = []
    for v in [entrada.get("page_id")] + extra:
        v = str(v).strip() if v not in (None, "") else ""
        if v and v not in ids:
            ids.append(v)
    return ids


def _nombres_de(entrada: Dict[str, Any]) -> List[str]:
    """Nombres normalizados de una entrada: el principal y los de `otros_nombres` (otra página, el pagador declarado, otra grafía…)."""
    extra = entrada.get("otros_nombres") if isinstance(entrada.get("otros_nombres"), list) else []
    nombres: List[str] = []
    for v in [entrada.get("nombre")] + extra:
        n = _norm_entidad(v)
        if n and n not in nombres:
            nombres.append(n)
    return nombres


# Equivalencias de nombres: nombre normalizado -> número de la entrada que lo agrupa (solo entradas con más de un nombre).
# «unidades»: las entidades que reúnen varias páginas de Meta (varios ID) o varios nombres, por ID de página y por nombre normalizado.
# Se vuelve a leer el archivo como mucho una vez por segundo y solo si cambió; guardar o unificar la invalida al momento.
_EQ: Dict[str, Any] = {"ruta": None, "mtime": None, "revisado": 0.0, "mapa": {}, "unidades": {"id": {}, "nombre": {}}}


def _invalidar_equivalencias() -> None:
    _EQ["mtime"] = None
    _EQ["revisado"] = 0.0


def _equivalencias() -> Dict[str, int]:
    ruta, ahora = RUTA_AFILIACIONES, time.monotonic()
    if _EQ["ruta"] == ruta and ahora - _EQ["revisado"] < 1.0:
        return _EQ["mapa"]
    try:
        mtime = os.stat(ruta).st_mtime_ns
    except OSError:
        mtime = None
    if _EQ["ruta"] == ruta and mtime is not None and _EQ["mtime"] == mtime:
        _EQ["revisado"] = ahora
        return _EQ["mapa"]
    mapa: Dict[str, int] = {}
    unidades: Dict[str, Dict[str, Dict[str, Any]]] = {"id": {}, "nombre": {}}
    if mtime is not None:
        try:
            with open(ruta, encoding="utf-8") as f:
                entidades = json.load(f).get("entidades", [])
        except (OSError, ValueError):
            entidades = []
        for i, e in enumerate(entidades):
            nombres, ids = _nombres_de(e), _ids_de(e)
            if len(nombres) > 1:
                for n in nombres:
                    mapa[n] = i
            if (len(ids) > 1 or len(nombres) > 1) and e.get("nombre"):
                u = {"nombre": e["nombre"], "page_id": str(e.get("page_id") or (ids[0] if ids else "")) or None, "ids": ids}
                for pid in ids:
                    unidades["id"][pid] = u
                for n in nombres:
                    unidades["nombre"][n] = u
    _EQ.update(ruta=ruta, mtime=mtime, revisado=ahora, mapa=mapa, unidades=unidades)
    return mapa


def _unidades() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Entidades de afiliaciones.json que reúnen varias páginas de Meta u otros nombres: {"id": {ID: unidad}, "nombre": {nombre normalizado: unidad}}."""
    _equivalencias()
    return _EQ["unidades"]


def _unificar_paginas(ads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Una entidad con varias páginas de Meta (page_ids) u otros nombres es UNA sola página para todo el análisis: sus anuncios pasan a llevar el nombre y el ID
    principal de la entidad, de modo que la red, las listas y las cifras la cuentan una vez. Los datos originales de Meta quedan en `page_name_meta` y
    `page_id_meta`. Los anuncios de páginas que no están en una entidad unificada no se tocan.
    """
    u = _unidades()
    if not u["id"] and not u["nombre"]:
        return ads
    salida = []
    for a in ads:
        pid = str(a.get("page_id") or "")
        unidad = u["id"].get(pid) or u["nombre"].get(_norm_entidad(a.get("page_name")))
        if not unidad:
            salida.append(a)
            continue
        nuevo_id = unidad["page_id"] or a.get("page_id")
        if a.get("page_name") == unidad["nombre"] and str(a.get("page_id") or "") == str(nuevo_id or ""):
            salida.append(a)                                   # ya es la página principal: nada que cambiar
            continue
        salida.append({**a, "page_name": unidad["nombre"], "page_id": nuevo_id, "page_name_meta": a.get("page_name"), "page_id_meta": a.get("page_id")})
    return salida


def _grupo_de_entidad(nombre: Any) -> Tuple[List[str], set]:
    """
    ID de página y nombres normalizados que el archivo de afiliaciones agrupa bajo una entidad (se busca por cualquiera de sus nombres):
    así «Ver anuncios» incluye todas sus páginas y lo que paga con otro nombre.
    """
    clave = _norm_entidad(nombre)
    nombres: set = {clave} if clave else set()
    ids: List[str] = []
    if not clave:
        return ids, nombres
    try:
        with open(RUTA_AFILIACIONES, encoding="utf-8") as f:
            entidades = json.load(f).get("entidades", [])
    except (OSError, ValueError):
        return ids, nombres
    for e in entidades:
        if clave in _nombres_de(e):
            nombres.update(_nombres_de(e))
            ids += [i for i in _ids_de(e) if i not in ids]
    return ids, nombres


def _ids_de_entidad(nombre: Any) -> List[str]:
    """ID de página que el archivo de afiliaciones asocia a una entidad por su nombre."""
    return _grupo_de_entidad(nombre)[0]


def _parsear_otros_nombres(valor: Any, principal: Any = None) -> Optional[List[str]]:
    """
    Otros nombres de una entidad (otra página, el pagador declarado, otra grafía…) a partir de una lista o de un texto separado por «;» o
    saltos de línea; None si no se indicó. Quedan en NFC, sin repetirse y sin el nombre principal.
    """
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = re.split(r"[;\n]+", valor)
    if not isinstance(valor, (list, tuple)):
        raise ValueError("«otros_nombres» debe ser una lista de nombres.")
    nombres: List[str] = []
    vistos = {_norm_entidad(principal)} if principal else set()
    for v in valor:
        if v is None:
            continue
        v = unicodedata.normalize("NFC", str(v).strip())[:200]
        n = _norm_entidad(v)
        if n and n not in vistos:
            vistos.add(n)
            nombres.append(v)
    if len(nombres) > 20:
        raise ValueError("Demasiados nombres alternos (máximo 20).")
    return nombres


_ORDEN_CAMPOS = ("nombre", "page_id", "page_ids", "otros_nombres", "tipo", "afiliacion", "partido", "fuente", "verificado", "actualizado")


def _ordenar_entrada(e: Dict[str, Any]) -> Dict[str, Any]:
    """La entrada con sus campos en el orden habitual del archivo (los desconocidos, al final)."""
    return {**{k: e[k] for k in _ORDEN_CAMPOS if k in e}, **{k: v for k, v in e.items() if k not in _ORDEN_CAMPOS}}


def _leer_afiliaciones() -> Dict[str, Any]:
    try:
        with open(RUTA_AFILIACIONES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError(f"No se pudo leer afiliaciones.json ({type(e).__name__}).") from e


def _escribir_afiliaciones(contenido: Dict[str, Any]) -> None:
    """Guarda afiliaciones.json de forma atómica (archivo temporal y reemplazo). Quien llame debe tener _LOCK_AFIL."""
    ruta = RUTA_AFILIACIONES
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(contenido, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ruta)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RuntimeError(f"No se pudo guardar afiliaciones.json ({type(e).__name__}).") from e
    _invalidar_equivalencias()


def _parsear_page_ids(valor: Any) -> Optional[List[str]]:
    """Lista de ID de página válidos (solo dígitos) a partir de una lista o de un texto separado por comas o espacios; None si no se indicó."""
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = re.split(r"[,;\s]+", valor)
    if not isinstance(valor, (list, tuple)):
        raise ValueError("«page_ids» debe ser una lista de ID de página.")
    ids: List[str] = []
    for v in valor:
        v = str(v).strip()
        if not v:
            continue
        if not re.fullmatch(r"\d{1,40}", v):
            raise ValueError(f"El ID de página «{v[:40]}» no es válido (solo dígitos).")
        if v not in ids:
            ids.append(v)
    if len(ids) > 20:
        raise ValueError("Demasiados ID de página (máximo 20).")
    return ids


def _cargar_afiliaciones() -> Dict[str, Dict[str, Any]]:
    """
    Afiliaciones curadas a mano (backend/afiliaciones.json), indexadas por page_id (todos los de la entrada) y por nombre normalizado
    (sin tildes: «Muñoz» y «Munoz» son la misma clave).
    Cada dato lleva `verificado`: solo los verificados (con afiliación y fuente) se muestran como hechos;
    los demás se muestran como «sin verificar» para que se puedan revisar.
    """
    try:
        with open(RUTA_AFILIACIONES, encoding="utf-8") as f:
            entidades = json.load(f).get("entidades", [])
    except (OSError, ValueError):
        return {}
    indice: Dict[str, Dict[str, Any]] = {}
    for e in entidades:
        if not e.get("afiliacion"):
            continue
        dato = {
            "afiliacion": e["afiliacion"], "partido": e.get("partido"), "tipo": e.get("tipo"), "fuente": e.get("fuente"),
            "verificado": bool(e.get("verificado") and e.get("fuente")),
        }
        for pid in _ids_de(e):
            indice["id:" + pid] = dato
        for n in _nombres_de(e):
            indice["n:" + n] = dato
    return indice


# «Neutral» es un valor reservado de `partido`: marca un medio que informa sin alinearse con un partido (otros medios sí están
# alineados con el oficialismo). No es una organización: no forma centro ni aristas de partido en la red y se pinta en gris.
# Solo lo aceptan las entradas de los tipos de TIPOS_NEUTRALES.
PARTIDO_NEUTRAL = "Neutral"
COLOR_NEUTRAL = "#94a3b8"
AFIL_NEUTRAL = "Medio neutral: sin alineación partidista"       # texto de la afiliación si quien lo marca no escribe otro
TIPOS_NEUTRALES = {"medio"}
# Entradas que cuentan como candidatos al unir con una línea las provincias donde un mismo partido tiene gente (ver _grafo_red).
TIPOS_CANDIDATO = {"candidato", "persona"}


def _es_neutral(partido: Any) -> bool:
    """¿El partido es el valor reservado «Neutral»? Se reconoce sin tildes ni mayúsculas («neutral», «NEUTRAL»)."""
    return _norm(partido) == "neutral"


def _cargar_partidos() -> Dict[str, Dict[str, str]]:
    """
    Colores por partido definidos en afiliaciones.json (clave «partidos»); solo se aceptan colores #rrggbb.
    «Neutral» siempre tiene color (gris), salvo que el archivo defina otro.
    """
    colores: Dict[str, Dict[str, str]] = {PARTIDO_NEUTRAL: {"color": COLOR_NEUTRAL}}
    try:
        with open(RUTA_AFILIACIONES, encoding="utf-8") as f:
            crudo = json.load(f).get("partidos", {})
    except (OSError, ValueError):
        return colores
    colores.update({str(k): {"color": v["color"]} for k, v in crudo.items()
                    if isinstance(v, dict) and re.match(r"^#[0-9a-fA-F]{6}$", str(v.get("color", "")))})
    return colores


def _afiliacion(indice: Dict[str, Dict[str, Any]], nombre: Any, page_id: Any = None) -> Optional[Dict[str, Any]]:
    """Dato de afiliación (verificado o no) para una página o pagador, o None si no hay registro."""
    if page_id and ("id:" + str(page_id)) in indice:
        return indice["id:" + str(page_id)]
    return indice.get("n:" + _norm_entidad(nombre))


def _anotar_afiliacion(lista: List[Dict[str, Any]], indice: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Copia de cada anuncio con la afiliación de su página y, si es otro, de su pagador declarado."""
    indice = indice if indice is not None else _cargar_afiliaciones()
    salida = []
    for a in lista:
        fin = (a.get("financiador") or "").strip()
        salida.append({**{k: v for k, v in a.items() if not k.startswith("_")}, "afiliacion": _afiliacion(indice, a["page_name"], a.get("page_id")),
                       "pagador_afiliacion": _afiliacion(indice, fin) if fin and not _misma_entidad(fin, a["page_name"]) else None})
    return salida


TIPOS_AFILIACION = {"partido", "candidato", "persona", "institucion", "medio", "agencia", "gobierno", "empresa", "otro"}
# Tipos de anunciante para filtrar listas (parámetro «tipo» de /api/ads/anuncios y /api/ads/top-gastadores): agrupan los «tipo» de afiliaciones.json.
GRUPOS_TIPO = {
    "candidatos": {"candidato", "persona", "partido"},
    "instituciones": {"gobierno", "institucion"},
    "medios": {"medio"},
    "agencias": {"agencia", "empresa"},
    "otros": {"otro"},
}
GRUPOS_TIPO_VALIDOS = set(GRUPOS_TIPO) | {"sin_clasificar"}


def _parsear_tipos(valor: Optional[str]) -> set:
    """«candidatos,medios» → {'candidatos','medios'}; ignora lo desconocido. Vacío = sin filtro."""
    return {t.strip() for t in str(valor or "").lower().split(",") if t.strip() in GRUPOS_TIPO_VALIDOS}


def _grupo_de_afiliacion(dato: Optional[Dict[str, Any]]) -> str:
    """Grupo de tipo de anunciante de una página según su entrada en afiliaciones.json; «sin_clasificar» si no tiene tipo."""
    tipo = (dato or {}).get("tipo")
    if not tipo:
        return "sin_clasificar"
    return next((g for g, tipos in GRUPOS_TIPO.items() if tipo in tipos), "otros")


def _filtrar_por_tipo(ads: List[Dict[str, Any]], tipos: set) -> List[Dict[str, Any]]:
    """Deja los anuncios cuya página pertenece a alguno de los grupos de tipo pedidos (sin filtro si `tipos` está vacío)."""
    if not tipos:
        return ads
    indice, memo = _cargar_afiliaciones(), {}
    salida = []
    for a in ads:
        clave = (a.get("page_id"), a.get("page_name"))
        if clave not in memo:
            memo[clave] = _grupo_de_afiliacion(_afiliacion(indice, a.get("page_name"), a.get("page_id")))
        if memo[clave] in tipos:
            salida.append(a)
    return salida
_LOCK_AFIL = threading.Lock()


# --- Mensajes repetidos revisados (backend/mensajes_revisados.json) ---
# Una revisión es la decisión de alguien del equipo de que un mensaje repetido entre ciertas páginas es esperable (la misma organización, un partido
# y sus candidatos, comunicación oficial difundida por varios medios…). No dice que el mensaje sea bueno ni malo: solo que ya se revisó. Los grupos
# que cubre dejan de contarse como señal (lista, red y comparación) y se pueden ver aparte. El archivo se versiona como afiliaciones.json.
RUTA_REVISIONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mensajes_revisados.json")
_LOCK_REV = threading.Lock()
MOTIVOS_REVISION = {
    "misma_entidad": "Misma persona u organización",
    "partido": "Partido y sus candidatos o aliados",
    "comunicacion_oficial": "Comunicación oficial difundida por varios medios",
    "texto_comun": "Texto de uso común (plantilla o comunicado público)",
    "otro": "Otro motivo (explícalo en la nota)",
}
ALCANCES_REVISION = ("mensaje", "paginas")        # «mensaje»: solo ese texto entre esas páginas; «paginas»: cualquier mensaje repetido entre ellas
_HUELLA_RE = re.compile(r"^[0-9a-f]{12}$")
_LEEME_REVISIONES = (
    "Grupos de «Mensajes repetidos» que el equipo ya revisó y dio por esperados. Se marcan desde Conexiones → Mensajes repetidos → «Marcar como "
    "revisado» y se quitan con «Quitar revisión» (o borrando su entrada aquí). Una revisión no dice que el mensaje sea bueno o malo: solo que ya se "
    "miró, y los grupos que cubre dejan de contarse como señal. Si luego aparece una página que no estaba entre las revisadas, el grupo vuelve a mostrarse.")
_CAMPOS_REVISIONES = {
    "id": "Identificador de la revisión (lo genera el servidor).",
    "alcance": "«mensaje»: solo ese texto (huellas) entre esas páginas. «paginas»: cualquier mensaje repetido entre esas páginas.",
    "paginas": "Las páginas revisadas (nombre y page_id). Un grupo queda cubierto solo si TODAS sus páginas están aquí.",
    "huellas": "Huellas de 12 caracteres de los textos revisados (solo con alcance «mensaje»). Se calculan sobre el texto normalizado "
               "(ads_library._texto_comparable): si esa normalización cambia, dejan de reconocerse y los grupos vuelven a mostrarse.",
    "ejemplo": "Comienzo del texto revisado, para poder leer este archivo.",
    "motivo": "Uno de: " + ", ".join(MOTIVOS_REVISION) + ".",
    "nota": "Qué se revisó (obligatoria con el motivo «otro»).",
    "revisado": "Fecha de la revisión.",
}


def _huella(texto_comparable: str) -> str:
    """Identificador estable (12 caracteres) de un texto ya normalizado: así una revisión reconoce el mismo mensaje aunque cambie la descarga."""
    return hashlib.sha1(texto_comparable.encode("utf-8")).hexdigest()[:12]


def _leer_revisiones() -> Dict[str, Any]:
    """Contenido de mensajes_revisados.json; sin archivo no hay revisiones. Un archivo ilegible lanza RuntimeError (no se sobrescribe a ciegas)."""
    try:
        with open(RUTA_REVISIONES, encoding="utf-8") as f:
            contenido = json.load(f)
    except FileNotFoundError:
        return {"revisados": []}
    except (OSError, ValueError) as e:
        raise RuntimeError(f"No se pudo leer mensajes_revisados.json ({type(e).__name__}).") from e
    if not isinstance(contenido, dict) or not isinstance(contenido.get("revisados", []), list):
        raise RuntimeError("mensajes_revisados.json no tiene el formato esperado (un objeto con la lista «revisados»).")
    contenido.setdefault("revisados", [])
    return contenido


def _escribir_revisiones(contenido: Dict[str, Any]) -> None:
    """Guarda mensajes_revisados.json de forma atómica (archivo temporal y reemplazo). Quien llame debe tener _LOCK_REV."""
    salida = {"_leeme": _LEEME_REVISIONES, "_campos": _CAMPOS_REVISIONES,
              **{k: v for k, v in contenido.items() if k not in ("_leeme", "_campos", "revisados")}, "revisados": contenido["revisados"]}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(RUTA_REVISIONES), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RUTA_REVISIONES)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RuntimeError(f"No se pudo guardar mensajes_revisados.json ({type(e).__name__}).") from e


def _cargar_revisiones() -> List[Dict[str, Any]]:
    """
    Las revisiones listas para comparar con los grupos (ID de página y nombres normalizados). Un archivo ilegible no rompe el análisis: se ignora.
    Las páginas se reconocen por su ID y, si falta, por el nombre exacto sin tildes ni mayúsculas (`_norm`): `_norm_entidad` también quita los
    sufijos legales («S.A.», «C.A.») y confundiría páginas distintas como «Noticias A» y «Noticias C».
    """
    try:
        crudas = _leer_revisiones()["revisados"]
    except RuntimeError as e:
        logger.warning(f"[Revisiones] {e} Se ignoran las revisiones hasta que se corrija.")
        return []
    salida = []
    for r in crudas:
        if not isinstance(r, dict) or r.get("alcance") not in ALCANCES_REVISION or not isinstance(r.get("paginas"), list):
            continue
        paginas = [p for p in r["paginas"] if isinstance(p, dict)]
        if len(paginas) < 2:
            continue
        salida.append({
            "id": str(r.get("id") or ""), "alcance": r["alcance"],
            "ids": {str(p["page_id"]).strip() for p in paginas if p.get("page_id")},
            "nombres": {n for n in (_norm(p.get("nombre")) for p in paginas) if n},
            "huellas": {h for h in (r.get("huellas") or []) if isinstance(h, str)},
            "motivo": str(r.get("motivo") or "otro"), "nota": str(r.get("nota") or ""), "revisado": str(r.get("revisado") or ""),
        })
    return salida


def _revision_de_grupo(revisiones: List[Dict[str, Any]], paginas: Dict[str, Any], huellas: List[str]) -> Optional[Dict[str, Any]]:
    """
    La revisión que cubre un grupo de mensajes repetidos. `paginas`: nombre de página -> page_id. Es `completa` si todas sus páginas están entre las
    revisadas (y, en una revisión de un solo mensaje, comparte su texto); `parcial` si comparte al menos dos páginas con lo revisado pero ya
    aparecen otras: el grupo vuelve a mostrarse porque hay algo que nadie ha visto. Sin relación con ninguna revisión devuelve None.
    """
    parcial = None
    conjunto = set(huellas)
    for rev in revisiones:
        if rev["alcance"] == "mensaje" and not (rev["huellas"] & conjunto):
            continue
        cubiertas = [n for n, pid in paginas.items() if (pid and str(pid) in rev["ids"]) or _norm(n) in rev["nombres"]]
        if len(cubiertas) < 2:
            continue
        nuevas = [n for n in paginas if n not in cubiertas]
        dato = {"id": rev["id"], "alcance": rev["alcance"], "motivo": rev["motivo"], "motivo_texto": MOTIVOS_REVISION.get(rev["motivo"], rev["motivo"]),
                "nota": rev["nota"], "revisado": rev["revisado"], "estado": "parcial" if nuevas else "completa", "paginas_nuevas": nuevas}
        if not nuevas:
            return dato
        parcial = parcial or dato
    return parcial


def _reemplaza_revision(nueva: Dict[str, Any], previa: Dict[str, Any]) -> bool:
    """¿La revisión nueva hace innecesaria la previa? Sí si cubre todas sus páginas y, si la nueva es de un solo mensaje, también sus textos."""
    ids = {p["page_id"] for p in nueva["paginas"] if p.get("page_id")}
    nombres = {_norm(p["nombre"]) for p in nueva["paginas"]}
    for p in previa.get("paginas") or []:
        if not isinstance(p, dict) or not ((p.get("page_id") and str(p["page_id"]) in ids) or _norm(p.get("nombre")) in nombres):
            return False
    if nueva["alcance"] == "paginas":
        return True
    return previa.get("alcance") == "mensaje" and set(previa.get("huellas") or []) <= set(nueva.get("huellas") or [])


# Filtro global por petición: lo activa main.py cuando la URL trae sin_cne=true (todos los métodos que usan los anuncios lo respetan).
SIN_CNE: "contextvars.ContextVar[bool]" = contextvars.ContextVar("sin_cne", default=False)
# Igual que SIN_CNE, pero deja solo los anuncios que siguen activos (sin fecha de fin): lo activa main.py con solo_activos=true.
SOLO_ACTIVOS: "contextvars.ContextVar[bool]" = contextvars.ContextVar("solo_activos", default=False)
# Rango de fechas global (desde, hasta), cada uno "AAAA-MM-DD" o None: deja los anuncios que circularon algún día de ese rango (con desde = hasta,
# los de ese día). Lo activa main.py con fecha_desde= y fecha_hasta=. Los montos siguen siendo los de todo el anuncio: Meta no los da por día.
RANGO_FECHAS: "contextvars.ContextVar[Tuple[Optional[str], Optional[str]]]" = contextvars.ContextVar("rango_fechas", default=(None, None))


def _circulo_entre(ad: Dict[str, Any], desde: Optional[str], hasta: Optional[str]) -> bool:
    """
    ¿El anuncio circuló algún día entre `desde` y `hasta` (incluidos)? Circula desde su fecha de inicio hasta su fecha de fin; sin fecha de fin
    sigue activo, así que cuenta para cualquier día posterior a su inicio. Un anuncio sin fecha de inicio no se puede situar: queda fuera.
    """
    inicio, fin = str(ad.get("date") or "")[:10], str(ad.get("fecha_fin") or "")[:10]
    if not inicio:
        return False
    if hasta and inicio > hasta:
        return False
    return not (desde and fin and fin < desde)
_CNE_RE = re.compile(r"\bconsejo nacional electoral\b")


def _es_cne(ad: Dict[str, Any]) -> bool:
    """Anuncio de la autoridad electoral (CNE): página o pagador declarado."""
    pagina, pagador = _norm(ad.get("page_name")), _norm(ad.get("financiador"))
    return bool(_CNE_RE.search(pagina) or _CNE_RE.search(pagador) or pagina in ("cne", "cne ecuador"))


def _sin_cne(ads: List[Dict[str, Any]], activo: bool) -> List[Dict[str, Any]]:
    return [a for a in ads if not _es_cne(a)] if activo else ads


# Hosts genéricos (acortadores, redes, tiendas de apps, formularios, buscadores): los usa cualquiera, así que compartir el host no dice nada;
# se compara la URL completa. Un subdominio de estos también es genérico (maps.app.goo.gl, chat.whatsapp.com…).
_HOSTS_GENERICOS = {
    # acortadores
    "bit.ly", "tinyurl.com", "goo.gl", "goo.su", "t.co", "ow.ly", "n9.cl", "acortar.link", "f.mtr.cool", "mtr.cool", "cutt.ly", "rebrand.ly",
    "rb.gy", "is.gd", "t.ly", "tiny.cc", "shorturl.at", "short.gy", "s.id", "lc.cx", "buff.ly", "lnkd.in", "dub.sh", "surl.li", "urlz.fr",
    "v.gd", "shre.ink", "tr.ee", "flic.kr", "link.msgsndr.com", "g.co", "share.google",
    # páginas de enlaces
    "linktr.ee", "linkr.bio", "bio.link", "beacons.ai", "taplink.cc", "lnk.bio", "linkin.bio", "msha.ke", "heylink.me",
    # mensajería
    "wa.me", "wa.link", "walink.co", "api.whatsapp.com", "whatsapp.com", "t.me", "telegram.me", "m.me", "msng.link",
    # redes y plataformas de contenido
    "facebook.com", "m.facebook.com", "fb.me", "fb.com", "fb.watch", "instagram.com", "threads.net", "threads.com", "youtube.com",
    "m.youtube.com", "youtu.be", "x.com", "twitter.com", "tiktok.com", "vm.tiktok.com", "linkedin.com", "pinterest.com", "pin.it",
    "twitch.tv", "kick.com", "vimeo.com", "open.spotify.com", "spotify.link", "soundcloud.com", "ivoox.com", "issuu.com", "medium.com",
    # Google, formularios, documentos y reuniones
    "google.com", "google.com.ec", "sites.google.com", "docs.google.com", "drive.google.com", "forms.gle", "g.page", "play.google.com",
    "forms.office.com", "forms.cloud.microsoft", "typeform.com", "surveymonkey.com", "jotform.com", "survey.app.do", "canva.com",
    "dropbox.com", "1drv.ms", "onedrive.live.com", "zoom.us", "teams.microsoft.com", "calendly.com", "eventbrite.com", "doi.org",
    # tiendas
    "apps.apple.com", "amazon.com", "mercadolibre.com.ec", "hotmart.com", "change.org",
}
# Parámetros que no cambian a dónde lleva el enlace (seguimiento, idioma, mensaje ya escrito): no cuentan al comparar dos URL de un host genérico.
_PARAMS_SIN_DESTINO = {"fbclid", "gclid", "igshid", "igsh", "si", "feature", "ref", "ref_src", "ref_url", "mibextid", "sfnsn", "rdid", "share_url",
                       "app", "text", "hl", "lang", "locale", "s", "t", "pp", "ab_channel", "usp", "source", "share", "type", "context"}
PAGINAS_POR_PROVINCIA_GARANTIZADAS = 2   # vista nacional de la red: páginas con que entra cada provincia que quedaría sin ninguna
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)


def _clave_enlace(url: str) -> Optional[str]:
    """
    Clave para comparar enlaces entre anuncios: el dominio, o la URL completa si el dominio es genérico. En un host genérico cuenta también lo
    que va tras «?» cuando dice a dónde lleva (youtube.com/watch?v=…, play.google.com/…?id=…): sin eso, dos vídeos distintos parecerían el mismo
    enlace. Los parámetros de seguimiento (utm_*, fbclid…) no cuentan.
    """
    url = url.rstrip(".,;:!?")
    m = re.match(r"https?://([^/?#\s]+)([^?#\s]*)(?:\?([^#\s]*))?", url, re.IGNORECASE)
    if not m:
        return None
    host = m.group(1).lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host in _HOSTS_GENERICOS or any(host.endswith("." + g) for g in _HOSTS_GENERICOS):
        ruta = m.group(2).rstrip("/")
        destino = sorted(p for p in (m.group(3) or "").split("&")
                         if p and "=" in p and p.split("=", 1)[1] and not p.lower().startswith("utm_") and p.split("=", 1)[0].lower() not in _PARAMS_SIN_DESTINO)
        if not ruta and not destino:
            return None
        return host + ruta + ("?" + "&".join(destino) if destino else "")
    return host


def _to_int(valor: Any) -> Optional[int]:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _to_float(valor: Any) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def _medio(rango: Optional[Dict[str, Optional[int]]]) -> float:
    """Punto medio de un rango {min, max} (si falta un extremo, usa el otro)."""
    if not rango:
        return 0.0
    lo, hi = rango.get("min"), rango.get("max")
    if lo is None and hi is None:
        return 0.0
    if hi is None:
        return float(lo)
    if lo is None:
        return float(hi)
    return (lo + hi) / 2.0


def _rango(obj: Any) -> Optional[Dict[str, Optional[int]]]:
    """{'lower_bound': '100', 'upper_bound': '499'} -> {'min': 100, 'max': 499}."""
    if not isinstance(obj, dict):
        return None
    return {"min": _to_int(obj.get("lower_bound")), "max": _to_int(obj.get("upper_bound"))}


def _pagina_pesada(status: Optional[int], err: str) -> bool:
    """¿El error indica una página demasiado grande o lenta? Entonces se reintenta pidiendo la mitad."""
    e = err.lower()
    return status in (500, 502, 503, 504) or "reduce the amount" in e or "timed out" in e or "timeout" in e


_RITMO_RE = re.compile(r"\(código (?:4|17|32|613|368)\)")


def _limite_de_ritmo(status: Optional[int], err: str) -> bool:
    """¿Meta está limitando el ritmo de las consultas (HTTP 429 o los códigos de límite de llamadas)?"""
    return status == 429 or bool(_RITMO_RE.search(err))


class AdLibraryClient:
    def __init__(self):
        self.token = ""
        # El entorno no cambia mientras corre el servidor: se lee una sola vez.
        self._env_token = os.getenv("META_AD_LIBRARY_TOKEN", "").strip()
        self._env_enabled = os.getenv("META_INTEGRATION_ENABLED", "").strip().lower()
        self.version = os.getenv("META_GRAPH_VERSION", "v23.0").strip() or "v23.0"
        self.country = os.getenv("AD_LIBRARY_COUNTRY", "EC").strip().upper() or "EC"
        self.terms = [t.strip() for t in os.getenv("AD_LIBRARY_TERMS", DEFAULT_TERMS).split(",") if t.strip()]
        self.days = _env_int("AD_LIBRARY_DAYS", 120)
        # Páginas grandes y recorrido hasta agotar los resultados: la API de Meta devuelve cientos de anuncios por consulta (1000 como máximo por
        # página). Con páginas de 50 y un tope de 2 solo se bajaba el 11 % de los anuncios (los más recientes de cada término).
        self.pages_per_term = max(1, _env_int("AD_LIBRARY_PAGES", 80))
        self.limit = max(50, min(1000, _env_int("AD_LIBRARY_LIMIT", 500)))
        self.timeout = max(5.0, _env_float("AD_LIBRARY_TIMEOUT", 45.0))
        # Con la caché caducada se siguen sirviendo los datos anteriores y se renuevan en segundo plano (AD_LIBRARY_SEGUNDO_PLANO=false lo apaga).
        self.segundo_plano = os.getenv("AD_LIBRARY_SEGUNDO_PLANO", "true").strip().lower() not in ("0", "false", "no")
        self.cache_ttl = _env_float("AD_LIBRARY_CACHE_MIN", 60.0) * 60          # la descarga completa son unas 65 consultas (~8 min): una vez por hora
        self.min_region_pct = _env_float("AD_LIBRARY_MIN_REGION_PCT", 0.05)
        self.url = GRAPH_URL.format(version=self.version)
        carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        _def_snap = os.path.join(carpeta, "ads_snapshot.jsonl.gz") if os.path.exists(os.path.join(carpeta, "ads_snapshot.jsonl.gz")) else os.path.join(carpeta, "ads_snapshot.json")
        self.snapshot_path = os.getenv("AD_LIBRARY_SNAPSHOT", _def_snap)
        # Archivo histórico (archivo_meta.py): cada descarga se fusiona en él con la respuesta cruda de Meta, para conservar los anuncios que
        # salen de la ventana de `days` días. Por defecto va junto a la copia local; AD_LIBRARY_ARCHIVAR=false lo apaga.
        self.archivar = os.getenv("AD_LIBRARY_ARCHIVAR", "true").strip().lower() not in ("0", "false", "no")
        self.archivo_dir = os.getenv("AD_LIBRARY_ARCHIVO_DIR", "").strip() or os.path.join(os.path.dirname(os.path.abspath(self.snapshot_path)), "archivo")
        # Modo «solo copia»: se sirve la copia en disco tal cual (p. ej. una generada desde el archivo histórico), sin token y sin llamar nunca a Meta.
        self.solo_copia = os.getenv("AD_LIBRARY_SOLO_COPIA", "").strip().lower() in ("1", "true", "yes", "si", "sí")

        self._cache: Optional[Dict[str, Any]] = None
        self._lock = threading.RLock()
        self._bajando = threading.Lock()                   # una sola descarga a la vez (la de segundo plano y la primera de todas no se pisan)
        self._hilo: Optional[threading.Thread] = None
        self._lock_textos = threading.Lock()               # la comparación de textos de toda la descarga se calcula una sola vez
        self._textos: Optional[Dict[str, Any]] = None
        self._fb_keys: Dict[str, str] = {}
        self._fb_checado = 0.0
        self.reload_token(force=True)

    # ------------------------------------------------------------------
    # Credenciales y interruptor de la integración
    # ------------------------------------------------------------------
    def _claves_firebase(self, force: bool = False) -> Dict[str, str]:
        """Claves privadas del servidor en Firebase (/config/api_keys). Se consultan como mucho cada 5 minutos."""
        ahora = time.time()
        if firebase_store is None or (not force and ahora - self._fb_checado < 300):
            return self._fb_keys
        self._fb_checado = ahora
        try:
            self._fb_keys = firebase_store.get_api_keys() or {}
        except Exception:
            logger.warning("[AdLibrary] No se pudo consultar la configuración privada de Firebase.")
            self._fb_keys = {}
        return self._fb_keys

    def reload_token(self, force: bool = False) -> bool:
        """Token de Meta: primero el entorno local (.env.local); si no hay, Firebase. Nunca se expone."""
        nuevo = self._env_token
        if not nuevo:
            claves = self._claves_firebase(force)
            nuevo = (claves.get("META_AD_LIBRARY_TOKEN") or claves.get("FB_META_ACCESS_TOKEN") or "").strip()
        if nuevo != self.token:
            with self._lock:
                self.token = nuevo
                self._cache = None
        return bool(self.token)

    @property
    def habilitado(self) -> bool:
        """La integración está APAGADA salvo que se encienda: META_INTEGRATION_ENABLED=true o FB_META_API_ENABLED en Firebase."""
        if self.solo_copia:                                # no se llama a Meta: basta con la copia en disco
            return True
        env = self._env_enabled
        if env in ("1", "true", "yes", "si", "sí"):
            return True
        if env in ("0", "false", "no"):
            return False
        return str(self._claves_firebase().get("FB_META_API_ENABLED", "false")).strip().lower() == "true"

    @property
    def configurado(self) -> bool:
        return self.solo_copia or (self.habilitado and bool(self.token))

    # ------------------------------------------------------------------
    # Acceso a la API
    # ------------------------------------------------------------------
    def _scrub(self, texto: Any) -> str:
        limpio = _TOKEN_RE.sub(r"\1***", str(texto))
        if self.token:
            limpio = limpio.replace(self.token, "***")
        return limpio[:300]

    def _get(self, params: Dict[str, Any]) -> Tuple[Optional[int], Optional[Dict[str, Any]], str]:
        """Devuelve (status_http, cuerpo_json, error). `error` queda vacío si todo salió bien."""
        try:
            r = requests.get(self.url, params={**params, "access_token": self.token}, timeout=self.timeout)
        except requests.RequestException as e:
            return None, None, self._scrub(f"Error de red: {e}")

        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = None
        # Qué parte de la cuota de la hora va gastada, según Meta (la captura del archivo histórico lo lee para frenar antes de que la limiten).
        cabeceras = getattr(r, "headers", None)
        uso = cabeceras.get("x-business-use-case-usage") if hasattr(cabeceras, "get") else None
        self._ultimo_uso = uso if isinstance(uso, str) else None

        if r.status_code != 200:
            err = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {}
            detalle = err.get("message") or r.text[:200]
            if err.get("code") == 190:
                return r.status_code, None, "El token de acceso a la API de Meta venció o no es válido (código 190)."
            return r.status_code, None, self._scrub(f"HTTP {r.status_code} (código {err.get('code')}): {detalle}")
        if not isinstance(cuerpo, dict):
            return r.status_code, None, "Respuesta no válida de la API."
        return r.status_code, cuerpo, ""

    def _fetch_term(self, term: str, limit: Optional[int] = None, pages: Optional[int] = None,
                    fields: Optional[List[str]] = None) -> Tuple[List[Dict[str, Any]], str]:
        """
        Descarga los anuncios crudos de un término siguiendo la paginación por cursor hasta agotar los resultados (o `pages` páginas).
        Las páginas son grandes (`self.limit`). Si una es demasiado pesada o tarda demasiado se pide la mitad (el cursor sigue valiendo) y,
        si Meta limita el ritmo de las consultas, se espera un poco y se reintenta.
        """
        campos = fields or (CORE_FIELDS + POLITICAL_FIELDS)
        desde = (date.today() - timedelta(days=self.days)).isoformat()
        limite_normal = max(10, int(limit or self.limit))
        limite = limite_normal
        crudos: List[Dict[str, Any]] = []
        after = None
        consultas, inicio = 0, time.time()

        for _ in range(pages or self.pages_per_term):
            params = {
                "search_terms": term,
                "ad_type": "POLITICAL_AND_ISSUE_ADS",
                "ad_reached_countries": json.dumps([self.country]),
                "ad_active_status": "ALL",
                "ad_delivery_date_min": desde,
                "fields": ",".join(campos),
                "limit": limite,
            }
            if after:
                params["after"] = after

            reintentos = 0
            while True:
                params["limit"] = limite
                consultas += 1
                status, cuerpo, err = self._get(params)
                if not err:
                    break
                # Si esta versión de la API rechaza un campo, reintentar solo con los básicos.
                if status == 400 and not crudos and fields is None and "field" in err.lower():
                    logger.warning("[AdLibrary] Campo rechazado por la API; reintentando con campos básicos.")
                    return self._fetch_term(term, limit, pages, CORE_FIELDS)
                if limite > 50 and reintentos < 3 and _pagina_pesada(status, err):
                    limite = max(50, limite // 2)
                    reintentos += 1
                    logger.warning(f"[AdLibrary] Página demasiado pesada o lenta para «{term}»: se pide de {limite} en {limite}.")
                    continue
                if reintentos < 3 and _limite_de_ritmo(status, err):
                    reintentos += 1
                    logger.warning(f"[AdLibrary] Meta limita el ritmo de las consultas; se espera antes de reintentar «{term}».")
                    time.sleep(min(30.0, 4.0 * reintentos))
                    continue
                return crudos, err

            datos = cuerpo.get("data") or []
            crudos.extend(datos)
            paging = cuerpo.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not datos or not paging.get("next") or not after:
                break
            if limite < limite_normal:                       # tras una página buena se vuelve a subir, poco a poco, al tamaño normal
                limite = min(limite_normal, limite * 2)
        else:
            # Se agotó el tope de páginas y Meta aún tenía más: el resultado es parcial.
            self.__dict__.setdefault("_truncados", set()).add(term)

        logger.info(f"[AdLibrary] «{term}»: {len(crudos)} anuncios en {consultas} consultas ({time.time() - inicio:.0f} s).")
        return crudos, ""

    # ------------------------------------------------------------------
    # Normalización
    # ------------------------------------------------------------------
    def _normalizar(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        ad_id = str(raw.get("id") or "")
        cuerpos = raw.get("ad_creative_bodies") or []
        titulos = raw.get("ad_creative_link_titles") or []
        texto = (cuerpos[0] if cuerpos else "") or (titulos[0] if titulos else "")

        inicio = raw.get("ad_delivery_start_time") or raw.get("ad_creation_time") or ""
        fin = raw.get("ad_delivery_stop_time") or ""

        regiones = [
            {"region": str(r.get("region") or ""), "porcentaje": _to_float(r.get("percentage"))}
            for r in (raw.get("delivery_by_region") or []) if isinstance(r, dict)
        ]
        total = sum(r["porcentaje"] for r in regiones)
        if total > 1.5:  # llegó como 0-100 en vez de 0-1
            for r in regiones:
                r["porcentaje"] /= 100.0
        regiones.sort(key=lambda r: r["porcentaje"], reverse=True)

        return _derivar({
            "id": ad_id,
            "text": str(texto).strip(),
            "page_name": raw.get("page_name") or "Página sin nombre",
            "page_id": raw.get("page_id"),
            "financiador": raw.get("bylines") or "",
            "date": inicio,
            "fecha_fin": fin,
            "activo": not fin,
            "anio": inicio[:4] if re.match(r"^\d{4}", inicio) else "",
            "link": LIBRARY_URL.format(ad_id=ad_id) if ad_id.isdigit() else "https://www.facebook.com/ads/library/",
            "moneda": raw.get("currency") or "",
            "gasto": _rango(raw.get("spend")),
            "impresiones": _rango(raw.get("impressions")),
            "audiencia_estimada": _rango(raw.get("estimated_audience_size")),
            "plataformas": raw.get("publisher_platforms") or [],
            "regiones": regiones,
            "demografia": raw.get("demographic_distribution") or [],
            "fuente": "meta_ad_library",
        })

    # ------------------------------------------------------------------
    # API pública del servicio
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Copia en disco del último resultado completo (resiliencia ante token vencido o caída de la API)
    # ------------------------------------------------------------------
    def _guardar_snapshot(self, ads: List[Dict[str, Any]], estado: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.snapshot_path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                limpios = [{k: v for k, v in a.items() if not k.startswith("_")} for a in ads]          # lo derivado (claves con «_») se recalcula al cargar
                json.dump({"guardado": estado["actualizado"], "terminos": self.terms, "dias": self.days, "ads": limpios}, f, ensure_ascii=False)
            os.replace(tmp, self.snapshot_path)
        except OSError as e:
            logger.warning(f"[AdLibrary] No se pudo guardar la copia local: {type(e).__name__}")

    def _leer_snapshot(self) -> Optional[Dict[str, Any]]:
        try:
            if self.snapshot_path.endswith(".gz"):
                return _leer_copia_compacta(self.snapshot_path)
            with open(self.snapshot_path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d.get("ads"), list) and d["ads"] else None
        except (OSError, ValueError):
            return None

    def obtener_nacional(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Anuncios políticos nacionales (cacheados) y estado; sin los anuncios del CNE si la petición lo pidió (sin_cne). Nunca incluye los anuncios que
        Meta retiró (sin el descargo obligatorio, por incumplir sus normas o de una cuenta inhabilitada): en su lugar solo queda su aviso, así que no
        cuentan en el mapa, la red, las listas ni las cifras. Cuántos eran se informa en `estado["retirados_por_meta"]`. La copia en disco los conserva.
        """
        ads, estado = self._obtener_nacional_crudo()
        retirados = sum(1 for a in ads if a.get("_retirado"))
        if retirados:
            ads = [a for a in ads if not a.get("_retirado")]
            estado = {**estado, "retirados_por_meta": retirados, "total_nacional": len(ads)}
        ads = _unificar_paginas(ads)               # una entidad con varias páginas de Meta es una sola página en todo el análisis
        if SIN_CNE.get() and ads:
            filtrados = [a for a in ads if not _es_cne(a)]
            estado = {**estado, "sin_cne": True, "excluidos_cne": len(ads) - len(filtrados), "total_nacional": len(filtrados)}
            ads = filtrados
        if SOLO_ACTIVOS.get() and ads:
            activos = [a for a in ads if a.get("activo")]
            estado = {**estado, "solo_activos": True, "excluidos_inactivos": len(ads) - len(activos), "total_nacional": len(activos)}
            ads = activos
        desde, hasta = RANGO_FECHAS.get()
        if (desde or hasta) and ads:
            en_rango = [a for a in ads if _circulo_entre(a, desde, hasta)]
            estado = {**estado, "rango_fechas": {"desde": desde, "hasta": hasta}, "excluidos_fechas": len(ads) - len(en_rango), "total_nacional": len(en_rango)}
            ads = en_rango
        return ads, estado

    def _obtener_nacional_crudo(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Anuncios políticos nacionales (cacheados), sin duplicados, y un estado legible."""
        if self.solo_copia:
            with self._lock:
                if self._cache is None:
                    self._cache = self._cache_solo_copia()
                return self._cache["ads"], self._cache["estado"]
        self.reload_token()
        if not self.habilitado:
            return [], {
                "configurado": bool(self.token),
                "habilitado": False,
                "ok": False,
                "mensaje": "Los datos de anuncios de Meta están desactivados en este servidor. "
                           "Para activarlos: META_INTEGRATION_ENABLED=true (o FB_META_API_ENABLED en Firebase).",
            }
        if not self.token:
            return [], {
                "configurado": False,
                "habilitado": True,
                "ok": False,
                "mensaje": "Falta el token de Meta: META_AD_LIBRARY_TOKEN en backend/.env.local o en Firebase (/config/api_keys).",
            }

        with self._lock:
            if self._cache is None and self.segundo_plano:
                self._cache = self._cache_desde_copia()
            if self._cache:
                if time.time() - self._cache["ts"] < self.cache_ttl:
                    return self._cache["ads"], self._cache["estado"]
                if self.segundo_plano and self._cache["ads"]:
                    # Caducada: se siguen sirviendo los datos que hay y se renuevan en segundo plano; así ninguna petición espera a la descarga completa.
                    self._actualizar_en_segundo_plano()
                    return self._cache["ads"], {**self._cache["estado"], "actualizando": True}
            ads, errores, truncados, por_termino = self._bajar()
            return self._aplicar(ads, errores, truncados, por_termino)

    def _cache_desde_copia(self) -> Optional[Dict[str, Any]]:
        """
        Tras reiniciar, la copia en disco de la última descarga completa se sirve al instante (si está caducada se renueva en segundo plano), siempre
        que sea de los mismos términos y período. Sin ella la primera visita tendría que esperar toda la descarga.
        """
        snap = self._leer_snapshot()
        if not snap or snap.get("terminos") != self.terms or snap.get("dias") != self.days:
            return None
        guardado = str(snap.get("guardado") or "")
        try:
            ts = datetime.fromisoformat(guardado).timestamp()
        except ValueError:
            return None
        ads = [_derivar(a) for a in snap["ads"]]
        estado = {"configurado": True, "habilitado": True, "ok": True, "total_nacional": len(ads), "terminos": self.terms, "dias": self.days,
                  "cache_min": int(self.cache_ttl // 60), "version_api": self.version, "actualizado": guardado, "mensaje": "", "desde_copia": True}
        return {"ts": ts, "ads": ads, "estado": estado}

    def _cache_solo_copia(self) -> Dict[str, Any]:
        """
        Modo «solo copia» (AD_LIBRARY_SOLO_COPIA=true): la copia de AD_LIBRARY_SNAPSHOT se sirve tal cual, sea de los días y términos que sea, sin
        token y sin llamar a Meta. Es la carga manual de datos guardados (ver archivo_meta.py y docs/archivo-meta.md). Nunca caduca.
        """
        snap = self._leer_snapshot()
        base = {"configurado": True, "habilitado": True, "solo_copia": True, "version_api": self.version, "cache_min": 0}
        if not snap:
            return {"ts": time.time(), "ads": [], "estado": {**base, "ok": False, "total_nacional": 0, "terminos": self.terms, "dias": self.days,
                    "mensaje": "Modo solo copia: no hay una copia de anuncios que cargar (revisa AD_LIBRARY_SNAPSHOT)."}}
        ads = [_derivar(a) for a in snap["ads"]]
        guardado = str(snap.get("guardado") or "")
        dias = snap.get("dias") if isinstance(snap.get("dias"), int) else self.days
        self.days = dias                                   # el período que anuncia la app es el de la copia cargada
        estado = {**base, "ok": True, "total_nacional": len(ads), "terminos": snap.get("terminos") or self.terms, "dias": dias,
                  "actualizado": guardado, "mensaje": "", "desde_copia": True, "desactualizado": True,
                  "aviso": f"Datos guardados (copia de {guardado[:16].replace('T', ' ')}): este servidor no se actualiza con Meta."}
        for clave in ("desde", "hasta"):
            if snap.get(clave):
                estado[clave] = snap[clave]
        return {"ts": time.time(), "ads": ads, "estado": estado}

    def _archivar(self, crudos: List[Dict[str, Any]]) -> None:
        """Fusiona una descarga en el archivo histórico. Nunca interrumpe a la app: si falla, solo se avisa en el registro."""
        if not self.archivar or not crudos:
            return
        try:
            import archivo_meta
            cuentas = archivo_meta.ArchivoMeta(self.archivo_dir, pais=self.country, espera_candado=60).fusionar(crudos, origen="renovacion")
            logger.info(f"[AdLibrary] Archivo histórico: {cuentas['nuevos']} anuncios nuevos, {cuentas['actualizados']} actualizados.")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[AdLibrary] No se pudo actualizar el archivo histórico: {type(e).__name__}")

    def _bajar(self) -> Tuple[List[Dict[str, Any]], List[str], List[str], Dict[str, int]]:
        """Descarga todos los términos (en paralelo): (anuncios sin duplicados, errores, términos con resultados truncados, anuncios por término)."""
        with self._bajando:
            self.__dict__["_truncados"] = set()
            with ThreadPoolExecutor(max_workers=4) as ex:
                resultados = list(ex.map(self._fetch_term, self.terms))
            truncados = sorted(self.__dict__.get("_truncados", ()))

        por_id: Dict[str, Dict[str, Any]] = {}
        errores: List[str] = []
        for crudos, err in resultados:
            if err:
                errores.append(err)
            for raw in crudos:
                ad = self._normalizar(raw)
                if ad["id"] and ad["id"] not in por_id:
                    por_id[ad["id"]] = ad
        por_termino = {t: len(crudos) for t, (crudos, _) in zip(self.terms, resultados)}
        self._archivar([raw for crudos, _ in resultados for raw in crudos])
        return list(por_id.values()), errores, truncados, por_termino

    def _aplicar(self, ads: List[Dict[str, Any]], errores: List[str], truncados: List[str], por_termino: Dict[str, int],
                 guardar: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Convierte una descarga en estado y caché (con la copia en disco, o los últimos datos guardados si todo falló). Quien llama tiene `_lock`.
        Con `guardar=False` no escribe la copia (decenas de MB): la guarda quien llama, ya sin el candado.
        """
        if errores:
            logger.warning(f"[AdLibrary] {len(errores)} consulta(s) con error. Primera: {errores[0]}")

        snap = None
        if not ads and errores:
            snap = self._leer_snapshot()
            if snap:
                ads = [_derivar(a) for a in snap["ads"]]

        estado = {
            "configurado": True,
            "habilitado": True,
            "ok": not errores or bool(ads),
            "total_nacional": len(ads),
            "terminos": self.terms,
            "dias": self.days,
            "cache_min": int(self.cache_ttl // 60),
            "version_api": self.version,
            "actualizado": datetime.now().isoformat(timespec="seconds"),
            "mensaje": "" if ads else (errores[0] if errores else
                                       "La API respondió sin anuncios para esos términos y período."),
        }
        if not snap:
            estado["por_termino"] = por_termino
        if truncados and not snap:
            estado["parcial"] = True
            estado["terminos_truncados"] = truncados
        if errores and ads and not snap:
            estado["advertencia"] = (f"{len(errores)} de {len(self.terms)} búsquedas fallaron: {errores[0]}" if len(self.terms) > 1
                                     else f"La descarga quedó incompleta: {errores[0]}")
        if snap:
            guardado = snap.get("guardado", "")
            estado.update({
                "desactualizado": True,
                "actualizado": guardado,
                "total_nacional": len(ads),
                "mensaje": "",
                "aviso": f"No se pudo consultar a Meta ({errores[0]}) Se muestran los últimos datos guardados, de {guardado[:16].replace('T', ' ')}.",
            })

        if snap or (errores and not ads):
            # Fallo: se recuerda 2 minutos para no repetir las consultas fallidas en cada petición.
            self._cache = {"ts": time.time() - self.cache_ttl + 120, "ads": ads, "estado": estado}
        else:
            self._cache = {"ts": time.time(), "ads": ads, "estado": estado}
            if ads and not errores and guardar:
                self._guardar_snapshot(ads, estado)
        return ads, estado

    def _actualizar_en_segundo_plano(self) -> None:
        """Renueva la caché en un hilo aparte (solo uno a la vez). Una renovación fallida no pisa los datos buenos: se avisa y se reintenta en 2 minutos."""
        if self._hilo is not None and self._hilo.is_alive():
            return

        def trabajo() -> None:
            try:
                ads, errores, truncados, por_termino = self._bajar()
                a_guardar = None
                with self._lock:
                    previos = len(self._cache["ads"]) if self._cache else 0
                    if ads and not (errores and len(ads) < 0.8 * previos):        # con fallos parciales no se cambia un conjunto mayor por uno recortado
                        ads_ok, estado_ok = self._aplicar(ads, errores, truncados, por_termino, guardar=False)
                        a_guardar = (ads_ok, estado_ok) if not errores else None
                    else:
                        self._avisar_renovacion_fallida(errores[0] if errores else "la API respondió sin anuncios")
                if a_guardar:
                    self._guardar_snapshot(*a_guardar)                           # fuera del candado: escribir decenas de MB no bloquea las peticiones
                self.precalcular()                                               # y la comparación de textos queda lista antes de la primera consulta
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[AdLibrary] Falló la renovación en segundo plano: {type(e).__name__}")
                with self._lock:
                    self._avisar_renovacion_fallida(type(e).__name__)

        self._hilo = threading.Thread(target=trabajo, name="ads-library-renovacion", daemon=True)
        self._hilo.start()

    def _avisar_renovacion_fallida(self, motivo: str) -> None:
        """Se conservan los datos anteriores (marcados como desactualizados) y se vuelve a intentar en 2 minutos. Quien llama tiene `_lock`."""
        if not self._cache:
            return
        guardado = str(self._cache["estado"].get("actualizado", ""))
        self._cache["estado"] = {**self._cache["estado"], "desactualizado": True,
                                 "aviso": f"No se pudo actualizar con Meta ({self._scrub(motivo)}) Se muestran los últimos datos guardados, de {guardado[:16].replace('T', ' ')}."}
        self._cache["ts"] = time.time() - self.cache_ttl + 120

    def _porcentaje_region(self, regiones: List[Dict[str, Any]], objetivo: str) -> Optional[float]:
        """Fracción del alcance en la provincia; None si el anuncio no trae datos regionales."""
        if not regiones:
            return None
        suma = 0.0
        for r in regiones:
            nombre = _norm(r["region"])
            if nombre and objetivo and (nombre == objetivo or objetivo in nombre or (len(nombre) >= 4 and nombre in objetivo)):
                suma += r["porcentaje"]
        return suma

    def _alcance_en(self, ad: Dict[str, Any], objetivo: str) -> Optional[float]:
        """
        Regla única de «el anuncio llega a la provincia»: devuelve la fracción de su alcance que cayó allí si llega al mínimo
        (`min_region_pct`) y None si no (o si no trae datos regionales). La usan el mapa, el resumen, la comparación, la red y
        las listas de anuncios, para que una misma provincia dé las mismas cifras en todas partes.
        """
        prov = ad.get("_prov")
        if prov is not None and ad["regiones"] and objetivo in _PROVINCIAS_EC:
            pct = prov.get(objetivo, 0.0)                      # camino rápido: una provincia exacta (ya sumada al cargar el anuncio)
        else:
            pct = self._porcentaje_region(ad["regiones"], objetivo)
        return pct if pct and pct >= self.min_region_pct else None

    def por_provincia(self, provincia: str, limite: int = 15) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Anuncios cuyo alcance incluye la provincia, ordenados por impresiones (rango alto)."""
        ads, estado = self.obtener_nacional()
        if not ads:
            return [], estado

        objetivo = _norm(provincia)
        elegidos = []
        for ad in ads:
            pct = self._porcentaje_region(ad["regiones"], objetivo)
            if pct is None:
                # Sin datos regionales: solo se incluye si el texto menciona la provincia.
                if not objetivo or objetivo not in _norm(ad["text"]):
                    continue
            elif pct < self.min_region_pct:
                continue
            elegidos.append({**ad, "porcentaje_provincia": pct})

        elegidos.sort(key=lambda a: ((a["impresiones"] or {}).get("max") or 0, a["date"]), reverse=True)
        return _anotar_afiliacion(elegidos[:limite]), {**estado, "total_provincia": len(elegidos)}

    def _region_principal_por_pagina(self, ads: List[Dict[str, Any]]) -> Dict[str, Tuple[str, float]]:
        """Provincia donde llega más cada página (ponderada por impresiones): la misma regla que usa el grafo de la red."""
        acumulado: Dict[str, Dict[str, float]] = {}
        for ad in ads:
            clave = ad["page_name"] or str(ad["page_id"] or "")
            peso = _medio(ad["impresiones"]) or 1.0
            reg = acumulado.setdefault(clave, {})
            for r in ad["regiones"]:
                nombre = _nombre_region(r["region"])
                reg[nombre] = reg.get(nombre, 0.0) + r["porcentaje"] * peso
        salida: Dict[str, Tuple[str, float]] = {}
        for clave, reg in acumulado.items():
            total = sum(reg.values())
            if reg and total > 0:
                nombre, valor = max(reg.items(), key=lambda kv: kv[1])
                salida[clave] = (nombre, round(valor / total, 3))
        return salida

    def anuncios(self, alcance: Optional[str] = None, pagina: Optional[str] = None, page_id: Optional[str] = None,
                 pagador: Optional[str] = None, region: Optional[str] = None, entidad: Optional[str] = None,
                 solo_terceros: bool = False, orden: str = "recientes", desde: int = 0, limite: int = 25,
                 sin_cne: bool = False, dias: int = 0, tipo: Optional[str] = None, completo: bool = False) -> Dict[str, Any]:
        """
        Todos los anuncios que cumplen los filtros (se combinan con «y»), paginados. Alimenta la lista de anuncios de una
        provincia, el detalle de un nodo de la red y el de una entidad, con las mismas reglas que el resto de la API para que
        los totales coincidan con lo que se ve en cada pestaña:
          - alcance: los anuncios que LLEGAN a esa provincia (al menos `min_region_pct` de su alcance; vacío = todo el país).
            Con provincia, el resumen trae además la inversión y las impresiones prorrateadas por ese porcentaje: son las
            cifras del mapa y del resumen;
          - pagina / page_id: anuncios de esa página (por nombre, como el nodo); page_id acepta varios ID separados por comas;
          - pagador: anuncios cuyo pagador declarado es ese (con solo_terceros, solo si es distinto de la página);
          - region: anuncios de las páginas CON BASE en esa provincia (donde llega más cada página): los que suma el sol de la red;
          - entidad: anuncios publicados por una página con ese nombre (sin tildes: «Muñoz» = «Munoz»), por cualquiera de los ID de página
            que afiliaciones.json asocia a esa entidad (o los de page_id) o pagados por ese pagador declarado;
          - dias: solo los activos o los que terminaron (o, si no tienen fin, empezaron) en los últimos N días; 0 = sin límite.
        Hace falta al menos uno de los filtros anteriores (`alcance` cuenta).
        """
        objetivo = _norm(alcance) if alcance else ""
        if objetivo in ("todas", "ecuador", "ecuador todas"):
            objetivo = ""
        if not (objetivo or any((pagina, page_id, pagador, region, entidad))):
            raise ValueError("Indica al menos un filtro: alcance (provincia), pagina, page_id, pagador, region o entidad.")
        ads, estado = self.obtener_nacional()
        ads = _sin_cne(ads, sin_cne)
        orden = orden if orden in ("recientes", "inversion", "impresiones") else "recientes"
        desde, limite = max(0, int(desde)), max(1, min(int(limite), 100))
        dias = max(0, int(dias or 0))
        vacio = {"anuncios": 0, "activos": 0, "gasto": {"min": 0, "max": 0, "medio": 0}, "paginas": 0, "pagadores": 0, "primero": "", "ultimo": ""}
        if not ads:
            return {"total": 0, "desde": desde, "limite": limite, "orden": orden, "resumen": vacio, "anuncios": [], "estado": estado}

        # Mismo universo que el grafo (red_pagadores): anuncios del alcance cuya página se puede identificar.
        universo = []
        pesos: Dict[Any, float] = {}              # fracción del alcance de cada anuncio en `alcance` (para prorratear)
        for ad in ads:
            if objetivo:
                pct = self._alcance_en(ad, objetivo)
                if pct is None:
                    continue
                pesos[ad["id"]] = pct
            if not (ad["page_name"] or ad["page_id"]):
                continue
            universo.append(ad)

        principal = self._region_principal_por_pagina(universo) if region else {}
        n_region = _norm(_nombre_region(region)) if region else ""
        n_pagina, n_pagador, e_entidad = _norm(pagina), _norm(pagador), _norm_entidad(entidad)
        ids_pagina = {p.strip() for p in str(page_id or "").split(",") if p.strip()}
        unidades_id = _unidades()["id"]                       # un ID de una entidad unificada vale por todas sus páginas (sus anuncios llevan el ID principal)
        ids_pagina |= {i for pid in list(ids_pagina) for i in (unidades_id.get(pid) or {}).get("ids", [])}
        nombres_entidad = {e_entidad} if e_entidad else set()
        if entidad:                                           # una entidad puede tener varias páginas y pagar con otro nombre
            ids_g, nombres_g = _grupo_de_entidad(entidad)
            ids_pagina.update(ids_g)
            nombres_entidad |= nombres_g

        def es_de_pagina(ad: Dict[str, Any]) -> bool:
            return bool(str(ad["page_id"] or "") in ids_pagina or _norm_entidad(ad["page_name"]) in nombres_entidad)

        def es_de_pagador(ad: Dict[str, Any]) -> bool:
            fin = (ad["financiador"] or "").strip()
            return bool(fin) and _norm_entidad(fin) in nombres_entidad

        def cumple(ad: Dict[str, Any]) -> bool:
            fin = (ad["financiador"] or "").strip()
            if entidad:
                if not (es_de_pagina(ad) or es_de_pagador(ad)):
                    return False
            elif ids_pagina and str(ad["page_id"] or "") not in ids_pagina:
                return False
            if pagina and _norm(ad["page_name"]) != n_pagina:
                return False
            if pagador and _norm(fin) != n_pagador:
                return False
            if solo_terceros and (not fin or _misma_entidad(fin, ad["page_name"])):
                return False
            if region:
                p = principal.get(ad["page_name"] or str(ad["page_id"] or ""))
                if not p or _norm(p[0]) != n_region:
                    return False
            return True

        desde_fecha = (date.today() - timedelta(days=dias)).isoformat() if dias else ""

        def en_periodo(ad: Dict[str, Any]) -> bool:
            # Igual que el filtro de período del front: un anuncio activo siempre cuenta; si no, vale su fecha de fin (o de inicio).
            return not dias or ad["activo"] or (ad["fecha_fin"] or ad["date"] or "")[:10] >= desde_fecha

        elegidos = [ad for ad in universo if cumple(ad) and en_periodo(ad)]
        elegidos = _filtrar_por_tipo(elegidos, _parsear_tipos(tipo))          # tipo de anunciante (candidatos, instituciones, medios…)
        claves = {
            "recientes": lambda a: (a["date"] or "", a["id"]),
            "inversion": lambda a: (_medio(a["gasto"]), a["date"] or ""),
            "impresiones": lambda a: (_medio(a["impresiones"]), a["date"] or ""),
        }
        elegidos.sort(key=claves[orden], reverse=True)

        objetivo_pct = n_region or objetivo
        salida = []
        for ad in _anotar_afiliacion(elegidos[desde:desde + limite]):
            fila = {k: v for k, v in ad.items() if k not in ("demografia", "regiones") and not k.startswith("_")}   # lo pesado y lo derivado no hace falta en una lista
            reg = ad["regiones"][0] if ad.get("regiones") else None
            fila["region_principal"] = ({"region": _nombre_region(reg["region"]), "porcentaje": round(reg["porcentaje"], 3)} if reg else None)
            if objetivo_pct:
                pct = self._porcentaje_region(ad["regiones"], objetivo_pct)
                if pct is not None:
                    fila["porcentaje_provincia"] = pct
            fila["pagado_por_tercero"] = bool((ad["financiador"] or "").strip()) and not _misma_entidad(ad["financiador"], ad["page_name"])
            if completo:       # para exportar: el alcance del anuncio en cada provincia (las que tienen al menos 0,1 %)
                fila["regiones"] = [{"region": _nombre_region(r["region"]), "porcentaje": round(r["porcentaje"], 4)} for r in ad.get("regiones") or [] if r["porcentaje"] >= 0.001]
            fila["grupo_tipo"] = _grupo_de_afiliacion(ad.get("afiliacion"))
            if entidad:
                de_pagina, de_pagador = es_de_pagina(ad), es_de_pagador(ad)
                fila["rol"] = "ambos" if de_pagina and de_pagador else ("pagina" if de_pagina else "pagador")
            salida.append(fila)

        fechas = sorted(a["date"] for a in elegidos if a["date"])
        resumen = {
            "anuncios": len(elegidos),
            "activos": sum(1 for a in elegidos if a["activo"]),
            "gasto": {"min": round(sum((a["gasto"] or {}).get("min") or 0 for a in elegidos)),
                      "max": round(sum((a["gasto"] or {}).get("max") or (a["gasto"] or {}).get("min") or 0 for a in elegidos)),
                      "medio": round(sum(_medio(a["gasto"]) for a in elegidos))},
            "paginas": len({a["page_name"] or str(a["page_id"] or "") for a in elegidos}),
            "pagadores": len({(a["financiador"] or "").strip() for a in elegidos if (a["financiador"] or "").strip()}),
            "primero": fechas[0] if fechas else "", "ultimo": fechas[-1] if fechas else "",
        }
        if objetivo:        # cifras «de la provincia»: cada anuncio cuenta en proporción a su alcance allí (como el mapa y el resumen)
            for campo, destino in (("gasto", "gasto_prorrateado"), ("impresiones", "impresiones_prorrateadas")):
                lo = hi = medio = 0.0
                for a in elegidos:
                    peso, rango = pesos.get(a["id"], 1.0), a[campo] or {}
                    lo += (rango.get("min") or 0) * peso
                    hi += (rango.get("max") or rango.get("min") or 0) * peso
                    medio += _medio(a[campo]) * peso
                resumen[destino] = {"min": round(lo), "max": round(hi), "medio": round(medio)}
        return {"total": len(elegidos), "desde": desde, "limite": limite, "orden": orden, "resumen": resumen, "anuncios": salida, "estado": estado,
                "nota": "Meta publica rangos de inversión e impresiones, no cifras exactas."}

    def top_gastadores(self, provincia: Optional[str] = None, limite: int = 10, sin_cne: bool = False, tipo: Optional[str] = None) -> Dict[str, Any]:
        """
        Anunciantes políticos ordenados por inversión estimada (punto medio de los rangos de Meta).
        Con provincia, cada anuncio cuenta en proporción a su alcance allí (estimación).
        """
        ads, estado = self.obtener_nacional()
        ads = _filtrar_por_tipo(_sin_cne(ads, sin_cne), _parsear_tipos(tipo))
        objetivo = _norm(provincia) if provincia else ""
        if objetivo in ("todas", "ecuador", "ecuador todas"):
            objetivo = ""
        if not ads:
            return {"alcance": "provincia" if objetivo else "nacional", "anunciantes": [], "estado": estado}

        def medio(r: Optional[Dict[str, Optional[int]]]) -> float:
            if not r:
                return 0.0
            lo, hi = r.get("min"), r.get("max")
            if lo is None and hi is None:
                return 0.0
            if hi is None:
                return float(lo)
            if lo is None:
                return float(hi)
            return (lo + hi) / 2.0

        grupos: Dict[str, Dict[str, Any]] = {}
        for ad in ads:
            peso = 1.0
            if objetivo:
                pct = self._alcance_en(ad, objetivo)
                if pct is None:
                    continue
                peso = pct

            g = grupos.setdefault(str(ad["page_id"] or ad["page_name"]), {
                "page_name": ad["page_name"], "page_id": ad["page_id"], "moneda": ad["moneda"],
                "anuncios": 0, "activos": 0, "gasto_min": 0.0, "gasto_max": 0.0, "gasto_medio": 0.0,
                "impr_min": 0.0, "impr_max": 0.0, "impr_medio": 0.0,
                "financiadores": set(), "regiones": {}, "primero": "", "ultimo": "",
            })
            g["anuncios"] += 1
            g["activos"] += 1 if ad["activo"] else 0
            gasto, impr = ad["gasto"] or {}, ad["impresiones"] or {}
            g["gasto_min"] += (gasto.get("min") or 0) * peso
            g["gasto_max"] += (gasto.get("max") or gasto.get("min") or 0) * peso
            g["gasto_medio"] += medio(ad["gasto"]) * peso
            g["impr_min"] += (impr.get("min") or 0) * peso
            g["impr_max"] += (impr.get("max") or impr.get("min") or 0) * peso
            impr_medio = medio(ad["impresiones"]) * peso
            g["impr_medio"] += impr_medio
            if ad["financiador"]:
                g["financiadores"].add(ad["financiador"])
            for r in ad["regiones"]:
                nombre = _nombre_region(r["region"])
                g["regiones"][nombre] = g["regiones"].get(nombre, 0.0) + r["porcentaje"] * medio(ad["impresiones"])
            if ad["date"]:
                g["primero"] = min(g["primero"] or ad["date"], ad["date"])
                g["ultimo"] = max(g["ultimo"], ad["date"])

        anunciantes = []
        for g in grupos.values():
            total_reg = sum(g["regiones"].values())
            principal = max(g["regiones"].items(), key=lambda kv: kv[1]) if g["regiones"] else None
            anunciantes.append({
                "page_name": g["page_name"],
                "page_id": g["page_id"],
                "moneda": g["moneda"],
                "anuncios": g["anuncios"],
                "activos": g["activos"],
                "gasto": {"min": round(g["gasto_min"]), "max": round(g["gasto_max"]), "medio": round(g["gasto_medio"])},
                "impresiones": {"min": round(g["impr_min"]), "max": round(g["impr_max"]), "medio": round(g["impr_medio"])},
                "costo_por_mil": round(g["gasto_medio"] / g["impr_medio"] * 1000, 2) if g["impr_medio"] >= 10000 else None,
                "financiadores": sorted(g["financiadores"]),
                "pagado_por_tercero": any(not _misma_entidad(f, g["page_name"]) for f in g["financiadores"]),
                "region_principal": ({"region": principal[0], "porcentaje": round(principal[1] / total_reg, 3)}
                                     if principal and total_reg > 0 else None),
                "primer_anuncio": g["primero"],
                "ultimo_anuncio": g["ultimo"],
            })
        anunciantes.sort(key=lambda a: a["gasto"]["medio"], reverse=True)
        _indice_afil = _cargar_afiliaciones()
        for a in anunciantes:
            a["afiliacion"] = _afiliacion(_indice_afil, a["page_name"], a["page_id"])
            a["pagador_afiliacion"] = next((d for d in (_afiliacion(_indice_afil, f) for f in a["financiadores"]
                                                        if not _misma_entidad(f, a["page_name"])) if d), None)

        # Los totales se suman sin redondear y se redondean una vez: así coinciden con el mapa y con la lista de anuncios.
        total_gasto = sum(g["gasto_medio"] for g in grupos.values())
        gasto_min_total = round(sum(g["gasto_min"] for g in grupos.values()))
        gasto_max_total = round(sum(g["gasto_max"] for g in grupos.values()))
        total_impr = sum(g["impr_medio"] for g in grupos.values())
        top5 = sum(a["gasto"]["medio"] for a in anunciantes[:5])

        # Un mismo financiador detrás de varias páginas distintas (posible red de páginas).
        paginas_por_financiador: Dict[str, set] = {}
        for ad in ads:
            if ad["financiador"]:
                paginas_por_financiador.setdefault(ad["financiador"], set()).add(ad["page_name"])
        redes = sorted(
            ({"financiador": f, "paginas": sorted(p)} for f, p in paginas_por_financiador.items() if len(p) >= 2),
            key=lambda r: len(r["paginas"]), reverse=True,
        )[:5]

        return {
            "alcance": "provincia" if objetivo else "nacional",
            "resumen": {
                "anunciantes": len(anunciantes),
                "anuncios": sum(a["anuncios"] for a in anunciantes),
                "gasto_medio_total": round(total_gasto),
                "gasto_min_total": gasto_min_total,
                "gasto_max_total": gasto_max_total,
                "impresiones_medias_total": round(total_impr),
                "concentracion_top5": round(top5 / total_gasto, 3) if total_gasto and len(anunciantes) >= 10 else None,
            },
            "anunciantes": anunciantes[:max(1, limite)],
            "redes_de_financiadores": redes,
            "estado": estado,
            "nota": "Meta publica rangos, no cifras exactas: la inversión es el punto medio de cada rango."
                    + (" Para una provincia, cada anuncio se prorratea por su porcentaje de alcance allí (estimación)." if objetivo else ""),
        }

    def red_pagadores(self, provincia: Optional[str] = None, limite: int = 15, sin_cne: bool = False,
                      max_paginas: int = 80) -> Dict[str, Any]:
        """
        Quién paga qué páginas: vínculos pagador -> página donde el pagador declarado (bylines) es distinto de la página.
        Agrupa los vínculos conectados en redes (un pagador con varias páginas, o una página con varios pagadores).
        Es un indicador, no una prueba: agencias y partidos pagan legítimamente por terceros.
        """
        ads, estado = self.obtener_nacional()
        ads = _sin_cne(ads, sin_cne)
        objetivo = _norm(provincia) if provincia else ""
        if objetivo in ("todas", "ecuador", "ecuador todas"):
            objetivo = ""
        alcance = "provincia" if objetivo else "nacional"
        if not ads:
            return {"alcance": alcance, "redes": [], "resumen": {}, "estado": estado}

        total_paginas, propios, usados = set(), 0, []
        aristas: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for ad in ads:
            if objetivo and self._alcance_en(ad, objetivo) is None:
                continue
            pagina = ad["page_name"] or str(ad["page_id"] or "")
            if not pagina:
                continue
            total_paginas.add(pagina)
            usados.append(ad)
            pagador = (ad["financiador"] or "").strip()
            if not pagador or _misma_entidad(pagador, pagina):
                propios += 1
                continue
            e = aristas.setdefault((pagador, pagina), {
                "pagador": pagador, "pagina": pagina, "page_id": ad["page_id"], "anuncios": 0, "activos": 0,
                "gasto": 0.0, "gasto_min": 0.0, "gasto_max": 0.0, "primero": "", "ultimo": "", "ejemplo_id": ad["id"],
            })
            gasto = ad["gasto"] or {}
            e["anuncios"] += 1
            e["activos"] += 1 if ad["activo"] else 0
            e["gasto"] += _medio(ad["gasto"])
            e["gasto_min"] += gasto.get("min") or 0
            e["gasto_max"] += gasto.get("max") or gasto.get("min") or 0
            if ad["date"]:
                e["primero"] = min(e["primero"] or ad["date"], ad["date"])
                e["ultimo"] = max(e["ultimo"], ad["date"])

        # Redes = componentes conexos del grafo pagador–página.
        padre: Dict[str, str] = {}

        def raiz(x: str) -> str:
            padre.setdefault(x, x)
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        for pagador, pagina in aristas:
            padre[raiz("P:" + pagador)] = raiz("G:" + pagina)

        grupos: Dict[str, List[Dict[str, Any]]] = {}
        for arista in aristas.values():
            grupos.setdefault(raiz("P:" + arista["pagador"]), []).append(arista)

        redes = []
        for miembros in grupos.values():
            pagadores = sorted({m["pagador"] for m in miembros})
            paginas = sorted({m["pagina"] for m in miembros})
            if len(pagadores) == 1 and len(paginas) >= 2:
                tipo = "pagador_compartido"
            elif len(paginas) == 1 and len(pagadores) >= 2:
                tipo = "varios_pagadores"
            elif len(miembros) == 1:
                tipo = "tercero"
            else:
                tipo = "red_mixta"
            redes.append({
                "tipo": tipo,
                "pagadores": pagadores,
                "paginas": paginas,
                "vinculos": [
                    {"pagador": m["pagador"], "pagina": m["pagina"], "page_id": m["page_id"], "anuncios": m["anuncios"],
                     "activos": m["activos"], "gasto": {"min": round(m["gasto_min"]), "max": round(m["gasto_max"]), "medio": round(m["gasto"])},
                     "primer_anuncio": m["primero"], "ultimo_anuncio": m["ultimo"],
                     "ejemplo_link": f"https://www.facebook.com/ads/library/?id={m['ejemplo_id']}" if m["ejemplo_id"] else ""}
                    for m in sorted(miembros, key=lambda m: m["gasto"], reverse=True)
                ],
                "anuncios": sum(m["anuncios"] for m in miembros),
                "gasto_medio": round(sum(m["gasto"] for m in miembros)),
            })
        # Primero lo más conectado (más páginas/pagadores), luego por inversión.
        redes.sort(key=lambda r: (len(r["paginas"]) + len(r["pagadores"]), r["gasto_medio"]), reverse=True)
        n_conectadas = sum(1 for r in redes if r["tipo"] != "tercero")
        indice = _cargar_afiliaciones()
        for r in redes:
            ids = {v["pagina"]: v["page_id"] for v in r["vinculos"]}
            r["afiliaciones"] = {
                nombre: dato for nombre, dato in (
                    [(p, _afiliacion(indice, p, ids.get(p))) for p in r["paginas"]]
                    + [(p, _afiliacion(indice, p)) for p in r["pagadores"]]
                ) if dato and dato["verificado"]
            }
        try:
            # Los grupos que el equipo ya revisó (mensajes_revisados.json) no se dibujan: dejan de ser una señal.
            r_textos = self.textos_duplicados(provincia, limite=200, sin_cne=sin_cne)
            textos, textos_revisados = r_textos.get("grupos", []), r_textos.get("total_revisados", 0)
        except Exception as e:  # el grafo sigue funcionando sin la capa de textos
            logger.warning(f"[AdLibrary] Textos repetidos no disponibles para el grafo: {type(e).__name__}")
            textos, textos_revisados = [], 0
        grafo = self._grafo_red(usados, aristas, textos, indice, max_paginas=max_paginas, garantizar_provincias=not objetivo)
        return {
            "alcance": alcance,
            "resumen": {
                "paginas": len(total_paginas),
                "pagan_ellas_mismas": propios,
                "vinculos_con_tercero": len(aristas),
                "redes_conectadas": n_conectadas,
                "pagadores_terceros": len({a["pagador"] for a in aristas.values()}),
            },
            "redes": redes[:max(1, limite)],
            "total_redes": len(redes),
            "grafo": grafo,
            "textos_revisados": textos_revisados,
            "estado": estado,
            "nota": "Un vínculo aparece cuando el pagador declarado a Meta no coincide con el nombre de la página. "
                    "Agencias, partidos y campañas pagan legítimamente por terceros: es una pista para investigar, no una prueba.",
        }

    def _grafo_red(self, usados: List[Dict[str, Any]], aristas_pagador: Dict[Tuple[str, str], Dict[str, Any]],
                   textos: List[Dict[str, Any]], indice: Dict[str, Dict[str, Any]],
                   max_paginas_enlace: int = 8, max_paginas: int = 80, garantizar_provincias: bool = False) -> Dict[str, Any]:
        """
        Grafo plano para el frontend. Nodos: pagadores, páginas y provincias (centros). Aristas de seis tipos:
        `pagador` (pagador declarado distinto de la página), `enlace` (páginas con el mismo enlace/dominio en sus
        anuncios), `texto` (páginas con anuncios de texto casi idéntico), `alcance` (página -> la provincia donde
        llega más), `partido` (la página del partido con las demás de su partido) y `partido_prov` (conector entre
        las provincias donde un mismo partido tiene candidatos). Entran todas las páginas conectadas y, hasta
        `max_paginas`, las de mayor inversión, de modo que todo nodo tiene al menos una conexión.
        """
        por_pagina: Dict[str, List[Dict[str, Any]]] = {}
        for ad in usados:
            por_pagina.setdefault(ad["page_name"] or str(ad["page_id"] or ""), []).append(ad)

        aristas: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        def par(a: str, b: str) -> Tuple[str, str]:
            return (a, b) if a <= b else (b, a)

        def conectar(tipo: str, paginas: List[str], detalle: str, primero: str, ultimo: str) -> None:
            paginas = sorted(set(paginas))
            if len(paginas) < 2:
                return
            pares = ([(x, y) for i, x in enumerate(paginas) for y in paginas[i + 1:]] if len(paginas) <= 6
                     else [(paginas[0], y) for y in paginas[1:]])
            for x, y in pares:
                a, b = par("G:" + x, "G:" + y)
                e = aristas.setdefault((a, b, tipo), {"a": a, "b": b, "tipo": tipo, "detalles": [], "primero": "", "ultimo": ""})
                if detalle and detalle not in e["detalles"] and len(e["detalles"]) < 3:
                    e["detalles"].append(detalle)
                if primero:
                    e["primero"] = min(e["primero"] or primero, primero)
                if ultimo:
                    e["ultimo"] = max(e["ultimo"], ultimo)

        # enlaces compartidos
        enlaces: Dict[str, Dict[str, Any]] = {}
        for ad in usados:
            for url in _URL_RE.findall(ad["text"] or ""):
                clave = _clave_enlace(url)
                if clave:
                    g = enlaces.setdefault(clave, {"paginas": set(), "fechas": []})
                    g["paginas"].add(ad["page_name"])
                    if ad["date"]:
                        g["fechas"].append(ad["date"])
        for clave, g in enlaces.items():
            if 2 <= len(g["paginas"]) <= max_paginas_enlace:
                f = sorted(g["fechas"])
                conectar("enlace", list(g["paginas"]), clave, f[0] if f else "", f[-1] if f else "")

        # textos repetidos
        for grupo in textos:
            conectar("texto", [p["page_name"] for p in grupo["paginas"]], (grupo["texto"] or "").strip()[:90],
                     grupo.get("primer_anuncio") or "", grupo.get("ultimo_anuncio") or "")

        # pagadores
        for (pagador, pagina), e in aristas_pagador.items():
            aristas[("P:" + pagador, "G:" + pagina, "pagador")] = {
                "a": "P:" + pagador, "b": "G:" + pagina, "tipo": "pagador", "anuncios": e["anuncios"], "activos": e["activos"],
                "gasto": {"min": round(e["gasto_min"]), "max": round(e["gasto_max"]), "medio": round(e["gasto"])},
                "primero": e["primero"], "ultimo": e["ultimo"],
                "ejemplo_link": f"https://www.facebook.com/ads/library/?id={e['ejemplo_id']}" if e["ejemplo_id"] else "",
                "detalles": [],
            }

        # nodos (solo los conectados)
        ids_usados = {x for e in aristas.values() for x in (e["a"], e["b"])}
        for n_pag, ads_pag in por_pagina.items():   # las páginas con partido siempre entran (pueden unirse a su partido)
            dato = _afiliacion(indice, n_pag, ads_pag[0].get("page_id"))
            if dato and dato.get("partido"):
                ids_usados.add("G:" + n_pag)
        principal_por_pagina = self._region_principal_por_pagina(usados)
        if garantizar_provincias:
            # Vista nacional: ninguna provincia con anuncios queda fuera. Si ninguna página ya incluida llega sobre todo a una provincia,
            # entran sus páginas de mayor inversión (así el nodo de la provincia nace con conexiones y no hay nodos sueltos).
            con_provincia = {principal_por_pagina[n][0] for n in por_pagina if "G:" + n in ids_usados and n in principal_por_pagina}
            pendientes: Dict[str, List[str]] = {}
            for n, (region, _) in principal_por_pagina.items():
                if region not in con_provincia and n in por_pagina:
                    pendientes.setdefault(region, []).append(n)
            for paginas_region in pendientes.values():
                paginas_region.sort(key=lambda n: sum(_medio(a["gasto"]) for a in por_pagina[n]), reverse=True)
                for n in paginas_region[:PAGINAS_POR_PROVINCIA_GARANTIZADAS]:
                    ids_usados.add("G:" + n)
        conectadas = sum(1 for i in ids_usados if i.startswith("G:"))
        resto = sorted(
            (n for n, ads_n in por_pagina.items() if "G:" + n not in ids_usados and any(a["regiones"] for a in ads_n)),
            key=lambda n: sum(_medio(a["gasto"]) for a in por_pagina[n]), reverse=True)
        for n in resto[:max(0, max_paginas - conectadas)]:
            ids_usados.add("G:" + n)
        nodos: List[Dict[str, Any]] = []

        def estado_afil(nombre: str, page_id: Any = None) -> Dict[str, Any]:
            dato = _afiliacion(indice, nombre, page_id)
            if not dato:
                return {"afiliacion": None, "afiliacion_estado": "sin_registro"}
            return {"afiliacion": dato, "afiliacion_estado": "verificada" if dato["verificado"] else "pendiente"}

        for nid in sorted(ids_usados):
            nombre = nid[2:]
            if nid.startswith("P:"):
                gasto = sum(e["gasto"]["medio"] for e in aristas.values() if e["tipo"] == "pagador" and e["a"] == nid)
                anuncios = sum(e["anuncios"] for e in aristas.values() if e["tipo"] == "pagador" and e["a"] == nid)
                nodos.append({"id": nid, "nombre": nombre, "tipo": "pagador", "anuncios": anuncios,
                              "gasto": {"medio": round(gasto)}, **estado_afil(nombre)})
                continue
            ads = por_pagina.get(nombre, [])
            if not ads:
                continue
            gmin = sum((a["gasto"] or {}).get("min") or 0 for a in ads)
            gmax = sum((a["gasto"] or {}).get("max") or (a["gasto"] or {}).get("min") or 0 for a in ads)
            reg: Dict[str, float] = {}
            demo_edad: Dict[str, float] = {}
            demo_gen: Dict[str, float] = {}
            plataformas = set()
            for a in ads:
                peso = _medio(a["impresiones"]) or 1.0
                plataformas.update(a["plataformas"] or [])
                for r in a["regiones"]:
                    n = _nombre_region(r["region"])
                    reg[n] = reg.get(n, 0.0) + r["porcentaje"] * peso
                for d in a["demografia"] or []:
                    edad, genero, pct = (d.get("age"), d.get("gender"), d.get("percentage")) if isinstance(d, dict) else d   # copia compacta: ternas
                    p = _to_float(pct) * peso
                    demo_edad[edad or "?"] = demo_edad.get(edad or "?", 0.0) + p
                    demo_gen[genero or "unknown"] = demo_gen.get(genero or "unknown", 0.0) + p
            total_reg, total_demo = sum(reg.values()), sum(demo_edad.values())
            principal = max(reg.items(), key=lambda kv: kv[1]) if reg else None
            fechas = sorted(a["date"] for a in ads if a["date"])
            rep = max(ads, key=lambda a: _medio(a["impresiones"]))
            metas: Dict[str, str] = {}                      # las páginas de Meta que reúne este punto (varias si la entidad está unificada)
            for a in ads:
                metas.setdefault(str(a.get("page_id_meta") or a.get("page_id") or ""), a.get("page_name_meta") or a["page_name"])
            nodos.append({
                "id": nid, "nombre": nombre, "tipo": "pagina", "page_id": ads[0]["page_id"],
                **({"unificada": [{"page_id": pid, "nombre": nm} for pid, nm in metas.items()]} if len(metas) > 1 else {}),
                "anuncios": len(ads), "activos": sum(1 for a in ads if a["activo"]),
                "gasto": {"min": round(gmin), "max": round(gmax), "medio": round(sum(_medio(a["gasto"]) for a in ads))},
                "region": ({"region": principal[0], "pct": round(principal[1] / total_reg, 3)} if principal and total_reg > 0 else None),
                # alcance en cada provincia ([nombre, fracción], de mayor a menor, desde 0,5 %): la red dibuja las demás al seleccionar la página
                "regiones": ([[k, round(v / total_reg, 4)] for k, v in sorted(reg.items(), key=lambda kv: -kv[1]) if v / total_reg >= 0.005]
                             if total_reg > 0 else []),
                "plataformas": sorted(plataformas),
                "edades": ([{"edad": k, "pct": round(v / total_demo, 3)} for k, v in sorted(demo_edad.items())] if total_demo > 0 else []),
                "genero": ({k: round(v / total_demo, 3) for k, v in demo_gen.items()} if total_demo > 0 else {}),
                "primero": fechas[0] if fechas else "", "ultimo": fechas[-1] if fechas else "",
                "texto": (rep["text"] or "").strip()[:200], "ejemplo_link": rep["link"],
                "paga_ella_misma": any(not (a["financiador"] or "").strip() or _misma_entidad(a["financiador"], nombre) for a in ads),
                **estado_afil(nombre, ads[0]["page_id"]),
            })

        # Totales de TODAS las páginas con base en cada provincia (el gráfico solo dibuja las de mayor inversión): son los mismos
        # que devuelve `anuncios(region=…)`, que usa la misma regla de provincia principal.
        totales: Dict[str, Dict[str, float]] = {}
        for clave, (nombre_region, _) in principal_por_pagina.items():
            t = totales.setdefault(nombre_region, {"paginas": 0, "anuncios": 0, "gasto": 0.0})
            t["paginas"] += 1
            t["anuncios"] += len(por_pagina.get(clave, []))
            t["gasto"] += sum(_medio(a["gasto"]) for a in por_pagina.get(clave, []))

        # Centros por provincia: cada página se une a la provincia donde llega más (así nunca queda un nodo suelto).
        centros: Dict[str, Dict[str, Any]] = {}
        for n in [x for x in nodos if x["tipo"] == "pagina" and x.get("region")]:
            reg = n["region"]["region"]
            t = totales.get(reg, {"paginas": 0, "anuncios": 0, "gasto": 0.0})
            h = centros.setdefault("R:" + reg, {"id": "R:" + reg, "nombre": reg, "tipo": "provincia", "anuncios": 0, "paginas": 0,
                                                "gasto": {"medio": 0}, "paginas_total": int(t["paginas"]), "anuncios_total": int(t["anuncios"]),
                                                "gasto_total": {"medio": round(t["gasto"])},
                                                "afiliacion": None, "afiliacion_estado": "sin_registro"})
            h["anuncios"] += n["anuncios"]
            h["paginas"] += 1
            h["gasto"]["medio"] += n["gasto"]["medio"]
            aristas[(n["id"], h["id"], "alcance")] = {"a": n["id"], "b": h["id"], "tipo": "alcance", "pct": n["region"]["pct"],
                                                      "primero": n["primero"], "ultimo": n["ultimo"], "detalles": []}
        nodos.extend(centros.values())

        # Partidos: la entrada de tipo «partido» (p. ej. la página oficial) se une a todos los demás nodos de su partido.
        por_partido: Dict[str, List[Dict[str, Any]]] = {}
        for n in nodos:
            dato = n.get("afiliacion")
            if n["tipo"] != "provincia" and dato and dato.get("partido"):
                por_partido.setdefault(dato["partido"], []).append(n)
        for nombre_partido, miembros in por_partido.items():
            if _es_neutral(nombre_partido):
                continue                                    # «Neutral» no es una organización: sin centro ni aristas de partido
            centro = next((n for n in miembros if n["afiliacion"].get("tipo") == "partido"), None)
            if not centro:
                continue
            for n in miembros:
                if n is not centro:
                    aristas[(centro["id"], n["id"], "partido")] = {"a": centro["id"], "b": n["id"], "tipo": "partido", "partido": nombre_partido,
                                                                    "primero": "", "ultimo": "", "detalles": [nombre_partido]}

        # Conectores entre soles: las provincias donde un mismo partido tiene candidatos se unen entre sí, con una línea por partido y par de
        # provincias. Cuentan las páginas de personas (tipo «candidato» o «persona») con partido, en la provincia donde llegan más; «Neutral»
        # no es un partido. La línea es «verificada» si en sus dos extremos hay al menos un candidato con afiliación verificada; si no, la
        # vista solo la muestra al incluir los partidos sin verificar. Dos candidatos del mismo partido en una misma provincia no necesitan línea.
        soles_de_partido: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for n in nodos:
            dato = n.get("afiliacion")
            if (n["tipo"] != "pagina" or not dato or not dato.get("partido") or _es_neutral(dato["partido"])
                    or dato.get("tipo") not in TIPOS_CANDIDATO or not n.get("region")):
                continue
            soles_de_partido.setdefault(dato["partido"], {}).setdefault("R:" + n["region"]["region"], []).append(n)

        def quienes(miembros: List[Dict[str, Any]]) -> str:
            nombres = [m["nombre"] for m in sorted(miembros, key=lambda m: -m["gasto"]["medio"])]
            return ", ".join(nombres[:2]) + (f" y {len(nombres) - 2} más" if len(nombres) > 2 else "")

        for nombre_partido, soles in soles_de_partido.items():
            ids_soles = sorted(s for s in soles if s in centros)
            for i, x in enumerate(ids_soles):
                for y in ids_soles[i + 1:]:
                    mx, my = soles[x], soles[y]
                    verificada = (any(m["afiliacion"].get("verificado") for m in mx) and any(m["afiliacion"].get("verificado") for m in my))
                    aristas[(x, y, "partido_prov|" + nombre_partido)] = {
                        "a": x, "b": y, "tipo": "partido_prov", "partido": nombre_partido, "verificada": verificada, "primero": "", "ultimo": "",
                        "detalles": [f"{nombre_partido}: {quienes(mx)} ({x[2:]}) ↔ {quienes(my)} ({y[2:]})"],
                        "candidatos": [{"id": m["id"], "nombre": m["nombre"], "sol": s, "verificado": bool(m["afiliacion"].get("verificado"))}
                                       for s, miembros in ((x, mx), (y, my)) for m in miembros],
                    }

        existentes = {n["id"] for n in nodos}
        lista_aristas = [e for e in aristas.values() if e["a"] in existentes and e["b"] in existentes]
        conteo = {"verificada": 0, "pendiente": 0, "sin_registro": 0}
        for n in nodos:
            if n["tipo"] != "provincia":
                conteo[n["afiliacion_estado"]] += 1
        return {
            "nodos": nodos, "aristas": lista_aristas,
            "tipos": {t: sum(1 for e in lista_aristas if e["tipo"] == t) for t in ("pagador", "enlace", "texto", "alcance", "partido", "partido_prov")},
            "partidos": _cargar_partidos(),
            "afiliaciones": conteo,
        }

    def enlaces_par(self, pagina_a: str, pagina_b: str, provincia: Optional[str] = None, sin_cne: bool = False,
                    max_paginas_enlace: int = 8) -> Dict[str, Any]:
        """
        Los enlaces que comparten dos páginas, con los anuncios de cada una que los llevan (texto, fechas y su propio enlace a la Biblioteca de
        Meta) para verlos lado a lado. Es el detalle de una línea «mismo enlace» de la red y sigue su misma regla: `_clave_enlace` y un enlace
        que usan más de `max_paginas_enlace` páginas no cuenta. El formato de cada grupo es el de `textos_duplicados(entre=…)`.
        """
        ads, estado = self.obtener_nacional()
        ads = _sin_cne(ads, sin_cne)
        objetivo = _norm(provincia) if provincia else ""
        if objetivo in ("todas", "ecuador", "ecuador todas"):
            objetivo = ""
        par = {pagina_a, pagina_b}
        paginas_de: Dict[str, set] = {}                      # clave de enlace -> páginas que la usan (todas, para aplicar el tope de la red)
        del_par: Dict[str, Dict[str, Any]] = {}              # clave -> {"urls": {...}, "ads": {id: anuncio}} solo con anuncios de las dos páginas
        for ad in ads:
            if objetivo and self._alcance_en(ad, objetivo) is None:
                continue
            pagina = ad["page_name"] or str(ad["page_id"] or "")
            if not pagina:
                continue
            for url in _URL_RE.findall(ad["text"] or ""):
                clave = _clave_enlace(url)
                if not clave:
                    continue
                paginas_de.setdefault(clave, set()).add(pagina)
                if pagina in par:
                    g = del_par.setdefault(clave, {"urls": {}, "ads": {}})
                    limpia = url.rstrip(".,;:!?")
                    g["urls"][limpia] = g["urls"].get(limpia, 0) + 1
                    g["ads"][ad["id"]] = ad
        indice = _cargar_afiliaciones()
        grupos: List[Dict[str, Any]] = []
        for clave, g in del_par.items():
            miembros = list(g["ads"].values())
            if not par <= {a["page_name"] for a in miembros} or len(par) < 2 or len(paginas_de[clave]) > max_paginas_enlace:
                continue
            fechas = sorted(a["date"] for a in miembros if a["date"])
            tabla_textos: Dict[str, int] = {}
            detalle: List[Dict[str, Any]] = []
            por_pagina: Dict[str, int] = {}
            omitidos = 0
            for a in sorted(miembros, key=lambda a: (a["date"] or "", a["id"])):
                if por_pagina.get(a["page_name"], 0) >= MAX_ANUNCIOS_POR_PAGINA_DETALLE:
                    omitidos += 1
                    continue
                por_pagina[a["page_name"]] = por_pagina.get(a["page_name"], 0) + 1
                detalle.append({"id": a["id"], "page_name": a["page_name"], "page_id": a.get("page_id"), "fecha": a["date"], "fecha_fin": a["fecha_fin"],
                                "activo": a["activo"], "t": tabla_textos.setdefault((a["text"] or "")[:1500], len(tabla_textos)), "link": a["link"],
                                "financiador": a["financiador"], "moneda": a["moneda"], "gasto": a["gasto"], "impresiones": a["impresiones"],
                                "plataformas": a["plataformas"]})
            ids = {a["page_name"]: a.get("page_id") for a in miembros}
            grupos.append({
                "clave": clave, "por_dominio": "/" not in clave and "?" not in clave,
                "urls": [u for u, _ in sorted(g["urls"].items(), key=lambda kv: (-kv[1], kv[0]))[:6]], "n_urls": len(g["urls"]),
                "anuncios": len(miembros), "n_paginas": len(paginas_de[clave]),
                "otras_paginas": sorted(paginas_de[clave] - par),
                "paginas": [{"page_name": p, "page_id": ids.get(p), "afiliacion": _afiliacion(indice, p, ids.get(p)),
                             "anuncios": sum(1 for a in miembros if a["page_name"] == p)} for p in (pagina_a, pagina_b)],
                "primer_anuncio": fechas[0] if fechas else "", "ultimo_anuncio": fechas[-1] if fechas else "",
                "detalle": {"textos": list(tabla_textos), "anuncios": detalle, "omitidos": omitidos},
            })
        grupos.sort(key=lambda x: (-x["anuncios"], x["clave"]))
        return {"alcance": "provincia" if objetivo else "nacional", "pagina_a": pagina_a, "pagina_b": pagina_b, "grupos": grupos, "estado": estado}

    def guardar_afiliacion(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crea o actualiza una entrada de backend/afiliaciones.json (se busca por nombre normalizado, sin tildes, o por cualquiera de
        sus ID de página) y guarda el archivo completo de forma atómica. `page_ids` es opcional: todos los ID de página de la
        entidad (una misma persona puede tener varias páginas); si no se envía, se conservan los que ya tenía.
        Lanza ValueError con un mensaje legible si los datos no son válidos.
        """
        def limpio(clave: str, largo: int = 300) -> Optional[str]:
            v = datos.get(clave)
            v = unicodedata.normalize("NFC", v.strip()) if isinstance(v, str) else None     # NFC: una «ñ» se guarda siempre igual
            return v[:largo] if v else None

        nombre = limpio("nombre", 200)
        if not nombre:
            raise ValueError("Falta el nombre.")
        tipo, afil, partido = limpio("tipo", 30), limpio("afiliacion"), limpio("partido", 60)
        fuente, page_id = limpio("fuente", 500), limpio("page_id", 40)
        ids_nuevos = _parsear_page_ids(datos.get("page_ids"))
        otros_nuevos = _parsear_otros_nombres(datos.get("otros_nombres"), nombre)
        verificado = bool(datos.get("verificado"))
        if tipo and tipo not in TIPOS_AFILIACION:
            raise ValueError("El tipo no es válido.")
        if partido and _es_neutral(partido):
            # Un medio puede mantenerse neutral (no responde a un partido); para el resto de entidades no tiene sentido.
            partido = PARTIDO_NEUTRAL
            if tipo and tipo not in TIPOS_NEUTRALES:
                raise ValueError("«Neutral» solo se puede usar en medios: cambia el tipo a «medio» o elige otro partido.")
            tipo = tipo or "medio"
            afil = afil or AFIL_NEUTRAL                     # sin afiliación la entrada no se indexa ni se ve en la red
        if fuente and not re.match(r"^https?://\S+$", fuente):
            raise ValueError("La fuente debe ser un enlace que empiece por http:// o https://")
        if verificado and not afil:
            raise ValueError("Para marcarla como verificada escribe la afiliación.")
        if verificado and not fuente:
            raise ValueError("Para marcarla como verificada agrega el enlace de la fuente.")

        with _LOCK_AFIL:
            contenido = _leer_afiliaciones()
            entidades = contenido.setdefault("entidades", [])
            clave = _norm_entidad(nombre)
            buscados = set(ids_nuevos or []) | ({page_id} if page_id else set())
            nombres_buscados = {clave} | {_norm_entidad(n) for n in (otros_nuevos or [])}
            coinciden = [i for i, e in enumerate(entidades) if (nombres_buscados & set(_nombres_de(e))) or (buscados & set(_ids_de(e)))]
            if len(coinciden) > 1:
                dos = " y ".join(f"«{entidades[i].get('nombre')}»" for i in coinciden[:2])
                raise ValueError(f"Las entradas {dos} comparten nombre, otro nombre o ID de página: únelas con «Unificar» antes de guardar.")
            idx = coinciden[0] if coinciden else None
            nuevo = {"page_id": page_id, "tipo": tipo, "afiliacion": afil, "partido": partido, "fuente": fuente,
                     "verificado": verificado, "actualizado": date.today().isoformat() if (tipo or afil or partido or fuente or verificado) else None}
            if idx is None:
                entrada = {"nombre": nombre, **nuevo}
                if not entrada["page_id"] and ids_nuevos:
                    entrada["page_id"] = ids_nuevos[0]
                if ids_nuevos:
                    entrada["page_ids"] = ids_nuevos
                if otros_nuevos:
                    entrada["otros_nombres"] = otros_nuevos
                entrada = _ordenar_entrada(entrada)
                entidades.append(entrada)
            else:
                previo = entidades[idx]
                nuevo["page_id"] = page_id or previo.get("page_id") or (ids_nuevos[0] if ids_nuevos else None)
                entrada = {**previo, **nuevo}
                if ids_nuevos is not None:
                    if ids_nuevos:
                        entrada["page_ids"] = ids_nuevos
                    else:
                        entrada.pop("page_ids", None)
                if otros_nuevos is not None:
                    if otros_nuevos:
                        entrada["otros_nombres"] = otros_nuevos
                    else:
                        entrada.pop("otros_nombres", None)
                entrada = _ordenar_entrada(entrada)
                entidades[idx] = entrada
            if isinstance(entrada.get("page_ids"), list) and entrada.get("page_id") and str(entrada["page_id"]) not in entrada["page_ids"]:
                entrada["page_ids"] = [str(entrada["page_id"])] + entrada["page_ids"]       # el ID principal siempre forma parte de la lista
            _escribir_afiliaciones(contenido)
        estado = "verificada" if verificado else ("pendiente" if afil else "vacia")
        logger.info(f"[Afiliaciones] Guardada «{nombre}» ({estado}).")
        return {"ok": True, "entidad": {**entrada, "estado": estado, "problemas": []}}

    def unificar_afiliaciones(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Une varias entradas de backend/afiliaciones.json en una: la persona o entidad que aparece con otro nombre (el pagador con su
        segundo nombre, la página con y sin «ñ») o con otra página de Meta.
          - principal: {nombre, page_id?} de la entrada que se conserva (si aún no existe, se crea);
          - otras: [{nombre, page_id?}] que pasan a ser la principal: sus ID de página se suman a `page_ids` y sus nombres a
            `otros_nombres`, y su entrada se borra (si no tenía entrada, solo se suman su nombre y su ID);
          - nombre_final (opcional): nuevo nombre de la entrada unificada (el anterior pasa a `otros_nombres`).
        La principal conserva su afiliación, partido, fuente y verificación; si no tenía afiliación se toma la de la primera que sí la
        tenga. Una verificación de otra entrada con la misma afiliación se conserva. Si las afiliaciones difieren, se descarta la de las
        otras y se devuelve en `conflictos`. Lanza ValueError con un mensaje legible si los datos no son válidos.
        """
        def limpio(v: Any, largo: int = 200) -> Optional[str]:
            v = unicodedata.normalize("NFC", v.strip()) if isinstance(v, str) else None
            return v[:largo] if v else None

        def ref(r: Any) -> Dict[str, Optional[str]]:
            r = r if isinstance(r, dict) else {}
            pid = limpio(r.get("page_id"), 40)
            if pid and not re.fullmatch(r"\d{1,40}", pid):
                raise ValueError(f"El ID de página «{pid[:40]}» no es válido (solo dígitos).")
            return {"nombre": limpio(r.get("nombre")), "page_id": pid}

        principal = ref(datos.get("principal"))
        otras = [ref(o) for o in (datos.get("otras") or [])]
        nombre_final = limpio(datos.get("nombre_final"))
        if not (principal["nombre"] or principal["page_id"]):
            raise ValueError("Falta la entidad principal.")
        if not otras or any(not (o["nombre"] or o["page_id"]) for o in otras):
            raise ValueError("Elige al menos otra entidad para unificar.")
        if len(otras) > 10:
            raise ValueError("No se pueden unificar más de 11 entidades a la vez.")

        with _LOCK_AFIL:
            contenido = _leer_afiliaciones()
            entidades = contenido.setdefault("entidades", [])

            def buscar(r: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
                n = _norm_entidad(r["nombre"])
                return [e for e in entidades if (n and n in _nombres_de(e)) or (r["page_id"] and r["page_id"] in _ids_de(e))]

            ya = buscar(principal)
            if len(ya) > 1:
                dos = " y ".join(f"«{e.get('nombre')}»" for e in ya[:2])
                raise ValueError(f"La entidad principal coincide con varias entradas ({dos}): elige una de ellas.")
            if ya:
                base = ya[0]
            else:
                if not principal["nombre"]:
                    raise ValueError("Falta el nombre de la entidad principal.")
                base = {"nombre": principal["nombre"], "page_id": principal["page_id"], "tipo": None, "afiliacion": None,
                        "partido": None, "fuente": None, "verificado": False, "actualizado": None}
                entidades.append(base)

            absorbidas: List[Dict[str, Any]] = []         # entradas del archivo que desaparecen
            sueltas: List[Dict[str, Any]] = []            # nombres o páginas sin entrada que se suman
            for r in otras:
                halladas = [e for e in buscar(r) if e is not base]
                for e in halladas:
                    if not any(e is x for x in absorbidas):
                        absorbidas.append(e)
                if not halladas:
                    # Sin entrada propia: solo aporta lo que la principal aún no tiene (un ID de página o un nombre distinto).
                    nuevo_id = bool(r["page_id"]) and r["page_id"] not in _ids_de(base)
                    nuevo_nombre = bool(r["nombre"]) and _norm_entidad(r["nombre"]) not in _nombres_de(base)
                    if nuevo_id or nuevo_nombre:
                        sueltas.append({"nombre": r["nombre"], "page_id": r["page_id"]})
            if not absorbidas and not sueltas:
                raise ValueError("Esas entradas ya son la misma entidad.")

            ids = _ids_de(base)
            nombres_extra: List[Any] = list(base.get("otros_nombres") or [])
            conflictos: List[str] = []
            for o in absorbidas + sueltas:
                for pid in _ids_de(o):
                    if pid not in ids:
                        ids.append(pid)
                nombres_extra += [o.get("nombre")] + list(o.get("otros_nombres") or [])
                if o.get("afiliacion"):
                    if not base.get("afiliacion"):
                        for k in ("tipo", "afiliacion", "partido", "fuente", "verificado", "actualizado"):
                            base[k] = o.get(k)
                    elif _norm(o.get("afiliacion")) == _norm(base.get("afiliacion")) and _norm(o.get("partido")) == _norm(base.get("partido")):
                        if o.get("verificado") and o.get("fuente") and not (base.get("verificado") and base.get("fuente")):
                            base["verificado"], base["fuente"] = True, o["fuente"]
                            base["actualizado"] = o.get("actualizado") or base.get("actualizado")
                    else:
                        conflictos.append(f"«{o.get('nombre')}» tenía «{o['afiliacion']}»; se conservó «{base['afiliacion']}».")
                if not base.get("tipo") and o.get("tipo"):
                    base["tipo"] = o["tipo"]

            if nombre_final and _norm_entidad(nombre_final) != _norm_entidad(base.get("nombre")):
                nombres_extra.append(base.get("nombre"))      # el nombre anterior pasa a ser un nombre alterno
            if nombre_final:
                base["nombre"] = nombre_final
            otros = _parsear_otros_nombres(nombres_extra, base["nombre"])
            if otros:
                base["otros_nombres"] = otros
            else:
                base.pop("otros_nombres", None)
            if ids:
                base["page_id"] = base.get("page_id") or ids[0]
                if len(ids) > 1 or isinstance(base.get("page_ids"), list):
                    base["page_ids"] = [str(base["page_id"])] + [i for i in ids if i != str(base["page_id"])]
            if base.get("actualizado") is None and (base.get("afiliacion") or base.get("partido") or base.get("fuente")):
                base["actualizado"] = date.today().isoformat()

            # Se borran las entradas absorbidas y se reordenan los campos de la unificada.
            entidades[:] = [e for e in entidades if not any(e is x for x in absorbidas)]
            pos = next(i for i, e in enumerate(entidades) if e is base)
            entidades[pos] = base = _ordenar_entrada(base)
            nombres_base, ids_base = set(_nombres_de(base)), set(_ids_de(base))
            for e in entidades:
                if e is not base and (nombres_base & set(_nombres_de(e)) or ids_base & set(_ids_de(e))):
                    raise ValueError(f"«{e.get('nombre')}» también coincide con esa entidad: inclúyela en la unificación.")
            _escribir_afiliaciones(contenido)
        estado = "verificada" if (base.get("verificado") and base.get("afiliacion") and base.get("fuente")) else ("pendiente" if base.get("afiliacion") else "vacia")
        unidas = [str(o.get("nombre")) for o in absorbidas + sueltas if o.get("nombre")]
        logger.info(f"[Afiliaciones] Unificadas {len(unidas)} entrada(s) en «{base['nombre']}» ({estado}).")
        return {"ok": True, "entidad": {**base, "estado": estado, "problemas": []}, "unidas": unidas, "conflictos": conflictos}

    def afiliaciones_estado(self, faltantes: int = 15) -> Dict[str, Any]:
        """Contenido de afiliaciones.json con su estado y problemas de formato, más las páginas con más inversión sin registro."""
        try:
            with open(RUTA_AFILIACIONES, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError) as e:
            return {"error": f"No se pudo leer afiliaciones.json ({type(e).__name__}).", "entidades": [], "faltantes": [], "resumen": {}}
        tipos = TIPOS_AFILIACION
        entidades, vistos = [], {}
        ids_vistos: Dict[str, int] = {}
        for i, e in enumerate(datos.get("entidades", []), 1):
            problemas = []
            nombre = (e.get("nombre") or "").strip()
            if not nombre:
                problemas.append("Falta el nombre.")
            clave = _norm_entidad(nombre)
            if clave in vistos:
                problemas.append(f"Nombre repetido (también en la entrada {vistos[clave]}).")
            vistos[clave] = i
            otros = e.get("otros_nombres")
            if otros is not None and (not isinstance(otros, list) or any(not isinstance(x, str) or not x.strip() for x in otros)):
                problemas.append("«otros_nombres» debe ser una lista de nombres.")
            for n in _nombres_de(e)[1:]:                      # los otros nombres (el principal ya se revisó arriba)
                if vistos.get(n, i) != i:
                    problemas.append(f"El otro nombre «{n}» también es de la entrada {vistos[n]}.")
                else:
                    vistos[n] = i
            if e.get("tipo") is not None and e["tipo"] not in tipos:
                problemas.append("«tipo» no es válido.")
            if e.get("partido") and _es_neutral(e["partido"]):
                if e["partido"] != PARTIDO_NEUTRAL:
                    problemas.append(f"El partido debe escribirse «{PARTIDO_NEUTRAL}».")
                if e.get("tipo") not in TIPOS_NEUTRALES:
                    problemas.append("«Neutral» solo se usa en medios (tipo «medio»).")
            fuente = e.get("fuente")
            if fuente and not re.match(r"^https?://\S+$", str(fuente)):
                problemas.append("«fuente» debe ser una URL http(s).")
            if e.get("verificado") and not e.get("afiliacion"):
                problemas.append("Marcada como verificada pero falta la afiliación.")
            if e.get("verificado") and not fuente:
                problemas.append("Marcada como verificada pero falta la fuente.")
            if e.get("verificado") and not e.get("actualizado"):
                problemas.append("Falta la fecha «actualizado».")
            ids_e = e.get("page_ids")
            if ids_e is not None and (not isinstance(ids_e, list) or any(not re.fullmatch(r"\d{1,40}", str(x).strip()) for x in ids_e)):
                problemas.append("«page_ids» debe ser una lista de ID de página (solo dígitos).")
            for pid in _ids_de(e):
                if pid in ids_vistos:
                    problemas.append(f"El ID de página {pid} también está en la entrada {ids_vistos[pid]}.")
                else:
                    ids_vistos[pid] = i
            if e.get("afiliacion") and not e.get("verificado"):
                estado = "pendiente"
            elif e.get("verificado") and e.get("afiliacion") and fuente:
                estado = "verificada"
            else:
                estado = "vacia"
            entidades.append({**e, "n": i, "estado": estado, "problemas": problemas})
        conocidos = {n for e in entidades for n in _nombres_de(e)} | {pid for e in entidades for pid in _ids_de(e)}
        sin_registro = []
        try:
            for a in self.top_gastadores(None, 200).get("anunciantes", []):
                if _norm_entidad(a["page_name"]) not in conocidos and str(a["page_id"]) not in conocidos:
                    sin_registro.append({"nombre": a["page_name"], "page_id": a["page_id"], "anuncios": a["anuncios"], "gasto_medio": a["gasto"]["medio"]})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[AdLibrary] No se pudo calcular las páginas sin registro: {type(e).__name__}")
        cuenta = lambda est: sum(1 for e in entidades if e["estado"] == est)  # noqa: E731
        return {
            "archivo": "backend/afiliaciones.json", "leeme": datos.get("_leeme", ""), "campos": datos.get("_campos", {}),
            "resumen": {"total": len(entidades), "verificadas": cuenta("verificada"), "pendientes": cuenta("pendiente"),
                        "vacias": cuenta("vacia"), "con_problemas": sum(1 for e in entidades if e["problemas"]), "sin_registro": len(sin_registro)},
            "entidades": entidades, "faltantes": sin_registro[:max(0, faltantes)],
        }

    def buscar_texto(self, termino: str, limite: int = 5) -> Dict[str, Any]:
        """Anuncios (ya descargados y cacheados) cuyo texto o página contiene el término. No consume cuota de la API."""
        ads, estado = self.obtener_nacional()
        buscado = _norm(termino)
        if not ads or not buscado:
            return {"total": 0, "anuncios": [], "estado": estado}
        patron = re.compile(r"\b" + re.escape(buscado) + r"\b")
        coinciden = [a for a in ads if patron.search(_norm(a["text"])) or patron.search(_norm(a["page_name"]))]
        coinciden.sort(key=lambda a: ((a["impresiones"] or {}).get("max") or 0), reverse=True)
        gasto = sum(((a["gasto"] or {}).get("min") or 0) + ((a["gasto"] or {}).get("max") or (a["gasto"] or {}).get("min") or 0)
                    for a in coinciden) / 2.0
        return {
            "total": len(coinciden),
            "gasto_medio": round(gasto),
            "paginas": len({a["page_name"] for a in coinciden}),
            "anuncios": _anotar_afiliacion(coinciden[:limite]),
            "estado": estado,
        }

    def alcance_por_provincia(self) -> List[Dict[str, Any]]:
        """Impresiones estimadas por provincia: punto medio del rango × porcentaje de alcance de cada anuncio."""
        ads, _ = self.obtener_nacional()
        acumulado: Dict[str, Dict[str, float]] = {}
        for ad in ads:
            imp = ad["impresiones"] or {}
            lo, hi = imp.get("min"), imp.get("max")
            if lo is None and hi is None:
                continue
            medio = float(lo or 0) if hi is None else (float(hi or 0) if lo is None else (lo + hi) / 2.0)
            for r in ad["regiones"]:
                nombre = _nombre_region(r["region"])
                if not nombre or _norm(nombre) not in _PROVINCIAS_EC:
                    continue
                g = acumulado.setdefault(nombre, {"impresiones": 0.0, "anuncios": 0})
                g["impresiones"] += medio * r["porcentaje"]
                g["anuncios"] += 1
        total = sum(g["impresiones"] for g in acumulado.values()) or 1.0
        filas = [{"provincia": n, "impresiones": round(g["impresiones"]), "anuncios": int(g["anuncios"]),
                  "porcentaje": round(g["impresiones"] / total * 100, 1)} for n, g in acumulado.items()]
        filas.sort(key=lambda f: f["impresiones"], reverse=True)
        return filas

    def metricas_por_provincia(self) -> Dict[str, Any]:
        """
        Por provincia: impresiones e inversión estimadas (prorrateadas por el % de alcance de cada anuncio),
        número de anuncios y de anunciantes. Solo cuentan los anuncios que LLEGAN a la provincia (`_alcance_en`): la misma regla
        del resumen, la comparación y las listas de anuncios, así que las cifras coinciden. Alimenta el mapa de burbujas.
        """
        ads, estado = self.obtener_nacional()
        acumulado: Dict[str, Dict[str, Any]] = {}
        fuera = 0.0
        for ad in ads:
            imp, gasto = _medio(ad["impresiones"]), _medio(ad["gasto"])
            fuera += imp * ad.get("_fuera", 0.0)                 # lo que llegó fuera de las 24 provincias (ya sumado al cargar el anuncio)
            for r in ad["regiones"]:
                nombre = r["region"]
                pct = self._alcance_en(ad, _norm(nombre))
                if pct is None:
                    continue
                g = acumulado.setdefault(nombre, {"impresiones": 0.0, "gasto": 0.0, "anuncios": 0, "paginas": set()})
                g["impresiones"] += imp * pct
                g["gasto"] += gasto * pct
                g["anuncios"] += 1
                g["paginas"].add(ad["page_id"] or ad["page_name"])
        provincias = [
            {"provincia": n, "impresiones": round(g["impresiones"]), "gasto": round(g["gasto"]),
             "anuncios": g["anuncios"], "anunciantes": len(g["paginas"])}
            for n, g in acumulado.items()
        ]
        provincias.sort(key=lambda p: p["impresiones"], reverse=True)
        return {"provincias": provincias, "fuera_de_ecuador_impresiones": round(fuera), "estado": estado}

    def comparar(self, alcances: List[Optional[str]]) -> Dict[str, Any]:
        """Compara hasta 3 alcances (None = nacional): resumen, mayores anunciantes y anunciantes en común."""
        columnas = []
        _indice_afil = _cargar_afiliaciones()
        listas: List[Dict[str, Dict[str, Any]]] = []
        estado: Dict[str, Any] = {}
        for provincia in alcances[:3]:
            top = self.top_gastadores(provincia, 500)
            estado = top.get("estado") or estado
            anunciantes = top.get("anunciantes") or []
            resumen = top.get("resumen") or {}
            dup = self.textos_duplicados(provincia, 1)
            columnas.append({
                "alcance": provincia or "Nacional",
                "resumen": {
                    **resumen,
                    "anuncios_activos": sum(a["activos"] for a in anunciantes),
                    "pagador_distinto": sum(1 for a in anunciantes if a["pagado_por_tercero"]),
                },
                "top": anunciantes[:5],
                "mensajes_repetidos": dup.get("total_grupos", 0),
            })
            listas.append({str(a["page_id"] or a["page_name"]): a for a in anunciantes})

        en_comun = []
        if len(listas) >= 2:
            claves = set(listas[0])
            for otra in listas[1:]:
                claves &= set(otra)
            for k in claves:
                nombre = listas[0][k]["page_name"]
                gastos = [l[k]["gasto"]["medio"] for l in listas]
                en_comun.append({"page_name": nombre, "page_id": listas[0][k]["page_id"], "gasto_medio": gastos,
                                 "afiliacion": _afiliacion(_indice_afil, nombre, listas[0][k]["page_id"])})
            en_comun.sort(key=lambda e: sum(e["gasto_medio"]), reverse=True)

        return {"columnas": columnas, "en_comun": en_comun[:10], "total_en_comun": len(en_comun), "estado": estado}

    def _info_textos(self, umbral: float) -> Dict[str, Any]:
        """
        Compara los textos de TODOS los anuncios de la descarga actual una sola vez (con decenas de miles de anuncios cuesta unos segundos) y deja el
        resultado en memoria mientras no cambie la descarga: `por_id` (id del anuncio -> id de su texto, solo los comparables), `retirados` (anuncios que
        Meta sustituyó por su aviso estándar) y `pares` (parejas de textos DISTINTOS con similitud de Jaccard ≥ umbral sobre trigramas de palabras).
        Los anuncios con exactamente el mismo texto comparten id de texto, así que no se comparan entre sí; para el resto se usa el filtro por
        prefijo (solo se comparan textos que comparten alguno de sus trigramas menos frecuentes), que no pierde ninguna pareja que alcance el umbral.

        Para no dar falsos positivos, el texto se compara SIN enlaces, hashtags ni menciones (`_texto_comparable`) y quedan fuera: los avisos estándar
        de Meta, los textos de menos de MIN_PALABRAS_TEXTO palabras y los que aparecen en MAX_PAGINAS_POR_TEXTO páginas o más (`extendidos`: avisos de
        la plataforma o plantillas masivas; se informan aparte). Dos textos parecidos que solo se distinguen por un nombre propio o una cifra
        (`_sustituye_datos`) son la misma plantilla con otro dato, no el mismo mensaje: no se unen y quedan en `vetos` (parejas de ids de texto).
        """
        with self._lock:
            base = self._cache["ads"] if self._cache else []
        with self._lock_textos:
            c = self._textos
            if c is not None and c["base"] is base and c["umbral"] == umbral:
                return c
            por_id: Dict[str, int] = {}
            retirados: set = set()
            textos: Dict[str, int] = {}
            conjuntos: List[frozenset] = []
            originales: List[str] = []                       # el texto de un anuncio de cada id de texto (para ver qué cambia entre dos variantes)
            huellas: List[str] = []                          # huella estable de cada id de texto (así las revisiones reconocen el mismo mensaje)
            paginas_de: List[set] = []
            for ad in base:
                limpio = _texto_comparable(ad["text"])
                if _PLACEHOLDER_RETIRADO.search(limpio):
                    retirados.add(ad["id"])
                    continue
                palabras = limpio.split()
                if len(palabras) < MIN_PALABRAS_TEXTO or _PLACEHOLDER_SIN_DESCARGO.search(limpio):
                    continue
                tid = textos.get(limpio)
                if tid is None:
                    tid = textos[limpio] = len(conjuntos)
                    conjuntos.append(frozenset(hash(" ".join(palabras[i:i + 3])) for i in range(len(palabras) - 2)))
                    originales.append(ad["text"])
                    huellas.append(_huella(limpio))
                    paginas_de.append(set())
                por_id[ad["id"]] = tid
                paginas_de[tid].add(ad["page_name"])

            extendidos: List[Dict[str, Any]] = []
            anuncios_de = collections.Counter(por_id.values())
            for tid, paginas in enumerate(paginas_de):
                if len(paginas) >= MAX_PAGINAS_POR_TEXTO:
                    extendidos.append({"texto": " ".join(str(originales[tid]).split())[:160], "paginas": len(paginas), "anuncios": anuncios_de[tid]})
                    conjuntos[tid] = frozenset()                # fuera de la comparación: ni se une con otros textos ni forma grupo
            if extendidos:
                fuera = {tid for tid, paginas in enumerate(paginas_de) if len(paginas) >= MAX_PAGINAS_POR_TEXTO}
                por_id = {i: t for i, t in por_id.items() if t not in fuera}
            extendidos.sort(key=lambda e: -e["paginas"])

            vetos: List[Tuple[int, int]] = []
            frecuencia: Dict[int, int] = {}
            for s in conjuntos:
                for g in s:
                    frecuencia[g] = frecuencia.get(g, 0) + 1
            indice: Dict[int, List[int]] = {}
            pares: List[Tuple[int, int, float]] = []
            for k, sk in enumerate(conjuntos):
                nk = len(sk)
                ordenado = sorted(sk, key=lambda g: (frecuencia[g], g))
                prefijo = ordenado[:max(1, nk - ceil(umbral * nk) + 1)]
                vistos: set = set()
                for g in prefijo:
                    for j in indice.get(g, ()):
                        if j in vistos:
                            continue
                        vistos.add(j)
                        sj = conjuntos[j]
                        nj = len(sj)
                        if nj < umbral * nk or nk < umbral * nj:   # por tamaño no pueden llegar al umbral
                            continue
                        comunes = len(sk & sj)
                        sim = comunes / (nk + nj - comunes)
                        if sim >= umbral:
                            if _sustituye_datos(originales[j], originales[k]):
                                vetos.append((j, k))            # la misma plantilla con otro nombre o cifra: otro mensaje
                                continue
                            pares.append((j, k, sim))
                for g in prefijo:
                    indice.setdefault(g, []).append(k)
            self._textos = {"base": base, "umbral": umbral, "por_id": por_id, "retirados": retirados, "pares": pares,
                            "extendidos": extendidos, "vetos": vetos, "huellas": huellas}
            return self._textos

    def precalcular(self) -> None:
        """Deja lista la comparación de textos de la descarga actual (la primera consulta de mensajes repetidos o de la red no la espera)."""
        try:
            self._info_textos(0.8)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[AdLibrary] No se pudo precalcular la comparación de textos: {type(e).__name__}")

    def textos_duplicados(self, provincia: Optional[str] = None, limite: int = 10,
                          umbral: float = 0.8, sin_cne: bool = False, revisados: bool = False,
                          entre: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
        """
        Agrupa anuncios con texto casi idéntico (similitud de Jaccard sobre n-gramas de palabras)
        y devuelve los grupos que aparecen en 2 o más páginas distintas. Es un indicador de
        posible coordinación, no una prueba: partidos y gobiernos también reutilizan mensajes.

        Con `entre=(página A, página B)` (nombres tal como salen en los grupos) solo se devuelven los grupos donde están las dos páginas, incluidos
        los ya revisados, y cada uno trae su `detalle` para verlos lado a lado: `textos` (cada texto distinto, completo), `anuncios` (cada anuncio
        con su fecha, su pagador, sus rangos y su propio enlace a la Biblioteca de Meta; hasta MAX_ANUNCIOS_POR_PAGINA_DETALLE por página,
        los más antiguos primero) y `omitidos`.

        Los grupos que el equipo ya revisó (backend/mensajes_revisados.json) no cuentan como señal: se omiten, salvo con `revisados=True`, que los
        incluye al final con su `revision`. Un grupo con páginas que la revisión no vio (`revision.estado == "parcial"`) sigue siendo una señal.
        """
        ads, estado = self.obtener_nacional()
        ads = _sin_cne(ads, sin_cne)
        objetivo = _norm(provincia) if provincia else ""
        if objetivo in ("todas", "ecuador", "ecuador todas"):
            objetivo = ""
        if entre:
            revisados = True                                   # entre dos páginas se ve todo: lo ya revisado va marcado
        base = {"alcance": "provincia" if objetivo else "nacional", "umbral": umbral, "grupos": [], "analizados": 0, "total_grupos": 0, "estado": estado}
        if entre:
            base["entre"] = list(entre)
        if not ads:
            return base

        # La comparación de textos de TODA la descarga se hace una sola vez (ver _info_textos); aquí solo se filtra por provincia y se agrupa.
        info = self._info_textos(umbral)
        por_id, retirados_ids = info["por_id"], info["retirados"]
        candidatos: List[Tuple[Dict[str, Any], int]] = []
        retirados: Dict[str, int] = {}
        for ad in ads:
            if objetivo and self._alcance_en(ad, objetivo) is None:
                continue
            if ad["id"] in retirados_ids:
                # Aviso estándar de Meta en lugar del anuncio retirado: se cuenta aparte.
                retirados[ad["page_name"]] = retirados.get(ad["page_name"], 0) + 1
                continue
            tid = por_id.get(ad["id"])
            if tid is not None:
                candidatos.append((ad, tid))

        # Los textos distintos que se parecen (≥ umbral) se unen; los anuncios con el mismo texto ya comparten texto.
        presentes = {tid for _, tid in candidatos}
        padre = {tid: tid for tid in presentes}

        def raiz(x: int) -> int:
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        sim_min: Dict[int, float] = {}
        for a, b, sim in info["pares"]:
            if a in presentes and b in presentes:
                ra, rb = raiz(a), raiz(b)
                if ra != rb:
                    padre[rb] = ra
                    sim_min[ra] = min(sim_min.get(ra, 1.0), sim_min.pop(rb, 1.0), sim)
                else:
                    sim_min[ra] = min(sim_min.get(ra, 1.0), sim)

        grupos_idx: Dict[int, List[int]] = {}
        for i, (_, tid) in enumerate(candidatos):
            grupos_idx.setdefault(raiz(tid), []).append(i)

        def medio(r: Optional[Dict[str, Optional[int]]]) -> float:
            if not r:
                return 0.0
            lo, hi = r.get("min"), r.get("max")
            return float(lo or 0) if hi is None else (float(hi or 0) if lo is None else (lo + hi) / 2.0)

        def dias_entre(primero: str, ultimo: str) -> Optional[int]:
            try:
                return (date.fromisoformat(ultimo[:10]) - date.fromisoformat(primero[:10])).days
            except ValueError:
                return None

        grupos = []
        paginas_de_grupo: List[List[str]] = []
        _indice_afil = _cargar_afiliaciones()
        _revisiones = _cargar_revisiones()
        for idx in grupos_idx.values():
            miembros = [candidatos[i][0] for i in idx]
            paginas = {}
            ids_pagina = {}
            for a in miembros:
                paginas.setdefault(a["page_name"], 0)
                paginas[a["page_name"]] += 1
                ids_pagina.setdefault(a["page_name"], a.get("page_id"))
            if len(paginas) < 2:
                continue
            if entre and not (entre[0] in paginas and entre[1] in paginas):
                continue
            financiadores = {a["financiador"] for a in miembros if a["financiador"]}
            entidades: List[str] = []
            for f in sorted(financiadores):
                if not any(_misma_entidad(f, e) for e in entidades):
                    entidades.append(f)
            fechas = sorted(a["date"] for a in miembros if a["date"])
            representante = max(miembros, key=lambda a: medio(a["impresiones"]))
            afiliaciones = {p: _afiliacion(_indice_afil, p, ids_pagina[p]) for p in paginas}
            # Reutilizar un mensaje dentro del mismo partido (candidatos y su partido) es lo esperado: solo se afirma si TODAS las páginas tienen
            # su partido verificado y es el mismo.
            partidos = {(a.get("partido") if a and a.get("verificado") else None) for a in afiliaciones.values()}
            comun = next(iter(partidos)) if len(partidos) == 1 else None
            paginas_de_grupo.append(sorted(paginas))
            huellas = sorted({info["huellas"][candidatos[i][1]] for i in idx})[:40]
            grupo = {
                "texto": representante["text"][:400],
                "anuncios": len(miembros),
                "paginas": [{"page_name": p, "page_id": ids_pagina[p], "anuncios": c, "afiliacion": afiliaciones[p]}
                            for p, c in sorted(paginas.items(), key=lambda kv: -kv[1])],
                "n_paginas": len(paginas),
                "n_textos": len({candidatos[i][1] for i in idx}),
                "huellas": huellas,
                "revision": _revision_de_grupo(_revisiones, ids_pagina, huellas),
                "financiadores": sorted(financiadores),
                "financiadores_distintos": len(entidades) >= 2,
                "mismo_partido": comun if comun and not _es_neutral(comun) else "",
                "gasto_medio": round(sum(medio(a["gasto"]) for a in miembros)),
                "impresiones_medias": round(sum(medio(a["impresiones"]) for a in miembros)),
                "primer_anuncio": fechas[0] if fechas else "",
                "ultimo_anuncio": fechas[-1] if fechas else "",
                "dias": dias_entre(fechas[0], fechas[-1]) if fechas else None,
                "similitud_minima": round(sim_min.get(raiz(candidatos[idx[0]][1]), 1.0), 2),
                "ejemplo_link": representante["link"],
            }
            if entre:
                tabla_textos: Dict[str, int] = {}
                detalle: List[Dict[str, Any]] = []
                por_pagina: Dict[str, int] = {}
                omitidos = 0
                for a in sorted(miembros, key=lambda a: (a["date"] or "", a["id"])):
                    if por_pagina.get(a["page_name"], 0) >= MAX_ANUNCIOS_POR_PAGINA_DETALLE:
                        omitidos += 1
                        continue
                    por_pagina[a["page_name"]] = por_pagina.get(a["page_name"], 0) + 1
                    detalle.append({"id": a["id"], "page_name": a["page_name"], "page_id": a.get("page_id"), "fecha": a["date"], "fecha_fin": a["fecha_fin"],
                                    "activo": a["activo"], "t": tabla_textos.setdefault(a["text"][:1500], len(tabla_textos)), "link": a["link"],
                                    "financiador": a["financiador"], "moneda": a["moneda"], "gasto": a["gasto"], "impresiones": a["impresiones"],
                                    "plataformas": a["plataformas"]})
                grupo["detalle"] = {"textos": list(tabla_textos), "anuncios": detalle, "omitidos": omitidos}
            grupos.append(grupo)

        # Cuántos mensajes repetidos comparten las mismas páginas: una coincidencia aislada puede ser casual (dos páginas que copian el mismo
        # comunicado); que dos páginas coincidan una y otra vez ya es un patrón (o una sola mano detrás de ambas).
        pares_de_paginas = collections.Counter(par for ps in paginas_de_grupo for par in itertools.combinations(ps, 2))
        for g, ps in zip(grupos, paginas_de_grupo):
            g["coincidencias"] = max(pares_de_paginas[par] for par in itertools.combinations(ps, 2))

        def revisado(g: Dict[str, Any]) -> bool:
            return bool(g["revision"]) and g["revision"]["estado"] == "completa"

        total_revisados = sum(1 for g in grupos if revisado(g))
        if not revisados:
            grupos = [g for g in grupos if not revisado(g)]
        grupos.sort(key=lambda g: (revisado(g), -g["n_paginas"], -g["gasto_medio"]))          # primero las señales; los revisados, al final
        return {
            **base,
            "analizados": len(candidatos),
            "retirados_por_meta": {
                "anuncios": sum(retirados.values()),
                "paginas": [{"page_name": p, "anuncios": c} for p, c in sorted(retirados.items(), key=lambda kv: -kv[1])[:5]],
            },
            "plantillas_separadas": len({t for a, b in info["vetos"] if a in presentes and b in presentes for t in (a, b)}),
            "textos_muy_extendidos": {"textos": len(info["extendidos"]), "paginas_minimas": MAX_PAGINAS_POR_TEXTO, "ejemplos": info["extendidos"][:3]},
            "total_grupos": len(grupos),
            "total_revisados": total_revisados,
            "revisados_incluidos": revisados,
            "motivos_revision": [{"id": k, "texto": v} for k, v in MOTIVOS_REVISION.items()],
            "grupos": grupos[:max(1, limite)],
            "nota": "Textos con similitud ≥ %d %% entre páginas distintas, sin contar enlaces, hashtags ni menciones. Es un indicador, no una prueba: "
                    "campañas, partidos y gobiernos también reutilizan mensajes, y las páginas de una misma persona u organización "
                    "(únelas en «Entidades») cuentan como páginas distintas hasta que se unan." % round(umbral * 100),
        }

    def guardar_revision(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Registra en backend/mensajes_revisados.json que un grupo de «Mensajes repetidos» ya se revisó y es esperable (ver MOTIVOS_REVISION).
        `alcance` «mensaje» cubre solo ese texto (sus `huellas`) entre esas páginas; «paginas», cualquier mensaje repetido entre ellas. Una revisión
        nueva reemplaza a las anteriores que hace innecesarias (las mismas páginas, o menos, y los mismos textos o menos).
        Lanza ValueError con un mensaje legible si los datos no son válidos.
        """
        alcance = datos.get("alcance")
        if alcance not in ALCANCES_REVISION:
            raise ValueError("El alcance de la revisión no es válido.")
        motivo = datos.get("motivo")
        if motivo not in MOTIVOS_REVISION:
            raise ValueError("Elige el motivo de la revisión.")
        nota = unicodedata.normalize("NFC", str(datos.get("nota") or "").strip())[:500]
        if motivo == "otro" and not nota:
            raise ValueError("Con «otro motivo» escribe en la nota qué revisaste.")
        paginas: List[Dict[str, str]] = []
        vistas: set = set()
        for p in datos.get("paginas") or []:
            p = p if isinstance(p, dict) else {}
            nombre = unicodedata.normalize("NFC", str(p.get("nombre") or "").strip())[:200]
            pid = str(p.get("page_id") or "").strip()
            pid = pid if re.fullmatch(r"\d{1,40}", pid) else ""
            clave = pid or _norm(nombre)
            if not nombre or not clave or clave in vistas:
                continue
            vistas.add(clave)
            paginas.append({"nombre": nombre, **({"page_id": pid} if pid else {})})
        if len(paginas) < 2:
            raise ValueError("Una revisión necesita al menos dos páginas.")
        if len(paginas) > 60:
            raise ValueError("Demasiadas páginas en una sola revisión (el máximo es 60).")
        huellas: List[str] = []
        if alcance == "mensaje":
            huellas = sorted({h for h in (datos.get("huellas") or []) if isinstance(h, str) and _HUELLA_RE.match(h)})[:40]
            if not huellas:
                raise ValueError("Falta el mensaje que se revisó.")
        ejemplo = " ".join(str(datos.get("ejemplo") or "").split())[:200]
        nueva: Dict[str, Any] = {"id": uuid.uuid4().hex[:10], "alcance": alcance, "paginas": paginas}
        if huellas:
            nueva["huellas"] = huellas
        if ejemplo:
            nueva["ejemplo"] = ejemplo
        nueva.update({"motivo": motivo, "nota": nota, "revisado": date.today().isoformat()})
        with _LOCK_REV:
            contenido = _leer_revisiones()
            contenido["revisados"] = [r for r in contenido["revisados"] if not (isinstance(r, dict) and _reemplaza_revision(nueva, r))] + [nueva]
            _escribir_revisiones(contenido)
            total = len(contenido["revisados"])
        logger.info(f"[Revisiones] Guardada una revisión de {len(paginas)} páginas ({alcance}, {motivo}).")
        return {"ok": True, "revision": nueva, "total": total}

    def quitar_revision(self, revision_id: Any) -> Dict[str, Any]:
        """Quita una revisión de backend/mensajes_revisados.json por su `id`: los grupos que cubría vuelven a mostrarse como señal."""
        rid = str(revision_id or "").strip()
        with _LOCK_REV:
            contenido = _leer_revisiones()
            quedan = [r for r in contenido["revisados"] if not (isinstance(r, dict) and str(r.get("id")) == rid)]
            if not rid or len(quedan) == len(contenido["revisados"]):
                raise ValueError("Esa revisión ya no existe.")
            contenido["revisados"] = quedan
            _escribir_revisiones(contenido)
        logger.info("[Revisiones] Se quitó una revisión.")
        return {"ok": True, "total": len(quedan)}

    def diagnostico(self) -> Dict[str, Any]:
        """Prueba mínima contra la API para comprobar token, versión y cobertura de Ecuador."""
        if self.solo_copia:
            ads, estado = self._obtener_nacional_crudo()
            return {"configurado": True, "habilitado": True, "solo_copia": True, "version_api": self.version, "pais": self.country,
                    "ok": bool(ads), "anuncios_devueltos": len(ads), "mensaje": estado.get("aviso") or estado.get("mensaje") or ""}
        self.reload_token()
        base = {"configurado": self.configurado, "habilitado": self.habilitado, "version_api": self.version, "pais": self.country}
        if not self.habilitado:
            return {**base, "ok": False, "mensaje": "Integración de Meta desactivada (META_INTEGRATION_ENABLED / FB_META_API_ENABLED)."}
        if not self.token:
            return {**base, "ok": False, "mensaje": "Falta META_AD_LIBRARY_TOKEN en backend/.env.local o en Firebase."}

        termino = self.terms[0] if self.terms else "*"          # el mismo tipo de consulta que usa la descarga real
        crudos, err = self._fetch_term(termino, limit=5, pages=1)
        if err:
            return {**base, "ok": False, "error": err}

        primero = crudos[0] if crudos else {}
        regiones = [r.get("region") for r in (primero.get("delivery_by_region") or []) if isinstance(r, dict)]
        return {
            **base,
            "ok": True,
            "anuncios_devueltos": len(crudos),
            "campos_recibidos": sorted(primero.keys()),
            "regiones_ejemplo": regiones[:10],
            "mensaje": "" if crudos else
                       f"La API respondió pero sin anuncios para '{termino}'. Prueba otros términos en AD_LIBRARY_TERMS.",
        }
