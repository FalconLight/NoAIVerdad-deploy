import gzip
import json
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import archivo_meta
from archivo_meta import ArchivoMeta, capturar, escribir_snapshot, fusionar_registro, mes_de, ventanas_mensuales
from ads_library import AdLibraryClient

SECRET = "EAAB-super-secret-token"


def _crudo(ad_id, inicio="2026-10-01", texto="Vota por el cambio en tu provincia", **extra):
    base = {
        "id": str(ad_id), "page_id": "111", "page_name": "Página de prueba", "bylines": "Movimiento Ejemplo",
        "ad_delivery_start_time": inicio, "ad_creative_bodies": [texto], "currency": "USD",
        "spend": {"lower_bound": "100", "upper_bound": "499"}, "impressions": {"lower_bound": "10000", "upper_bound": "50000"},
        "publisher_platforms": ["FACEBOOK"], "delivery_by_region": [{"region": "Guayas", "percentage": "1"}],
        "ad_snapshot_url": f"https://www.facebook.com/ads/archive/render_ad/?id={ad_id}&access_token={SECRET}",
    }
    base.update(extra)
    return base


def _archivo():
    return ArchivoMeta(os.path.join(tempfile.mkdtemp(prefix="noai_arch_"), "archivo"))


def _cliente(**env):
    entorno = {"META_AD_LIBRARY_TOKEN": SECRET, "META_INTEGRATION_ENABLED": "true", "AD_LIBRARY_TERMS": "*",
               "AD_LIBRARY_SNAPSHOT": os.path.join(tempfile.mkdtemp(prefix="noai_test_"), "snapshot.json")}
    entorno.update(env)
    with mock.patch.dict(os.environ, entorno):
        return AdLibraryClient()


class FusionTest(unittest.TestCase):
    def test_nuevo_actualizado_y_sin_cambios(self):
        reg, que = fusionar_registro(None, _crudo(1), "2026-11-01T10:00:00", "meta-api")
        self.assertEqual(que, "nuevo")
        self.assertNotIn("ad_snapshot_url", reg["raw"])
        igual, que = fusionar_registro(reg, _crudo(1), "2026-11-02T10:00:00", "meta-api")
        self.assertEqual(que, "sin_cambios")
        self.assertEqual((igual["visto_primero"], igual["visto_ultimo"]), ("2026-11-01T10:00:00", "2026-11-02T10:00:00"))
        mas, que = fusionar_registro(igual, _crudo(1, spend={"lower_bound": "500", "upper_bound": "999"}), "2026-11-03T10:00:00", "meta-api")
        self.assertEqual(que, "actualizado")
        self.assertEqual(mas["raw"]["spend"]["lower_bound"], "500")

    def test_una_descarga_con_menos_campos_no_borra_los_extra(self):
        reg, _ = fusionar_registro(None, _crudo(1, languages=["es"], ad_creative_link_captions=["ejemplo.ec"]), "2026-11-01T10:00:00", "meta-api")
        sin_extra = _crudo(1)
        del sin_extra["ad_creative_bodies"]                 # p. ej. Meta deja de devolver el texto
        reg, _ = fusionar_registro(reg, sin_extra, "2026-11-02T10:00:00", "renovacion")
        self.assertEqual(reg["raw"]["languages"], ["es"])
        self.assertEqual(reg["raw"]["ad_creative_bodies"], ["Vota por el cambio en tu provincia"])

    def test_si_cambia_el_texto_se_guarda_la_version_anterior(self):
        reg, _ = fusionar_registro(None, _crudo(1), "2026-11-01T10:00:00", "meta-api")
        aviso = "This content was removed because it didn't follow our Advertising Standards."
        reg, que = fusionar_registro(reg, _crudo(1, texto=aviso), "2026-11-05T10:00:00", "meta-api")
        self.assertEqual(que, "actualizado")
        self.assertEqual(reg["raw"]["ad_creative_bodies"], [aviso])
        self.assertEqual(reg["versiones"], [{"hasta": "2026-11-01T10:00:00", "ad_creative_bodies": ["Vota por el cambio en tu provincia"]}])
        otra_vez, que = fusionar_registro(reg, _crudo(1, texto=aviso), "2026-11-06T10:00:00", "meta-api")
        self.assertEqual((que, len(otra_vez["versiones"])), ("sin_cambios", 1))

    def test_una_captura_mas_antigua_solo_rellena_lo_que_falta(self):
        reg, _ = fusionar_registro(None, _crudo(1, spend={"lower_bound": "500", "upper_bound": "999"}), "2026-11-05T10:00:00", "meta-api")
        reg, _ = fusionar_registro(reg, _crudo(1, languages=["es"]), "2026-10-01T10:00:00", "importacion")
        self.assertEqual(reg["raw"]["spend"]["lower_bound"], "500")          # manda la captura más reciente
        self.assertEqual(reg["raw"]["languages"], ["es"])                    # y lo que no tenía se rellena
        self.assertEqual((reg["visto_primero"], reg["visto_ultimo"]), ("2026-10-01T10:00:00", "2026-11-05T10:00:00"))

    def test_mes_de(self):
        self.assertEqual(mes_de({"ad_delivery_start_time": "2026-10-07"}), "2026-10")
        self.assertEqual(mes_de({"ad_creation_time": "2025-02-28T10:00:00+0000"}), "2025-02")
        self.assertEqual(mes_de({}), "sin-fecha")


class ArchivoTest(unittest.TestCase):
    def test_particion_por_mes_manifiesto_y_lectura(self):
        a = _archivo()
        c = a.fusionar([_crudo(1, "2026-10-01"), _crudo(2, "2026-10-20"), _crudo(3, "2026-09-15"), _crudo(4, inicio=None), {"sin": "id"}],
                       capturado="2026-11-01T10:00:00")
        self.assertEqual((c["recibidos"], c["nuevos"]), (4, 4))
        self.assertEqual(a.meses(), ["2026-09", "2026-10", "sin-fecha"])
        m = a.manifiesto()
        self.assertEqual((m["esquema"], m["total"], m["meses"]["2026-10"]["anuncios"]), (1, 4, 2))
        self.assertEqual([r["id"] for r in a.registros()], ["3", "1", "2", "4"])
        self.assertEqual([r["id"] for r in a.registros(desde="2026-10-10")], ["2"])
        self.assertEqual([r["id"] for r in a.registros(hasta="2026-10-05")], ["3", "1"])
        self.assertFalse(os.path.exists(a.ruta_candado))
        self.assertEqual([n for n in os.listdir(a.dir_anuncios) if n.endswith(".tmp")], [])

    def test_nunca_guarda_la_url_con_el_token(self):
        a = _archivo()
        a.fusionar([_crudo(1)])
        with gzip.open(a._ruta_mes("2026-10"), "rt", encoding="utf-8") as f:
            contenido = f.read()
        self.assertNotIn(SECRET, contenido)
        self.assertNotIn("ad_snapshot_url", contenido)

    def test_volver_a_fusionar_no_duplica_y_el_archivo_es_reproducible(self):
        a = _archivo()
        a.fusionar([_crudo(2), _crudo(1)], capturado="2026-11-01T10:00:00")
        sha = a.manifiesto()["meses"]["2026-10"]["sha256"]
        c = a.fusionar([_crudo(1), _crudo(2)], capturado="2026-11-01T10:00:00")
        self.assertEqual((c["nuevos"], c["sin_cambios"]), (0, 2))
        self.assertEqual(a.manifiesto()["meses"]["2026-10"]["sha256"], sha)
        self.assertEqual(a.manifiesto()["total"], 2)

    def test_verificar_detecta_un_archivo_alterado_o_ausente(self):
        a = _archivo()
        a.fusionar([_crudo(1, "2026-10-01"), _crudo(2, "2026-09-01")])
        self.assertEqual(a.verificar(), {"ok": True, "meses": 2, "anuncios": 2, "problemas": []})
        with gzip.open(a._ruta_mes("2026-10"), "wt", encoding="utf-8") as f:
            f.write(json.dumps({"id": "9", "raw": _crudo(9)}) + "\n")
        os.remove(a._ruta_mes("2026-09"))
        v = a.verificar()
        self.assertFalse(v["ok"])
        self.assertTrue(any("sha256" in p for p in v["problemas"]))
        self.assertTrue(any("falta el archivo" in p for p in v["problemas"]))

    def test_exportar_e_importar_ida_y_vuelta(self):
        a = _archivo()
        a.fusionar([_crudo(1), _crudo(2, "2025-03-01")], capturado="2026-11-01T10:00:00")
        a.fusionar([_crudo(1, texto="Texto corregido del anuncio")], capturado="2026-11-02T10:00:00")
        ruta = os.path.join(tempfile.mkdtemp(prefix="noai_zip_"), "archivo.zip")
        self.assertEqual(a.exportar(ruta)["anuncios"], 2)

        b = _archivo()
        b.fusionar([_crudo(3, "2026-10-09"), _crudo(1, spend={"lower_bound": "0", "upper_bound": "99"})], capturado="2026-10-15T10:00:00")
        c = b.importar(ruta)
        self.assertEqual((c["recibidos"], c["nuevos"], c["actualizados"]), (2, 1, 1))
        regs = {r["id"]: r for r in b.registros()}
        self.assertEqual(sorted(regs), ["1", "2", "3"])                       # unión: lo que había (3) no se pierde
        self.assertEqual(regs["1"]["raw"]["ad_creative_bodies"], ["Texto corregido del anuncio"])
        self.assertEqual(regs["1"]["raw"]["spend"]["lower_bound"], "100")     # manda la captura más reciente (la importada)
        self.assertEqual(regs["1"]["visto_primero"], "2026-10-15T10:00:00")
        self.assertEqual(len(regs["1"]["versiones"]), 1)
        self.assertTrue(b.verificar()["ok"])
        self.assertEqual(b.importar(ruta)["nuevos"], 0)                       # importar dos veces no cambia nada

    def test_la_bitacora_acumula_las_renovaciones_del_dia(self):
        a = _archivo()
        a.fusionar([_crudo(1)], origen="renovacion", capturado="2026-11-01T10:00:00")
        a.fusionar([_crudo(1), _crudo(2)], origen="renovacion", capturado="2026-11-01T11:00:00")
        a.fusionar([_crudo(3)], origen="renovacion", capturado="2026-11-02T09:00:00")
        capturas = a.manifiesto()["capturas"]
        self.assertEqual(len(capturas), 2)
        self.assertEqual((capturas[0]["nuevos"], capturas[0]["veces"]), (2, 2))


class EngancheAppTest(unittest.TestCase):
    def test_cada_descarga_de_la_app_queda_en_el_archivo(self):
        cliente = _cliente()
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {"data": [_crudo(1), _crudo(2, "2026-09-03")]}
        with mock.patch("ads_library.requests.get", return_value=respuesta):
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(len(ads), 2)
        a = ArchivoMeta(cliente.archivo_dir)
        self.assertEqual(cliente.archivo_dir, os.path.join(os.path.dirname(cliente.snapshot_path), "archivo"))
        self.assertEqual(sorted(r["id"] for r in a.registros()), ["1", "2"])
        self.assertEqual(a.manifiesto()["capturas"][-1]["origen"], "renovacion")
        self.assertTrue(a.verificar()["ok"])

    def test_se_puede_apagar_y_un_fallo_del_archivo_no_rompe_la_app(self):
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {"data": [_crudo(1)]}
        apagado = _cliente(AD_LIBRARY_ARCHIVAR="false")
        with mock.patch("ads_library.requests.get", return_value=respuesta):
            apagado.obtener_nacional()
        self.assertFalse(os.path.exists(apagado.archivo_dir))
        roto = _cliente()
        with mock.patch("ads_library.requests.get", return_value=respuesta), mock.patch.object(ArchivoMeta, "fusionar", side_effect=OSError("disco lleno")):
            ads, estado = roto.obtener_nacional()
        self.assertEqual((len(ads), estado["ok"]), (1, True))

    def test_snapshot_del_archivo_se_carga_en_modo_solo_copia_sin_token(self):
        a = _archivo()
        a.fusionar([_crudo(1, "2025-02-01"), _crudo(2, "2026-10-01"), _crudo(3, "2024-06-01")])
        salida = os.path.join(tempfile.mkdtemp(prefix="noai_snap_"), "historico.json")
        r = escribir_snapshot(a, _cliente(), salida, desde="2025-01-01", hoy=date(2026, 11, 10))
        self.assertEqual((r["anuncios"], r["desde"], r["hasta"]), (2, "2025-01-01", "2026-10-01"))
        with open(salida, encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual(sorted(x["id"] for x in snap["ads"]), ["1", "2"])
        self.assertFalse(any(k.startswith("_") for x in snap["ads"] for k in x))
        self.assertNotIn(SECRET, json.dumps(snap))

        # sin token, con otros días y con la integración sin encender: en modo solo copia se sirve igual y nunca se llama a Meta
        cliente = _cliente(META_AD_LIBRARY_TOKEN="", META_INTEGRATION_ENABLED="", AD_LIBRARY_SNAPSHOT=salida, AD_LIBRARY_SOLO_COPIA="true",
                           AD_LIBRARY_DAYS="30")
        with mock.patch("ads_library.requests.get", side_effect=AssertionError("no debe llamar a Meta")), \
                mock.patch.object(cliente, "_claves_firebase", return_value={}):
            ads, estado = cliente.obtener_nacional()
            self.assertEqual(sorted(x["id"] for x in ads), ["1", "2"])
            self.assertTrue(estado["ok"] and estado["solo_copia"] and estado["desactualizado"])
            self.assertEqual(estado["dias"], r["dias"])
            self.assertTrue(cliente.configurado)
            self.assertEqual(cliente.diagnostico()["anuncios_devueltos"], 2)
            self.assertEqual(cliente.top_gastadores(None, 5)["anunciantes"][0]["anuncios"], 2)

    def test_solo_copia_sin_archivo_lo_dice_y_no_llama_a_meta(self):
        cliente = _cliente(META_AD_LIBRARY_TOKEN="", AD_LIBRARY_SOLO_COPIA="true")
        with mock.patch("ads_library.requests.get", side_effect=AssertionError("no debe llamar a Meta")):
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(ads, [])
        self.assertFalse(estado["ok"])
        self.assertIn("AD_LIBRARY_SNAPSHOT", estado["mensaje"])


class ExportarEstandarTest(unittest.TestCase):
    def _archivo_con_datos(self):
        a = _archivo()
        a.fusionar([_crudo(1, "2026-10-01", languages=["es"], ad_delivery_stop_time="2026-10-09",
                           demographic_distribution=[{"age": "18-24", "gender": "female", "percentage": "0.4"}, {"age": "25-34", "gender": "male", "percentage": "0.6"}],
                           delivery_by_region=[{"region": "Guayas", "percentage": "0.75"}, {"region": "Pichincha", "percentage": "0.25"}]),
                    _crudo(2, "2025-03-05", texto="Segundo anuncio, con «comillas», coma y\nsalto de línea")], capturado="2026-11-01T10:00:00")
        a.fusionar([_crudo(2, "2025-03-05", texto="This content was removed because it didn't follow our Advertising Standards.")], capturado="2026-11-05T10:00:00")
        return a

    def test_sqlite_tiene_las_tablas_y_los_rangos_como_numeros(self):
        import sqlite3
        import ads_library
        a = self._archivo_con_datos()
        salida = os.path.join(tempfile.mkdtemp(prefix="noai_db_"), "anuncios.sqlite")
        r = archivo_meta.exportar_sqlite(a, salida, retirado=ads_library._retirado_por_meta)
        self.assertEqual((r["anuncios"], r["regiones"], r["demografia"], r["versiones"]), (2, 3, 2, 1))
        self.assertEqual((r["primer_inicio"], r["ultimo_inicio"]), ("2025-03-05", "2026-10-01"))
        db = sqlite3.connect(salida)
        try:
            fila = db.execute("SELECT page_name, pagador, inicio, fin, activo, gasto_min, gasto_max, impresiones_max, idiomas, plataformas, enlace, "
                              "retirado_por_meta FROM anuncios WHERE id = '1'").fetchone()
            self.assertEqual(fila, ("Página de prueba", "Movimiento Ejemplo", "2026-10-01", "2026-10-09", 0, 100, 499, 50000, "es", "FACEBOOK",
                                    "https://www.facebook.com/ads/library/?id=1", 0))
            self.assertEqual(db.execute("SELECT activo, retirado_por_meta, versiones_de_texto FROM anuncios WHERE id = '2'").fetchone(), (1, 1, 1))
            self.assertEqual(db.execute("SELECT region, porcentaje FROM anuncio_regiones WHERE anuncio_id = '1' ORDER BY porcentaje DESC").fetchall(),
                             [("Guayas", 0.75), ("Pichincha", 0.25)])
            self.assertEqual(db.execute("SELECT edad, genero, porcentaje FROM anuncio_demografia ORDER BY edad").fetchall(),
                             [("18-24", "female", 0.4), ("25-34", "male", 0.6)])
            self.assertIn("Segundo anuncio", db.execute("SELECT texto FROM anuncio_versiones WHERE anuncio_id = '2'").fetchone()[0])
            crudo = json.loads(db.execute("SELECT raw_json FROM anuncios WHERE id = '1'").fetchone()[0])
            self.assertEqual(crudo["languages"], ["es"])
            volcado = "\n".join(db.iterdump())
            self.assertNotIn(SECRET, volcado)
            self.assertNotIn("ad_snapshot_url", volcado)
            self.assertEqual(db.execute("SELECT valor FROM info WHERE clave = 'anuncios'").fetchone()[0], "2")
        finally:
            db.close()
        # filtrar por fechas y sin la respuesta original; exportar encima reemplaza la base anterior
        r = archivo_meta.exportar_sqlite(a, salida, desde="2026-01-01", con_raw=False)
        db = sqlite3.connect(salida)
        try:
            self.assertEqual(db.execute("SELECT id, raw_json, retirado_por_meta FROM anuncios").fetchall(), [("1", None, None)])
        finally:
            db.close()

    def test_csv_se_lee_de_vuelta_con_tildes_y_saltos_de_linea(self):
        import csv
        a = self._archivo_con_datos()
        carpeta = os.path.join(tempfile.mkdtemp(prefix="noai_csv_"), "csv")
        r = archivo_meta.exportar_csv(a, carpeta)
        self.assertEqual((r["anuncios"], r["anuncio_regiones"], r["anuncio_demografia"], r["anuncio_versiones"]), (2, 3, 2, 1))
        self.assertEqual(sorted(os.listdir(carpeta)), ["anuncio_demografia.csv", "anuncio_regiones.csv", "anuncio_versiones.csv", "anuncios.csv"])
        with open(os.path.join(carpeta, "anuncios.csv"), "rb") as f:
            self.assertEqual(f.read(3), b"\xef\xbb\xbf")                 # BOM: Excel reconoce el UTF-8
        with open(os.path.join(carpeta, "anuncios.csv"), encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f))
        self.assertEqual([x["id"] for x in filas], ["2", "1"])
        self.assertEqual(list(filas[0])[:4], ["id", "page_id", "page_name", "pagador"])
        self.assertEqual((filas[1]["page_name"], filas[1]["gasto_min"], filas[1]["gasto_max"], filas[1]["fin"]), ("Página de prueba", "100", "499", "2026-10-09"))
        with open(os.path.join(carpeta, "anuncio_versiones.csv"), encoding="utf-8-sig", newline="") as f:
            versiones = list(csv.DictReader(f))
        self.assertEqual(versiones[0]["texto"], "Segundo anuncio, con «comillas», coma y\nsalto de línea")
        with open(os.path.join(carpeta, "anuncio_regiones.csv"), encoding="utf-8-sig", newline="") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 3)


class _MetaFalsa:
    """Sustituye a `cliente._get`: responde según la ventana pedida y anota cada consulta."""

    def __init__(self, por_mes, fallos=None, por_pagina=2):
        self.por_mes, self.fallos, self.por_pagina = por_mes, list(fallos or []), por_pagina
        self.llamadas = []

    def __call__(self, params):
        self.llamadas.append(dict(params))
        if "ad_snapshot_url" in params["fields"]:
            raise AssertionError("nunca se pide ad_snapshot_url")
        if params["limit"] == 5:                                  # la prueba inicial de campos
            return 200, {"data": []}, ""
        mes = params["ad_delivery_date_min"][:7]
        if self.fallos and self.fallos[0][0] == mes:
            return self.fallos.pop(0)[1]
        datos = self.por_mes.get(mes, [])
        i = int(params.get("after") or 0)
        trozo = datos[i:i + self.por_pagina]
        paging = {"cursors": {"after": str(i + self.por_pagina)}}
        if i + self.por_pagina < len(datos):
            paging["next"] = "https://graph.facebook.com/siguiente"
        return 200, {"data": trozo, "paging": paging}, ""


class CapturaTest(unittest.TestCase):
    HOY = date(2026, 11, 10)

    def _capturar(self, meta, archivo, **kw):
        cliente = _cliente()
        cliente._get = meta
        esperas = []
        kw.setdefault("desde", date(2026, 7, 1))
        kw.setdefault("refrescar_horas", 0)
        r = capturar(cliente, archivo, hoy=self.HOY, pausa=0, log=lambda _m: None, dormir=esperas.append, **kw)
        return r, esperas

    def test_ventanas_mensuales(self):
        v = ventanas_mensuales(date(2025, 12, 15), date(2026, 2, 10))
        self.assertEqual(v, [("2026-02", date(2026, 2, 1), date(2026, 2, 10)), ("2026-01", date(2026, 1, 1), date(2026, 1, 31)),
                             ("2025-12", date(2025, 12, 15), date(2025, 12, 31))])

    def test_baja_por_meses_paginando_y_marca_las_ventanas(self):
        meta = _MetaFalsa({"2026-11": [_crudo(1, "2026-11-02")], "2026-10": [_crudo(i, "2026-10-05") for i in (2, 3, 4, 5, 6)],
                           "2026-08": [_crudo(7, "2026-08-20")]})
        a = _archivo()
        r, _ = self._capturar(meta, a)
        self.assertEqual((r["ventanas"], r["recibidos"], r["nuevos"], r["detenido"], r["mes_mas_antiguo"]), (5, 7, 7, "", "2026-08"))
        self.assertEqual(a.manifiesto()["total"], 7)
        v = a.manifiesto()["ventanas"]
        self.assertEqual(sorted(v), ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11"])
        self.assertTrue(all(x["completo"] for x in v.values()))
        self.assertEqual((v["2026-11"]["hasta"], v["2026-10"]["anuncios"], v["2026-09"]["anuncios"]), ("2026-11-10", 5, 0))
        pedidas = [p for p in meta.llamadas if p["limit"] != 5]
        self.assertEqual(len([p for p in pedidas if p["ad_delivery_date_min"] == "2026-10-01"]), 3)      # 5 anuncios de 2 en 2
        self.assertTrue(all(p["search_terms"] == "*" and p["ad_active_status"] == "ALL" and "languages" in p["fields"] for p in pedidas))
        self.assertEqual(pedidas[-1]["ad_delivery_date_max"], "2026-07-31")
        self.assertNotIn("ad_delivery_date_max", pedidas[0])           # el mes en curso va sin tope: Meta rechaza una fecha posterior a su «hoy»
        self.assertTrue(a.verificar()["ok"])

    def test_reanuda_salta_lo_completo_antiguo_y_refresca_lo_reciente(self):
        datos = {"2026-11": [_crudo(1, "2026-11-02")], "2026-03": [_crudo(2, "2026-03-05")], "2026-02": [_crudo(3, "2026-02-05")]}
        a = _archivo()
        self._capturar(_MetaFalsa(datos), a, desde=date(2026, 2, 1))
        meta = _MetaFalsa(datos)
        r, _ = self._capturar(meta, a, desde=date(2026, 2, 1))
        bajados = sorted({p["ad_delivery_date_min"][:7] for p in meta.llamadas if p["limit"] != 5})
        self.assertEqual(bajados, ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11"])       # los que tocan los últimos 120 días
        self.assertEqual((r["saltadas"], r["nuevos"], r["mes_mas_antiguo"]), (5, 0, "2026-02"))
        meta = _MetaFalsa(datos)
        r, _ = self._capturar(meta, a, desde=date(2026, 2, 1), forzar=True)
        self.assertEqual((r["saltadas"], r["ventanas"]), (0, 10))
        # lo reciente recién bajado (hace menos de `refrescar_horas`) tampoco se repite: reanudar una captura cortada no vuelve a empezar
        meta = _MetaFalsa(datos)
        r, _ = self._capturar(meta, a, desde=date(2026, 1, 1), refrescar_horas=12)
        self.assertEqual(sorted({p["ad_delivery_date_min"][:7] for p in meta.llamadas if p["limit"] != 5}), ["2026-01"])
        self.assertEqual((r["saltadas"], r["ventanas"]), (10, 1))

    def test_limite_de_ritmo_espera_y_si_sigue_se_detiene_reanudable(self):
        ritmo = (400, None, "HTTP 400 (código 613): Calls to this api have exceeded the rate limit.")
        datos = {"2026-11": [_crudo(1, "2026-11-02")], "2026-10": [_crudo(2, "2026-10-02")], "2026-09": [_crudo(3, "2026-09-02")]}
        a = _archivo()
        # un tropiezo: espera y sigue
        r, esperas = self._capturar(_MetaFalsa(datos, fallos=[("2026-10", ritmo)]), a, espera_ritmo=300)
        self.assertEqual((r["detenido"], r["recibidos"]), ("", 3))
        self.assertIn(300, esperas)
        # Meta no cede: se detiene, el mes queda incompleto y lo ya bajado se conserva
        b = _archivo()
        r, esperas = self._capturar(_MetaFalsa(datos, fallos=[("2026-10", ritmo)] * 3), b, espera_ritmo=300, max_esperas=2)
        self.assertIn("2026-10", r["detenido"])
        self.assertEqual([e for e in esperas if e], [300, 600])
        v = b.manifiesto()["ventanas"]
        self.assertEqual((v["2026-11"]["completo"], v["2026-10"]["completo"]), (True, False))
        self.assertEqual(b.manifiesto()["total"], 1)
        # al volver a ejecutar continúa y termina
        r, _ = self._capturar(_MetaFalsa(datos), b)
        self.assertEqual((r["detenido"], b.manifiesto()["total"]), ("", 3))
        self.assertTrue(b.manifiesto()["ventanas"]["2026-10"]["completo"])

    def test_pagina_pesada_pide_la_mitad_y_campo_rechazado_vuelve_a_los_basicos(self):
        pesada = (500, None, "HTTP 500 (código 1): Please reduce the amount of data you're asking for")
        meta = _MetaFalsa({"2026-11": [_crudo(1, "2026-11-02")]}, fallos=[("2026-11", pesada)])
        r, _ = self._capturar(meta, _archivo(), desde=date(2026, 11, 1), limite=400)
        self.assertEqual((r["detenido"], r["recibidos"]), ("", 1))
        self.assertEqual([p["limit"] for p in meta.llamadas if p["limit"] != 5], [400, 200])

        class Rechaza(_MetaFalsa):
            def __call__(self, params):
                if "languages" in params["fields"]:
                    self.llamadas.append(dict(params))
                    return 400, None, "HTTP 400 (código 100): (#100) Tried accessing nonexisting field (languages)"
                return super().__call__(params)

        meta = Rechaza({"2026-11": [_crudo(1, "2026-11-02")]})
        r, _ = self._capturar(meta, _archivo(), desde=date(2026, 11, 1))
        self.assertEqual((r["campos"], r["recibidos"], r["detenido"]), ("basicos", 1, ""))

    def test_frena_cuando_meta_avisa_de_que_la_cuota_se_agota(self):
        cabecera = '{"1":[{"type":"ads_archive","call_count":12,"total_cputime":3,"total_time":81,"estimated_time_to_regain_access":7}]}'
        self.assertEqual(archivo_meta.uso_de(cabecera), (81, 7))
        self.assertEqual(archivo_meta.uso_de(None), (0, 0))
        self.assertEqual(archivo_meta.uso_de("no es json"), (0, 0))
        meta = _MetaFalsa({"2026-11": [_crudo(1, "2026-11-02")]})
        cliente = _cliente()
        avisos = ['{"1":[{"type":"ads_archive","call_count":5,"total_cputime":2,"total_time":90,"estimated_time_to_regain_access":0}]}']

        def con_uso(params):
            cliente._ultimo_uso = avisos.pop() if avisos and params["limit"] != 5 else '{"1":[{"total_time":10}]}'
            return meta(params)

        cliente._get = con_uso
        esperas = []
        r = capturar(cliente, _archivo(), desde=date(2026, 11, 1), hoy=self.HOY, pausa=0, log=lambda _m: None, dormir=esperas.append, espera_ritmo=300)
        self.assertEqual((r["detenido"], r["recibidos"]), ("", 1))
        self.assertEqual([e for e in esperas if e], [300])

    def test_un_fallo_de_red_se_reintenta_con_esperas_y_si_no_cede_se_detiene(self):
        red = (None, None, "Error de red: HTTPSConnectionPool(host='graph.facebook.com', port=443): Max retries exceeded")
        datos = {"2026-11": [_crudo(1, "2026-11-02")]}
        r, esperas = self._capturar(_MetaFalsa(datos, fallos=[("2026-11", red)] * 2), _archivo(), desde=date(2026, 11, 1), espera_red=60)
        self.assertEqual((r["detenido"], r["recibidos"]), ("", 1))
        self.assertEqual([e for e in esperas if e], [60, 120])
        caido = (400, None, "HTTP 400 (código 2): (#2) Service temporarily unavailable")          # Meta caída un momento: también se reintenta
        r, esperas = self._capturar(_MetaFalsa(datos, fallos=[("2026-11", caido)]), _archivo(), desde=date(2026, 11, 1), espera_red=60)
        self.assertEqual((r["detenido"], r["recibidos"], [e for e in esperas if e]), ("", 1, [60]))
        a = _archivo()
        r, esperas = self._capturar(_MetaFalsa(datos, fallos=[("2026-11", red)] * 9), a, desde=date(2026, 11, 1), espera_red=60, max_red=3)
        self.assertIn("Error de red", r["detenido"])
        self.assertEqual([e for e in esperas if e], [60, 120, 180])
        self.assertFalse(a.manifiesto()["ventanas"]["2026-11"]["completo"])

    def test_un_anuncio_que_meta_no_entrega_entero_se_guarda_sin_su_campo_pesado(self):
        reduce_ = (500, None, "HTTP 500 (código 1): Please reduce the amount of data you're asking for, then retry your request")

        class Gigante(_MetaFalsa):
            """El anuncio 3 (el tercero) solo sale si se pide solo y sin el reparto por edad."""
            def __call__(self, params):
                if params["limit"] != 5 or params.get("after"):
                    i = int(params.get("after") or 0)
                    if i <= 2 < i + params["limit"] and (params["limit"] > 1 or "demographic_distribution" in params["fields"]):
                        self.llamadas.append(dict(params))
                        return reduce_
                self.por_pagina = params["limit"]
                return super().__call__(params)

        meta = Gigante({"2026-11": [_crudo(i, "2026-11-02") for i in range(1, 9)]})
        a = _archivo()
        r, esperas = self._capturar(meta, a, desde=date(2026, 11, 1), limite=16, piso=2)
        self.assertEqual((r["detenido"], r["recibidos"], r["campos_reducidos"]), ("", 8, 1))
        self.assertEqual(a.manifiesto()["ventanas"]["2026-11"]["campos_reducidos"], ["3"])
        self.assertTrue(a.manifiesto()["ventanas"]["2026-11"]["completo"])
        self.assertEqual(sorted(x["id"] for x in a.registros()), [str(i) for i in range(1, 9)])
        self.assertEqual([e for e in esperas if e], [])                      # no hizo falta esperar: bastó con pedir menos
        tamanos = [p["limit"] for p in meta.llamadas if p["limit"] != 5 or p.get("after")]
        self.assertEqual(tamanos[:8], [16, 8, 4, 2, 2, 1, 1, 2])                    # baja hasta uno, lo pide sin el campo y vuelve a subir

    def test_para_tras_varios_meses_vacios_y_sin_token_no_hace_nada(self):
        meta = _MetaFalsa({"2026-11": [_crudo(1, "2026-11-02")]})
        r, _ = self._capturar(meta, _archivo(), desde=date(2020, 1, 1), max_vacias=3)
        self.assertEqual((r["ventanas"], r["mes_mas_antiguo"]), (4, "2026-11"))
        cliente = _cliente(META_AD_LIBRARY_TOKEN="")
        with mock.patch.object(cliente, "_claves_firebase", return_value={}):
            cliente.reload_token(force=True)
        cliente._get = mock.Mock(side_effect=AssertionError("sin token no se consulta"))
        r = capturar(cliente, _archivo(), hoy=self.HOY, log=lambda _m: None, dormir=lambda _s: None)
        self.assertIn("token", r["detenido"])


if __name__ == "__main__":
    unittest.main()
