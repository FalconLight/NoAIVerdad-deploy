"""
Archivo histórico de anuncios de Meta: conserva, sin límite de tiempo, la respuesta CRUDA de la Biblioteca de Anuncios.

Por qué existe
- La app solo consulta los últimos `AD_LIBRARY_DAYS` días (120 por defecto) y guarda una copia ya normalizada (un texto por anuncio, sin los
  campos extra). Lo que sale de esa ventana deja de verse, y si el token vence o Meta sustituye un anuncio por su aviso de «retirado», el
  dato original ya no se puede recuperar desde la app.
- Meta conserva los anuncios políticos unos 7 años, así que hoy todavía se pueden bajar; este archivo los deja en disco, en un formato
  simple (JSON por líneas, comprimido) que cualquier versión futura puede leer sin depender de este programa.

Reglas
- Solo se añade o se actualiza: nada se borra. Un anuncio visto otra vez actualiza sus cifras (los rangos de gasto e impresiones cambian) pero
  no pierde campos: `raw = {**anterior, **nuevo}`. Si su texto cambia (p. ej. Meta lo retira), el texto anterior queda en `versiones`.
- `ad_snapshot_url` nunca se pide ni se guarda (Meta incrusta en ella el token de acceso).

Disposición en disco (carpeta del archivo)
    manifest.json                 esquema, país, totales, cada mes (anuncios, bytes, sha256), ventanas capturadas y bitácora de capturas
    anuncios/AAAA-MM.jsonl.gz     una línea por anuncio; el mes es el de `ad_delivery_start_time` (o `ad_creation_time`; si no hay, «sin-fecha»)
Cada línea: {"id", "visto_primero", "visto_ultimo", "origen", "raw": {…respuesta de Meta…}, "versiones": [{"hasta", "ad_creative_bodies", …}]}

Uso: `backend/tools/archivo_meta.py` (capturar, estado, verificar, exportar, importar, snapshot, sqlite, csv). Ver docs/archivo-meta.md.
Para analizarlo con otras herramientas, `exportar_sqlite` y `exportar_csv` lo vuelcan a una base de datos SQLite o a tablas CSV.
"""
import calendar
import contextlib
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

ESQUEMA = 1
SIN_FECHA = "sin-fecha"
MAX_VERSIONES = 5
MAX_CAPTURAS = 400                                   # entradas de la bitácora que se conservan en el manifiesto
# Campos que la app no pide pero que conviene conservar (texto del enlace e idiomas). Si la API rechaza alguno se vuelve a los básicos.
CAMPOS_EXTRA = ["ad_creative_link_captions", "ad_creative_link_descriptions", "languages"]
# Nunca se guardan: Meta incrusta el token de acceso en esta URL.
CAMPOS_PROHIBIDOS = ("ad_snapshot_url",)
# Último recurso cuando un solo anuncio pesa tanto que Meta no lo entrega («reduce the amount of data»): se pide sin estos campos, en este orden.
CAMPOS_PESADOS = ["demographic_distribution", "delivery_by_region"]
_MES_RE = re.compile(r"^\d{4}-\d{2}$")


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mes_de(raw: Dict[str, Any]) -> str:
    """Mes (AAAA-MM) en el que empezó a circular el anuncio: decide en qué archivo vive. No cambia aunque el anuncio se actualice."""
    f = str(raw.get("ad_delivery_start_time") or raw.get("ad_creation_time") or "")
    return f[:7] if re.match(r"^\d{4}-\d{2}", f) else SIN_FECHA


def fecha_de(raw: Dict[str, Any]) -> str:
    """Fecha de inicio (AAAA-MM-DD) o cadena vacía."""
    f = str(raw.get("ad_delivery_start_time") or raw.get("ad_creation_time") or "")
    return f[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", f) else ""


def _limpio(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in raw.items() if k not in CAMPOS_PROHIBIDOS}


def _version_de(raw: Dict[str, Any], hasta: str) -> Dict[str, Any]:
    v = {"hasta": hasta, "ad_creative_bodies": raw.get("ad_creative_bodies")}
    if raw.get("ad_creative_link_titles"):
        v["ad_creative_link_titles"] = raw["ad_creative_link_titles"]
    return v


def _unir_versiones(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vistas, salida = set(), []
    for v in sorted(list(a) + list(b), key=lambda x: str(x.get("hasta") or "")):
        clave = json.dumps(v.get("ad_creative_bodies"), ensure_ascii=False, sort_keys=True)
        if clave not in vistas:
            vistas.add(clave)
            salida.append(v)
    return salida[-MAX_VERSIONES:]


def fusionar_registro(viejo: Optional[Dict[str, Any]], raw: Dict[str, Any], capturado: str, origen: str) -> Tuple[Dict[str, Any], str]:
    """
    Une una respuesta de Meta con lo que ya había del mismo anuncio. Devuelve (registro, "nuevo" | "actualizado" | "sin_cambios").
    Una captura posterior manda sobre los campos que trae y deja intactos los que no trae; una anterior (importar un archivo viejo) solo rellena
    lo que faltaba. Si el texto del anuncio cambió, el anterior se guarda en `versiones`.
    """
    raw = _limpio(raw)
    if viejo is None:
        return {"id": str(raw.get("id") or ""), "visto_primero": capturado, "visto_ultimo": capturado, "origen": origen, "raw": raw, "versiones": []}, "nuevo"
    base = viejo.get("raw") or {}
    anterior = capturado < str(viejo.get("visto_ultimo") or "")
    final = {**raw, **base} if anterior else {**base, **raw}
    versiones = list(viejo.get("versiones") or [])
    t_base, t_nuevo = base.get("ad_creative_bodies"), raw.get("ad_creative_bodies")
    if t_base and t_nuevo and t_base != t_nuevo:
        # la versión que NO queda en `raw` es la que se guarda aparte
        perdida = _version_de(raw, capturado) if anterior else _version_de(base, str(viejo.get("visto_ultimo") or ""))
        versiones = _unir_versiones(versiones, [perdida])
    nuevo = {**viejo, "raw": final, "versiones": versiones,
             "visto_primero": min(str(viejo.get("visto_primero") or capturado), capturado),
             "visto_ultimo": max(str(viejo.get("visto_ultimo") or capturado), capturado)}
    cambio = final != base or versiones != (viejo.get("versiones") or [])
    return nuevo, ("actualizado" if cambio else "sin_cambios")


class ArchivoOcupado(RuntimeError):
    """Otro proceso está escribiendo en el archivo y no lo soltó a tiempo."""


class ArchivoMeta:
    def __init__(self, carpeta: str, pais: str = "EC", espera_candado: float = 300.0):
        self.carpeta = os.path.abspath(carpeta)
        self.dir_anuncios = os.path.join(self.carpeta, "anuncios")
        self.ruta_manifiesto = os.path.join(self.carpeta, "manifest.json")
        self.ruta_candado = os.path.join(self.carpeta, ".lock")
        self.pais = pais
        self.espera_candado = espera_candado
        self._hilo = threading.RLock()
        self._nivel = 0

    # ------------------------------------------------------------------
    # Candado: el servidor (que archiva cada descarga) y la herramienta de captura pueden escribir a la vez
    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def _candado(self):
        with self._hilo:
            if self._nivel:                               # ya lo tiene este mismo hilo
                self._nivel += 1
                try:
                    yield
                finally:
                    self._nivel -= 1
                return
            os.makedirs(self.dir_anuncios, exist_ok=True)
            limite = time.time() + self.espera_candado
            while True:
                try:
                    fd = os.open(self.ruta_candado, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, f"{os.getpid()} {_ahora()}".encode())
                    os.close(fd)
                    break
                except FileExistsError:
                    try:
                        if time.time() - os.path.getmtime(self.ruta_candado) > 900:      # un candado de hace 15 min es de un proceso que murió
                            os.remove(self.ruta_candado)
                            continue
                    except OSError:
                        continue
                    if time.time() > limite:
                        raise ArchivoOcupado(f"El archivo está en uso por otro proceso ({self.ruta_candado}).")
                    time.sleep(0.5)
            self._nivel = 1
            try:
                yield
            finally:
                self._nivel = 0
                with contextlib.suppress(OSError):
                    os.remove(self.ruta_candado)

    # ------------------------------------------------------------------
    # Manifiesto
    # ------------------------------------------------------------------
    def manifiesto(self) -> Dict[str, Any]:
        try:
            with open(self.ruta_manifiesto, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict) and isinstance(m.get("meses"), dict):
                m.setdefault("ventanas", {})
                m.setdefault("capturas", [])
                return m
        except (OSError, ValueError):
            pass
        return {"esquema": ESQUEMA, "pais": self.pais, "tipo": "POLITICAL_AND_ISSUE_ADS", "creado": _ahora(), "actualizado": "", "total": 0,
                "meses": {}, "ventanas": {}, "capturas": []}

    def _guardar_manifiesto(self, m: Dict[str, Any]) -> None:
        m["esquema"] = ESQUEMA
        m["actualizado"] = _ahora()
        m["total"] = sum(int(x.get("anuncios") or 0) for x in m["meses"].values())
        m["meses"] = dict(sorted(m["meses"].items()))
        m["ventanas"] = dict(sorted(m["ventanas"].items()))
        m["capturas"] = m["capturas"][-MAX_CAPTURAS:]
        os.makedirs(self.carpeta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.carpeta, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        _reemplazar(tmp, self.ruta_manifiesto)

    # ------------------------------------------------------------------
    # Archivos por mes
    # ------------------------------------------------------------------
    def _ruta_mes(self, mes: str) -> str:
        if mes != SIN_FECHA and not _MES_RE.match(mes):
            raise ValueError(f"Mes no válido: {mes!r}")
        return os.path.join(self.dir_anuncios, f"{mes}.jsonl.gz")

    def _leer_mes(self, mes: str) -> Dict[str, Dict[str, Any]]:
        ruta = self._ruta_mes(mes)
        regs: Dict[str, Dict[str, Any]] = {}
        if not os.path.exists(ruta):
            return regs
        with gzip.open(ruta, "rt", encoding="utf-8") as f:
            for linea in f:
                if linea.strip():
                    r = json.loads(linea)
                    regs[str(r["id"])] = r
        return regs

    def _escribir_mes(self, mes: str, regs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Escritura atómica y reproducible (ordenada por id, gzip sin fecha): el mismo contenido da siempre el mismo sha256."""
        os.makedirs(self.dir_anuncios, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir_anuncios, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as crudo:
                with gzip.GzipFile(filename="", fileobj=crudo, mode="wb", compresslevel=6, mtime=0) as gz:
                    for ad_id in sorted(regs, key=lambda x: (len(x), x)):
                        gz.write((json.dumps(regs[ad_id], ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
            info = {"anuncios": len(regs), "bytes": os.path.getsize(tmp), "sha256": _sha256(tmp), "actualizado": _ahora()}
            _reemplazar(tmp, self._ruta_mes(mes))
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise
        return info

    def meses(self) -> List[str]:
        """Meses con archivo en disco (aunque el manifiesto se hubiera perdido), en orden; «sin-fecha» al final."""
        try:
            nombres = [n[:-len(".jsonl.gz")] for n in os.listdir(self.dir_anuncios) if n.endswith(".jsonl.gz")]
        except OSError:
            return []
        return sorted(n for n in nombres if _MES_RE.match(n)) + ([SIN_FECHA] if SIN_FECHA in nombres else [])

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------
    def fusionar(self, crudos: Iterable[Dict[str, Any]], origen: str = "meta-api", capturado: Optional[str] = None,
                 anotar: bool = True) -> Dict[str, Any]:
        """
        Añade o actualiza anuncios a partir de respuestas crudas de Meta. Devuelve las cuentas: recibidos, nuevos, actualizados, sin_cambios.
        `origen` queda en la bitácora («meta-api», «renovacion» de la app, «importacion»). Con `anotar=False` no escribe en la bitácora.
        """
        capturado = capturado or _ahora()
        por_mes: Dict[str, Dict[str, Dict[str, Any]]] = {}
        recibidos = 0
        for raw in crudos:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            recibidos += 1
            por_mes.setdefault(mes_de(raw), {})[str(raw["id"])] = raw
        cuentas = {"recibidos": recibidos, "nuevos": 0, "actualizados": 0, "sin_cambios": 0, "meses": sorted(por_mes)}
        if not por_mes:
            return cuentas
        with self._candado():
            m = self.manifiesto()
            for mes, nuevos in por_mes.items():
                regs = self._leer_mes(mes)
                tocado = False
                for ad_id, raw in nuevos.items():
                    reg, que = fusionar_registro(regs.get(ad_id), raw, capturado, origen)
                    regs[ad_id] = reg
                    cuentas[{"nuevo": "nuevos", "actualizado": "actualizados", "sin_cambios": "sin_cambios"}[que]] += 1
                    tocado = True
                if tocado:
                    m["meses"][mes] = self._escribir_mes(mes, regs)
            if anotar:
                self._anotar(m, origen, capturado, cuentas)
            self._guardar_manifiesto(m)
        return cuentas

    @staticmethod
    def _anotar(m: Dict[str, Any], origen: str, capturado: str, cuentas: Dict[str, Any]) -> None:
        """Bitácora de capturas. Las renovaciones de la app (una por hora) se acumulan en una entrada por día para no llenarla."""
        entrada = {"fecha": capturado, "origen": origen, **{k: cuentas[k] for k in ("recibidos", "nuevos", "actualizados", "sin_cambios")}}
        ult = m["capturas"][-1] if m["capturas"] else None
        if ult and origen == "renovacion" and ult.get("origen") == origen and str(ult.get("fecha"))[:10] == capturado[:10]:
            ult.update({"fecha": capturado, "recibidos": cuentas["recibidos"], "nuevos": ult.get("nuevos", 0) + cuentas["nuevos"],
                        "actualizados": ult.get("actualizados", 0) + cuentas["actualizados"], "sin_cambios": cuentas["sin_cambios"],
                        "veces": ult.get("veces", 1) + 1})
        else:
            m["capturas"].append(entrada)

    def marcar_ventana(self, clave: str, datos: Dict[str, Any]) -> None:
        """Deja constancia de una ventana de captura (un mes de calendario): rango pedido, cuándo, cuántos anuncios y si terminó sin errores."""
        with self._candado():
            m = self.manifiesto()
            m["ventanas"][clave] = datos
            self._guardar_manifiesto(m)

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    def registros(self, desde: Optional[str] = None, hasta: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """
        Recorre los registros, mes a mes y en orden. `desde`/`hasta` (AAAA-MM-DD, inclusive) filtran por la fecha de inicio del anuncio; los
        anuncios sin fecha solo salen cuando no se pide ningún rango.
        """
        for mes in self.meses():
            if mes == SIN_FECHA:
                if desde or hasta:
                    continue
            elif (desde and mes < desde[:7]) or (hasta and mes > hasta[:7]):
                continue
            with gzip.open(self._ruta_mes(mes), "rt", encoding="utf-8") as f:
                for linea in f:
                    if not linea.strip():
                        continue
                    r = json.loads(linea)
                    if desde or hasta:
                        fch = fecha_de(r.get("raw") or {})
                        if not fch or (desde and fch < desde) or (hasta and fch > hasta):
                            continue
                    yield r

    def estado(self) -> Dict[str, Any]:
        m = self.manifiesto()
        con_fecha = [k for k in m["meses"] if k != SIN_FECHA]
        completas = [k for k, v in m["ventanas"].items() if v.get("completo")]
        return {
            "carpeta": self.carpeta, "esquema": m.get("esquema"), "pais": m.get("pais"), "total": m.get("total", 0),
            "meses": len(m["meses"]), "primer_mes": min(con_fecha) if con_fecha else None, "ultimo_mes": max(con_fecha) if con_fecha else None,
            "sin_fecha": int((m["meses"].get(SIN_FECHA) or {}).get("anuncios") or 0),
            "bytes": sum(int(v.get("bytes") or 0) for v in m["meses"].values()),
            "ventanas_completas": len(completas), "ventanas_incompletas": sorted(k for k, v in m["ventanas"].items() if not v.get("completo")),
            "primera_ventana_completa": min(completas) if completas else None,
            "actualizado": m.get("actualizado"), "ultima_captura": m["capturas"][-1] if m["capturas"] else None,
            "por_mes": {k: int(v.get("anuncios") or 0) for k, v in m["meses"].items()},
        }

    def verificar(self) -> Dict[str, Any]:
        """Comprueba cada archivo contra el manifiesto (existe, sha256, número de líneas, cada línea es un anuncio de ese mes y sin token)."""
        m = self.manifiesto()
        problemas: List[str] = []
        total = 0
        en_disco = set(self.meses())
        for mes in sorted(en_disco - set(m["meses"])):
            problemas.append(f"{mes}: hay archivo pero no está en el manifiesto")
        for mes, info in m["meses"].items():
            if mes not in en_disco:
                problemas.append(f"{mes}: está en el manifiesto pero falta el archivo")
                continue
            ruta = self._ruta_mes(mes)
            if _sha256(ruta) != info.get("sha256"):
                problemas.append(f"{mes}: el sha256 no coincide con el manifiesto")
            n, ids = 0, set()
            try:
                with gzip.open(ruta, "rt", encoding="utf-8") as f:
                    for linea in f:
                        if not linea.strip():
                            continue
                        r = json.loads(linea)
                        n += 1
                        ids.add(str(r["id"]))
                        if mes_de(r["raw"]) != mes:
                            problemas.append(f"{mes}: el anuncio {r['id']} es de {mes_de(r['raw'])}")
                        if any(c in r["raw"] for c in CAMPOS_PROHIBIDOS) or "access_token=" in linea:
                            problemas.append(f"{mes}: el anuncio {r['id']} lleva un campo que no debe guardarse")
            except (OSError, ValueError, KeyError, EOFError) as e:
                problemas.append(f"{mes}: no se puede leer ({type(e).__name__})")
                continue
            if n != info.get("anuncios") or len(ids) != n:
                problemas.append(f"{mes}: {n} líneas ({len(ids)} ids distintos) y el manifiesto dice {info.get('anuncios')}")
            total += n
        return {"ok": not problemas, "meses": len(m["meses"]), "anuncios": total, "problemas": problemas}

    # ------------------------------------------------------------------
    # Mover el archivo entre equipos o versiones
    # ------------------------------------------------------------------
    def exportar(self, ruta_zip: str) -> Dict[str, Any]:
        """Un solo .zip con el manifiesto y todos los meses (sin recomprimir: ya van en gzip)."""
        with self._candado():
            os.makedirs(os.path.dirname(os.path.abspath(ruta_zip)) or ".", exist_ok=True)
            tmp = ruta_zip + ".tmp"
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
                if os.path.exists(self.ruta_manifiesto):
                    z.write(self.ruta_manifiesto, "manifest.json")
                for mes in self.meses():
                    z.write(self._ruta_mes(mes), f"anuncios/{mes}.jsonl.gz")
            os.replace(tmp, ruta_zip)
        return {"ruta": os.path.abspath(ruta_zip), "bytes": os.path.getsize(ruta_zip), "meses": len(self.meses()), "anuncios": self.manifiesto().get("total", 0)}

    def importar(self, ruta: str) -> Dict[str, Any]:
        """
        Fusiona otro archivo (un .zip de `exportar` o su carpeta) con este. Es una unión: lo que ya había no se pierde, y de cada anuncio queda la
        captura más reciente, con las versiones de texto de ambos lados.
        """
        temporal = None
        try:
            if os.path.isdir(ruta):
                otra = ruta
            else:
                temporal = tempfile.mkdtemp(prefix="archivo_meta_imp_")
                with zipfile.ZipFile(ruta) as z:
                    for nombre in z.namelist():
                        if nombre == "manifest.json" or re.match(r"^anuncios/(\d{4}-\d{2}|sin-fecha)\.jsonl\.gz$", nombre):      # nada más sale del zip
                            z.extract(nombre, temporal)
                otra = temporal
            origen = ArchivoMeta(otra)
            cuentas = {"recibidos": 0, "nuevos": 0, "actualizados": 0, "sin_cambios": 0, "meses": []}
            capturado = _ahora()
            with self._candado():
                m = self.manifiesto()
                for mes in origen.meses():
                    regs = self._leer_mes(mes)
                    for ad_id, ajeno in origen._leer_mes(mes).items():
                        cuentas["recibidos"] += 1
                        propio = regs.get(ad_id)
                        if propio is None:
                            regs[ad_id] = ajeno
                            cuentas["nuevos"] += 1
                            continue
                        reg, que = fusionar_registro(propio, ajeno.get("raw") or {}, str(ajeno.get("visto_ultimo") or ""), "importacion")
                        reg["visto_primero"] = min(str(propio.get("visto_primero") or ""), str(ajeno.get("visto_primero") or "")) or reg["visto_primero"]
                        versiones = _unir_versiones(reg.get("versiones") or [], ajeno.get("versiones") or [])
                        if versiones != (reg.get("versiones") or []):
                            reg["versiones"], que = versiones, "actualizado"
                        regs[ad_id] = reg
                        cuentas["actualizados" if que == "actualizado" else "sin_cambios"] += 1
                    m["meses"][mes] = self._escribir_mes(mes, regs)
                    cuentas["meses"].append(mes)
                # las ventanas completas del otro archivo valen aquí solo si este no tenía ya esa ventana
                for clave, v in (origen.manifiesto().get("ventanas") or {}).items():
                    m["ventanas"].setdefault(clave, v)
                self._anotar(m, "importacion", capturado, cuentas)
                self._guardar_manifiesto(m)
            return cuentas
        finally:
            if temporal:
                shutil.rmtree(temporal, ignore_errors=True)


def _reemplazar(tmp: str, destino: str, intentos: int = 60) -> None:
    """
    `os.replace` con paciencia: en Windows falla mientras otro proceso tiene abierto el destino (alguien leyendo el archivo, un antivirus, una
    copia de seguridad). Se reintenta medio minuto antes de darse por vencido.
    """
    for i in range(intentos):
        try:
            os.replace(tmp, destino)
            return
        except PermissionError:
            if i == intentos - 1:
                raise
            time.sleep(0.5)


def _sha256(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


# ----------------------------------------------------------------------
# Captura desde Meta, por meses y reanudable
# ----------------------------------------------------------------------
def ventanas_mensuales(desde: date, hasta: date) -> List[Tuple[str, date, date]]:
    """Meses de calendario entre dos fechas, del más reciente al más antiguo: (AAAA-MM, primer día pedido, último día pedido)."""
    salida = []
    anio, mes = hasta.year, hasta.month
    while (anio, mes) >= (desde.year, desde.month):
        ini = max(date(anio, mes, 1), desde)
        fin = min(date(anio, mes, calendar.monthrange(anio, mes)[1]), hasta)
        salida.append((f"{anio:04d}-{mes:02d}", ini, fin))
        anio, mes = (anio, mes - 1) if mes > 1 else (anio - 1, 12)
    return salida


def uso_de(cabecera: Any) -> Tuple[int, int]:
    """
    Lee la cabecera `x-business-use-case-usage` de Meta: (mayor porcentaje gastado de la cuota de la hora, minutos que Meta estima para recuperar
    el acceso). (0, 0) si no hay cabecera o no se entiende.
    """
    try:
        datos = json.loads(cabecera) if isinstance(cabecera, str) else None
    except ValueError:
        datos = None
    gastado = minutos = 0
    for lista in (datos.values() if isinstance(datos, dict) else []):
        for u in (lista if isinstance(lista, list) else []):
            if isinstance(u, dict):
                gastado = max([gastado] + [int(u.get(k) or 0) for k in ("call_count", "total_cputime", "total_time")])
                minutos = max(minutos, int(u.get("estimated_time_to_regain_access") or 0))
    return gastado, minutos


def capturar(cliente: Any, archivo: ArchivoMeta, desde: Optional[date] = None, hasta: Optional[date] = None, forzar: bool = False,
             pausa: float = 1.5, refrescar_dias: int = 120, max_vacias: int = 12, lote: int = 5000, espera_ritmo: float = 300.0,
             max_esperas: int = 6, limite: Optional[int] = None, termino: str = "*", hoy: Optional[date] = None,
             uso_maximo: int = 75, espera_red: float = 60.0, max_red: int = 5, piso: int = 50, refrescar_horas: float = 12.0,
             log: Callable[[str], None] = print, dormir: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """
    Baja de la Biblioteca de Anuncios todos los anuncios políticos del país, mes a mes y hacia atrás, y los fusiona en `archivo`.

    - Reanudable: cada mes que termina sin errores queda marcado como completo y la siguiente ejecución lo salta (salvo `forzar`, o que toque
      los últimos `refrescar_dias` días: esos anuncios siguen cambiando, así que se vuelven a bajar si su captura tiene más de
      `refrescar_horas` horas). Lo bajado de un mes interrumpido no se pierde.
    - Cortés con la API: `pausa` segundos entre consultas; Meta dice en cada respuesta qué parte de la cuota de la hora va gastada y, al pasar
      de `uso_maximo` %, se espera a que baje (antes de que empiece a responder lento o a cortar). Si aun así limita el ritmo se espera
      `espera_ritmo` × intento (hasta `max_esperas`) y, si sigue, se para con un mensaje. Una página demasiado pesada se vuelve a pedir con la
      mitad de anuncios (nunca menos de `piso`), y un fallo de red o una respuesta que no llega se reintenta `max_red` veces con esperas crecientes.
    - Para sola al llegar a `desde` (por defecto hace 7 años, lo que Meta conserva) o tras `max_vacias` meses seguidos sin anuncios.
    `cliente` es un `AdLibraryClient` (se usan su token, su país y `_get`). Devuelve un resumen con lo hecho y, si se detuvo, el motivo.
    """
    import ads_library as al                              # aquí y no arriba: ads_library importa este módulo

    hoy = hoy or date.today()
    hasta = min(hasta or hoy, hoy)
    desde = desde or date(hoy.year - 7, hoy.month, 1)
    limite_normal = max(10, int(limite or cliente.limit))
    basicos = al.CORE_FIELDS + al.POLITICAL_FIELDS
    campos, tipo_campos = basicos + CAMPOS_EXTRA, "ampliados"
    resumen: Dict[str, Any] = {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "ventanas": 0, "saltadas": 0, "recibidos": 0, "nuevos": 0,
                               "actualizados": 0, "consultas": 0, "detenido": "", "campos": tipo_campos, "mes_mas_antiguo": None,
                               "campos_reducidos": 0}
    if not cliente.token:
        resumen["detenido"] = "Falta el token de Meta (META_AD_LIBRARY_TOKEN)."
        return resumen

    def consulta(params: Dict[str, Any]) -> Tuple[Optional[int], Optional[Dict[str, Any]], str]:
        """Una consulta con sus reintentos por límite de ritmo. Devuelve lo mismo que `cliente._get`."""
        esperas = 0
        while True:
            resumen["consultas"] += 1
            status, cuerpo, err = cliente._get(params)
            if err and esperas < max_esperas and al._limite_de_ritmo(status, err):
                esperas += 1
                log(f"    Meta limita el ritmo de las consultas: espera de {int(espera_ritmo * esperas / 60)} min (intento {esperas} de {max_esperas})…")
                dormir(espera_ritmo * esperas)
                continue
            gastado, minutos = uso_de(getattr(cliente, "_ultimo_uso", None))
            if not err and gastado >= uso_maximo:
                espera = max(espera_ritmo, minutos * 60.0)
                log(f"    Cuota de Meta al {gastado} %: pausa de {int(espera / 60)} min para no ser limitados…")
                cliente._ultimo_uso = None
                dormir(espera)
            return status, cuerpo, err

    def parametros(ini: date, fin: date, cuantos: int) -> Dict[str, Any]:
        p = {"search_terms": termino, "ad_type": "POLITICAL_AND_ISSUE_ADS", "ad_reached_countries": json.dumps([cliente.country]),
             "ad_active_status": "ALL", "ad_delivery_date_min": ini.isoformat(), "fields": ",".join(campos), "limit": cuantos}
        # La ventana que llega a hoy va sin tope: Meta rechaza un `ad_delivery_date_max` posterior a SU «hoy» (va varias horas por detrás de Ecuador).
        if fin < hoy:
            p["ad_delivery_date_max"] = fin.isoformat()
        return p

    # Prueba pequeña: ¿acepta la API los campos ampliados? Si rechaza alguno se sigue con los básicos (los que usa la app).
    status, _cuerpo, err = consulta(parametros(max(desde, hasta - timedelta(days=30)), hasta, 5))
    if err and status == 400 and "field" in err.lower():
        log("  La API rechazó un campo ampliado: se sigue con los campos básicos.")
        campos, tipo_campos = basicos, "basicos"
        resumen["campos"] = tipo_campos
        status, _cuerpo, err = consulta(parametros(max(desde, hasta - timedelta(days=30)), hasta, 5))
    if err:
        resumen["detenido"] = f"No se pudo consultar a Meta: {err}"
        return resumen
    dormir(pausa)

    vacias = 0
    techo = limite_normal        # anuncios por consulta; si una página resulta demasiado pesada baja a la mitad y ya no vuelve a subir en esta captura
    previas = archivo.manifiesto().get("ventanas") or {}
    for clave, ini, fin in ventanas_mensuales(desde, hasta):
        previa = previas.get(clave)
        # un mes reciente se refresca, salvo que se acabe de bajar (al reanudar una captura cortada no se repite lo de hace un rato)
        fresca = bool(previa) and refrescar_horas > 0 and str(previa.get("capturado") or "") >= (datetime.now() - timedelta(hours=refrescar_horas)).isoformat(timespec="seconds")
        reciente = fin >= hoy - timedelta(days=refrescar_dias) and not fresca
        if (previa and previa.get("completo") and not forzar and not reciente
                and str(previa.get("desde")) <= ini.isoformat() and str(previa.get("hasta")) >= fin.isoformat()):
            resumen["saltadas"] += 1
            vacias = vacias + 1 if not previa.get("anuncios") else 0
            if previa.get("anuncios"):
                resumen["mes_mas_antiguo"] = clave
            if vacias >= max_vacias:
                break
            continue

        log(f"  {clave}: bajando ({ini.isoformat()} a {fin.isoformat()})…")
        inicio, pendientes, ids, error = time.time(), [], set(), ""
        reducidos: List[str] = []                           # anuncios que hubo que pedir sin algún campo pesado
        cuentas = {"nuevos": 0, "actualizados": 0}
        techo = min(limite_normal, techo * 2)               # cada mes vuelve a probar un tamaño mayor (los anuncios de unos meses pesan más que los de otros)
        cuantos, after = techo, None

        def volcar() -> None:
            if pendientes:
                c = archivo.fusionar(pendientes, origen="meta-api", anotar=False)
                cuentas["nuevos"] += c["nuevos"]
                cuentas["actualizados"] += c["actualizados"]
                pendientes.clear()

        for _ in range(5000):                               # tope de seguridad: nunca se alcanza con datos reales
            params = parametros(ini, fin, cuantos)
            if after:
                params["after"] = after
            red = quitar = 0
            while True:
                params["limit"] = cuantos
                params["fields"] = ",".join(c for c in campos if c not in CAMPOS_PESADOS[:quitar])
                status, cuerpo, err = consulta(params)
                pesada = bool(err) and al._pagina_pesada(status, err)
                # «reduce the amount of data»: no es lentitud, es que la página no cabe; se baja hasta de uno en uno si hace falta
                demasiado = pesada and "reduce the amount" in err.lower()
                minimo = 1 if demasiado else piso
                if pesada and cuantos > minimo:
                    cuantos = max(minimo, cuantos // 2)
                    techo = max(piso, min(techo, cuantos))   # el resto del mes no vuelve a pasar de aquí (por debajo de `piso` sí se recupera)
                    log(f"    Página demasiado pesada o lenta: se pide de {cuantos} en {cuantos}.")
                    dormir(pausa)
                    continue
                if demasiado and quitar < len(CAMPOS_PESADOS):          # un solo anuncio que Meta no entrega entero: se guarda sin su campo más pesado
                    quitar += 1
                    log(f"    Un anuncio pesa demasiado para la API: se pide sin {CAMPOS_PESADOS[quitar - 1]}.")
                    dormir(pausa)
                    continue
                pasajero = bool(err) and (status is None or pesada or "temporarily unavailable" in err.lower() or "(código 2)" in err or "(código 1)" in err)
                if pasajero and red < max_red:      # red caída o Meta sin responder: suele pasarse solo
                    red += 1
                    log(f"    Sin respuesta de Meta ({err[:60]}…): espera de {int(espera_red * red)} s (intento {red} de {max_red})…")
                    dormir(espera_red * red)
                    continue
                break
            if err:
                error = err
                break
            datos = cuerpo.get("data") or []
            pendientes.extend(datos)
            ids.update(str(d.get("id")) for d in datos if isinstance(d, dict))
            if quitar:
                reducidos.extend(str(d.get("id")) for d in datos if isinstance(d, dict))
            if cuantos < techo:                             # pasado el anuncio pesado, se vuelve al tamaño del mes
                cuantos = min(techo, cuantos * 2)
            if len(pendientes) >= lote:
                volcar()
                log(f"    … {len(ids)} anuncios")
            paging = cuerpo.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not datos or not paging.get("next") or not after:
                break
            dormir(pausa)
        else:
            error = "se alcanzó el tope de páginas de una ventana"
        volcar()

        archivo.marcar_ventana(clave, {"desde": ini.isoformat(), "hasta": fin.isoformat(), "capturado": _ahora(), "anuncios": len(ids),
                                       "completo": not error, "campos": tipo_campos, **({"error": error} if error else {}),
                                       **({"campos_reducidos": reducidos[:500]} if reducidos else {})})
        resumen["campos_reducidos"] += len(reducidos)
        resumen["ventanas"] += 1
        resumen["recibidos"] += len(ids)
        resumen["nuevos"] += cuentas["nuevos"]
        resumen["actualizados"] += cuentas["actualizados"]
        log(f"  {clave}: {len(ids)} anuncios ({cuentas['nuevos']} nuevos, {cuentas['actualizados']} actualizados) en {time.time() - inicio:.0f} s"
            + (f" · INCOMPLETO: {error}" if error else ""))
        if error:
            resumen["detenido"] = f"{clave}: {error}"
            break
        if ids:
            vacias = 0
            resumen["mes_mas_antiguo"] = clave
        else:
            vacias += 1
            if vacias >= max_vacias:
                log(f"  {max_vacias} meses seguidos sin anuncios: no hay nada más antiguo.")
                break
        dormir(pausa)

    with archivo._candado():
        m = archivo.manifiesto()
        archivo._anotar(m, "meta-api", _ahora(), {"recibidos": resumen["recibidos"], "nuevos": resumen["nuevos"],
                                                 "actualizados": resumen["actualizados"], "sin_cambios": 0})
        archivo._guardar_manifiesto(m)
    return resumen


# ----------------------------------------------------------------------
# Del archivo a una copia que la app sabe cargar
# ----------------------------------------------------------------------
def escribir_snapshot(archivo: ArchivoMeta, cliente: Any, salida: str, desde: Optional[str] = None, hasta: Optional[str] = None,
                      dias: Optional[int] = None, hoy: Optional[date] = None) -> Dict[str, Any]:
    """
    Escribe una copia en el formato de `backend/data/ads_snapshot.json` ({guardado, terminos, dias, ads}) con los anuncios del archivo cuyo
    inicio cae entre `desde` y `hasta` (o los últimos `dias` días). Se carga con AD_LIBRARY_SNAPSHOT=<salida> y AD_LIBRARY_SOLO_COPIA=true.
    """
    hoy = hoy or date.today()
    if dias and not desde:
        desde = (hoy - timedelta(days=int(dias))).isoformat()
    n = 0
    os.makedirs(os.path.dirname(os.path.abspath(salida)) or ".", exist_ok=True)
    tmp = salida + ".tmp"
    primero = ultimo = ""
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("{\"ads\": [")
        for reg in archivo.registros(desde, hasta):
            ad = cliente._normalizar(reg["raw"])
            if not ad.get("id"):
                continue
            f.write(("," if n else "") + json.dumps({k: v for k, v in ad.items() if not k.startswith("_")}, ensure_ascii=False))
            n += 1
            fch = str(ad.get("date") or "")[:10]
            if fch:
                primero, ultimo = min(primero or fch, fch), max(ultimo, fch)
        dias_reales = dias or ((hoy - date.fromisoformat(primero)).days if primero else 0)
        f.write("], " + json.dumps({"guardado": _ahora(), "terminos": list(cliente.terms), "dias": int(dias_reales), "origen": "archivo-meta",
                                    "desde": desde or primero, "hasta": hasta or ultimo}, ensure_ascii=False)[1:])
    os.replace(tmp, salida)
    return {"ruta": os.path.abspath(salida), "anuncios": n, "desde": desde or primero, "hasta": hasta or ultimo, "dias": int(dias_reales),
            "bytes": os.path.getsize(salida)}


# ----------------------------------------------------------------------
# Exportar a formatos estándar: una base de datos SQLite y tablas CSV
# ----------------------------------------------------------------------
# Una fila por anuncio, con los rangos de Meta partidos en columnas numéricas. Los nombres de columna son los de las dos salidas (SQLite y CSV).
COLUMNAS_ANUNCIO = [
    ("id", "TEXT PRIMARY KEY"), ("page_id", "TEXT"), ("page_name", "TEXT"), ("pagador", "TEXT"),
    ("inicio", "TEXT"), ("fin", "TEXT"), ("creado", "TEXT"), ("activo", "INTEGER"), ("moneda", "TEXT"),
    ("gasto_min", "INTEGER"), ("gasto_max", "INTEGER"), ("impresiones_min", "INTEGER"), ("impresiones_max", "INTEGER"),
    ("audiencia_min", "INTEGER"), ("audiencia_max", "INTEGER"),
    ("texto", "TEXT"), ("titulo", "TEXT"), ("textos", "INTEGER"), ("plataformas", "TEXT"), ("idiomas", "TEXT"), ("enlace", "TEXT"),
    ("retirado_por_meta", "INTEGER"), ("versiones_de_texto", "INTEGER"), ("visto_primero", "TEXT"), ("visto_ultimo", "TEXT"), ("origen", "TEXT"),
]
_ESQUEMA_SQL = """
CREATE TABLE anuncios ({columnas}, raw_json TEXT);
CREATE TABLE anuncio_regiones (anuncio_id TEXT NOT NULL REFERENCES anuncios(id), region TEXT, porcentaje REAL);
CREATE TABLE anuncio_demografia (anuncio_id TEXT NOT NULL REFERENCES anuncios(id), edad TEXT, genero TEXT, porcentaje REAL);
CREATE TABLE anuncio_versiones (anuncio_id TEXT NOT NULL REFERENCES anuncios(id), hasta TEXT, texto TEXT);
CREATE TABLE info (clave TEXT PRIMARY KEY, valor TEXT);
"""
_INDICES_SQL = """
CREATE INDEX ix_anuncios_pagina ON anuncios(page_id);
CREATE INDEX ix_anuncios_inicio ON anuncios(inicio);
CREATE INDEX ix_anuncios_pagador ON anuncios(pagador);
CREATE INDEX ix_regiones_anuncio ON anuncio_regiones(anuncio_id);
CREATE INDEX ix_regiones_region ON anuncio_regiones(region);
CREATE INDEX ix_demografia_anuncio ON anuncio_demografia(anuncio_id);
CREATE INDEX ix_versiones_anuncio ON anuncio_versiones(anuncio_id);
"""


def _entero(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _decimal(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _limites(obj: Any) -> Tuple[Optional[int], Optional[int]]:
    return (_entero(obj.get("lower_bound")), _entero(obj.get("upper_bound"))) if isinstance(obj, dict) else (None, None)


def filas_de(reg: Dict[str, Any], retirado: Optional[Callable[[Any], bool]] = None) -> Dict[str, Any]:
    """
    Un registro del archivo como filas de tabla: {"anuncio": {columna: valor}, "regiones": [...], "demografia": [...], "versiones": [...]}.
    `retirado(texto)` dice si el texto es el aviso con que Meta sustituye un anuncio retirado (la app pasa el suyo).
    """
    raw = reg.get("raw") or {}
    ad_id = str(reg.get("id") or raw.get("id") or "")
    cuerpos = [str(t) for t in (raw.get("ad_creative_bodies") or []) if t]
    titulos = [str(t) for t in (raw.get("ad_creative_link_titles") or []) if t]
    gasto, impresiones, audiencia = _limites(raw.get("spend")), _limites(raw.get("impressions")), _limites(raw.get("estimated_audience_size"))
    texto = cuerpos[0] if cuerpos else ""
    anuncio = {
        "id": ad_id, "page_id": str(raw.get("page_id") or ""), "page_name": raw.get("page_name") or "", "pagador": raw.get("bylines") or "",
        "inicio": str(raw.get("ad_delivery_start_time") or "")[:10], "fin": str(raw.get("ad_delivery_stop_time") or "")[:10],
        "creado": str(raw.get("ad_creation_time") or "")[:10], "activo": 0 if raw.get("ad_delivery_stop_time") else 1,
        "moneda": raw.get("currency") or "", "gasto_min": gasto[0], "gasto_max": gasto[1],
        "impresiones_min": impresiones[0], "impresiones_max": impresiones[1], "audiencia_min": audiencia[0], "audiencia_max": audiencia[1],
        "texto": texto, "titulo": titulos[0] if titulos else "", "textos": len(cuerpos),
        "plataformas": ", ".join(str(p) for p in (raw.get("publisher_platforms") or [])),
        "idiomas": ", ".join(str(p) for p in (raw.get("languages") or [])),
        "enlace": f"https://www.facebook.com/ads/library/?id={ad_id}" if ad_id.isdigit() else "",
        "retirado_por_meta": int(bool(retirado(texto))) if retirado else None,
        "versiones_de_texto": len(reg.get("versiones") or []),
        "visto_primero": reg.get("visto_primero") or "", "visto_ultimo": reg.get("visto_ultimo") or "", "origen": reg.get("origen") or "",
    }
    regiones = [{"anuncio_id": ad_id, "region": str(r.get("region") or ""), "porcentaje": _decimal(r.get("percentage"))}
                for r in (raw.get("delivery_by_region") or []) if isinstance(r, dict)]
    demografia = [{"anuncio_id": ad_id, "edad": str(d.get("age") or ""), "genero": str(d.get("gender") or ""), "porcentaje": _decimal(d.get("percentage"))}
                  for d in (raw.get("demographic_distribution") or []) if isinstance(d, dict)]
    versiones = [{"anuncio_id": ad_id, "hasta": v.get("hasta") or "", "texto": " ¶ ".join(str(t) for t in (v.get("ad_creative_bodies") or []))}
                 for v in (reg.get("versiones") or []) if isinstance(v, dict)]
    return {"anuncio": anuncio, "regiones": regiones, "demografia": demografia, "versiones": versiones}


def exportar_sqlite(archivo: ArchivoMeta, salida: str, desde: Optional[str] = None, hasta: Optional[str] = None, con_raw: bool = True,
                    retirado: Optional[Callable[[Any], bool]] = None) -> Dict[str, Any]:
    """
    Vuelca el archivo a una base de datos SQLite (un solo archivo, estándar y libre: la abren DB Browser for SQLite, DBeaver, Python, R, Power BI
    por ODBC…). Tablas: `anuncios` (una fila por anuncio; `raw_json` guarda la respuesta original de Meta salvo `con_raw=False`),
    `anuncio_regiones`, `anuncio_demografia`, `anuncio_versiones` e `info`. Se reescribe entera en cada exportación: la fuente sigue siendo el archivo.
    """
    import sqlite3
    os.makedirs(os.path.dirname(os.path.abspath(salida)) or ".", exist_ok=True)
    tmp = salida + ".tmp"
    with contextlib.suppress(OSError):
        os.remove(tmp)
    nombres = [c for c, _ in COLUMNAS_ANUNCIO]
    cuentas = {"anuncios": 0, "regiones": 0, "demografia": 0, "versiones": 0}
    db = sqlite3.connect(tmp)
    try:
        db.executescript(_ESQUEMA_SQL.format(columnas=", ".join(f"{c} {t}" for c, t in COLUMNAS_ANUNCIO)))
        sql_anuncio = f"INSERT OR REPLACE INTO anuncios VALUES ({', '.join('?' * (len(nombres) + 1))})"
        for reg in archivo.registros(desde, hasta):
            f = filas_de(reg, retirado)
            a = f["anuncio"]
            db.execute(sql_anuncio, [a[c] for c in nombres] + [json.dumps(reg.get("raw") or {}, ensure_ascii=False) if con_raw else None])
            db.executemany("INSERT INTO anuncio_regiones VALUES (?, ?, ?)", [(r["anuncio_id"], r["region"], r["porcentaje"]) for r in f["regiones"]])
            db.executemany("INSERT INTO anuncio_demografia VALUES (?, ?, ?, ?)", [(d["anuncio_id"], d["edad"], d["genero"], d["porcentaje"]) for d in f["demografia"]])
            db.executemany("INSERT INTO anuncio_versiones VALUES (?, ?, ?)", [(v["anuncio_id"], v["hasta"], v["texto"]) for v in f["versiones"]])
            cuentas["anuncios"] += 1
            cuentas["regiones"] += len(f["regiones"])
            cuentas["demografia"] += len(f["demografia"])
            cuentas["versiones"] += len(f["versiones"])
        m = archivo.manifiesto()
        rango = db.execute("SELECT MIN(inicio), MAX(inicio) FROM anuncios WHERE inicio <> ''").fetchone()
        info = {"esquema_archivo": m.get("esquema"), "pais": m.get("pais"), "tipo": m.get("tipo"), "exportado": _ahora(),
                "archivo_actualizado": m.get("actualizado"), "anuncios": cuentas["anuncios"], "primer_inicio": rango[0], "ultimo_inicio": rango[1],
                "filtro_desde": desde or "", "filtro_hasta": hasta or "", "fuente": "Biblioteca de Anuncios de Meta (ads_archive), datos públicos",
                "nota": "gasto, impresiones y audiencia son rangos de Meta (mínimo y máximo), no cifras exactas; porcentaje va de 0 a 1"}
        db.executemany("INSERT INTO info VALUES (?, ?)", [(k, "" if v is None else str(v)) for k, v in info.items()])
        db.executescript(_INDICES_SQL)
        db.commit()
    finally:
        db.close()
    _reemplazar(tmp, salida)
    return {"ruta": os.path.abspath(salida), "bytes": os.path.getsize(salida), **cuentas, "primer_inicio": rango[0], "ultimo_inicio": rango[1]}


def exportar_csv(archivo: ArchivoMeta, carpeta: str, desde: Optional[str] = None, hasta: Optional[str] = None,
                 retirado: Optional[Callable[[Any], bool]] = None) -> Dict[str, Any]:
    """
    Las mismas tablas en CSV (UTF-8 con BOM, para que Excel y Power BI lean bien las tildes): anuncios.csv, anuncio_regiones.csv,
    anuncio_demografia.csv y anuncio_versiones.csv. Se relacionan por `id` / `anuncio_id`.
    """
    import csv
    os.makedirs(carpeta, exist_ok=True)
    tablas = {"anuncios": [c for c, _ in COLUMNAS_ANUNCIO], "anuncio_regiones": ["anuncio_id", "region", "porcentaje"],
              "anuncio_demografia": ["anuncio_id", "edad", "genero", "porcentaje"], "anuncio_versiones": ["anuncio_id", "hasta", "texto"]}
    claves = {"anuncios": "anuncio", "anuncio_regiones": "regiones", "anuncio_demografia": "demografia", "anuncio_versiones": "versiones"}
    cuentas = {t: 0 for t in tablas}
    with contextlib.ExitStack() as pila:
        escritores = {}
        for tabla, columnas in tablas.items():
            f = pila.enter_context(open(os.path.join(carpeta, tabla + ".csv.tmp"), "w", encoding="utf-8-sig", newline=""))
            escritores[tabla] = csv.DictWriter(f, fieldnames=columnas)
            escritores[tabla].writeheader()
        for reg in archivo.registros(desde, hasta):
            filas = filas_de(reg, retirado)
            for tabla, clave in claves.items():
                lote = [filas[clave]] if clave == "anuncio" else filas[clave]
                escritores[tabla].writerows(lote)
                cuentas[tabla] += len(lote)
    for tabla in tablas:
        _reemplazar(os.path.join(carpeta, tabla + ".csv.tmp"), os.path.join(carpeta, tabla + ".csv"))
    return {"carpeta": os.path.abspath(carpeta), **cuentas,
            "bytes": sum(os.path.getsize(os.path.join(carpeta, t + ".csv")) for t in tablas)}
