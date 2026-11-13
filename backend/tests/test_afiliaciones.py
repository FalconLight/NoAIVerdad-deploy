"""Afiliaciones: una persona con varias páginas de Meta es UNA entidad, y las tildes (la «ñ» incluida) no importan al comparar nombres."""
import json
import os
import tempfile
import unicodedata
import unittest
from unittest import mock

import ads_library
from tests.test_ads_library import _anuncio, _cliente, _respuesta


def _archivo(entidades):
    ruta = os.path.join(tempfile.mkdtemp(prefix="noai_afil_"), "afiliaciones.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"partidos": {}, "entidades": entidades}, f, ensure_ascii=False, indent=2)
    return ruta


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)["entidades"]


def _leonel(**extra):
    base = {"nombre": "Leonel Muñoz Zambrano", "page_id": "111", "page_ids": ["111", "222"], "tipo": "candidato",
            "afiliacion": "Acción Democrática Nacional (ADN)", "partido": "ADN", "fuente": "https://ejemplo.ec/nota",
            "verificado": False, "actualizado": "2026-11-05"}
    base.update(extra)
    return base


class _ConArchivo(unittest.TestCase):
    """Cada prueba trabaja con su propia copia de afiliaciones.json: nunca toca el archivo real."""

    def usar(self, entidades):
        ruta = _archivo(entidades)
        parche = mock.patch.object(ads_library, "RUTA_AFILIACIONES", ruta)
        parche.start()
        self.addCleanup(parche.stop)
        return ruta


class EnieTests(_ConArchivo):
    def test_la_enie_y_las_tildes_no_cambian_la_comparacion(self):
        variantes = ["Muñoz", "Munoz", "MUÑOZ", "muñoz", unicodedata.normalize("NFD", "Muñoz"), unicodedata.normalize("NFC", "MUÑOZ")]
        self.assertEqual({ads_library._norm(v) for v in variantes}, {"munoz"})
        self.assertEqual(ads_library._norm_entidad("Leonel Muñoz Zambrano S.A.S"), ads_library._norm_entidad("LEONEL MUNOZ ZAMBRANO"))
        self.assertTrue(ads_library._misma_entidad("Ordóñez", "ORDONEZ"))
        self.assertEqual(ads_library._norm("Cañar Province"), "canar")           # la provincia con ñ también se reconoce

    def test_una_entrada_con_enie_encuentra_la_pagina_y_el_pagador_escritos_sin_ella(self):
        self.usar([_leonel()])
        indice = ads_library._cargar_afiliaciones()
        self.assertEqual(ads_library._afiliacion(indice, "Leonel Munoz Zambrano")["partido"], "ADN")       # como lo escribe Meta
        self.assertEqual(ads_library._afiliacion(indice, "LEONEL MUÑOZ ZAMBRANO")["partido"], "ADN")        # pagador declarado
        self.assertIsNone(ads_library._afiliacion(indice, "Leonel Muñoz Zambrano Otro"))

    def test_guardar_con_otra_grafia_actualiza_la_misma_entrada_y_conserva_el_nombre_con_enie(self):
        ruta = self.usar([_leonel()])
        cliente = _cliente()
        r = cliente.guardar_afiliacion({"nombre": "Leonel Munoz Zambrano", "afiliacion": "ADN (revisada)", "partido": "ADN", "verificado": False})
        entidades = _leer(ruta)
        self.assertEqual(len(entidades), 1)
        self.assertEqual(entidades[0]["nombre"], "Leonel Muñoz Zambrano")
        self.assertEqual(entidades[0]["afiliacion"], "ADN (revisada)")
        self.assertEqual(entidades[0]["page_ids"], ["111", "222"])                                          # no se pierden los ID
        self.assertEqual(r["entidad"]["estado"], "pendiente")

    def test_lo_que_se_guarda_queda_en_nfc_aunque_llegue_descompuesto(self):
        ruta = self.usar([])
        cliente = _cliente()
        cliente.guardar_afiliacion({"nombre": unicodedata.normalize("NFD", "Pedro Peña"), "afiliacion": unicodedata.normalize("NFD", "Alianza Peñón"), "partido": "X"})
        guardado = _leer(ruta)[0]
        self.assertEqual(guardado["nombre"], unicodedata.normalize("NFC", "Pedro Peña"))
        self.assertEqual(guardado["afiliacion"], unicodedata.normalize("NFC", "Alianza Peñón"))
        self.assertIn("ñ", guardado["nombre"])
        with open(ruta, encoding="utf-8") as f:
            self.assertIn("Peña", f.read())                                                                 # la ñ se escribe tal cual, no como ñ


class VariasPaginasTests(_ConArchivo):
    def _datos(self):
        return [
            _anuncio("1", [("Guayas", "1.0")], page_id="111", page_name="Leonel Munoz Zambrano", bylines="Leonel Munoz Zambrano"),
            _anuncio("2", [("Guayas", "1.0")], page_id="222", page_name="Leonel Munoz", bylines="LEONEL MUÑOZ ZAMBRANO"),
            _anuncio("3", [("Guayas", "1.0")], page_id="333", page_name="Página aliada", bylines="LEONEL MUÑOZ ZAMBRANO"),
            _anuncio("4", [("Guayas", "1.0")], page_id="444", page_name="Otra persona", bylines="Otra persona"),
        ]

    def _con_anuncios(self):
        cliente = _cliente()
        parche = mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos()}))
        parche.start()
        self.addCleanup(parche.stop)
        return cliente

    def test_todas_las_paginas_comparten_la_afiliacion_por_id(self):
        self.usar([_leonel()])
        indice = ads_library._cargar_afiliaciones()
        self.assertEqual(ads_library._afiliacion(indice, "Leonel Munoz", "222")["partido"], "ADN")          # segunda página, otro nombre
        self.assertIsNone(ads_library._afiliacion(indice, "Leonel Munoz"))                                  # sin su ID no se adivina por el nombre
        self.assertEqual(ads_library._ids_de_entidad("LEONEL MUNOZ ZAMBRANO"), ["111", "222"])

    def test_ver_anuncios_de_la_entidad_incluye_todas_sus_paginas_y_lo_que_paga(self):
        self.usar([_leonel()])
        cliente = self._con_anuncios()
        lista = cliente.anuncios(entidad="Leonel Muñoz Zambrano")
        self.assertEqual(sorted(a["id"] for a in lista["anuncios"]), ["1", "2", "3"])                       # sus dos páginas y el anuncio que paga
        solo_ids = cliente.anuncios(page_id="111,222")
        self.assertEqual(sorted(a["id"] for a in solo_ids["anuncios"]), ["1", "2"])
        self.assertEqual(cliente.anuncios(page_id="444")["total"], 1)

    def test_las_paginas_sin_registro_no_incluyen_ningun_id_de_la_entidad(self):
        self.usar([_leonel()])
        cliente = self._con_anuncios()
        estado = cliente.afiliaciones_estado(20)
        pendientes = {f["page_id"] for f in estado["faltantes"]}
        self.assertNotIn("111", pendientes)
        self.assertNotIn("222", pendientes)
        self.assertIn("444", pendientes)

    def test_un_id_no_puede_estar_en_dos_entradas(self):
        self.usar([_leonel(), {"nombre": "Otra entrada", "page_id": "222", "tipo": None, "afiliacion": None, "partido": None,
                              "fuente": None, "verificado": False, "actualizado": None}])
        estado = _cliente().afiliaciones_estado(0)
        self.assertEqual(estado["resumen"]["con_problemas"], 1)
        self.assertTrue(any("222" in p for p in estado["entidades"][1]["problemas"]))

    def test_guardar_conserva_o_reemplaza_la_lista_de_id(self):
        ruta = self.usar([])
        cliente = _cliente()
        cliente.guardar_afiliacion({"nombre": "Ana Peña", "page_ids": ["5", "6"], "afiliacion": "Movimiento X", "partido": "X"})
        ana = _leer(ruta)[0]
        self.assertEqual((ana["page_id"], ana["page_ids"]), ("5", ["5", "6"]))
        cliente.guardar_afiliacion({"nombre": "Ana Pena", "afiliacion": "Movimiento X", "partido": "X", "fuente": "https://ejemplo.ec/a"})   # sin page_ids: se conservan
        self.assertEqual(_leer(ruta)[0]["page_ids"], ["5", "6"])
        cliente.guardar_afiliacion({"nombre": "Ana Peña", "page_ids": "6, 7", "afiliacion": "Movimiento X"})                               # texto con comas
        self.assertEqual(_leer(ruta)[0]["page_ids"], ["5", "6", "7"])                                                                   # el principal siempre está
        self.assertEqual(len(_leer(ruta)), 1)

    def test_guardar_rechaza_id_invalidos_y_entradas_que_chocan(self):
        self.usar([_leonel(), {"nombre": "Otra", "page_id": "999", "tipo": None, "afiliacion": None, "partido": None,
                              "fuente": None, "verificado": False, "actualizado": None}])
        cliente = _cliente()
        with self.assertRaises(ValueError):
            cliente.guardar_afiliacion({"nombre": "Nueva", "page_ids": ["12ab"]})
        with self.assertRaises(ValueError):
            cliente.guardar_afiliacion({"nombre": "Nueva", "page_ids": {"a": 1}})
        with self.assertRaises(ValueError):                                      # el nombre es de «Leonel» pero el ID es de «Otra»
            cliente.guardar_afiliacion({"nombre": "Leonel Munoz Zambrano", "page_id": "999", "afiliacion": "ADN"})


def _ent(nombre, page_id=None, partido="ADN", verificado=False, fuente="https://ejemplo.ec/nota", **extra):
    base = {"nombre": nombre, "page_id": page_id, "tipo": "candidato", "afiliacion": f"{partido} (afiliación)" if partido else None,
            "partido": partido, "fuente": fuente if partido else None, "verificado": verificado, "actualizado": "2026-11-05" if partido else None}
    base.update(extra)
    return base


class OtrosNombresTests(_ConArchivo):
    """«Hernán Vladimir Salcedo Loor» (el pagador) es «Hernán Salcedo Loor» (la página): un nombre alterno los junta en una entidad."""

    def test_el_pagador_con_otro_nombre_cuenta_como_la_misma_entidad(self):
        self.usar([_ent("Hernán Salcedo Loor", "10", otros_nombres=["Hernán Vladimir Salcedo Loor"])])
        self.assertTrue(ads_library._misma_entidad("Hernán Salcedo Loor", "HERNÁN VLADIMIR SALCEDO LOOR"))
        self.assertTrue(ads_library._misma_entidad("hernan vladimir salcedo loor", "Hernán Salcedo Loor"))
        self.assertFalse(ads_library._misma_entidad("Hernán Salcedo Loor", "Hernán Vladimir Salcedo Pérez"))
        self.assertEqual(ads_library._afiliacion(ads_library._cargar_afiliaciones(), "Hernán Vladimir Salcedo Loor")["partido"], "ADN")

    def test_sin_nombre_alterno_los_nombres_distintos_no_se_igualan(self):
        self.usar([_ent("Hernán Salcedo Loor", "10")])
        self.assertFalse(ads_library._misma_entidad("Hernán Salcedo Loor", "Hernán Vladimir Salcedo Loor"))
        self.assertIsNone(ads_library._afiliacion(ads_library._cargar_afiliaciones(), "Hernán Vladimir Salcedo Loor"))

    def _anuncios(self):
        cliente = _cliente()
        datos = [_anuncio("1", [("Guayas", "1.0")], page_id="10", page_name="Hernán Salcedo Loor", bylines="Hernán Vladimir Salcedo Loor"),
                 _anuncio("2", [("Guayas", "1.0")], page_id="20", page_name="Página aliada", bylines="HERNÁN VLADIMIR SALCEDO LOOR"),
                 _anuncio("3", [("Guayas", "1.0")], page_id="30", page_name="Otra persona", bylines="Otra persona")]
        parche = mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos}))
        parche.start()
        self.addCleanup(parche.stop)
        return cliente

    def test_lo_que_paga_con_el_otro_nombre_no_es_un_tercero_y_entra_en_ver_anuncios(self):
        self.usar([_ent("Hernán Salcedo Loor", "10", otros_nombres=["Hernán Vladimir Salcedo Loor"])])
        cliente = self._anuncios()
        lista = cliente.anuncios(entidad="Hernán Salcedo Loor")
        self.assertEqual(sorted(a["id"] for a in lista["anuncios"]), ["1", "2"])                 # su página y lo que paga en otra página
        propio = next(a for a in lista["anuncios"] if a["id"] == "1")
        self.assertFalse(propio["pagado_por_tercero"])                                            # el pagador es él mismo
        self.assertEqual(sorted(a["id"] for a in cliente.anuncios(entidad="Hernán Vladimir Salcedo Loor")["anuncios"]), ["1", "2"])

    def test_sin_el_nombre_alterno_el_pagador_si_cuenta_como_tercero(self):
        self.usar([_ent("Hernán Salcedo Loor", "10")])
        cliente = self._anuncios()
        propio = next(a for a in cliente.anuncios(pagina="Hernán Salcedo Loor")["anuncios"] if a["id"] == "1")
        self.assertTrue(propio["pagado_por_tercero"])

    def test_las_paginas_sin_registro_no_incluyen_los_nombres_alternos(self):
        self.usar([_ent("Hernán Salcedo Loor", None, otros_nombres=["Otra persona"])])
        cliente = self._anuncios()
        nombres = {f["nombre"] for f in cliente.afiliaciones_estado(20)["faltantes"]}
        self.assertNotIn("Otra persona", nombres)
        self.assertIn("Página aliada", nombres)

    def test_un_otro_nombre_repetido_en_dos_entradas_es_un_problema(self):
        self.usar([_ent("Ana Peña", "1", otros_nombres=["Ana P."]), _ent("Ana P.", "2")])
        estado = _cliente().afiliaciones_estado(0)
        self.assertEqual(estado["resumen"]["con_problemas"], 1)
        self.assertTrue(any("repetido" in p.lower() for p in estado["entidades"][1]["problemas"]))

    def test_guardar_con_un_nombre_alterno_actualiza_la_entidad_y_acepta_texto(self):
        ruta = self.usar([_ent("Hernán Salcedo Loor", "10", otros_nombres=["Hernán Vladimir Salcedo Loor"])])
        cliente = _cliente()
        cliente.guardar_afiliacion({"nombre": "HERNÁN VLADIMIR SALCEDO LOOR", "afiliacion": "ADN (revisada)", "partido": "ADN"})
        entidades = _leer(ruta)
        self.assertEqual(len(entidades), 1)
        self.assertEqual(entidades[0]["otros_nombres"], ["Hernán Vladimir Salcedo Loor"])                     # sigue igual
        cliente.guardar_afiliacion({"nombre": "Hernán Salcedo Loor", "otros_nombres": "H. Salcedo; Hernán V. Salcedo\nHernán Salcedo Loor"})
        self.assertEqual(_leer(ruta)[0]["otros_nombres"], ["H. Salcedo", "Hernán V. Salcedo"])                # sin repetidos ni el principal
        cliente.guardar_afiliacion({"nombre": "Hernán Salcedo Loor", "otros_nombres": []})
        self.assertNotIn("otros_nombres", _leer(ruta)[0])


class UnificarTests(_ConArchivo):
    def test_une_el_pagador_con_la_pagina_y_conserva_la_verificacion(self):
        ruta = self.usar([_ent("Hernán Salcedo Loor", "10", verificado=True), _ent("Hernán Vladimir Salcedo Loor")])
        r = _cliente().unificar_afiliaciones({"principal": {"nombre": "Hernán Salcedo Loor"}, "otras": [{"nombre": "Hernán Vladimir Salcedo Loor"}]})
        entidades = _leer(ruta)
        self.assertEqual(len(entidades), 1)
        e = entidades[0]
        self.assertEqual((e["nombre"], e["page_id"], e["otros_nombres"]), ("Hernán Salcedo Loor", "10", ["Hernán Vladimir Salcedo Loor"]))
        self.assertTrue(e["verificado"])
        self.assertEqual((r["unidas"], r["conflictos"], r["entidad"]["estado"]), (["Hernán Vladimir Salcedo Loor"], [], "verificada"))
        self.assertTrue(ads_library._misma_entidad("Hernán Salcedo Loor", "Hernán Vladimir Salcedo Loor"))   # y se nota al instante

    def test_suma_los_id_de_la_otra_pagina_y_conserva_su_verificacion_si_la_afiliacion_coincide(self):
        ruta = self.usar([_ent("Leonel Muñoz Zambrano", "111"), _ent("Leonel Munoz", "222", verificado=True, fuente="https://ejemplo.ec/otra")])
        _cliente().unificar_afiliaciones({"principal": {"nombre": "Leonel Muñoz Zambrano"}, "otras": [{"nombre": "Leonel Munoz"}]})
        e = _leer(ruta)[0]
        self.assertEqual(e["page_ids"], ["111", "222"])
        self.assertTrue(e["verificado"])
        self.assertEqual(e["fuente"], "https://ejemplo.ec/otra")

    def test_la_principal_conserva_su_afiliacion_y_avisa_de_los_conflictos(self):
        ruta = self.usar([_ent("Ana Peña", "1", partido="PSC"), _ent("Ana Ruiz", "2", partido="ADN")])
        r = _cliente().unificar_afiliaciones({"principal": {"nombre": "Ana Peña"}, "otras": [{"nombre": "Ana Ruiz"}]})
        e = _leer(ruta)[0]
        self.assertEqual(e["partido"], "PSC")
        self.assertEqual(len(r["conflictos"]), 1)
        self.assertIn("ADN", r["conflictos"][0])

    def test_toma_la_afiliacion_de_la_otra_si_la_principal_no_tiene(self):
        ruta = self.usar([_ent("Ana Peña", "1", partido=None), _ent("Ana Ruiz", "2", partido="ADN", verificado=True)])
        _cliente().unificar_afiliaciones({"principal": {"nombre": "Ana Peña"}, "otras": [{"nombre": "Ana Ruiz"}]})
        e = _leer(ruta)[0]
        self.assertEqual((e["partido"], e["verificado"], e["fuente"]), ("ADN", True, "https://ejemplo.ec/nota"))

    def test_une_nombres_y_paginas_sin_entrada_y_permite_cambiar_el_nombre(self):
        ruta = self.usar([_ent("Leonel Munoz Zambrano", "111")])
        r = _cliente().unificar_afiliaciones({"principal": {"nombre": "Leonel Munoz Zambrano"}, "nombre_final": "Leonel Muñoz Zambrano",
                                              "otras": [{"nombre": "Leonel Munoz", "page_id": "222"}, {"nombre": "L. Muñoz Zambrano"}]})
        e = _leer(ruta)[0]
        self.assertEqual(e["nombre"], "Leonel Muñoz Zambrano")
        self.assertEqual(e["page_ids"], ["111", "222"])
        self.assertEqual(e["otros_nombres"], ["Leonel Munoz", "L. Muñoz Zambrano"])        # el nombre anterior solo cambia de grafía: no es un alterno
        self.assertEqual(len(_leer(ruta)), 1)
        self.assertEqual(sorted(r["unidas"]), ["L. Muñoz Zambrano", "Leonel Munoz"])

    def test_si_la_principal_no_existe_se_crea(self):
        ruta = self.usar([_ent("Otra", "9")])
        _cliente().unificar_afiliaciones({"principal": {"nombre": "Pedro Peña", "page_id": "5"}, "otras": [{"nombre": "Pedro Pena", "page_id": "6"}]})
        entidades = _leer(ruta)
        self.assertEqual([e["nombre"] for e in entidades], ["Otra", "Pedro Peña"])
        self.assertEqual(entidades[1]["page_ids"], ["5", "6"])
        self.assertNotIn("otros_nombres", entidades[1])                         # «Pedro Pena» es el mismo nombre sin la ñ: no hace falta como alterno

    def test_rechaza_lo_que_no_tiene_sentido_y_no_toca_el_archivo(self):
        ruta = self.usar([_ent("Ana Peña", "1"), _ent("Ana Ruiz", "2", otros_nombres=["Beto"]), _ent("Beto López", "3", otros_nombres=["Beto"])])
        antes = _leer(ruta)
        cliente = _cliente()
        with self.assertRaises(ValueError):
            cliente.unificar_afiliaciones({"principal": {"nombre": "Ana Peña"}, "otras": []})
        with self.assertRaises(ValueError):                                    # ya son la misma entidad (mismo nombre sin tilde)
            cliente.unificar_afiliaciones({"principal": {"nombre": "Ana Peña"}, "otras": [{"nombre": "ANA PEÑA"}]})
        with self.assertRaises(ValueError):
            cliente.unificar_afiliaciones({"principal": {"nombre": "Ana Peña"}, "otras": [{"page_id": "12ab"}]})
        with self.assertRaises(ValueError):                                    # «Beto» ya es de dos entradas: la principal no puede ser ambigua
            cliente.unificar_afiliaciones({"principal": {"nombre": "Beto"}, "otras": [{"nombre": "Ana Peña"}]})
        with self.assertRaises(ValueError):
            cliente.unificar_afiliaciones({"principal": {"nombre": "Ana Peña"}, "otras": [{"nombre": f"N{i}"} for i in range(11)]})
        self.assertEqual(_leer(ruta), antes)


class NeutralTests(_ConArchivo):
    """Un medio puede mantenerse neutral: «Neutral» es un valor reservado de `partido`, solo para medios, y no forma un partido."""

    def _medio(self, **extra):
        base = {"nombre": "Radio Costa", "page_id": "700", "tipo": "medio", "afiliacion": ads_library.AFIL_NEUTRAL, "partido": "Neutral",
                "fuente": "https://ejemplo.ec/linea-editorial", "verificado": True, "actualizado": "2026-11-05"}
        base.update(extra)
        return base

    def test_un_medio_se_marca_neutral_con_cualquier_grafia(self):
        ruta = self.usar([])
        cliente = _cliente()
        for escrito in ("Neutral", "neutral", " NEUTRAL ", "Neutrál"):
            r = cliente.guardar_afiliacion({"nombre": "Radio Costa", "tipo": "medio", "partido": escrito})
            self.assertEqual(r["entidad"]["partido"], "Neutral")
        entidades = _leer(ruta)
        self.assertEqual(len(entidades), 1)
        e = entidades[0]
        self.assertEqual((e["tipo"], e["partido"], e["afiliacion"], e["verificado"]), ("medio", "Neutral", ads_library.AFIL_NEUTRAL, False))
        self.assertEqual(r["entidad"]["estado"], "pendiente")          # lleva afiliación: está indexada y se ve en la red (sin verificar)
        self.assertEqual(ads_library._afiliacion(ads_library._cargar_afiliaciones(), "radio costa")["partido"], "Neutral")

    def test_sin_tipo_se_guarda_como_medio_y_la_afiliacion_escrita_se_respeta(self):
        ruta = self.usar([])
        _cliente().guardar_afiliacion({"nombre": "Radio Costa", "partido": "Neutral", "afiliacion": "Línea editorial independiente"})
        e = _leer(ruta)[0]
        self.assertEqual((e["tipo"], e["partido"], e["afiliacion"]), ("medio", "Neutral", "Línea editorial independiente"))

    def test_neutral_solo_vale_para_medios_y_un_rechazo_no_toca_el_archivo(self):
        ruta = self.usar([_ent("Ana Peña", "1")])
        antes = _leer(ruta)
        cliente = _cliente()
        for tipo in ("candidato", "persona", "partido", "institucion", "agencia", "gobierno", "empresa", "otro"):
            with self.assertRaises(ValueError) as ctx:
                cliente.guardar_afiliacion({"nombre": "Ana Peña", "tipo": tipo, "partido": "Neutral"})
            self.assertIn("medio", str(ctx.exception))
        self.assertEqual(_leer(ruta), antes)

    def test_verificar_un_medio_neutral_exige_la_fuente(self):
        self.usar([])
        cliente = _cliente()
        with self.assertRaises(ValueError):
            cliente.guardar_afiliacion({"nombre": "Radio Costa", "tipo": "medio", "partido": "Neutral", "verificado": True})
        r = cliente.guardar_afiliacion({"nombre": "Radio Costa", "tipo": "medio", "partido": "Neutral", "verificado": True, "fuente": "https://ejemplo.ec/linea"})
        self.assertEqual(r["entidad"]["estado"], "verificada")

    def test_un_medio_puede_pasar_de_neutral_a_un_partido_y_al_reves(self):
        ruta = self.usar([self._medio()])
        cliente = _cliente()
        cliente.guardar_afiliacion({"nombre": "Radio Costa", "tipo": "medio", "partido": "ADN", "afiliacion": "Medio afín al oficialismo (ADN)",
                                    "fuente": "https://ejemplo.ec/nota", "verificado": True})
        e = _leer(ruta)[0]
        self.assertEqual((e["partido"], e["afiliacion"], e["tipo"]), ("ADN", "Medio afín al oficialismo (ADN)", "medio"))
        cliente.guardar_afiliacion({"nombre": "Radio Costa", "tipo": "medio", "partido": "Neutral"})
        e = _leer(ruta)[0]
        self.assertEqual((e["partido"], e["afiliacion"]), ("Neutral", ads_library.AFIL_NEUTRAL))      # sin texto propio, el de siempre
        self.assertEqual(len(_leer(ruta)), 1)

    def test_neutral_tiene_color_gris_y_el_archivo_puede_cambiarlo(self):
        ruta = self.usar([])
        self.assertEqual(ads_library._cargar_partidos(), {"Neutral": {"color": ads_library.COLOR_NEUTRAL}})
        def escribir(partidos):
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"partidos": partidos, "entidades": []}, f)
        escribir({"ADN": {"color": "#a855f7"}, "Neutral": {"color": "#112233"}})
        colores = ads_library._cargar_partidos()
        self.assertEqual((colores["ADN"]["color"], colores["Neutral"]["color"]), ("#a855f7", "#112233"))
        escribir({"Neutral": {"color": "gris"}})                                                    # un color inválido se ignora
        self.assertEqual(ads_library._cargar_partidos()["Neutral"]["color"], ads_library.COLOR_NEUTRAL)

    def test_el_estado_del_archivo_senala_neutral_mal_escrito_o_en_otro_tipo(self):
        self.usar([self._medio(nombre="Bien", page_id="1"), self._medio(nombre="Mal escrito", page_id="2", partido="neutral"),
                   self._medio(nombre="Candidato neutral", page_id="3", tipo="candidato")])
        entidades = _cliente().afiliaciones_estado(0)["entidades"]
        self.assertEqual(entidades[0]["problemas"], [])
        self.assertTrue(any("«Neutral»" in p and "escribir" in p for p in entidades[1]["problemas"]))
        self.assertTrue(any("solo se usa en medios" in p for p in entidades[2]["problemas"]))

    def test_el_validador_del_archivo_aplica_la_misma_regla(self):
        import importlib.util
        ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "validar_afiliaciones.py")
        espec = importlib.util.spec_from_file_location("validar_afiliaciones", ruta)
        validador = importlib.util.module_from_spec(espec)
        espec.loader.exec_module(validador)
        errores, _ = validador.validar([self._medio(nombre="Bien", page_id="1"), self._medio(nombre="Mal", page_id="2", partido="NEUTRAL"),
                                        self._medio(nombre="Otro tipo", page_id="3", tipo="persona")])
        self.assertEqual(len(errores), 2)
        self.assertIn("#2", errores[0])
        self.assertIn("#3", errores[1])

    def _red(self, entidades, datos):
        self.usar(entidades)
        cliente = _cliente()
        parche = mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos}))
        parche.start()
        self.addCleanup(parche.stop)
        return cliente.red_pagadores(None, limite=10)["grafo"]

    def _anuncios_red(self):
        return [_anuncio("1", [("Guayas", "1.0")], page_id="10", page_name="Partido ADN", bylines="Partido ADN"),
                _anuncio("2", [("Guayas", "1.0")], page_id="20", page_name="Candidata ADN", bylines="Candidata ADN"),
                _anuncio("3", [("Guayas", "1.0")], page_id="700", page_name="Radio Costa", bylines="Radio Costa")]

    def test_en_la_red_un_medio_neutral_va_en_gris_y_no_se_une_a_ningun_partido(self):
        grafo = self._red([_ent("Partido ADN", "10", verificado=True, tipo="partido"), _ent("Candidata ADN", "20"), self._medio()], self._anuncios_red())
        radio = next(n for n in grafo["nodos"] if n["nombre"] == "Radio Costa")
        self.assertEqual((radio["afiliacion"]["partido"], radio["afiliacion_estado"]), ("Neutral", "verificada"))
        self.assertEqual(grafo["partidos"]["Neutral"], {"color": ads_library.COLOR_NEUTRAL})
        union = [(e["a"], e["b"]) for e in grafo["aristas"] if e["tipo"] == "partido"]
        self.assertEqual(union, [("G:Partido ADN", "G:Candidata ADN")])                              # el ADN sigue uniéndose; Neutral no

    def test_si_el_archivo_trae_un_partido_neutral_no_se_dibujan_aristas_de_partido(self):
        grafo = self._red([_ent("Partido ADN", "10", verificado=True, tipo="partido", partido="Neutral"), self._medio(page_id="20", nombre="Candidata ADN")],
                          self._anuncios_red())
        self.assertEqual([e for e in grafo["aristas"] if e["tipo"] == "partido"], [])


class PuntoUnicoTests(_ConArchivo):
    """Una entidad con varias páginas de Meta (o con otro nombre) es UN solo punto en la red y UN solo anunciante, no dos."""

    def _con(self, datos):
        cliente = _cliente()
        parche = mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos}))
        parche.start()
        self.addCleanup(parche.stop)
        return cliente

    def _datos_leonel(self):
        enlace = {"ad_creative_bodies": ["Mira todo aquí https://ejemplo.ec/leonel y comparte"]}
        return [
            _anuncio("1", [("Guayas", "1.0")], page_id="111", page_name="Leonel Munoz Zambrano", bylines="Leonel Munoz Zambrano", **enlace),
            _anuncio("2", [("Guayas", "1.0")], page_id="222", page_name="Leonel Munoz", bylines="LEONEL MUÑOZ ZAMBRANO", **enlace),
            _anuncio("3", [("Guayas", "1.0")], page_id="333", page_name="Página aliada", bylines="LEONEL MUÑOZ ZAMBRANO"),
            _anuncio("4", [("Guayas", "1.0")], page_id="444", page_name="Otra persona", bylines="Otra persona", **enlace),
        ]

    def test_las_dos_paginas_de_una_entidad_son_un_solo_punto_en_la_red(self):
        self.usar([_leonel(verificado=True)])
        grafo = self._con(self._datos_leonel()).red_pagadores(None, limite=10)["grafo"]
        paginas = {n["nombre"]: n for n in grafo["nodos"] if n["tipo"] == "pagina"}
        self.assertNotIn("Leonel Munoz", paginas)
        self.assertNotIn("Leonel Munoz Zambrano", paginas)
        punto = paginas["Leonel Muñoz Zambrano"]
        self.assertEqual((punto["anuncios"], punto["page_id"]), (2, "111"))                                      # los dos anuncios, bajo el ID principal
        self.assertEqual({(p["page_id"], p["nombre"]) for p in punto["unificada"]}, {("111", "Leonel Munoz Zambrano"), ("222", "Leonel Munoz")})
        self.assertEqual((punto["afiliacion"]["partido"], punto["afiliacion_estado"]), ("ADN", "verificada"))
        self.assertEqual(sorted(paginas), ["Leonel Muñoz Zambrano", "Otra persona", "Página aliada"])           # «Otra persona» conserva el nombre de Meta
        self.assertNotIn("unificada", paginas["Otra persona"])
        sol = next(n for n in grafo["nodos"] if n["tipo"] == "provincia")
        self.assertEqual(sol["paginas_total"], 3)                                                                # tres páginas con base en Guayas, no cuatro
        self.assertTrue(all(e["a"] != e["b"] for e in grafo["aristas"]))                                         # compartir un enlace entre sus dos páginas no crea un lazo

    def test_la_lista_de_anuncios_del_punto_coincide_con_su_cifra_y_un_id_secundario_sigue_valiendo(self):
        self.usar([_leonel()])
        cliente = self._con(self._datos_leonel())
        punto = next(n for n in cliente.red_pagadores(None, limite=10)["grafo"]["nodos"] if n["nombre"] == "Leonel Muñoz Zambrano")
        lista = cliente.anuncios(pagina=punto["nombre"])
        self.assertEqual((lista["total"], sorted(a["id"] for a in lista["anuncios"])), (punto["anuncios"], ["1", "2"]))
        self.assertEqual(sorted(a["id"] for a in cliente.anuncios(page_id="222")["anuncios"]), ["1", "2"])        # el ID de la segunda página encuentra los dos
        original = next(a for a in lista["anuncios"] if a["id"] == "2")
        self.assertEqual((original["page_name_meta"], original["page_id_meta"]), ("Leonel Munoz", "222"))       # el dato original de Meta no se pierde

    def test_los_anunciantes_cuentan_la_entidad_una_vez(self):
        self.usar([_leonel()])
        filas = {f["page_name"]: f for f in self._con(self._datos_leonel()).top_gastadores(None, 10)["anunciantes"]}
        self.assertEqual(sorted(filas), ["Leonel Muñoz Zambrano", "Otra persona", "Página aliada"])
        self.assertEqual(filas["Leonel Muñoz Zambrano"]["anuncios"], 2)

    def test_un_nombre_alterno_que_es_otra_pagina_tambien_se_une(self):
        self.usar([_ent("Hernán Salcedo Loor", "10", otros_nombres=["Hernán Salcedo"])])
        datos = [_anuncio("1", [("Manabí", "1.0")], page_id="10", page_name="Hernán Salcedo Loor"),
                 _anuncio("2", [("Manabí", "1.0")], page_id="11", page_name="HERNÁN SALCEDO"),                  # otra página, solo se conoce por el nombre alterno
                 _anuncio("3", [("Manabí", "1.0")], page_id="12", page_name="Hernán Salcedo Pérez")]            # un homónimo cercano que no es él
        paginas = {n["nombre"]: n for n in self._con(datos).red_pagadores(None, limite=10)["grafo"]["nodos"] if n["tipo"] == "pagina"}
        self.assertEqual(sorted(paginas), ["Hernán Salcedo Loor", "Hernán Salcedo Pérez"])
        self.assertEqual(paginas["Hernán Salcedo Loor"]["anuncios"], 2)

    def test_sin_entidad_unificada_los_nombres_de_meta_quedan_igual(self):
        self.usar([_ent("Ana Peña", "5")])                                                                       # una sola página y un solo nombre: no hay nada que unir
        datos = [_anuncio("1", [("Guayas", "1.0")], page_id="5", page_name="Ana Pena"), _anuncio("2", [("Guayas", "1.0")], page_id="6", page_name="Ana")]
        paginas = {n["nombre"] for n in self._con(datos).red_pagadores(None, limite=10)["grafo"]["nodos"] if n["tipo"] == "pagina"}
        self.assertEqual(paginas, {"Ana Pena", "Ana"})


class ConectoresTests(_ConArchivo):
    """Las provincias donde un mismo partido tiene candidatos se unen con una línea (un conector por partido y par de soles)."""

    def _ents(self):
        def p(nombre, pid, partido, tipo="candidato", verificado=True):
            return _ent(nombre, pid, partido=partido, verificado=verificado, tipo=tipo)
        return [
            p("Ana ADN", "1", "ADN"), p("Beto ADN", "2", "ADN"), p("Carla ADN", "3", "ADN", tipo="persona"), p("Dani PSC", "4", "PSC"),
            p("Elena ADN pendiente", "5", "ADN", verificado=False), p("Fede ADN", "6", "ADN"),
            _ent("ADN Oficial", "7", verificado=True, tipo="partido"),
            {"nombre": "Radio Neutral", "page_id": "8", "tipo": "medio", "afiliacion": ads_library.AFIL_NEUTRAL, "partido": "Neutral",
             "fuente": "https://ejemplo.ec/n", "verificado": True, "actualizado": "2026-11-05"},
            {"nombre": "Alcaldía X", "page_id": "9", "tipo": "institucion", "afiliacion": "ADN (gobierno)", "partido": "ADN",
             "fuente": "https://ejemplo.ec/a", "verificado": True, "actualizado": "2026-11-05"},
        ]

    def _grafo(self):
        self.usar(self._ents())
        paginas = {"1": ("Ana ADN", "Guayas"), "2": ("Beto ADN", "Manabí"), "3": ("Carla ADN", "Pichincha"), "4": ("Dani PSC", "Guayas"),
                   "5": ("Elena ADN pendiente", "Loja"), "6": ("Fede ADN", "Guayas"), "7": ("ADN Oficial", "Pichincha"),
                   "8": ("Radio Neutral", "Manabí"), "9": ("Alcaldía X", "Azuay")}
        datos = [_anuncio(f"a{i}", [(prov, "1.0")], page_id=i, page_name=nombre, bylines="") for i, (nombre, prov) in paginas.items()]
        cliente = _cliente()
        parche = mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos}))
        parche.start()
        self.addCleanup(parche.stop)
        return cliente.red_pagadores(None, limite=10)["grafo"]

    def test_une_las_provincias_con_candidatos_del_mismo_partido_una_linea_por_par(self):
        grafo = self._grafo()
        lineas = [e for e in grafo["aristas"] if e["tipo"] == "partido_prov"]
        pares = {(e["a"], e["b"], e["partido"]): e["verificada"] for e in lineas}
        # ADN verificado en Guayas (Ana y Fede), Manabí (Beto) y Pichincha (Carla, una persona); Loja solo tiene una candidata sin verificar
        self.assertEqual(pares[("R:Guayas", "R:Manabí", "ADN")], True)
        self.assertEqual(pares[("R:Guayas", "R:Pichincha", "ADN")], True)
        self.assertEqual(pares[("R:Manabí", "R:Pichincha", "ADN")], True)
        self.assertEqual(pares[("R:Guayas", "R:Loja", "ADN")], False)                                     # con una candidata sin verificar la línea solo sale con los pendientes
        self.assertEqual(len(lineas), 6)                                                                   # 4 soles con ADN: 6 pares; ninguna línea por PSC (un solo sol)
        self.assertEqual(grafo["tipos"]["partido_prov"], 6)

    def test_solo_cuentan_las_personas_con_partido_y_nunca_los_medios_neutrales_ni_las_instituciones(self):
        grafo = self._grafo()
        soles = {x for e in grafo["aristas"] if e["tipo"] == "partido_prov" for x in (e["a"], e["b"])}
        self.assertNotIn("R:Azuay", soles)                                                                # la institución «Alcaldía X» (ADN) no es un candidato
        self.assertTrue(all(e.get("partido") != "Neutral" for e in grafo["aristas"] if e["tipo"] == "partido_prov"))
        self.assertTrue(all(e["a"].startswith("R:") and e["b"].startswith("R:") for e in grafo["aristas"] if e["tipo"] == "partido_prov"))   # unen soles, no páginas

    def test_cada_linea_dice_quienes_une_y_dos_candidatos_de_una_provincia_no_se_unen_entre_si(self):
        grafo = self._grafo()
        linea = next(e for e in grafo["aristas"] if e["tipo"] == "partido_prov" and (e["a"], e["b"]) == ("R:Guayas", "R:Manabí"))
        self.assertIn("Ana ADN", linea["detalles"][0])
        self.assertIn("Beto ADN", linea["detalles"][0])
        self.assertEqual({(c["nombre"], c["sol"]) for c in linea["candidatos"]}, {("Ana ADN", "R:Guayas"), ("Fede ADN", "R:Guayas"), ("Beto ADN", "R:Manabí")})
        self.assertFalse(any(e["a"] == e["b"] for e in grafo["aristas"]))                                  # Ana y Fede (los dos en Guayas) no generan una línea Guayas–Guayas

    def test_la_red_conserva_las_estrellas_del_partido_y_el_resto_de_vinculos(self):
        grafo = self._grafo()
        estrella = [(e["a"], e["b"]) for e in grafo["aristas"] if e["tipo"] == "partido"]
        self.assertTrue(estrella and all(a == "G:ADN Oficial" for a, _ in estrella))                       # la página del partido sigue uniéndose a sus candidatos
        self.assertTrue(any(e["tipo"] == "alcance" for e in grafo["aristas"]))


if __name__ == "__main__":
    unittest.main()
