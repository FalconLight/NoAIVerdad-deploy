import os
import time
import unittest
from unittest import mock

import meta_service
from meta_service import UnifiedFeedService


class FuentesTests(unittest.TestCase):
    def _servicio(self):
        with mock.patch.dict(os.environ, {"META_INTEGRATION_ENABLED": "false", "X_BEARER_TOKEN": ""}):
            return UnifiedFeedService()

    def test_youtube_solo_devuelve_videos_electorales(self):
        s = self._servicio()
        s._youtube_channel_cache = [
            {"titulo": "CNE entrega kits para las elecciones seccionales", "url": "https://www.youtube.com/watch?v=1", "fecha": "2026-10-20", "fuente": "Ecuavisa"},
            {"titulo": "¿Por qué es difícil detectar el cáncer de mama en el primer chequeo?", "url": "https://www.youtube.com/watch?v=2", "fecha": "2026-10-20", "fuente": "Ecuavisa"},
            {"titulo": "Candidatos a la Alcaldía debaten sobre seguridad", "url": "https://www.youtube.com/watch?v=3", "fecha": "2026-10-19", "fuente": "Primicias"},
        ]
        s._youtube_cache_expiry = time.time() + 600
        titulos = [v["titulo"] for v in s.obtener_videos_youtube("Pichincha")]
        self.assertEqual(len(titulos), 2)
        self.assertFalse(any("cáncer" in t for t in titulos))

    def test_estado_de_youtube_aclara_que_son_canales_nacionales(self):
        s = self._servicio()
        s._youtube_channel_cache = [{"titulo": "Elecciones 2026: lo que debes saber", "url": "https://www.youtube.com/watch?v=1", "fecha": "", "fuente": "Ecuavisa"}]
        s._youtube_cache_expiry = time.time() + 600
        items, estado = s._cargar("Loja", "youtube")
        self.assertEqual(len(items), 1)
        self.assertIn("nacionales", estado["aviso"])

    def test_feed_completo_marca_reddit_como_bajo_demanda_y_no_lo_consulta(self):
        s = self._servicio()
        with mock.patch.object(UnifiedFeedService, "_cargar", return_value=([], {"configurado": True, "ok": True})) as cargar:
            feed = s.obtener_feed_completo("Azuay")
        secciones = {c.args[1] for c in cargar.call_args_list}
        self.assertNotIn("reddit", secciones)
        self.assertTrue(feed["estados"]["reddit"]["omitido"])

    def test_meta_apagada_por_defecto_no_hace_consultas(self):
        s = self._servicio()
        with mock.patch.object(meta_service.requests, "get") as get:
            items, estado = s._cargar("Azuay", "meta_ads")
        self.assertEqual(items, [])
        self.assertFalse(estado["habilitado"])
        get.assert_not_called()

    def test_el_entorno_local_tiene_prioridad_para_las_claves(self):
        with mock.patch.dict(os.environ, {"GNEWS_API_KEY": "local-gnews", "META_INTEGRATION_ENABLED": "false"}):
            with mock.patch.object(meta_service.firebase_store, "get_api_keys", return_value={"GNEWS_API_KEY": "fb-gnews", "GOOGLE_FACT_CHECK_API_KEY": "fb-fc"}):
                s = UnifiedFeedService()
        self.assertEqual(s.gnews_api_key, "local-gnews")
        self.assertEqual(s.fact_check_api_key, "fb-fc")


if __name__ == "__main__":
    unittest.main()
