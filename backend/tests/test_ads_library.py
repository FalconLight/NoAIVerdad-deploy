import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import requests

import ads_library
from ads_library import AdLibraryClient

SECRET = "EAAB-super-secret-token"


def _respuesta(status=200, cuerpo=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = cuerpo
    r.text = json.dumps(cuerpo)
    return r


def _anuncio(ad_id, regiones, **extra):
    base = {
        "id": ad_id,
        "page_id": "111",
        "page_name": "Página de prueba",
        "bylines": "Movimiento Ejemplo",
        "ad_delivery_start_time": "2026-10-01",
        "ad_creative_bodies": ["Vota por el cambio en tu provincia"],
        "currency": "USD",
        "spend": {"lower_bound": "100", "upper_bound": "499"},
        "impressions": {"lower_bound": "10000", "upper_bound": "50000"},
        "publisher_platforms": ["FACEBOOK", "INSTAGRAM"],
        "delivery_by_region": [{"region": r, "percentage": p} for r, p in regiones],
        # Meta incrusta el token en esta URL: nunca debe llegar a la salida.
        "ad_snapshot_url": f"https://www.facebook.com/ads/archive/render_ad/?id={ad_id}&access_token={SECRET}",
    }
    base.update(extra)
    return base


def _cliente(**env):
    # Los tests NUNCA deben tocar la copia real en backend/data: cada cliente usa su propia carpeta temporal.
    carpeta = tempfile.mkdtemp(prefix="noai_test_")
    entorno = {"META_AD_LIBRARY_TOKEN": SECRET, "META_INTEGRATION_ENABLED": "true", "AD_LIBRARY_TERMS": "elecciones", "AD_LIBRARY_PAGES": "1",
               "AD_LIBRARY_SNAPSHOT": os.path.join(carpeta, "snapshot.json"),
               # tampoco el archivo histórico real: si el entorno trae AD_LIBRARY_ARCHIVO_DIR (p. ej. de backend/.env.local), aquí no vale
               "AD_LIBRARY_ARCHIVO_DIR": os.path.join(carpeta, "archivo")}
    entorno.update(env)
    with mock.patch.dict(os.environ, entorno):
        return AdLibraryClient()


class AdLibraryTests(unittest.TestCase):
    def test_sin_token_no_llama_a_la_red_y_explica(self):
        cliente = _cliente(META_AD_LIBRARY_TOKEN="")
        with mock.patch.object(ads_library.requests, "get") as get:
            ads, estado = cliente.por_provincia("Pichincha")
        get.assert_not_called()
        self.assertEqual(ads, [])
        self.assertFalse(estado["configurado"])
        self.assertIn("META_AD_LIBRARY_TOKEN", estado["mensaje"])

    def test_por_defecto_se_buscan_todos_los_anuncios_con_el_comodin(self):
        # Buscar por palabras solo traía una parte (y nada de lo local que no las usa: Galápagos, municipios…): «*» pide todos los anuncios del período.
        entorno = {"META_AD_LIBRARY_TOKEN": SECRET, "META_INTEGRATION_ENABLED": "true",
                   "AD_LIBRARY_SNAPSHOT": os.path.join(tempfile.mkdtemp(prefix="noai_test_"), "snapshot.json")}
        with mock.patch.dict(os.environ, entorno):
            os.environ.pop("AD_LIBRARY_TERMS", None)                  # sin configuración propia: vale la de por defecto
            os.environ.pop("AD_LIBRARY_PAGES", None)
            cliente = AdLibraryClient()
        self.assertEqual(cliente.terms, ["*"])
        self.assertGreaterEqual(cliente.pages_per_term, 40)           # páginas de sobra para agotar los resultados
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": []})) as get:
            cliente.obtener_nacional()
        self.assertEqual({c.kwargs["params"]["search_terms"] for c in get.call_args_list}, {"*"})

    def test_filtra_por_provincia_con_tildes_y_ordena_por_impresiones(self):
        data = [
            _anuncio("1", [("Pichincha", "0.7"), ("Guayas", "0.3")]),
            _anuncio("2", [("Guayas", "1.0")]),
            _anuncio("3", [("Santo Domingo de los Tsáchilas Province", "0.9")],
                     impressions={"lower_bound": "100000", "upper_bound": "200000"}),
        ]
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": data})):
            pichincha, _ = cliente.por_provincia("Pichincha")
            guayas, _ = cliente.por_provincia("guayas")
            santo, estado = cliente.por_provincia("Santo Domingo de los Tsachilas")

        self.assertEqual([a["id"] for a in pichincha], ["1"])
        self.assertAlmostEqual(pichincha[0]["porcentaje_provincia"], 0.7)
        self.assertEqual([a["id"] for a in guayas], ["1", "2"])
        self.assertEqual([a["id"] for a in santo], ["3"])
        self.assertEqual(estado["total_nacional"], 3)

    def test_normaliza_campos_y_no_filtra_el_token(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get",
                               return_value=_respuesta(200, {"data": [_anuncio("42", [("Azuay", "1.0")])]})):
            ads, _ = cliente.por_provincia("Azuay")

        ad = ads[0]
        self.assertEqual(ad["financiador"], "Movimiento Ejemplo")
        self.assertEqual(ad["gasto"], {"min": 100, "max": 499})
        self.assertEqual(ad["impresiones"], {"min": 10000, "max": 50000})
        self.assertEqual(ad["link"], "https://www.facebook.com/ads/library/?id=42")
        self.assertTrue(ad["activo"])
        self.assertNotIn(SECRET, json.dumps(ads))

    def test_porcentajes_en_escala_0_100_se_normalizan(self):
        cliente = _cliente()
        anuncio = _anuncio("7", [("Loja", "80"), ("Azuay", "20")])
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": [anuncio]})):
            ads, _ = cliente.por_provincia("Loja")
        self.assertAlmostEqual(ads[0]["porcentaje_provincia"], 0.8)

    def test_errores_de_red_no_exponen_el_token(self):
        cliente = _cliente()
        error = requests.ConnectionError(f"Max retries exceeded with url: /v23.0/ads_archive?access_token={SECRET}&limit=50")
        with mock.patch.object(ads_library.requests, "get", side_effect=error):
            ads, estado = cliente.obtener_nacional()
            diag = cliente.diagnostico()
        self.assertEqual(ads, [])
        self.assertNotIn(SECRET, json.dumps(estado))
        self.assertNotIn(SECRET, json.dumps(diag))
        self.assertFalse(diag["ok"])

    def test_diagnostico_prueba_con_el_primer_termino_configurado(self):
        # La prueba usa el mismo tipo de consulta que la descarga real («*» por defecto), no una palabra fija.
        cliente = _cliente(AD_LIBRARY_TERMS="*,Galápagos")
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": []})) as get:
            diag = cliente.diagnostico()
        self.assertEqual(get.call_args.kwargs["params"]["search_terms"], "*")
        self.assertTrue(diag["ok"])
        self.assertIn("'*'", diag["mensaje"])                         # sin anuncios: el mensaje nombra la búsqueda que se probó

    def test_error_http_de_la_api_se_resume_sin_token(self):
        cliente = _cliente()
        cuerpo = {"error": {"code": 190, "message": f"Invalid OAuth access token. access_token={SECRET}"}}
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(401, cuerpo)):
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(ads, [])
        self.assertIn("190", estado["mensaje"])
        self.assertNotIn(SECRET, json.dumps(estado))

    def test_si_la_api_rechaza_un_campo_reintenta_con_campos_basicos(self):
        cliente = _cliente()
        rechazo = _respuesta(400, {"error": {"code": 100, "message": "Tried accessing nonexisting field (delivery_by_region)"}})
        exito = _respuesta(200, {"data": [_anuncio("9", [])]})
        with mock.patch.object(ads_library.requests, "get", side_effect=[rechazo, exito]) as get:
            ads, _ = cliente.obtener_nacional()
        self.assertEqual(len(ads), 1)
        segundo = get.call_args_list[1].kwargs["params"]["fields"]
        self.assertNotIn("delivery_by_region", segundo)

    def test_sigue_la_paginacion_por_cursor(self):
        cliente = _cliente(AD_LIBRARY_PAGES="3")
        p1 = _respuesta(200, {"data": [_anuncio("1", [("Manabí", "1.0")])],
                              "paging": {"cursors": {"after": "CUR1"}, "next": "https://x"}})
        p2 = _respuesta(200, {"data": [_anuncio("2", [("Manabí", "1.0")])]})
        with mock.patch.object(ads_library.requests, "get", side_effect=[p1, p2]) as get:
            ads, _ = cliente.obtener_nacional()
        self.assertEqual(sorted(a["id"] for a in ads), ["1", "2"])
        self.assertEqual(get.call_args_list[1].kwargs["params"]["after"], "CUR1")

    def test_pide_solo_anuncios_politicos_de_ecuador(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": []})) as get:
            cliente.obtener_nacional()
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["ad_type"], "POLITICAL_AND_ISSUE_ADS")
        self.assertEqual(json.loads(params["ad_reached_countries"]), ["EC"])
        self.assertNotIn("ad_snapshot_url", params["fields"])


class TextosDuplicadosTests(unittest.TestCase):
    TEXTO = "Este domingo vota por la lista seis y devuélvele la esperanza a tu provincia con trabajo y seguridad"

    def _grupos(self, anuncios):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": anuncios})):
            return cliente.textos_duplicados()

    def test_agrupa_texto_casi_identico_en_paginas_distintas(self):
        r = self._grupos([
            _anuncio("1", [("Azuay", "1.0")], page_name="Página A", ad_creative_bodies=[self.TEXTO], bylines="Partido X"),
            _anuncio("2", [("Azuay", "1.0")], page_name="Página B", ad_creative_bodies=[self.TEXTO + "!"], bylines="Partido Y"),
            _anuncio("3", [("Azuay", "1.0")], page_name="Página C", ad_creative_bodies=["Inscríbete gratis al taller de agricultura sostenible que organiza el municipio este sábado"]),
        ])
        self.assertEqual(r["total_grupos"], 1)
        g = r["grupos"][0]
        self.assertEqual(g["n_paginas"], 2)
        self.assertTrue(g["financiadores_distintos"])

    def test_mismo_texto_en_una_sola_pagina_no_es_grupo(self):
        r = self._grupos([
            _anuncio("1", [], page_name="Página A", ad_creative_bodies=[self.TEXTO]),
            _anuncio("2", [], page_name="Página A", ad_creative_bodies=[self.TEXTO]),
        ])
        self.assertEqual(r["total_grupos"], 0)


    def test_avisos_de_anuncio_retirado_no_forman_grupo_y_se_cuentan(self):
        aviso = "This ad was run by an account or Page we later disabled for not following our Advertising Standards."
        r = self._grupos([
            _anuncio("1", [], page_name="A", ad_creative_bodies=[aviso]),
            _anuncio("2", [], page_name="B", ad_creative_bodies=[aviso]),
        ])
        self.assertEqual(r["total_grupos"], 0)
        self.assertEqual(r["estado"]["retirados_por_meta"], 2)         # los retirados ya no llegan al análisis: se cuentan en el estado

    def test_textos_cortos_se_ignoran(self):
        r = self._grupos([
            _anuncio("1", [], page_name="A", ad_creative_bodies=["Vota por mí"]),
            _anuncio("2", [], page_name="B", ad_creative_bodies=["Vota por mí"]),
        ])
        self.assertEqual(r["analizados"], 0)


class MensajesRepetidosSinFalsosPositivosTests(unittest.TestCase):
    """Casos reales de la revisión del 2026-11-05: lo que parecía «el mismo mensaje» y no lo es, y lo que sí lo es aunque cambie la forma."""
    TEXTO = "Este domingo vota por la lista seis y devuélvele la esperanza a tu provincia con trabajo y seguridad"
    # Plantilla de una campaña con historias distintas («Conoce la historia de X»): casi todas las palabras coinciden y el mensaje es otro.
    PLANTILLA = ("Con nuestras soluciones de financiamiento acompañamos a las pequeñas empresas para que puedan invertir en su negocio, crecer con "
                 "tranquilidad y alcanzar nuevas metas durante los próximos años. Conoce la historia de {} que encontró en nuestro banco el respaldo "
                 "para seguir creciendo con todo el apoyo de su familia y de sus clientes.")

    def _resultado(self, anuncios, **entorno):
        cliente = _cliente(**entorno)
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": anuncios})):
            return cliente.textos_duplicados()

    def _ad(self, ad_id, pagina, texto, **extra):
        return _anuncio(ad_id, [], page_name=pagina, ad_creative_bodies=[texto], **extra)

    def test_enlaces_hashtags_y_menciones_no_impiden_ni_inventan_coincidencias(self):
        # El mismo mensaje con enlaces de seguimiento, hashtags y menciones distintos SÍ es el mismo mensaje.
        r = self._resultado([
            self._ad("1", "A", self.TEXTO + " https://bit.ly/aaa111?utm=uno #Lista6 @candidato1"),
            self._ad("2", "B", self.TEXTO + " https://otra.ec/xyz #Esperanza #Provincia @otro"),
        ])
        self.assertEqual(r["total_grupos"], 1)
        self.assertEqual(r["grupos"][0]["n_textos"], 1)
        # Un texto que solo son hashtags no es un mensaje: antes contaba como diez palabras y dos páginas «repetían» el mismo.
        solo_etiquetas = "#Vota7 #ADN7 #Lista7 #Cambio #Ecuador #Esperanza #Futuro #Seguridad #Trabajo #Pais"
        r = self._resultado([self._ad("1", "A", solo_etiquetas), self._ad("2", "B", solo_etiquetas)])
        self.assertEqual((r["analizados"], r["total_grupos"]), (0, 0))

    def test_el_enlace_no_cuenta_como_palabras_para_el_minimo(self):
        # Seis palabras y un enlace largo: sin el enlace es un texto corto y genérico.
        corto = "Inscríbete ya en la plataforma https://jovenesenaccion.trabajo.gob.ec/inscripcion/formulario/registro/nuevo"
        r = self._resultado([self._ad("1", "A", corto), self._ad("2", "B", corto)])
        self.assertEqual(r["analizados"], 0)

    def test_misma_plantilla_con_otro_nombre_no_es_el_mismo_mensaje(self):
        anuncios = [
            self._ad("1", "A", self.PLANTILLA.format("Kelly Sarmiento")),
            self._ad("2", "B", self.PLANTILLA.format("Gabriela Cedillo")),
            self._ad("3", "B", self.PLANTILLA.format("Kelly Sarmiento")),
        ]
        r = self._resultado(anuncios)
        # Solo la historia de Kelly está en las dos páginas: el grupo son esos dos anuncios, no los tres.
        self.assertEqual(r["total_grupos"], 1)
        self.assertEqual((r["grupos"][0]["anuncios"], r["grupos"][0]["n_textos"]), (2, 1))
        self.assertEqual(r["plantillas_separadas"], 2)
        # Sin la regla, la plantilla uniría las tres historias (el defecto de antes): la prueba sí ejercita la regla.
        with mock.patch.object(ads_library, "_sustituye_datos", return_value=False):
            sin_regla = self._resultado(anuncios)
        self.assertEqual((sin_regla["grupos"][0]["anuncios"], sin_regla["grupos"][0]["n_textos"]), (3, 2))

    def test_una_cifra_distinta_tambien_es_otro_mensaje(self):
        texto = ("El programa abre {} cupos para jóvenes de todo el país con capacitación, pasantías pagadas y apoyo económico durante dos meses; "
                 "las inscripciones empiezan esta semana y se hacen en línea, sin costo, desde cualquier teléfono o computadora con internet")
        r = self._resultado([self._ad("1", "A", texto.format("700.000")), self._ad("2", "B", texto.format("800.000"))])
        self.assertEqual(r["total_grupos"], 0)

    def test_otra_fecha_es_otro_mensaje_pero_una_mayuscula_inicial_distinta_no(self):
        agenda = ("Entrevista radial y agenda de medios: {} a las ocho de la mañana hablaremos de las obras de agua potable, vialidad y seguridad "
                  "que ya están en marcha en todos los barrios y recintos de nuestro cantón, y de lo que viene para el próximo año con todos ustedes")
        r = self._resultado([self._ad("1", "A", agenda.format("VIERNES 23")), self._ad("2", "B", agenda.format("LUNES 12"))])
        self.assertEqual(r["total_grupos"], 0)                  # otro día: otro anuncio
        # «Una nueva ruta…» / «La nueva ruta…» o «Continuamos…» / «Supervisamos…»: la mayúscula de abrir la frase no es un nombre propio.
        ruta = ("{} nueva ruta de la producción avanza a buen ritmo para los productores de la zona; aquí te contamos los detalles de la obra, "
                "sus beneficios para los agricultores y comerciantes, y las fechas previstas para su entrega final a la comunidad entera")
        r = self._resultado([self._ad("1", "A", ruta.format("Una")), self._ad("2", "B", ruta.format("La"))])
        self.assertEqual((r["total_grupos"], r["plantillas_separadas"]), (1, 0))

    def test_el_mismo_nombre_mas_largo_con_o_sin_tilde_o_una_firma_si_se_agrupa(self):
        base = ("Machala ha esperado demasiado pero mientras exista esperanza ninguna historia está terminada. Lo que viene también puede cambiarlo "
                "todo y por eso este domingo la decisión está en tus manos para que juntos construyamos el cambio que tanto necesitamos. "
                "Si es con Rafael es con {}")
        r = self._resultado([
            self._ad("1", "Partido", base.format("Andrés")),
            self._ad("2", "Candidato", base.format("Andres Esteban Vazquez Jadan")),          # nombre completo y sin tilde: no es otro dato
            self._ad("3", "Aliado", base.format("Andrés") + " Firma: Equipo de campaña"),     # una firma añadida tampoco
        ])
        self.assertEqual(r["total_grupos"], 1)
        self.assertEqual(r["grupos"][0]["n_paginas"], 3)
        self.assertEqual(r["plantillas_separadas"], 0)

    def test_aviso_de_meta_sin_descargo_no_forma_grupo_aunque_tenga_mas_palabras(self):
        aviso = "This ad ran without a required disclaimer. After it started running we determined that it was missing a disclaimer."
        r = self._resultado([self._ad("1", "A", aviso), self._ad("2", "B", aviso)])
        self.assertEqual((r["analizados"], r["total_grupos"]), (0, 0))

    def test_un_texto_en_muchas_paginas_se_deja_fuera_y_se_informa(self):
        anuncios = [self._ad(str(i), f"Página {i}", self.TEXTO) for i in range(4)]
        with mock.patch.object(ads_library, "MAX_PAGINAS_POR_TEXTO", 3):
            r = self._resultado(anuncios)
            dos = self._resultado(anuncios[:2])
        self.assertEqual(r["total_grupos"], 0)
        self.assertEqual(r["textos_muy_extendidos"]["textos"], 1)
        self.assertEqual((r["textos_muy_extendidos"]["ejemplos"][0]["paginas"], r["textos_muy_extendidos"]["ejemplos"][0]["anuncios"]), (4, 4))
        self.assertEqual((dos["total_grupos"], dos["textos_muy_extendidos"]["textos"]), (1, 0))      # dos páginas sí es una coincidencia

    def test_contexto_de_cada_grupo_dias_coincidencias_y_partido(self):
        textos = ["La obra de la nueva vía avanza según lo planificado y estará lista para el feriado con más seguridad para los conductores",
                  "Inscríbete gratis al taller de agricultura sostenible que organiza el municipio este sábado en el parque central del cantón",
                  "El nuevo hospital básico recibirá a los primeros pacientes el próximo mes con equipos modernos y personal especializado de la zona",
                  "Convocamos a todos los vecinos del barrio a la minga de limpieza que se realizará el domingo temprano en la cancha comunal"]
        fechas = [("2026-10-01", "2026-10-04"), ("2026-10-10", "2026-10-10"), ("2026-10-20", "2026-10-21"), ("2026-10-05", "2026-10-06")]
        paginas = [("Página A", "Página B")] * 3 + [("Página C", "Página D")]
        anuncios = []
        for i, (t, (f1, f2), (p1, p2)) in enumerate(zip(textos, fechas, paginas)):
            anuncios.append(self._ad(f"a{i}", p1, t, ad_delivery_start_time=f1))
            anuncios.append(self._ad(f"b{i}", p2, t, ad_delivery_start_time=f2))

        ruta = os.path.join(tempfile.mkdtemp(prefix="noai_afil_"), "afiliaciones.json")

        def con_afiliaciones(verificado_b):
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"partidos": {}, "entidades": [
                    {"nombre": "Página A", "tipo": "candidato", "afiliacion": "Candidata de ADN", "partido": "ADN", "fuente": "https://x.ec/a", "verificado": True},
                    {"nombre": "Página B", "tipo": "partido", "afiliacion": "Partido ADN", "partido": "ADN", "fuente": "https://x.ec/b", "verificado": verificado_b},
                ]}, f)
            with mock.patch.object(ads_library, "RUTA_AFILIACIONES", ruta):
                return self._resultado(anuncios)

        r = con_afiliaciones(True)
        por_texto = {g["texto"][:20]: g for g in r["grupos"]}
        ab = [por_texto[t[:20]] for t in textos[:3]]
        cd = por_texto[textos[3][:20]]
        self.assertEqual([g["coincidencias"] for g in ab], [3, 3, 3])          # las mismas dos páginas repiten tres mensajes: un patrón
        self.assertEqual(cd["coincidencias"], 1)                              # la otra pareja coincide una sola vez
        self.assertEqual([g["dias"] for g in ab], [3, 0, 1])
        self.assertEqual({g["n_textos"] for g in r["grupos"]}, {1})
        self.assertEqual([g["mismo_partido"] for g in ab], ["ADN"] * 3)       # las dos páginas tienen el mismo partido verificado: reuso esperado
        self.assertEqual(cd["mismo_partido"], "")                              # sin afiliación conocida no se afirma nada
        self.assertEqual({g["mismo_partido"] for g in con_afiliaciones(False)["grupos"]}, {""})      # con una sin verificar tampoco


class MensajesRevisadosTests(unittest.TestCase):
    """La lista de grupos revisados (backend/mensajes_revisados.json): lo que cubre una revisión, lo que no, y cómo vuelve a ser señal."""
    TEXTO = "El Gobierno anunció una nueva etapa del programa con setecientos mil cupos para jóvenes de todo el país en capacitación, pasantías pagadas y apoyo"
    OTRO = "Inscríbete gratis al taller de agricultura sostenible que organiza el municipio este sábado en el parque central del cantón con todos los vecinos"

    def setUp(self):
        self.ruta = os.path.join(tempfile.mkdtemp(prefix="noai_rev_"), "mensajes_revisados.json")
        parche = mock.patch.object(ads_library, "RUTA_REVISIONES", self.ruta)
        parche.start()
        self.addCleanup(parche.stop)

    def _ad(self, ad_id, pagina, texto, page_id):
        return _anuncio(ad_id, [("Azuay", "1.0")], page_name=pagina, page_id=page_id, ad_creative_bodies=[texto])

    def _cliente_con(self, anuncios):
        cliente = _cliente()
        parche = mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": anuncios}))
        parche.start()
        self.addCleanup(parche.stop)
        return cliente

    def _par(self, texto=None, a=("Página A", "101"), b=("Página B", "102"), prefijo="x"):
        texto = texto or self.TEXTO
        return [self._ad(f"{prefijo}1", a[0], texto, a[1]), self._ad(f"{prefijo}2", b[0], texto, b[1])]

    @staticmethod
    def _revision(grupo, alcance="mensaje", motivo="partido", **extra):
        return {"alcance": alcance, "motivo": motivo, "nota": "", "huellas": grupo["huellas"], "ejemplo": grupo["texto"],
                "paginas": [{"nombre": p["page_name"], "page_id": p["page_id"]} for p in grupo["paginas"]], **extra}

    def test_un_grupo_revisado_deja_de_ser_senal_y_se_puede_ver_aparte(self):
        cliente = self._cliente_con(self._par())
        antes = cliente.textos_duplicados()
        grupo = antes["grupos"][0]
        self.assertEqual((antes["total_grupos"], antes["total_revisados"], grupo["revision"]), (1, 0, None))
        self.assertEqual({p["page_id"] for p in grupo["paginas"]}, {"101", "102"})
        self.assertEqual(len(grupo["huellas"]), 1)

        cliente.guardar_revision(self._revision(grupo, nota="Candidata y su partido"))
        oculto = cliente.textos_duplicados()
        self.assertEqual((oculto["total_grupos"], oculto["total_revisados"], oculto["grupos"]), (0, 1, []))
        visto = cliente.textos_duplicados(revisados=True)
        self.assertEqual((visto["total_grupos"], visto["total_revisados"]), (1, 1))
        revision = visto["grupos"][0]["revision"]
        self.assertEqual((revision["estado"], revision["motivo"], revision["motivo_texto"], revision["nota"]),
                         ("completa", "partido", ads_library.MOTIVOS_REVISION["partido"], "Candidata y su partido"))
        with open(self.ruta, encoding="utf-8") as f:
            archivo = json.load(f)
        self.assertEqual(len(archivo["revisados"]), 1)
        self.assertIn("_leeme", archivo)
        self.assertEqual(archivo["revisados"][0]["revisado"], date.today().isoformat())

    def test_una_revision_de_un_mensaje_no_cubre_otro_mensaje_entre_las_mismas_paginas(self):
        cliente = self._cliente_con(self._par() + self._par(self.OTRO, prefijo="y"))
        grupos = cliente.textos_duplicados()["grupos"]
        self.assertEqual(len(grupos), 2)
        cliente.guardar_revision(self._revision(next(g for g in grupos if "Gobierno" in g["texto"])))
        r = cliente.textos_duplicados()
        self.assertEqual((r["total_grupos"], r["total_revisados"]), (1, 1))
        self.assertIn("agricultura", r["grupos"][0]["texto"])

    def test_una_revision_de_paginas_cubre_cualquier_mensaje_entre_ellas(self):
        cliente = self._cliente_con(self._par() + self._par(self.OTRO, prefijo="y"))
        cliente.guardar_revision(self._revision(cliente.textos_duplicados()["grupos"][0], alcance="paginas", motivo="misma_entidad", huellas=None))
        r = cliente.textos_duplicados()
        self.assertEqual((r["total_grupos"], r["total_revisados"]), (0, 2))

    def test_si_aparece_una_pagina_que_no_se_vio_el_grupo_vuelve_como_parcial(self):
        cliente = self._cliente_con(self._par())
        cliente.guardar_revision(self._revision(cliente.textos_duplicados()["grupos"][0]))
        # Otra descarga: la misma publicación, ahora también en una tercera página.
        r = self._cliente_con(self._par() + [self._ad("z3", "Página C", self.TEXTO, "103")]).textos_duplicados()
        self.assertEqual((r["total_grupos"], r["total_revisados"]), (1, 0))
        revision = r["grupos"][0]["revision"]
        self.assertEqual((revision["estado"], revision["paginas_nuevas"]), ("parcial", ["Página C"]))
        # Una página sin relación (dos páginas distintas que repiten el mismo texto) no hereda la revisión.
        otra = self._cliente_con(self._par(a=("Página X", "201"), b=("Página Y", "202"))).textos_duplicados()
        self.assertIsNone(otra["grupos"][0]["revision"])

    def test_la_revision_reconoce_el_mismo_mensaje_aunque_cambien_enlaces_y_hashtags(self):
        cliente = self._cliente_con(self._par(self.TEXTO + " #Uno https://a.ec/1"))
        cliente.guardar_revision(self._revision(cliente.textos_duplicados()["grupos"][0]))
        otro = self._cliente_con(self._par(self.TEXTO + " #Dos @alguien https://b.ec/2")).textos_duplicados()
        self.assertEqual((otro["total_grupos"], otro["total_revisados"]), (0, 1))

    def test_una_revision_nueva_reemplaza_las_que_hace_innecesarias(self):
        cliente = self._cliente_con(self._par())
        grupo = cliente.textos_duplicados()["grupos"][0]
        cliente.guardar_revision(self._revision(grupo))
        cliente.guardar_revision(self._revision(grupo, motivo="comunicacion_oficial"))                     # la misma: se sustituye, no se duplica
        self.assertEqual(len(ads_library._leer_revisiones()["revisados"]), 1)
        ampliada = self._revision(grupo, alcance="paginas", huellas=None)
        ampliada["paginas"].append({"nombre": "Página C", "page_id": "103"})
        resultado = cliente.guardar_revision(ampliada)
        self.assertEqual(resultado["total"], 1)                                                           # la de páginas incluye a la anterior
        self.assertEqual(ads_library._leer_revisiones()["revisados"][0]["alcance"], "paginas")

    def test_quitar_una_revision_devuelve_el_grupo_y_un_id_desconocido_falla(self):
        cliente = self._cliente_con(self._par())
        revision = cliente.guardar_revision(self._revision(cliente.textos_duplicados()["grupos"][0]))["revision"]
        self.assertEqual(cliente.textos_duplicados()["total_grupos"], 0)
        self.assertEqual(cliente.quitar_revision(revision["id"])["total"], 0)
        self.assertEqual(cliente.textos_duplicados()["total_grupos"], 1)
        for malo in (revision["id"], "", None):
            with self.assertRaises(ValueError):
                cliente.quitar_revision(malo)

    def test_datos_invalidos_se_rechazan_con_un_mensaje_claro_y_sin_escribir(self):
        cliente = _cliente()
        base = {"alcance": "mensaje", "motivo": "partido", "huellas": ["0123456789ab"], "paginas": [{"nombre": "Página A"}, {"nombre": "Página B"}]}
        malos = {
            "alcance": {**base, "alcance": "todo"},
            "motivo": {**base, "motivo": "porque sí"},
            "una sola página": {**base, "paginas": [{"nombre": "Página A"}, {"nombre": "PÁGINA a"}]},          # el mismo nombre con otra grafía
            "sin el mensaje": {**base, "huellas": []},
            "huella inválida": {**base, "huellas": ["no-es-una-huella"]},
            "otro sin nota": {**base, "motivo": "otro", "nota": "  "},
            "demasiadas páginas": {**base, "paginas": [{"nombre": f"P{i}"} for i in range(61)]},
        }
        for caso, datos in malos.items():
            with self.subTest(caso), self.assertRaises(ValueError):
                cliente.guardar_revision(datos)
        self.assertFalse(os.path.exists(self.ruta))
        self.assertTrue(cliente.guardar_revision({**base, "motivo": "otro", "nota": "Es el mismo equipo de campaña"})["ok"])

    def test_la_red_y_la_comparacion_no_cuentan_los_grupos_revisados(self):
        cliente = self._cliente_con(self._par() + self._par(self.OTRO, a=("Página C", "103"), b=("Página D", "104"), prefijo="y"))
        lineas = lambda: [e for e in cliente.red_pagadores(None, limite=10)["grafo"]["aristas"] if e["tipo"] == "texto"]
        self.assertEqual(len(lineas()), 2)
        self.assertEqual(cliente.comparar([None, "Azuay"])["columnas"][0]["mensajes_repetidos"], 2)
        cliente.guardar_revision(self._revision(next(g for g in cliente.textos_duplicados()["grupos"] if "Gobierno" in g["texto"])))
        self.assertEqual(len(lineas()), 1)                                                                # ya no se dibuja la línea del grupo revisado
        self.assertEqual(cliente.red_pagadores(None, limite=10)["textos_revisados"], 1)
        self.assertEqual(cliente.comparar([None, "Azuay"])["columnas"][0]["mensajes_repetidos"], 1)

    def test_un_archivo_ilegible_no_rompe_el_analisis_ni_se_sobrescribe(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            f.write("{esto no es json")
        cliente = self._cliente_con(self._par())
        self.assertEqual(cliente.textos_duplicados()["total_grupos"], 1)                                  # el análisis sigue sin revisiones
        with self.assertRaises(RuntimeError):
            cliente.guardar_revision(self._revision(cliente.textos_duplicados()["grupos"][0]))
        with open(self.ruta, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{esto no es json")                                               # no se pisó a ciegas


class ParDeAnunciosTests(unittest.TestCase):
    """Un mensaje repetido entre dos páginas se ve lado a lado: cada anuncio con su fecha y su propio enlace a la Biblioteca de Meta."""
    TEXTO = "El Gobierno anunció una nueva etapa del programa con setecientos mil cupos para jóvenes de todo el país en capacitación, pasantías pagadas y apoyo"
    OTRO = "Inscríbete gratis al taller de agricultura sostenible que organiza el municipio este sábado en el parque central del cantón con todos los vecinos"

    def setUp(self):
        parche = mock.patch.object(ads_library, "RUTA_REVISIONES", os.path.join(tempfile.mkdtemp(prefix="noai_rev_"), "mensajes_revisados.json"))
        parche.start()
        self.addCleanup(parche.stop)

    def _ad(self, ad_id, pagina, texto, fecha, page_id):
        return _anuncio(ad_id, [("Azuay", "1.0")], page_name=pagina, page_id=page_id, ad_creative_bodies=[texto], ad_delivery_start_time=fecha)

    def _cliente_con(self, anuncios):
        cliente = _cliente()
        parche = mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": anuncios}))
        parche.start()
        self.addCleanup(parche.stop)
        return cliente

    def test_el_detalle_trae_cada_anuncio_con_su_propio_enlace_y_solo_de_los_grupos_del_par(self):
        cliente = self._cliente_con([
            self._ad("11", "Página A", self.TEXTO, "2026-10-01", "101"), self._ad("12", "Página A", self.TEXTO + " #Otra", "2026-10-05", "101"),
            self._ad("21", "Página B", self.TEXTO, "2026-10-02", "102"), self._ad("31", "Página C", self.TEXTO, "2026-10-03", "103"),
            self._ad("41", "Página A", self.OTRO, "2026-10-01", "101"), self._ad("42", "Página C", self.OTRO, "2026-10-01", "103"),
        ])
        self.assertNotIn("detalle", cliente.textos_duplicados()["grupos"][0])                      # sin pedir un par, la lista sigue ligera
        r = cliente.textos_duplicados(entre=("Página A", "Página B"))
        self.assertEqual((r["total_grupos"], r["entre"]), (1, ["Página A", "Página B"]))            # el grupo entre A y C solo no sale
        detalle = r["grupos"][0]["detalle"]
        self.assertEqual([a["id"] for a in detalle["anuncios"]], ["11", "21", "31", "12"])          # del más antiguo al más reciente, de todas las páginas del grupo
        for a in detalle["anuncios"]:
            self.assertEqual(a["link"], f"https://www.facebook.com/ads/library/?id={a['id']}")      # un enlace por anuncio
            self.assertEqual({"fecha", "fecha_fin", "activo", "financiador", "gasto", "impresiones", "plataformas"} - set(a), set())
        self.assertEqual(detalle["omitidos"], 0)
        textos = detalle["textos"]
        self.assertEqual(len(textos), 2)                                                           # el mismo mensaje con otro hashtag es otro texto, completo
        self.assertTrue(textos[next(a for a in detalle["anuncios"] if a["id"] == "12")["t"]].endswith("#Otra"))

    def test_el_detalle_limita_los_anuncios_de_cada_pagina_y_cuenta_los_omitidos(self):
        anuncios = [self._ad(f"1{i}", "Página A", self.TEXTO, f"2026-10-0{i + 1}", "101") for i in range(4)] + [self._ad("21", "Página B", self.TEXTO, "2026-10-02", "102")]
        with mock.patch.object(ads_library, "MAX_ANUNCIOS_POR_PAGINA_DETALLE", 2):
            detalle = self._cliente_con(anuncios).textos_duplicados(entre=("Página A", "Página B"))["grupos"][0]["detalle"]
        self.assertEqual(sorted(a["id"] for a in detalle["anuncios"]), ["10", "11", "21"])          # los dos más antiguos de A y el de B
        self.assertEqual(detalle["omitidos"], 2)

    def test_entre_dos_paginas_tambien_salen_los_grupos_ya_revisados_con_su_marca(self):
        cliente = self._cliente_con([self._ad("11", "Página A", self.TEXTO, "2026-10-01", "101"), self._ad("21", "Página B", self.TEXTO, "2026-10-02", "102")])
        grupo = cliente.textos_duplicados()["grupos"][0]
        cliente.guardar_revision({"alcance": "paginas", "motivo": "partido", "paginas": [{"nombre": p["page_name"], "page_id": p["page_id"]} for p in grupo["paginas"]]})
        self.assertEqual(cliente.textos_duplicados()["total_grupos"], 0)
        r = cliente.textos_duplicados(entre=("Página A", "Página B"))
        self.assertEqual((r["total_grupos"], r["grupos"][0]["revision"]["estado"]), (1, "completa"))


class EntidadesTests(unittest.TestCase):
    def test_misma_entidad_ignora_mayusculas_tildes_y_sufijos_legales(self):
        self.assertTrue(ads_library._misma_entidad("LEONEL MUÑOZ ZAMBRANO", "Leonel Munoz Zambrano"))
        self.assertTrue(ads_library._misma_entidad("Goberna Ecuador S.A.S", "Asesoría Política - Goberna Ecuador"))
        self.assertFalse(ads_library._misma_entidad("Partido X", "Partido Y"))

    def test_mismos_financiadores_escritos_distinto_no_son_distintos(self):
        cliente = _cliente()
        texto = "Este domingo vota por la lista seis y devuélvele la esperanza a tu provincia con trabajo y seguridad"
        data = [
            _anuncio("1", [], page_name="A", ad_creative_bodies=[texto], bylines="LEONEL MUÑOZ ZAMBRANO"),
            _anuncio("2", [], page_name="B", ad_creative_bodies=[texto], bylines="Leonel Munoz Zambrano"),
        ]
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": data})):
            r = cliente.textos_duplicados()
        self.assertEqual(r["total_grupos"], 1)
        self.assertFalse(r["grupos"][0]["financiadores_distintos"])

    def test_costo_por_mil_se_omite_con_muestra_pequena(self):
        cliente = _cliente()
        data = [_anuncio("1", [("Azuay", "1.0")], impressions={"lower_bound": "0", "upper_bound": "99"})]
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": data})):
            r = cliente.top_gastadores()
        self.assertIsNone(r["anunciantes"][0]["costo_por_mil"])



class MapaYComparacionTests(unittest.TestCase):
    def _datos(self):
        return [
            _anuncio("1", [("Pichincha Province", "0.6"), ("Guayas Province", "0.4")], page_id="10", page_name="A",
                     impressions={"lower_bound": "1000", "upper_bound": "2999"}, spend={"lower_bound": "100", "upper_bound": "199"}),
            _anuncio("2", [("Guayas Province", "1.0")], page_id="11", page_name="B",
                     impressions={"lower_bound": "10000", "upper_bound": "14999"}, spend={"lower_bound": "200", "upper_bound": "299"}),
            _anuncio("3", [("Pichincha Province", "0.5"), ("Guayas Province", "0.5")], page_id="10", page_name="A",
                     impressions={"lower_bound": "1000", "upper_bound": "2999"}, spend={"lower_bound": "0", "upper_bound": "99"}),
        ]

    def test_metricas_por_provincia_prorratean_y_cuentan_anunciantes(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos()})):
            r = cliente.metricas_por_provincia()
        por_nombre = {p["provincia"]: p for p in r["provincias"]}
        self.assertEqual(set(por_nombre), {"Pichincha", "Guayas"})
        self.assertEqual(por_nombre["Guayas"]["anunciantes"], 2)
        self.assertEqual(por_nombre["Pichincha"]["anunciantes"], 1)
        # Guayas: 1999.5*0.4 + 12499.5*1.0 + 1999.5*0.5 = 14299.05 (el punto medio de un rango 1000-2999 es 1999.5)
        self.assertEqual(por_nombre["Guayas"]["impresiones"], 14299)
        self.assertEqual(r["provincias"][0]["provincia"], "Guayas")  # ordenadas por impresiones

    def test_regiones_fuera_de_ecuador_no_son_provincias(self):
        cliente = _cliente()
        datos = [_anuncio("9", [("Guayas Province", "0.7"), ("Madrid", "0.3")], page_id="5", page_name="Z",
                          impressions={"lower_bound": "1000", "upper_bound": "1999"})]
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            r = cliente.metricas_por_provincia()
            alcance = cliente.alcance_por_provincia()
        self.assertEqual([p["provincia"] for p in r["provincias"]], ["Guayas"])
        self.assertGreater(r["fuera_de_ecuador_impresiones"], 0)
        self.assertEqual([a["provincia"] for a in alcance], ["Guayas"])

    def test_comparar_devuelve_columnas_y_anunciantes_en_comun(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos()})):
            r = cliente.comparar(["Pichincha", "Guayas"])
        self.assertEqual([c["alcance"] for c in r["columnas"]], ["Pichincha", "Guayas"])
        self.assertEqual(r["columnas"][0]["resumen"]["anunciantes"], 1)
        self.assertEqual(r["columnas"][1]["resumen"]["anunciantes"], 2)
        self.assertEqual(r["total_en_comun"], 1)
        self.assertEqual(r["en_comun"][0]["page_name"], "A")
        self.assertEqual(len(r["en_comun"][0]["gasto_medio"]), 2)

    def test_comparar_incluye_el_total_nacional(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos()})):
            r = cliente.comparar([None, "Pichincha"])
        self.assertEqual(r["columnas"][0]["alcance"], "Nacional")
        self.assertEqual(r["columnas"][0]["resumen"]["anunciantes"], 2)



class SnapshotTests(unittest.TestCase):
    def _cliente_con_snapshot(self, ruta):
        return _cliente(AD_LIBRARY_SNAPSHOT=ruta)

    def _guardar_copia(self, ruta, **env):
        ok = _cliente(AD_LIBRARY_SNAPSHOT=ruta, **env)
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": [_anuncio("1", [("Loja", "1.0")])]})):
            ads, _ = ok.obtener_nacional()
        self.assertEqual(len(ads), 1)
        self.assertTrue(os.path.exists(ruta))

    def _envejecer_copia(self, ruta):
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
        d["guardado"] = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(d, f)

    def test_guarda_copia_y_la_usa_si_el_token_vence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "snap.json")
            self._guardar_copia(ruta)
            self._envejecer_copia(ruta)

            # nuevo cliente (p. ej. tras reiniciar) con la copia caducada y el token vencido
            caido = _cliente(AD_LIBRARY_SNAPSHOT=ruta)
            vencido = _respuesta(400, {"error": {"code": 190, "message": "Session has expired"}})
            with mock.patch.object(ads_library.requests, "get", return_value=vencido):
                ads2, estado2 = caido.obtener_nacional()
                self.assertEqual(len(ads2), 1)                                              # la copia se sirve al instante…
                self.assertTrue(estado2["actualizando"])
                caido._hilo.join(10)
                ads3, estado3 = caido.obtener_nacional()                                    # …y al fallar la renovación se marca como desactualizada
            self.assertEqual(len(ads3), 1)
            self.assertTrue(estado3["desactualizado"])
            self.assertIn("venció", estado3["aviso"])
            self.assertNotIn(SECRET, json.dumps(estado3))

    def test_sin_el_segundo_plano_el_token_vencido_sirve_la_copia_de_inmediato(self):
        import tempfile
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "snap.json")
            self._guardar_copia(ruta)
            caido = _cliente(AD_LIBRARY_SNAPSHOT=ruta, AD_LIBRARY_SEGUNDO_PLANO="false")
            vencido = _respuesta(400, {"error": {"code": 190, "message": "Session has expired"}})
            with mock.patch.object(ads_library.requests, "get", return_value=vencido):
                ads, estado = caido.obtener_nacional()
            self.assertEqual(len(ads), 1)
            self.assertTrue(estado["desactualizado"])
            self.assertIn("venció", estado["aviso"])

    def test_al_arrancar_se_sirve_la_copia_reciente_sin_llamar_a_meta(self):
        import tempfile
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "snap.json")
            self._guardar_copia(ruta)
            nuevo = _cliente(AD_LIBRARY_SNAPSHOT=ruta)
            with mock.patch.object(ads_library.requests, "get") as get:
                ads, estado = nuevo.obtener_nacional()
            get.assert_not_called()                                                         # la copia aún no caducó: ni una consulta a Meta
            self.assertEqual(len(ads), 1)
            self.assertTrue(estado["desde_copia"])

    def test_una_copia_de_otros_terminos_o_de_otro_periodo_no_se_usa(self):
        import tempfile
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "snap.json")
            self._guardar_copia(ruta)
            for env in ({"AD_LIBRARY_TERMS": "otra"}, {"AD_LIBRARY_DAYS": "30"}):
                otro = _cliente(AD_LIBRARY_SNAPSHOT=ruta, **env)
                with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": []})) as get:
                    otro.obtener_nacional()
                self.assertTrue(get.called, env)                                            # descarga en vez de servir datos de otra configuración

    def test_sin_copia_y_con_token_vencido_devuelve_mensaje_claro(self):
        import tempfile
        with tempfile.TemporaryDirectory() as carpeta:
            cliente = _cliente(AD_LIBRARY_SNAPSHOT=os.path.join(carpeta, "no_existe.json"))
            vencido = _respuesta(400, {"error": {"code": 190, "message": "Session has expired"}})
            with mock.patch.object(ads_library.requests, "get", return_value=vencido):
                ads, estado = cliente.obtener_nacional()
            self.assertEqual(ads, [])
            self.assertIn("venció", estado["mensaje"])



class InterruptorTests(unittest.TestCase):
    def test_apagado_por_defecto_aunque_haya_token(self):
        with mock.patch.dict(os.environ, {"META_AD_LIBRARY_TOKEN": SECRET, "META_INTEGRATION_ENABLED": "false",
                                          "AD_LIBRARY_SNAPSHOT": os.path.join(tempfile.mkdtemp(prefix="noai_test_"), "s.json")}):
            cliente = AdLibraryClient()
        with mock.patch.object(ads_library.requests, "get") as get:
            ads, estado = cliente.obtener_nacional()
        get.assert_not_called()
        self.assertEqual(ads, [])
        self.assertFalse(estado["habilitado"])
        self.assertFalse(cliente.configurado)
        self.assertNotIn(SECRET, json.dumps(estado))

    def test_el_token_del_entorno_local_tiene_prioridad_sobre_firebase(self):
        with mock.patch.dict(os.environ, {"META_AD_LIBRARY_TOKEN": "local-token", "META_INTEGRATION_ENABLED": "true"}):
            with mock.patch.object(ads_library.firebase_store, "get_api_keys", return_value={"META_AD_LIBRARY_TOKEN": "firebase-token"}):
                cliente = AdLibraryClient()
        self.assertEqual(cliente.token, "local-token")

    def test_sin_entorno_usa_el_token_de_firebase_y_su_interruptor(self):
        claves = {"META_AD_LIBRARY_TOKEN": "firebase-token", "FB_META_API_ENABLED": "true"}
        with mock.patch.dict(os.environ, {"META_AD_LIBRARY_TOKEN": "", "META_INTEGRATION_ENABLED": ""}):
            with mock.patch.object(ads_library.firebase_store, "get_api_keys", return_value=claves):
                cliente = AdLibraryClient()
                self.assertEqual(cliente.token, "firebase-token")
                self.assertTrue(cliente.habilitado)

    def test_firebase_se_consulta_con_pausa_no_en_cada_peticion(self):
        with mock.patch.dict(os.environ, {"META_AD_LIBRARY_TOKEN": "", "META_INTEGRATION_ENABLED": "true"}):
            with mock.patch.object(ads_library.firebase_store, "get_api_keys", return_value={}) as g:
                cliente = AdLibraryClient()
                for _ in range(5):
                    cliente.reload_token()
                    _ = cliente.habilitado
        self.assertEqual(g.call_count, 1)


class AnunciosTests(unittest.TestCase):
    """Detalle completo de un nodo de la red o de una entidad: los totales deben coincidir con los del grafo."""

    def _datos(self):
        return [
            # Alfa Noticias (Guayas): un anuncio pagado por ella misma y otro por una agencia
            _anuncio("1", [("Guayas", "1.0")], page_id="10", page_name="Alfa Noticias", bylines="Alfa Noticias", ad_delivery_start_time="2026-10-01"),
            _anuncio("2", [("Guayas", "1.0")], page_id="10", page_name="Alfa Noticias", bylines="Agencia Z", ad_delivery_start_time="2026-10-05",
                     spend={"lower_bound": "500", "upper_bound": "999"}),
            # Beta Noticias (Guayas, algo en Azuay), pagada por la misma agencia
            _anuncio("3", [("Guayas", "0.9"), ("Azuay", "0.1")], page_id="20", page_name="Beta Noticias", bylines="Agencia Z", ad_delivery_start_time="2026-10-09"),
            # Gamma Noticias (Azuay), otro pagador
            _anuncio("4", [("Azuay", "1.0")], page_id="30", page_name="Gamma Noticias", bylines="Movimiento Q", ad_delivery_start_time="2026-10-03"),
            _anuncio("5", [("Guayas", "1.0")], page_id="40", page_name="Consejo Nacional Electoral del Ecuador", bylines="", ad_delivery_start_time="2026-10-02"),
        ]

    def _llamar(self, metodo, *args, **kwargs):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos()})):
            return getattr(cliente, metodo)(*args, **kwargs)

    def test_por_pagina_devuelve_todos_sus_anuncios_del_mas_reciente_al_mas_antiguo_y_pagina(self):
        r = self._llamar("anuncios", pagina="Alfa Noticias")
        self.assertEqual(r["total"], 2)
        self.assertEqual([a["id"] for a in r["anuncios"]], ["2", "1"])
        self.assertEqual(r["resumen"]["anuncios"], 2)
        self.assertEqual(r["resumen"]["gasto"]["max"], 999 + 499)
        sig = self._llamar("anuncios", pagina="Alfa Noticias", desde=1, limite=1)
        self.assertEqual([a["id"] for a in sig["anuncios"]], ["1"])
        self.assertEqual(sig["total"], 2)

    def test_el_orden_por_inversion_pone_primero_el_mas_caro(self):
        r = self._llamar("anuncios", pagina="Alfa Noticias", orden="inversion")
        self.assertEqual(r["anuncios"][0]["id"], "2")

    def test_por_pagador_con_solo_terceros_excluye_lo_que_paga_la_propia_pagina(self):
        self.assertEqual(self._llamar("anuncios", pagador="Agencia Z", solo_terceros=True)["total"], 2)
        self.assertEqual(self._llamar("anuncios", pagador="Alfa Noticias")["total"], 1)
        self.assertEqual(self._llamar("anuncios", pagador="Alfa Noticias", solo_terceros=True)["total"], 0)

    def test_total_por_provincia_coincide_con_el_nodo_del_grafo(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos()})):
            grafo = cliente.red_pagadores(None, limite=10)["grafo"]
            for nodo in [n for n in grafo["nodos"] if n["tipo"] == "provincia"]:
                lista = cliente.anuncios(region=nodo["nombre"])
                self.assertEqual(lista["total"], nodo["anuncios"], nodo["nombre"])
            # y por pagador / página, igual que el nodo
            for nodo in [n for n in grafo["nodos"] if n["tipo"] == "pagador"]:
                self.assertEqual(cliente.anuncios(pagador=nodo["nombre"], solo_terceros=True)["total"], nodo["anuncios"], nodo["nombre"])
            for nodo in [n for n in grafo["nodos"] if n["tipo"] == "pagina"]:
                self.assertEqual(cliente.anuncios(pagina=nodo["nombre"])["total"], nodo["anuncios"], nodo["nombre"])

    def test_entidad_incluye_lo_que_publica_y_lo_que_paga_con_su_rol(self):
        r = self._llamar("anuncios", entidad="Agencia Z")
        self.assertEqual({a["id"]: a["rol"] for a in r["anuncios"]}, {"2": "pagador", "3": "pagador"})
        r = self._llamar("anuncios", entidad="Alfa Noticias")
        self.assertEqual({a["id"]: a["rol"] for a in r["anuncios"]}, {"1": "ambos", "2": "pagina"})
        r = self._llamar("anuncios", entidad="Algo", page_id="30")      # por page_id aunque el nombre no coincida
        self.assertEqual([a["id"] for a in r["anuncios"]], ["4"])

    def test_el_alcance_recorta_como_el_resto_de_la_api(self):
        r = self._llamar("anuncios", alcance="Azuay", pagina="Beta Noticias")
        self.assertEqual(r["total"], 1)
        self.assertAlmostEqual(r["anuncios"][0]["porcentaje_provincia"], 0.1)
        self.assertEqual(self._llamar("anuncios", alcance="Azuay", pagina="Alfa Noticias")["total"], 0)

    def test_sin_filtros_se_rechaza(self):
        with self.assertRaises(ValueError):
            self._llamar("anuncios")

    def test_sin_cne_quita_los_anuncios_de_la_autoridad_electoral(self):
        self.assertEqual(self._llamar("anuncios", pagina="Consejo Nacional Electoral del Ecuador")["total"], 1)
        self.assertEqual(self._llamar("anuncios", pagina="Consejo Nacional Electoral del Ecuador", sin_cne=True)["total"], 0)

    def test_la_respuesta_no_trae_el_token_ni_datos_pesados(self):
        r = self._llamar("anuncios", pagina="Alfa Noticias")
        self.assertNotIn(SECRET, json.dumps(r))
        for a in r["anuncios"]:
            self.assertNotIn("demografia", a)
            self.assertNotIn("regiones", a)
            self.assertTrue(a["link"].endswith("?id=" + a["id"]))
            self.assertEqual(a["region_principal"]["region"], "Guayas")


class UnaDefinicionTests(unittest.TestCase):
    """«Llega a la provincia» (al menos el 5 % del alcance) se cuenta igual en el mapa, el resumen, la comparación y las listas."""

    def _datos(self):
        # Inversión media de cada anuncio: 299,5 (rango por defecto de _anuncio); impresiones medias: 30 000.
        return [
            _anuncio("1", [("Guayas", "1.0")], page_id="10", page_name="Alfa Noticias", bylines="Alfa Noticias"),
            _anuncio("2", [("Guayas", "0.5"), ("Azuay", "0.5")], page_id="10", page_name="Alfa Noticias", bylines="Agencia Z"),
            _anuncio("3", [("Guayas", "0.04"), ("Azuay", "0.96")], page_id="20", page_name="Beta Noticias", bylines="Agencia Z"),   # 4 %: no llega
            _anuncio("4", [("Guayas", "0.06"), ("Azuay", "0.94")], page_id="20", page_name="Beta Noticias", bylines="Agencia Z"),
            _anuncio("5", [("Azuay", "1.0")], page_id="30", page_name="Gamma Noticias", bylines="Movimiento Q"),
            _anuncio("6", [("Guayas", "0.3"), ("Madrid", "0.7")], page_id="40", page_name="Delta Noticias", bylines="Delta Noticias"),
        ]

    def _llamar(self, datos, metodo, *args, **kwargs):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            return getattr(cliente, metodo)(*args, **kwargs)

    def test_el_mismo_anuncio_cuenta_igual_en_mapa_resumen_comparacion_y_lista(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos()})):
            burbuja = {p["provincia"]: p for p in cliente.metricas_por_provincia()["provincias"]}["Guayas"]
            kpis = cliente.top_gastadores("Guayas", 50)["resumen"]
            lista = cliente.anuncios(alcance="Guayas")
            _, estado = cliente.por_provincia("Guayas")
            comparacion = cliente.comparar(["Guayas", None])["columnas"][0]["resumen"]
        # Llegan a Guayas los anuncios 1, 2, 4 y 6 (el 3 solo tiene un 4 %): 4 anuncios de 3 páginas distintas.
        self.assertEqual((burbuja["anuncios"], burbuja["anunciantes"]), (4, 3))
        self.assertEqual((kpis["anuncios"], kpis["anunciantes"]), (4, 3))
        self.assertEqual((comparacion["anuncios"], comparacion["anunciantes"]), (4, 3))
        self.assertEqual((lista["total"], lista["resumen"]["paginas"]), (4, 3))
        self.assertEqual(estado["total_provincia"], 4)
        # Importes prorrateados por el % de alcance: 299,5 × (1 + 0,5 + 0,06 + 0,3) = 557,07; impresiones 30 000 × 1,86 = 55 800.
        self.assertEqual(burbuja["gasto"], 557)
        self.assertEqual(kpis["gasto_medio_total"], 557)
        self.assertEqual(lista["resumen"]["gasto_prorrateado"]["medio"], 557)
        self.assertEqual(burbuja["impresiones"], 55800)
        self.assertEqual(kpis["impresiones_medias_total"], 55800)
        self.assertEqual(lista["resumen"]["impresiones_prorrateadas"]["medio"], 55800)
        # La lista trae además el precio completo de esos anuncios, sin prorratear: 4 × 299,5.
        self.assertEqual(lista["resumen"]["gasto"]["medio"], 1198)

    def test_una_provincia_con_repartos_minimos_no_aparece_en_el_mapa(self):
        datos = [_anuncio("1", [("Guayas", "0.97"), ("Azuay", "0.03")], page_id="10", page_name="Alfa Noticias")]
        provincias = {p["provincia"] for p in self._llamar(datos, "metricas_por_provincia")["provincias"]}
        self.assertEqual(provincias, {"Guayas"})

    def test_la_lista_de_una_provincia_no_necesita_otro_filtro_y_trae_el_porcentaje_de_cada_anuncio(self):
        r = self._llamar(self._datos(), "anuncios", alcance="Guayas", orden="impresiones")
        self.assertEqual(r["total"], 4)
        self.assertEqual({a["id"]: round(a["porcentaje_provincia"], 2) for a in r["anuncios"]}, {"1": 1.0, "2": 0.5, "4": 0.06, "6": 0.3})
        with self.assertRaises(ValueError):       # «todo el país» sin otro filtro sigue sin ser una consulta válida
            self._llamar(self._datos(), "anuncios", alcance="todas")

    def test_el_periodo_deja_los_activos_y_los_que_terminaron_hace_poco(self):
        def hace(dias):
            return (date.today() - timedelta(days=dias)).isoformat()
        datos = [
            _anuncio("a", [("Guayas", "1.0")], page_id="1", page_name="Uno", ad_delivery_start_time=hace(200), ad_delivery_stop_time=hace(190)),   # viejo y terminado
            _anuncio("b", [("Guayas", "1.0")], page_id="2", page_name="Dos", ad_delivery_start_time=hace(200)),                                     # sin fin: sigue activo
            _anuncio("c", [("Guayas", "1.0")], page_id="3", page_name="Tres", ad_delivery_start_time=hace(40), ad_delivery_stop_time=hace(5)),      # terminó hace 5 días
            _anuncio("d", [("Guayas", "1.0")], page_id="4", page_name="Cuatro", ad_delivery_start_time=hace(40), ad_delivery_stop_time=hace(35)),   # terminó hace 35 días
        ]
        todos = {a["id"] for a in self._llamar(datos, "anuncios", alcance="Guayas", limite=100)["anuncios"]}
        ultimos_30 = self._llamar(datos, "anuncios", alcance="Guayas", dias=30, limite=100)
        self.assertEqual(todos, {"a", "b", "c", "d"})
        self.assertEqual({a["id"] for a in ultimos_30["anuncios"]}, {"b", "c"})
        self.assertEqual(ultimos_30["total"], 2)

    def test_el_sol_de_la_red_suma_todas_las_paginas_con_base_aunque_el_grafo_dibuje_menos(self):
        datos = [
            _anuncio("1", [("Guayas", "1.0")], page_id="10", page_name="Alfa Noticias", bylines="Alfa Noticias"),
            _anuncio("2", [("Guayas", "1.0")], page_id="10", page_name="Alfa Noticias", bylines="Agencia Z"),
            _anuncio("3", [("Guayas", "0.9"), ("Azuay", "0.1")], page_id="20", page_name="Beta Noticias", bylines="Agencia Z"),
            _anuncio("4", [("Azuay", "1.0")], page_id="30", page_name="Gamma Noticias", bylines="Movimiento Q"),
            _anuncio("5", [("Guayas", "1.0")], page_id="40", page_name="Radio Delta", bylines="Radio Delta"),    # sin pagador tercero: el grafo recortado no la dibuja
        ]
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": datos})):
            grafo = cliente.red_pagadores(None, limite=10, max_paginas=0)["grafo"]
            sol = next(n for n in grafo["nodos"] if n["tipo"] == "provincia" and n["nombre"] == "Guayas")
            lista = cliente.anuncios(region="Guayas")
        self.assertEqual((sol["paginas"], sol["anuncios"]), (2, 3))                  # lo dibujado: Alfa y Beta
        self.assertEqual((sol["paginas_total"], sol["anuncios_total"]), (3, 4))      # con Radio Delta, que el gráfico dejó fuera
        self.assertEqual(sol["anuncios_total"], lista["total"])                      # y es lo mismo que lista el detalle del sol
        self.assertEqual(sol["gasto_total"]["medio"], 1198)                          # 4 × 299,5


class DescargaCompletaTests(unittest.TestCase):
    """La descarga trae TODOS los anuncios de cada término (páginas grandes hasta agotar los resultados), reintenta y se renueva sin bloquear."""

    def _datos(self, desde, hasta, **extra):
        return [_anuncio(str(i), [("Guayas", "1.0")], page_id=str(1000 + i), page_name=f"Página {i}", **extra) for i in range(desde, hasta)]

    def test_sigue_las_paginas_hasta_que_se_acaban_y_pide_paginas_grandes(self):
        cliente = _cliente(AD_LIBRARY_PAGES="20", AD_LIBRARY_LIMIT="500")
        paginas = [_respuesta(200, {"data": self._datos(0, 500), "paging": {"cursors": {"after": "C1"}, "next": "https://x"}}),
                   _respuesta(200, {"data": self._datos(500, 845), "paging": {"cursors": {"after": "C2"}, "next": "https://x"}}),
                   _respuesta(200, {"data": [], "paging": {"cursors": {"after": "C3"}, "next": "https://x"}})]      # Meta a veces deja un cursor tras la última página
        with mock.patch.object(ads_library.requests, "get", side_effect=paginas) as get:
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(len(ads), 845)                                                         # no 100 como antes: todos los anuncios del término
        self.assertEqual(get.call_count, 3)                                                     # y se detiene en la primera página vacía
        self.assertEqual([c.kwargs["params"]["limit"] for c in get.call_args_list], [500, 500, 500])
        self.assertEqual([c.kwargs["params"].get("after") for c in get.call_args_list], [None, "C1", "C2"])
        self.assertEqual(estado["por_termino"], {"elecciones": 845})
        self.assertNotIn("parcial", estado)                                                     # se agotaron los resultados: no hay nada que avisar

    def test_si_se_agota_el_tope_de_paginas_avisa_de_que_es_parcial(self):
        cliente = _cliente(AD_LIBRARY_PAGES="2", AD_LIBRARY_LIMIT="100")
        paginas = [_respuesta(200, {"data": self._datos(i * 100, i * 100 + 100), "paging": {"cursors": {"after": f"C{i}"}, "next": "https://x"}}) for i in range(2)]
        with mock.patch.object(ads_library.requests, "get", side_effect=paginas):
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(len(ads), 200)
        self.assertEqual((estado["parcial"], estado["terminos_truncados"]), (True, ["elecciones"]))

    def test_una_pagina_demasiado_pesada_se_reintenta_con_la_mitad_y_el_mismo_cursor(self):
        cliente = _cliente(AD_LIBRARY_PAGES="3", AD_LIBRARY_LIMIT="500")
        pesada = _respuesta(400, {"error": {"code": 1, "message": "Please reduce the amount of data you're asking for, then retry your request"}})
        buena = _respuesta(200, {"data": self._datos(0, 10), "paging": {"cursors": {"after": "C1"}, "next": "https://x"}})
        ultima = _respuesta(200, {"data": self._datos(10, 15)})
        with mock.patch.object(ads_library.requests, "get", side_effect=[buena, pesada, ultima]) as get:
            ads, _ = cliente.obtener_nacional()
        self.assertEqual(len(ads), 15)
        pedidos = [(c.kwargs["params"]["limit"], c.kwargs["params"].get("after")) for c in get.call_args_list]
        self.assertEqual(pedidos, [(500, None), (500, "C1"), (250, "C1")])                      # la segunda página falló: se pide de 250 desde el mismo cursor

    def test_tras_una_pagina_pesada_el_tamano_vuelve_a_subir(self):
        cliente = _cliente(AD_LIBRARY_PAGES="6", AD_LIBRARY_LIMIT="400")
        pesada = _respuesta(500, {"error": {"code": 2, "message": "Service temporarily unavailable"}})
        def buena(desde, hasta, final=False):
            cuerpo = {"data": self._datos(desde, hasta)}
            if not final:
                cuerpo["paging"] = {"cursors": {"after": f"C{desde}"}, "next": "https://x"}
            return _respuesta(200, cuerpo)
        respuestas = [pesada, pesada, buena(0, 10), buena(10, 20), buena(20, 30), buena(30, 40, final=True)]
        with mock.patch.object(ads_library.requests, "get", side_effect=respuestas) as get:
            ads, _ = cliente.obtener_nacional()
        self.assertEqual(len(ads), 40)
        limites = [c.kwargs["params"]["limit"] for c in get.call_args_list]
        self.assertEqual(limites, [400, 200, 100, 200, 400, 400])                               # baja a 100 y recupera el tamaño normal en dos páginas

    def test_si_meta_limita_el_ritmo_espera_y_reintenta(self):
        cliente = _cliente()
        limite = _respuesta(400, {"error": {"code": 613, "message": "Calls to this api have exceeded the rate limit."}})
        buena = _respuesta(200, {"data": self._datos(0, 3)})
        with mock.patch.object(ads_library.requests, "get", side_effect=[limite, buena]) as get, mock.patch.object(ads_library.time, "sleep") as dormir:
            ads, _ = cliente.obtener_nacional()
        self.assertEqual(len(ads), 3)
        self.assertEqual(get.call_count, 2)
        dormir.assert_called_once()                                                             # hubo una pausa antes de reintentar

    def _caducar(self, cliente):
        cliente._cache["ts"] -= 10 ** 6

    def test_con_la_cache_caducada_se_sirven_los_datos_y_se_renuevan_en_segundo_plano(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos(0, 1)})):
            ads, _ = cliente.obtener_nacional()
            self.assertEqual(len(ads), 1)
            self._caducar(cliente)
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos(0, 3)})):
            ads, estado = cliente.obtener_nacional()                                            # no espera a la descarga: devuelve lo que había
            self.assertEqual(len(ads), 1)
            self.assertTrue(estado["actualizando"])
            cliente._hilo.join(10)
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(len(ads), 3)
        self.assertNotIn("actualizando", estado)

    def test_si_se_apaga_el_segundo_plano_la_renovacion_es_inmediata(self):
        cliente = _cliente(AD_LIBRARY_SEGUNDO_PLANO="false")
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos(0, 1)})):
            cliente.obtener_nacional()
            self._caducar(cliente)
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos(0, 2)})):
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(len(ads), 2)
        self.assertNotIn("actualizando", estado)

    def test_una_renovacion_fallida_conserva_los_datos_y_avisa(self):
        cliente = _cliente()
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos(0, 4)})):
            cliente.obtener_nacional()
            self._caducar(cliente)
        vencido = _respuesta(400, {"error": {"code": 190, "message": "Session has expired"}})
        with mock.patch.object(ads_library.requests, "get", return_value=vencido):
            cliente.obtener_nacional()
            cliente._hilo.join(10)
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(len(ads), 4)                                                           # los datos buenos siguen ahí
        self.assertTrue(estado["desactualizado"])
        self.assertIn("venció", estado["aviso"])
        self.assertNotIn(SECRET, json.dumps(estado))

    def test_una_renovacion_parcial_que_recorta_el_conjunto_no_lo_pisa(self):
        cliente = _cliente(AD_LIBRARY_TERMS="uno,dos")
        with mock.patch.object(ads_library.requests, "get", return_value=_respuesta(200, {"data": self._datos(0, 10)})):
            self.assertEqual(len(cliente.obtener_nacional()[0]), 10)
            self._caducar(cliente)

        def por_termino(url, params=None, timeout=None):
            if params["search_terms"] == "dos":
                return _respuesta(500, {"error": {"code": 2, "message": "Service temporarily unavailable"}})
            return _respuesta(200, {"data": self._datos(0, 3)})
        with mock.patch.object(ads_library.requests, "get", side_effect=por_termino):
            cliente.obtener_nacional()
            cliente._hilo.join(10)
            ads, estado = cliente.obtener_nacional()
        self.assertEqual(len(ads), 10)                                                          # 3 de 10 con un término caído: no se cambia un conjunto mayor por uno recortado
        self.assertTrue(estado["desactualizado"])


if __name__ == "__main__":
    unittest.main()
