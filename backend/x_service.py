"""
Cliente de la API oficial de X (v2) para buscar publicaciones recientes sobre una provincia.

- Usa `GET /2/tweets/search/recent` (últimos 7 días) con un Bearer Token de aplicación.
- La API de X cobra por recurso devuelto (pago por uso). Para controlar costos hay: caché por
  provincia (X_CACHE_MIN), un tope diario de consultas (X_DAILY_REQUEST_CAP) y un máximo de
  resultados por consulta (X_MAX_RESULTS, mínimo 10 por la API).
- Sin token o ante cualquier error devuelve una lista vacía y un estado explicativo. Nunca inventa
  publicaciones.
- Además del texto y las métricas públicas, devuelve datos de la cuenta (antigüedad, seguidores)
  que sirven para análisis posteriores de cuentas sospechosas.
"""
import logging
import os
import threading
import time
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.x.com"
SEARCH_PATH = "/2/tweets/search/recent"
TERMINOS = ["elecciones", "candidato", "candidata", "alcalde", "prefecto", "CNE", "voto"]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _clave(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


class XClient:
    def __init__(self):
        self.token = os.getenv("X_BEARER_TOKEN", "").strip()
        self.base = os.getenv("X_API_BASE", DEFAULT_BASE).strip().rstrip("/") or DEFAULT_BASE
        self.max_results = min(100, max(10, _env_int("X_MAX_RESULTS", 10)))
        self.cache_ttl = _env_int("X_CACHE_MIN", 60) * 60
        self.daily_cap = _env_int("X_DAILY_REQUEST_CAP", 40)

        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]], Dict[str, Any]]] = {}
        self._llamadas: Dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def configurado(self) -> bool:
        return bool(self.token)

    def _scrub(self, texto: Any) -> str:
        limpio = str(texto)
        if self.token:
            limpio = limpio.replace(self.token, "***")
        return limpio[:300]

    def _consulta(self, provincia: str) -> str:
        terminos = " OR ".join(TERMINOS)
        return f'({terminos}) "{provincia}" Ecuador -is:retweet lang:es'

    def _normalizar(self, tweets: List[Dict[str, Any]], usuarios: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        salida = []
        for t in tweets:
            u = usuarios.get(t.get("author_id"), {})
            m = t.get("public_metrics") or {}
            um = u.get("public_metrics") or {}
            username = u.get("username") or ""
            fecha = t.get("created_at") or ""
            salida.append({
                "id": t.get("id"),
                "text": t.get("text", ""),
                "user": {
                    "name": u.get("name") or username or "Cuenta de X",
                    "username": f"@{username}" if username else "",
                    "avatar": u.get("profile_image_url", ""),
                },
                "date": fecha,
                "anio": fecha[:4],
                "link": f"https://x.com/{username}/status/{t.get('id')}" if username else f"https://x.com/i/web/status/{t.get('id')}",
                "stats": {
                    "likes": m.get("like_count", 0),
                    "retweets": m.get("retweet_count", 0),
                    "replies": m.get("reply_count", 0),
                    "quotes": m.get("quote_count", 0),
                },
                "cuenta": {
                    "creada": u.get("created_at", ""),
                    "seguidores": um.get("followers_count"),
                    "siguiendo": um.get("following_count"),
                    "publicaciones": um.get("tweet_count"),
                    "verificada": u.get("verified"),
                },
            })
        return salida

    def buscar(self, provincia: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.configurado:
            return [], {
                "configurado": False, "ok": False,
                "mensaje": "Falta X_BEARER_TOKEN. Agrégalo en backend/.env.local y reinicia el backend "
                           "(la API oficial de X es de pago por uso).",
            }

        clave = _clave(provincia)
        with self._lock:
            en_cache = self._cache.get(clave)
            if en_cache and time.time() - en_cache[0] < self.cache_ttl:
                return en_cache[1], en_cache[2]

            hoy = date.today().isoformat()
            if self._llamadas.get(hoy, 0) >= self.daily_cap:
                return [], {
                    "configurado": True, "ok": False,
                    "mensaje": f"Se alcanzó el tope diario de {self.daily_cap} consultas a X (X_DAILY_REQUEST_CAP), "
                               "definido para controlar costos. Vuelve a intentar mañana o sube el tope.",
                }
            self._llamadas[hoy] = self._llamadas.get(hoy, 0) + 1

            params = {
                "query": self._consulta(provincia),
                "max_results": self.max_results,
                "tweet.fields": "created_at,public_metrics,lang,author_id",
                "expansions": "author_id",
                "user.fields": "username,name,created_at,public_metrics,verified,profile_image_url",
            }
            try:
                r = requests.get(self.base + SEARCH_PATH, params=params,
                                 headers={"Authorization": f"Bearer {self.token}"}, timeout=12)
            except requests.RequestException as e:
                return [], {"configurado": True, "ok": False, "mensaje": self._scrub(f"Error de red al consultar X: {e}")}

            if r.status_code != 200:
                return [], {"configurado": True, "ok": False, "mensaje": self._error_http(r)}

            try:
                cuerpo = r.json()
            except ValueError:
                return [], {"configurado": True, "ok": False, "mensaje": "Respuesta no válida de la API de X."}

            usuarios = {u["id"]: u for u in (cuerpo.get("includes") or {}).get("users", []) if "id" in u}
            items = self._normalizar(cuerpo.get("data") or [], usuarios)
            estado = {
                "configurado": True, "ok": True, "total": len(items),
                "actualizado": datetime.now().isoformat(timespec="seconds"),
                "ventana": "últimos 7 días",
                "mensaje": "" if items else "La API de X no devolvió publicaciones recientes para esta provincia.",
            }
            self._cache[clave] = (time.time(), items, estado)
            return items, estado

    def _error_http(self, r: requests.Response) -> str:
        codigo = r.status_code
        if codigo == 401:
            return "X rechazó el token (401). Revisa X_BEARER_TOKEN en la Developer Console."
        if codigo in (402, 403):
            return (f"X denegó la consulta ({codigo}): probablemente faltan créditos o permisos del plan. "
                    "Revisa tu saldo y el acceso de la app en la Developer Console de X.")
        if codigo == 429:
            return "X limitó las consultas (429). Intenta de nuevo en unos minutos."
        try:
            detalle = (r.json().get("detail") or r.json().get("title") or "")
        except ValueError:
            detalle = r.text[:120]
        return self._scrub(f"X respondió con error {codigo}: {detalle}")

    def diagnostico(self) -> Dict[str, Any]:
        hoy = date.today().isoformat()
        return {
            "configurado": self.configurado,
            "consultas_hoy": self._llamadas.get(hoy, 0),
            "tope_diario": self.daily_cap,
            "max_resultados_por_consulta": self.max_results,
            "cache_min": self.cache_ttl // 60,
            "mensaje": "" if self.configurado else "Falta X_BEARER_TOKEN en backend/.env.local.",
        }
