"""Filtro global «solo activos» y prensa local por provincia."""
import json
import os
import tempfile
import unittest
from unittest import mock

import ads_library
import meta_service
from tests.test_ads_library import _anuncio, _cliente, _respuesta
from tests.test_afiliaciones import _archivo


class RangoDeFechasTests(unittest.TestCase):
    """Filtro global por fechas: quedan los anuncios que circularon algún día del rango."""

    def _cliente_con_datos(self):
        datos = [
            _anuncio("1", [("Azuay", "1.0")], page_name="Septiembre", page_id="901", ad_delivery_start_time="2026-09-01", ad_delivery_stop_time="2026-09-10"),
            _anuncio("2", [("Azuay", "1.0")], page_name="Octubre", page_id="902", ad_delivery_start_time="2026-10-05", ad_delivery_stop_time="2026-10-20"),
            _anuncio("3", [("Azuay", "1.0")], page_name="Sigue activo", page_id="903", ad_delivery_start_time="2026-10-15"),
            _anuncio("4", [("Azuay", "1.0")], page_name="Noviembre", page_id="904", ad_delivery_start_time="2026-11-03", ad_delivery_stop_time="2026-11-04"),
        ]
        return _cliente(), datos

    def _con_rango(self, desde, hasta):
        cliente, datos = self._cliente_con_datos()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            cliente.obtener_nacional()
            marca = ads_library.RANGO_FECHAS.set((desde, hasta))
            try:
                ads, estado = cliente.obtener_nacional()
                top = cliente.top_gastadores(None, 10)["anunciantes"]
            finally:
                ads_library.RANGO_FECHAS.reset(marca)
        return sorted(a["id"] for a in ads), estado, sorted(a["page_name"] for a in top)

    def test_sin_rango_se_ven_todos(self):
        ids, estado, _ = self._con_rango(None, None)
        self.assertEqual(ids, ["1", "2", "3", "4"])
        self.assertNotIn("rango_fechas", estado)

    def test_un_rango_deja_lo_que_circulo_en_el_y_cuenta_lo_excluido(self):
        ids, estado, top = self._con_rango("2026-10-01", "2026-10-31")
        self.assertEqual(ids, ["2", "3"])                        # el de septiembre ya había terminado y el de noviembre aún no empezaba
        self.assertEqual(estado["rango_fechas"], {"desde": "2026-10-01", "hasta": "2026-10-31"})
        self.assertEqual((estado["excluidos_fechas"], estado["total_nacional"]), (2, 2))
        self.assertEqual(top, ["Octubre", "Sigue activo"])       # el ranking también lo respeta

    def test_un_solo_dia(self):
        self.assertEqual(self._con_rango("2026-10-20", "2026-10-20")[0], ["2", "3"])      # el día de fin cuenta
        self.assertEqual(self._con_rango("2026-10-21", "2026-10-21")[0], ["3"])
        self.assertEqual(self._con_rango("2026-11-03", "2026-11-03")[0], ["3", "4"])      # el activo cuenta para cualquier día tras su inicio

    def test_solo_desde_o_solo_hasta(self):
        self.assertEqual(self._con_rango("2026-10-21", None)[0], ["3", "4"])
        self.assertEqual(self._con_rango(None, "2026-09-30")[0], ["1"])

    def test_la_api_acepta_el_rango_ordena_las_fechas_y_rechaza_las_mal_escritas(self):
        from fastapi.testclient import TestClient
        cliente, datos = self._cliente_con_datos()
        # main.py carga backend/.env.local al importarse (claves reales, ruta del archivo histórico real): el entorno se restaura al salir de este
        # bloque para que ninguna otra prueba herede esas variables
        with mock.patch.dict(os.environ):
            import main
        with mock.patch.object(main.unified_service, "ads_library", cliente), \
                mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            api = TestClient(main.app)
            r = api.get("/api/ads/top-gastadores", params={"limite": 50, "fecha_desde": "2026-10-31", "fecha_hasta": "2026-10-01"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(sorted(a["page_name"] for a in r.json()["anunciantes"]), ["Octubre", "Sigue activo"])
            self.assertEqual(r.json()["estado"]["rango_fechas"], {"desde": "2026-10-01", "hasta": "2026-10-31"})
            self.assertEqual(len(api.get("/api/ads/top-gastadores", params={"limite": 50}).json()["anunciantes"]), 4)      # sin fechas: todo
            self.assertEqual(api.get("/api/ads/top-gastadores", params={"fecha_desde": "ayer"}).status_code, 422)


class SoloActivosTests(unittest.TestCase):
    def _cliente_con_datos(self):
        datos = [
            _anuncio("1", [("Azuay", "1.0")], page_name="Activa"),
            _anuncio("2", [("Azuay", "1.0")], page_name="Terminada", ad_delivery_stop_time="2026-10-20"),
        ]
        return _cliente(), datos

    def test_sin_el_filtro_se_ven_activos_y_terminados(self):
        cliente, datos = self._cliente_con_datos()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            ads, estado = cliente.obtener_nacional()
        self.assertEqual({a["id"]: a["activo"] for a in ads}, {"1": True, "2": False})
        self.assertNotIn("solo_activos", estado)

    def test_con_el_filtro_solo_quedan_los_activos_y_se_cuentan_los_excluidos(self):
        cliente, datos = self._cliente_con_datos()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            cliente.obtener_nacional()
            marca = ads_library.SOLO_ACTIVOS.set(True)
            try:
                ads, estado = cliente.obtener_nacional()
                top = cliente.top_gastadores(None, 10)["anunciantes"]
                lista = cliente.anuncios(region="Azuay")
            finally:
                ads_library.SOLO_ACTIVOS.reset(marca)
        self.assertEqual([a["id"] for a in ads], ["1"])
        self.assertTrue(estado["solo_activos"])
        self.assertEqual(estado["excluidos_inactivos"], 1)
        self.assertEqual([a["page_name"] for a in top], ["Activa"])           # el ranking también lo respeta
        self.assertEqual([a["id"] for a in lista["anuncios"]], ["1"])         # y las listas de anuncios

    def test_se_combina_con_el_filtro_del_cne(self):
        cliente = _cliente()
        datos = [
            _anuncio("1", [("Azuay", "1.0")], page_name="Consejo Nacional Electoral del Ecuador"),
            _anuncio("2", [("Azuay", "1.0")], page_name="Otra", ad_delivery_stop_time="2026-10-20"),
            _anuncio("3", [("Azuay", "1.0")], page_name="Tercera"),
        ]
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            cliente.obtener_nacional()
            m1, m2 = ads_library.SIN_CNE.set(True), ads_library.SOLO_ACTIVOS.set(True)
            try:
                ads, estado = cliente.obtener_nacional()
            finally:
                ads_library.SOLO_ACTIVOS.reset(m2)
                ads_library.SIN_CNE.reset(m1)
        self.assertEqual([a["id"] for a in ads], ["3"])
        self.assertEqual((estado["excluidos_cne"], estado["excluidos_inactivos"], estado["total_nacional"]), (1, 1, 1))


class TipoDeAnuncianteTests(unittest.TestCase):
    """Filtro por tipo de anunciante (según afiliaciones.json) y alcance por provincia en la exportación."""

    def setUp(self):
        ruta = _archivo([
            {"nombre": "Candidata X", "page_id": "1", "tipo": "candidato", "afiliacion": "Partido A", "partido": "A", "fuente": "https://e.ec/a", "verificado": True},
            {"nombre": "Municipio Y", "page_id": "2", "tipo": "gobierno", "afiliacion": "Sin afiliación (institución pública)", "partido": None, "fuente": "https://y.gob.ec", "verificado": True},
            {"nombre": "Medio M", "page_id": "4", "tipo": "medio", "afiliacion": "Sin afiliación documentada", "partido": None, "fuente": "https://m.ec", "verificado": False},
        ])
        parche = mock.patch.object(ads_library, "RUTA_AFILIACIONES", ruta)
        parche.start()
        self.addCleanup(parche.stop)
        self.cliente = _cliente()
        datos = [
            _anuncio("1", [("Azuay", "0.8"), ("Cañar", "0.2")], page_id="1", page_name="Candidata X"),
            _anuncio("2", [("Azuay", "1.0")], page_id="2", page_name="Municipio Y"),
            _anuncio("3", [("Azuay", "1.0")], page_id="3", page_name="Página Z"),
            _anuncio("4", [("Azuay", "1.0")], page_id="4", page_name="Medio M"),
        ]
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            self.cliente.obtener_nacional()

    def _nombres(self, **kw):
        return sorted(a["page_name"] for a in self.cliente.anuncios(region="Azuay", **kw)["anuncios"])

    def test_cada_grupo_deja_solo_sus_anuncios(self):
        self.assertEqual(self._nombres(tipo="candidatos"), ["Candidata X"])
        self.assertEqual(self._nombres(tipo="instituciones"), ["Municipio Y"])
        self.assertEqual(self._nombres(tipo="medios"), ["Medio M"])
        self.assertEqual(self._nombres(tipo="sin_clasificar"), ["Página Z"])

    def test_varios_grupos_y_valores_desconocidos(self):
        self.assertEqual(self._nombres(tipo="candidatos,instituciones"), ["Candidata X", "Municipio Y"])
        self.assertEqual(len(self._nombres(tipo="no-existe")), 4)         # un valor desconocido se ignora: sin filtro

    def test_el_resumen_y_el_ranking_respetan_el_tipo(self):
        self.assertEqual(self.cliente.anuncios(region="Azuay", tipo="medios")["resumen"]["anuncios"], 1)
        top = self.cliente.top_gastadores(None, 10, False, "candidatos")["anunciantes"]
        self.assertEqual([a["page_name"] for a in top], ["Candidata X"])

    def test_cada_anuncio_dice_su_grupo(self):
        grupos = {a["page_name"]: a["grupo_tipo"] for a in self.cliente.anuncios(region="Azuay")["anuncios"]}
        self.assertEqual(grupos, {"Candidata X": "candidatos", "Municipio Y": "instituciones", "Página Z": "sin_clasificar", "Medio M": "medios"})

    def test_completo_trae_el_alcance_por_provincia_y_por_defecto_no(self):
        normal = self.cliente.anuncios(pagina="Candidata X")["anuncios"][0]
        completo = self.cliente.anuncios(pagina="Candidata X", completo=True)["anuncios"][0]
        self.assertNotIn("regiones", normal)
        self.assertEqual({r["region"]: r["porcentaje"] for r in completo["regiones"]}, {"Azuay": 0.8, "Cañar": 0.2})


class PrensaLocalTests(unittest.TestCase):
    def _registro(self, provincias):
        ruta = os.path.join(tempfile.mkdtemp(prefix="noai_medios_"), "medios_locales.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"provincias": provincias}, f, ensure_ascii=False)
        return (mock.patch.object(meta_service, "RUTA_MEDIOS_LOCALES", ruta),
                mock.patch.dict(meta_service._MEDIOS_LOCALES_CACHE, {"mtime": None, "datos": {}}))

    def _servicio(self):
        with mock.patch.object(meta_service.firebase_store, "get_api_keys", return_value={}):
            return meta_service.UnifiedFeedService()

    def test_provincia_sin_medios_registrados_lo_dice_sin_inventar(self):
        a, b = self._registro({"Loja": [{"medio": "Crónica", "sitio": "cronica.com.ec"}]})
        with a, b:
            items, estado = self._servicio()._cargar("Guayas", "prensa_local")
        self.assertEqual(items, [])
        self.assertFalse(estado["configurado"])
        self.assertIn("medios_locales.json", estado["mensaje"])

    def test_filtra_por_tema_electoral_localidad_y_extranjero_y_prefiere_el_rss(self):
        rss = """<rss><channel>
          <item><title>Candidatos a la Alcaldía de Ambato presentan propuestas</title><link>https://elheraldo.com.ec/a</link><pubDate>Fri, 06 Nov 2026 10:00:00 +0000</pubDate></item>
          <item><title>Elecciones en Alaska: cómo funciona el voto</title><link>https://elheraldo.com.ec/b</link><pubDate>Fri, 06 Nov 2026 09:00:00 +0000</pubDate></item>
          <item><title>Turismo consumió platos típicos</title><link>https://elheraldo.com.ec/c</link><pubDate>Fri, 06 Nov 2026 08:00:00 +0000</pubDate></item>
          <item><title>Candidato de Quito presenta su plan</title><link>https://elheraldo.com.ec/d</link><pubDate>Fri, 06 Nov 2026 07:00:00 +0000</pubDate></item>
        </channel></rss>"""
        gnews = """<rss><channel>
          <item><title>Candidatos a la Alcaldía de Ambato presentan propuestas - El Heraldo</title><link>https://news.google.com/x</link><pubDate>Fri, 06 Nov 2026 10:00:00 +0000</pubDate><source>El Heraldo</source></item>
        </channel></rss>"""

        def falso_get(url, **kw):
            r = mock.Mock(status_code=200)
            r.content = (gnews if "news.google.com" in url else rss).encode("utf-8")
            r.raise_for_status = lambda: None
            return r

        a, b = self._registro({"Tungurahua": [{"medio": "El Heraldo", "sitio": "elheraldo.com.ec", "feed": "https://elheraldo.com.ec/feed/",
                                               "localidades": ["Tungurahua", "Ambato"]}]})
        with a, b, mock.patch.object(meta_service.requests, "get", side_effect=falso_get):
            items, estado = self._servicio()._cargar("Tungurahua", "prensa_local")
        self.assertEqual([i["titulo"] for i in items], ["Candidatos a la Alcaldía de Ambato presentan propuestas"])   # sin duplicado, sin Alaska, sin turismo, sin Quito
        self.assertEqual(items[0]["url"], "https://elheraldo.com.ec/a")                                               # gana el enlace directo del medio
        self.assertEqual(items[0]["ambito"], "local")
        self.assertIn("El Heraldo", estado["aviso"])

    def test_el_archivo_real_es_valido_y_cada_medio_trae_su_sitio(self):
        with open(meta_service.RUTA_MEDIOS_LOCALES, encoding="utf-8") as f:
            provincias = json.load(f)["provincias"]
        for provincia, medios in provincias.items():
            self.assertIn(provincia, meta_service.PROVINCIA_LOCALIDADES)
            for m in medios:
                self.assertTrue(m.get("medio") and m.get("sitio"), (provincia, m))


if __name__ == "__main__":
    unittest.main()
