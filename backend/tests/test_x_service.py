import json
import os
import unittest
from unittest import mock

import x_service
from x_service import XClient

SECRET = "AAAA-x-bearer-secret"

RESPUESTA = {
    "data": [{
        "id": "111", "text": "El CNE habilita recintos en Pichincha", "author_id": "9",
        "created_at": "2026-10-12T15:00:00.000Z",
        "public_metrics": {"like_count": 5, "retweet_count": 2, "reply_count": 1, "quote_count": 0},
    }],
    "includes": {"users": [{
        "id": "9", "username": "periodista", "name": "Periodista", "created_at": "2024-01-02T00:00:00.000Z",
        "verified": False, "public_metrics": {"followers_count": 120, "following_count": 80, "tweet_count": 900},
    }]},
}


def _resp(status=200, cuerpo=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = cuerpo if cuerpo is not None else {}
    r.text = json.dumps(cuerpo or {})
    return r


def _cliente(**env):
    entorno = {"X_BEARER_TOKEN": SECRET}
    entorno.update(env)
    with mock.patch.dict(os.environ, entorno):
        return XClient()


class XClientTests(unittest.TestCase):
    def test_sin_token_no_llama_a_la_red(self):
        with mock.patch.object(x_service.requests, "get") as get:
            items, estado = _cliente(X_BEARER_TOKEN="").buscar("Pichincha")
        get.assert_not_called()
        self.assertEqual(items, [])
        self.assertFalse(estado["configurado"])
        self.assertIn("X_BEARER_TOKEN", estado["mensaje"])

    def test_normaliza_publicaciones_y_cuenta(self):
        with mock.patch.object(x_service.requests, "get", return_value=_resp(200, RESPUESTA)) as get:
            items, estado = _cliente().buscar("Pichincha")
        self.assertEqual(len(items), 1)
        t = items[0]
        self.assertEqual(t["link"], "https://x.com/periodista/status/111")
        self.assertEqual(t["stats"]["likes"], 5)
        self.assertEqual(t["cuenta"]["creada"], "2024-01-02T00:00:00.000Z")
        self.assertEqual(t["cuenta"]["seguidores"], 120)
        self.assertTrue(estado["ok"])
        # El token va en el encabezado, nunca en la URL.
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], f"Bearer {SECRET}")
        self.assertNotIn(SECRET, json.dumps(get.call_args.kwargs["params"]))
        self.assertIn("-is:retweet", get.call_args.kwargs["params"]["query"])

    def test_cachea_por_provincia(self):
        cliente = _cliente()
        with mock.patch.object(x_service.requests, "get", return_value=_resp(200, RESPUESTA)) as get:
            cliente.buscar("Pichincha")
            cliente.buscar("pichincha")
        self.assertEqual(get.call_count, 1)

    def test_tope_diario_evita_gastar_mas(self):
        cliente = _cliente(X_DAILY_REQUEST_CAP="1", X_CACHE_MIN="0")
        with mock.patch.object(x_service.requests, "get", return_value=_resp(200, RESPUESTA)) as get:
            cliente.buscar("Azuay")
            items, estado = cliente.buscar("Guayas")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(items, [])
        self.assertIn("tope diario", estado["mensaje"])

    def test_errores_http_dan_mensajes_utiles_sin_token(self):
        for codigo, texto in ((401, "rechazó el token"), (402, "créditos"), (429, "limitó")):
            with mock.patch.object(x_service.requests, "get", return_value=_resp(codigo, {})):
                items, estado = _cliente().buscar("Loja")
            self.assertEqual(items, [])
            self.assertIn(texto, estado["mensaje"])
            self.assertNotIn(SECRET, estado["mensaje"])

    def test_los_errores_no_se_cachean(self):
        cliente = _cliente()
        with mock.patch.object(x_service.requests, "get", side_effect=[_resp(402, {}), _resp(200, RESPUESTA)]) as get:
            cliente.buscar("Napo")
            items, _ = cliente.buscar("Napo")
        self.assertEqual(len(items), 1)
        self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
