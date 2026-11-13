"""
Genera docs/Guia-NoAIVerdad-Beta-v<versión>.pdf (guía del probador: instalación y uso).

Solo la usa quien arma el paquete; los probadores reciben el PDF ya hecho.
Requiere:  pip install reportlab pillow
Las capturas van en beta/guia/img/ (01_tutorial.jpg, 02_mapa.jpg, ...). Si falta alguna, se omite con un aviso.

Uso:  python beta/guia/build_guia.py
"""
import os
import sys
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, ListFlowable, ListItem, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

AQUI = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(AQUI, "img")
with open(os.path.join(os.path.dirname(AQUI), "VERSION"), encoding="utf-8") as _v:
    VERSION = _v.read().strip()
SALIDA = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "docs", f"Guia-NoAIVerdad-Beta-v{VERSION}.pdf")

# Tipografías de Windows (con tildes, ñ y signos); si no existen se usa Helvetica
FUENTES = "C:/Windows/Fonts"
try:
    pdfmetrics.registerFont(TTFont("Cal", os.path.join(FUENTES, "calibri.ttf")))
    pdfmetrics.registerFont(TTFont("Cal-B", os.path.join(FUENTES, "calibrib.ttf")))
    pdfmetrics.registerFont(TTFont("Cal-I", os.path.join(FUENTES, "calibrii.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", os.path.join(FUENTES, "consola.ttf")))
    pdfmetrics.registerFontFamily("Cal", normal="Cal", bold="Cal-B", italic="Cal-I", boldItalic="Cal-B")
    F, FB, FM = "Cal", "Cal-B", "Mono"
except Exception:  # noqa: BLE001
    F, FB, FM = "Helvetica", "Helvetica-Bold", "Courier"

NAVY, ACENTO, GRIS, CLARO = colors.HexColor("#14213d"), colors.HexColor("#5b5fef"), colors.HexColor("#475569"), colors.HexColor("#eef0fb")
AMARILLO, AMARILLO_F = colors.HexColor("#b7791f"), colors.HexColor("#fff7e0")

S = {
    "cuerpo": ParagraphStyle("cuerpo", fontName=F, fontSize=10.5, leading=15, textColor=colors.HexColor("#1e293b"), spaceAfter=6, alignment=TA_LEFT),
    "peq": ParagraphStyle("peq", fontName=F, fontSize=9, leading=12, textColor=GRIS, spaceAfter=4),
    "h1": ParagraphStyle("h1", fontName=FB, fontSize=18, leading=22, textColor=NAVY, spaceBefore=6, spaceAfter=8, keepWithNext=1),
    "h2": ParagraphStyle("h2", fontName=FB, fontSize=13, leading=17, textColor=ACENTO, spaceBefore=10, spaceAfter=4, keepWithNext=1),
    "pie": ParagraphStyle("pie", fontName=F, fontSize=8.5, textColor=GRIS),
    "cod": ParagraphStyle("cod", fontName=FM, fontSize=9, leading=12, textColor=colors.HexColor("#0f172a")),
    "leyenda": ParagraphStyle("leyenda", fontName=F, fontSize=8.5, leading=11, textColor=GRIS, alignment=1, spaceAfter=10),
    "portada1": ParagraphStyle("p1", fontName=FB, fontSize=34, leading=38, textColor=colors.white),
    "portada2": ParagraphStyle("p2", fontName=F, fontSize=15, leading=20, textColor=colors.HexColor("#c7d2fe")),
}


def P(texto, estilo="cuerpo"):
    return Paragraph(texto, S[estilo])


def lista(items, estilo="cuerpo"):
    return ListFlowable([ListItem(P(i, estilo), leftIndent=12) for i in items], bulletType="bullet", start="•", leftIndent=14, bulletFontName=F)


def pasos(items):
    return ListFlowable([ListItem(P(i), leftIndent=14) for i in items], bulletType="1", leftIndent=16, bulletFontName=FB)


def caja(titulo, texto, color=ACENTO, fondo=CLARO):
    t = Table([[P(f"<b>{titulo}</b><br/>{texto}")]], colWidths=[16.6 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fondo), ("LINEBEFORE", (0, 0), (0, -1), 3, color),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return [t, Spacer(1, 8)]


def codigo(texto):
    t = Table([[Paragraph(texto.replace("\n", "<br/>").replace(" ", "&nbsp;"), S["cod"])]], colWidths=[16.6 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return [t, Spacer(1, 8)]


def captura(archivo, leyenda, ancho=13.2 * cm):
    ruta = os.path.join(IMG, archivo)
    if not os.path.exists(ruta):
        print(f"AVISO: falta la captura {archivo}; se omite.")
        return []
    w, h = ImageReader(ruta).getSize()
    img = Image(ruta, width=ancho, height=ancho * h / w)
    marco = Table([[img]], colWidths=[ancho + 0.2 * cm])
    marco.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#94a3b8")), ("LEFTPADDING", (0, 0), (-1, -1), 1),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return [KeepTogether([marco, Spacer(1, 3), P(leyenda, "leyenda")])]


def tabla(filas, anchos, cabecera=True):
    datos = [[P(c) if not isinstance(c, str) or True else c for c in fila] for fila in filas]
    t = Table(datos, colWidths=anchos, repeatRows=1 if cabecera else 0)
    est = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    if cabecera:
        est += [("BACKGROUND", (0, 0), (-1, 0), CLARO)]
    t.setStyle(TableStyle(est))
    return [t, Spacer(1, 8)]


def portada(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)
    canvas.setFillColor(ACENTO)
    canvas.rect(0, h * 0.60, w, 5, stroke=0, fill=1)
    canvas.restoreState()


def pagina(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 1.1 * cm, w, 1.1 * cm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont(FB, 9)
    canvas.drawString(2 * cm, h - 0.72 * cm, "NoAIVerdad · versión beta")
    canvas.setFont(F, 9)
    canvas.drawRightString(w - 2 * cm, h - 0.72 * cm, "Guía del probador")
    canvas.setFillColor(GRIS)
    canvas.setFont(F, 8.5)
    canvas.drawString(2 * cm, 1.1 * cm, "Esta guía acompaña el paquete de la beta. No la compartas fuera del grupo de prueba.")
    canvas.drawRightString(w - 2 * cm, 1.1 * cm, f"Página {doc.page}")
    canvas.restoreState()


def contenido():
    c = []
    # ------------------------------------------------------------ 1
    c += [P("1. Qué es NoAIVerdad", "h1"),
          P("NoAIVerdad es una herramienta cívica para periodistas y verificadores. Muestra <b>quién paga anuncios políticos en Meta (Facebook e Instagram) en Ecuador</b>, "
            "cuánto (en rangos), dónde llegan y qué páginas se parecen entre sí: comparten pagador, publican textos casi idénticos o usan el mismo enlace. "
            "También reúne prensa, verificaciones y publicaciones sociales por provincia."),
          *caja("Lo que NoAIVerdad NO hace", "No decide qué es verdad ni acusa a nadie. Entrega <b>pistas para investigar</b>. Cada pista debe contrastarse con otras fuentes antes de publicarse."),
          P("Esta es una <b>versión beta</b>: puede tener errores y cambiará según lo que ustedes encuentren. Sus comentarios son el objetivo de esta prueba.")]
    # ------------------------------------------------------------ 2
    c += [P("2. Qué recibes", "h1"),
          P(f"Un solo archivo <b>NoAIVerdad-Beta-v{VERSION}.zip</b>. Al descomprimirlo verás:"),
          *tabla([["<b>Elemento</b>", "<b>Para qué sirve</b>"],
                  ["INICIAR NoAIVerdad.bat", "<b>El archivo que debes abrir.</b> Prepara todo y abre la herramienta en tu navegador."],
                  ["INICIAR NoAIVerdad (red local).bat", "Lo mismo, pero además deja la herramienta disponible para otros dispositivos de tu misma red (celular, tableta). Ver «Usarlo desde el celular o la tableta»."],
                  [f"Guia-NoAIVerdad-Beta-v{VERSION}.pdf", "Esta guía."],
                  ["carpeta app", "La herramienta (programa, datos y claves). No necesitas abrirla."]], [6.8 * cm, 9.8 * cm])]
    # ------------------------------------------------------------ 3
    c += [P("3. Instalación paso a paso (Windows)", "h1"),
          P("<b>Requisitos:</b> Windows 10 u 11, conexión a internet, unos 500 MB libres y el navegador Chrome o Edge. Si el equipo no tiene Python (3.10 a 3.13), "
            "el instalador te ofrece instalarlo."),
          pasos(["<b>Descomprime el zip.</b> Clic derecho sobre el archivo → <i>Extraer todo…</i> → elige el Escritorio. No abras el programa desde dentro del zip.",
                 "<b>Abre «INICIAR NoAIVerdad.bat»</b> con doble clic. Si Windows muestra «Windows protegió su PC», pulsa <i>Más información</i> y luego <i>Ejecutar de todas formas</i> "
                 "(el archivo viene de tu equipo de trabajo; esto es normal con archivos descargados).",
                 "<b>Primera vez:</b> se abre una ventana negra que prepara la herramienta (de 1 a 3 minutos, con internet). Verás una <b>barra de progreso</b> con el porcentaje y el componente que se está descargando. No la cierres. Si no hay Python, escribe <b>S</b> cuando pregunte "
                 "para instalarlo, y vuelve a abrir el archivo al terminar.",
                 "<b>Se abre el navegador</b> con NoAIVerdad y un tutorial de bienvenida. La ventana negra debe quedar abierta mientras usas la herramienta.",
                 "<b>Para terminar,</b> cierra la ventana negra. Las siguientes veces arranca en pocos segundos."]),
          Spacer(1, 6),
          *caja("Si aparece un aviso de Meta", "Al arrancar, la ventana negra indica si se conectó a la Biblioteca de Anuncios de Meta. Si dice «AVISO», la herramienta abre igual, "
                "pero sin anuncios nuevos (por ejemplo, si el acceso venció). Avísanos.", AMARILLO, AMARILLO_F),
          KeepTogether([P("<b>Mac o Linux:</b> el paquete está pensado para Windows. Si lo necesitas en otro sistema, instala Python 3.12 y, desde la carpeta <i>app</i>, ejecuta:"),
                      *codigo("python3 -m venv .venv\n.venv/bin/pip install -r backend/requirements.txt\n.venv/bin/python launcher.py")]),
          P("Usarlo desde el celular o la tableta (red local)", "h2"),
          P("Si quieres abrir NoAIVerdad en otro dispositivo conectado a tu misma red WiFi, usa <b>«INICIAR NoAIVerdad (red local).bat»</b> en lugar del archivo normal:"),
          pasos(["Abre «INICIAR NoAIVerdad (red local).bat». Además de abrir el navegador en tu equipo, la ventana negra muestra una o más direcciones del tipo <font face='Mono'>http://192.168.1.25:3000/</font>.",
                 "Escribe esa dirección en el navegador del celular, la tableta u otro computador. Está pensado también para iPhone y iPad (Safari o Chrome), aunque todavía no se probó en equipos reales: si algo falla, avísanos. Entra sin pedir cuenta.",
                 "La primera vez, Windows pregunta si permite el acceso a Python: elige <i>Redes privadas</i> y pulsa <i>Permitir</i>."]),
          Spacer(1, 6),
          *caja("Solo lectura y redes de confianza", "Desde otro dispositivo la herramienta es de <b>solo lectura</b>: guardar afiliaciones solo funciona desde el propio equipo. "
                "Úsala solo en redes de confianza (tu casa, la oficina): cualquiera conectado a esa red podría abrir la dirección. Para dejar de compartirla, cierra la ventana negra.", AMARILLO, AMARILLO_F)]
    # ------------------------------------------------------------ 4
    c += [P("4. Primeros pasos: el tutorial integrado", "h1"),
          P("La primera vez que abres NoAIVerdad aparece un tutorial de 10 pasos. Puedes reabrirlo cuando quieras con el botón <b>?</b> de la barra superior. "
            "Resume lo que explica esta guía."),
          *captura("01_tutorial.jpg", "Figura 1. Tutorial de bienvenida (botón «?» de la barra superior para volver a verlo)."),
          P("NoAIVerdad se abre en <b>Conexiones</b>. La barra superior tiene: <b>Conexiones</b>, <b>Mapa</b>, <b>Comparar</b> y <b>Método</b>; a la derecha, el icono <b>Validar perfiles</b> (persona con visto), el botón <b>?</b> (tutorial), el calendario <b>Fechas</b>, los interruptores <b>Ocultar CNE</b> y <b>Solo activos</b>, el cambio de tema claro/oscuro e «Iniciar sesión» (opcional en la beta).")]
    # ------------------------------------------------------------ 5
    c += [P("5. Cómo usar la herramienta", "h1"),
          P("Conexiones: la red de pagadores", "h2"),
          P("<b>Conexiones</b> es la vista con la que se abre NoAIVerdad. Ocupa toda la pantalla con una red y empieza mostrando <b>todo el país</b>. Cada esfera es una página; las esferas grandes con nombre son provincias "
            "(«soles»): sus páginas giran a su alrededor. Cada rombo es un pagador y gira alrededor de la página que paga. El botón <b>Mapa</b> (abajo a la derecha) pone cada sol sobre su provincia, "
            "en la capital, encima del mapa de Ecuador; <b>Compacta</b> (en Filtros) los vuelve a agrupar."),
          *tabla([["<b>Línea o halo</b>", "<b>Qué significa</b>"],
                  ["Gris, continua", "Une cada página con la provincia donde llega más (la órbita también lo muestra)."],
                  ["Naranja", "El pagador declarado es distinto de la página (un tercero paga). Un halo naranja agrupa páginas que comparten pagador."],
                  ["Gris, punteada", "Dos páginas publican textos casi idénticos. La línea es tenue hasta que la seleccionas o activas su filtro; al pulsarla se leen, lado a lado, los dos anuncios, se encienden todas las páginas que repiten ese texto y el resto se atenúa. Un halo gris agrupa páginas que repiten un texto."],
                  ["Azul, punteada", "Dos páginas usan el mismo enlace en sus anuncios. Al pulsarla, el panel muestra el enlace y se encienden todas las páginas que lo usan. Un halo azul agrupa páginas que comparten un enlace."],
                  ["Fina, del color del partido", "Misma organización política: se une a la página del partido. Es sutil por defecto; se ilumina al elegir un partido en Filtros, al filtrar solo por «partido» o al seleccionar un nodo. Al pulsarla quedan encendidas solo las páginas de ese partido, como si filtraras por él."]], [4.2 * cm, 12.4 * cm]),
          P("El <b>tamaño</b> de la esfera es la inversión estimada. Con poco zoom solo se dibujan las páginas con más inversión; al acercarte aparecen más (las provincias pequeñas siempre se ven completas) "
            "y, al pasar el cursor por una zona, se muestran también las páginas ocultas más cercanas. Recuerda: son <b>pistas, no pruebas</b>; las agencias y los partidos pagan por terceros de forma legítima."),
          *captura("03_red.jpg", "Figura 2. Conexiones: la red ocupa toda la pantalla, con cada provincia («sol») sobre el mapa de Ecuador y la leyenda abierta; la barra superior abre los paneles."),
          P("Moverte por la red", "h2"),
          lista(["<b>Rueda del ratón</b> o pellizco con dos dedos: acercar y alejar.",
                 "<b>Arrastrar el fondo</b>: mover la vista. <b>Arrastrar un punto</b>: estirarlo (vuelve a su órbita al soltarlo). Si arrastras una <i>provincia</i>, se mueve todo su sistema; "
                 "«Reorganizar sistemas», en Filtros, lo devuelve a su sitio.",
                 "<b>Clic en un punto</b>: resalta sus conexiones y abre su detalle en el panel derecho, con la lista de <b>todos sus anuncios</b>. La vista se centra en la parte que el panel no tapa.",
                 "<b>Clic en una línea</b> de texto repetido, de mismo enlace o de partido: quedan encendidas esa línea y todas las que repiten lo mismo (o todas las del partido), "
                 "el resto de la red se atenúa y la vista se aleja o se acerca hasta encuadrar todas esas páginas. Un clic en el fondo vuelve a mostrar todo.",
                 "El panel derecho es <b>ajustable</b>: arrastra su borde izquierdo (o usa las flechas del teclado) para cambiar el ancho; doble clic lo devuelve al tamaño original. En el celular se ajusta el alto. "
                 "Su contenido (y el de la ventana Resumen) se reorganiza según el ancho: cifras en una o dos filas, más o menos columnas en las tablas.",
                 "Botón de ajuste (flechas) abajo a la derecha: encuadra todo. Tecla <b>Esc</b>: cierra paneles y quita la selección. "
                 "Botón <b>Leyenda</b> (abajo a la izquierda): pliega o despliega la leyenda; se recuerda tu elección. Botón <b>Galápagos</b>: te lleva a las islas.",
                 "Al recargar la página, el zoom y la selección se conservan."]),
          P("El detalle de una provincia", "h2"),
          P("Al hacer clic en una provincia, el panel derecho da <b>dos cuentas</b>, siempre nombradas: los anuncios que <b>llegan allí</b> (al menos el 5 % de su alcance cae en esa provincia; "
            "la inversión se reparte según ese porcentaje) y los de las páginas <b>con base allí</b> (las páginas cuya provincia principal es esa; es lo que agrupa cada sol, a precio completo). "
            "Un selector cambia la lista de anuncios entre ambas, y dos botones llevan a <i>Prensa y verificaciones</i> de esa provincia (en el Mapa) o a <i>Ver solo</i> esa provincia."),
          P("Cada lista de anuncios (de una provincia, una página, un pagador o una entidad) tiene <b>Descargar CSV</b>, que baja <b>solo lo que estás viendo</b> (hasta 5.000 anuncios, con el orden y el tipo elegidos), "
            "y cada anuncio tiene <b>Descargar este anuncio</b>. El archivo incluye el texto, el enlace a la Biblioteca de Meta, las fechas, el gasto, las impresiones y el alcance por provincia. "
            "En las listas de varias páginas, el selector <b>Tipo</b> separa candidatos y políticos, instituciones públicas, medios, agencias y empresas, y otros; lo que aún no está clasificado en Entidades va en «Sin clasificar»."),
          *captura("07_provincia.jpg", "Figura 3. Detalle de una provincia: «con base aquí» y «llegan aquí», enlaces a su prensa y selector de lista."),
          P("Filtros: elige qué quieres ver", "h2"),
          P("El botón <b>Filtros</b> abre un panel por la izquierda. Arriba tiene cuatro listas con casillas, como los filtros de un tablero de datos: <b>Provincia</b>, <b>Conector</b> "
            "(el tipo de conexión), <b>Partido</b> y <b>Entidad</b> (cada página o pagador). Al abrir la herramienta <b>todo está seleccionado</b>, así que se ve todo; "
            "lo que desmarcas <b>deja de dibujarse</b> en la red y sale también del Resumen y de las listas de Mensajes repetidos y Entidades."),
          lista(["<b>Seleccionar todo:</b> marca o desmarca la lista entera. Si escribiste algo en la búsqueda de esa lista, actúa solo sobre lo encontrado.",
                 "<b>solo:</b> aparece al pasar el cursor por una fila y deja seleccionada únicamente esa (por ejemplo, solo Pichincha, o solo «Texto repetido»).",
                 "<b>Conector</b> incluye «Sin otra conexión»: las páginas que solo están unidas a su provincia. Desmárcalo para ver únicamente las páginas con pagador distinto, enlace compartido, texto repetido o partido.",
                 "<b>Partido</b> lista los partidos con páginas verificadas y «Sin partido registrado». Al filtrar por partido los puntos toman el color de su partido y la leyenda muestra solo los que quedan; "
                 "la casilla «Incluir partidos sin verificar», más abajo, añade los que aún no tienen fuente confirmada.",
                 "Una página se ve si está seleccionada y también lo están su provincia, su partido y alguno de sus conectores. Un pagador se ve si queda a la vista alguna página a la que paga (su propio partido no cuenta).",
                 "El botón de la barra indica cuántas listas están filtrando («Filtros · 2») y <b>Quitar filtros</b> lo devuelve todo. Al cambiar el alcance (país o provincia) se vuelve a seleccionar todo."]),
          P("Debajo siguen las opciones de siempre: la disposición de los soles (sobre el mapa de Ecuador o compacta), "
            "búsqueda por nombre, color de los puntos, fecha y descarga de imagen o CSV (el CSV lleva solo lo que los filtros dejan ver). Estas opciones resaltan: lo que no coincide se atenúa."),
          *captura("04_filtros.jpg", "Figura 4. Panel de filtros con cuatro partidos seleccionados (ADN, PSC, CREO y RC): la red, la leyenda y las listas muestran solo sus páginas."),
          P("Más secciones de Conexiones", "h2"),
          lista(["<b>Resumen</b> (botón del extremo derecho de la barra): una <b>ventana flotante</b> con el ranking de <b>todos</b> los anunciantes por inversión estimada, «Copiar cita» y descarga CSV para tu nota. "
                 "Se mueve arrastrando su cabecera y cambia de tamaño desde sus bordes y esquinas inferiores (doble clic en la cabecera la devuelve a su sitio); puede quedar abierta a la vez que Mensajes repetidos o el detalle de una línea. "
                 "Los cuatro totales de arriba (anunciantes, anuncios, inversión estimada y parte del gasto en los 5 mayores) <b>se recalculan con lo seleccionado en Filtros y con lo que pulses en la red</b>: "
                 "una página, un pagador (las páginas que paga), una provincia (las páginas con base allí) o una línea de texto repetido, mismo enlace o partido (las páginas que deja encendidas). "
                 "Una línea de aviso lo indica y «Quitar selección» vuelve a todo. Se puede filtrar por <b>tipo de anunciante</b> y, al elegir una provincia, por «solo páginas con base aquí» "
                 "(las demás llegan a la provincia, pero su alcance principal está en otra); el CSV respeta esos filtros y dice si cada página tiene base en la provincia consultada.",
                 "<b>Mensajes repetidos:</b> anuncios con texto casi idéntico en páginas distintas. Mientras está abierto, las líneas grises punteadas de texto repetido se iluminan en la red. "
                 "Los grupos esperables (una misma organización, un partido y sus candidatos…) se marcan como revisados y dejan de contarse. Con filtros activos quedan los grupos que incluyen alguna página a la vista.",
                 "<b>Entidades:</b> personas, partidos y medios; aquí se editan las afiliaciones y, con «Ver anuncios», se listan todos los que publican o pagan.",
                 "<b>Buscar:</b> cuenta menciones de un término en prensa, verificaciones y anuncios.",
                 "<b>Icono de información (i):</b> fuente de los datos, fecha de actualización y cómo se calcula cada cifra.",
                 "El selector de la izquierda cambia el alcance: empieza con todo el país y puedes enfocar una provincia."]),
          *captura("05_anunciantes.jpg", "Figura 5. Ventana «Resumen» junto al panel de una línea de partido (ADN): los totales y el ranking cuentan solo las páginas encendidas en la red."),
          P("Mapa: noticias por provincia", "h2"),
          P("En <b>Mapa</b> cada punto es una provincia. Haz clic en uno (o elige la provincia en la lista) y se abre su panel con la <b>prensa</b>, la <b>prensa local</b> (notas electorales de los medios y portales de esa provincia), las <b>verificaciones</b> y las publicaciones de "
            "<b>Bluesky, YouTube y Reddit</b> de esa provincia, con filtro de período. Los anuncios no están aquí: se consultan en Conexiones. Sirve para contrastar lo que ves en la red con lo que dice la prensa local "
            "y los verificadores. El botón <i>Ir a Galápagos</i> lleva a las islas; X aparece como «pronto» porque todavía no está activo."),
          *captura("02_mapa.jpg", "Figura 6. Mapa: una provincia seleccionada y su panel de noticias (prensa y prensa local, verificaciones y publicaciones sociales)."),
          P("Tres filtros para todo el sitio", "h2"),
          P("Los anuncios de la autoridad electoral suelen encabezar el gasto y tapan al resto: el interruptor <b>Ocultar CNE</b> (arriba a la derecha) los quita. "
            "El interruptor <b>Solo activos</b> deja únicamente los anuncios que siguen circulando (sin fecha de fin): sirve para ver qué se está mostrando ahora y qué páginas siguen pagando; "
            "los terminados desaparecen de la red, las listas, las cifras y las descargas, y la información de la fuente (icono i) dice cuántos quedaron fuera."),
          P("El botón <b>Fechas</b> abre un calendario para quedarte con <b>un día</b> o con un <b>rango desde – hasta</b>: un clic elige un día; un segundo clic en otro día completa el rango. "
            "Hay atajos (Hoy, Últimos 7 días, Últimos 30 días); <b>Aplicar</b> lo activa y <b>Todo el período</b> lo quita. Quedan los anuncios que <b>circularon</b> algún día de ese rango "
            "(un anuncio sin fecha de fin cuenta para cualquier día posterior a su inicio). Solo se pueden elegir días de los últimos 120, que es lo que la herramienta tiene cargado."),
          *caja("Los montos no son por día", "Con fechas elegidas, la inversión y las impresiones siguen siendo las de <b>todo el anuncio</b>, no lo gastado en esos días: Meta no publica el gasto diario. "
                "Úsalo para saber <i>quién</i> anunciaba en esas fechas, no <i>cuánto</i> gastó en ellas.", AMARILLO, AMARILLO_F),
          *captura("09_calendario.jpg", "Figura 7. Calendario de la barra superior con un rango elegido (del 3 al 9 de noviembre), antes de pulsar «Aplicar»."),
          P("Los tres afectan a Conexiones y Comparar y se pueden combinar. Ocultar CNE y Solo activos se recuerdan; las fechas vuelven a «todo el período» al recargar la página."),
          P("Comparar y Método", "h2"),
          P("<b>Comparar</b> pone dos o tres provincias (o el total nacional) lado a lado. <b>Método</b> explica las fuentes, el calendario electoral y los límites de cada dato.")]
    # ------------------------------------------------------------ 6
    c += [P("6. Afiliación política: cómo se registra", "h1"),
          P("Meta no publica la afiliación política de las páginas. En NoAIVerdad se registra <b>a mano y solo con una fuente</b>:"),
          lista(["<b>Verificada</b> (etiqueta sólida): tiene afiliación y un enlace a la fuente que la respalda.", "<b>Sin verificar</b> (etiqueta punteada): es una propuesta; falta confirmar la fuente.",
                 "Una página sin registro no muestra etiqueta."]),
          P("Para editar, abre <b>Conexiones → Entidades</b>. Cada fila tiene tipo (persona, candidato, partido, institución, medio…), partido (nombre corto, p. ej. ADN), afiliación, fuente (enlace) y la casilla "
            "<b>Verificada</b>. Pulsa <b>Guardar</b>: el cambio se escribe en tu equipo y se refleja en todo el sitio. «Verificada» exige afiliación y enlace."),
          *captura("06_entidades.jpg", "Figura 8. Panel «Entidades»: edición de afiliaciones con guardado."),
          P("Validar perfiles desde cualquier pestaña", "h2"),
          P("El icono <b>Validar perfiles</b> (persona con visto, arriba a la derecha) abre una ficha flotante que se queda visible en cualquier pestaña. Busca una entidad por nombre, partido o id "
            "(o pulsa el icono de lápiz junto al nombre de un anuncio o de un nodo de la red) y edita su afiliación sin salir de lo que estabas mirando. Al guardar, la vista se actualiza sin perder el zoom ni la selección."),
          *captura("08_ficha.jpg", "Figura 9. Ficha «Validar perfiles» sobre la red: se busca la entidad y se edita partido, afiliación y fuente."),
          lista(["Si dos entradas son la misma persona (otra página, o el pagador con otro nombre), márcalas con su casilla (o con <b>Shift + clic</b> en el nombre) y pulsa <b>Unificar</b>.",
                 "Un <b>medio</b> que informa sin alinearse con un partido se marca con el partido <i>Neutral</i> (gris en la red); si está alineado, se escribe su partido.",
                 "Una línea punteada del color del partido une los <b>soles</b> (provincias) donde ese partido tiene candidatos."]),
          *caja("Reglas de prudencia", "Registra solo a <b>figuras públicas y organizaciones</b>, y solo lo que una fuente afirme de forma explícita. No deduzcas la afiliación por el nombre de la página ni por su contenido. "
                "Una entidad de tipo <i>partido</i> (por ejemplo, la página oficial) se convierte en el centro de su partido en la red.", AMARILLO, AMARILLO_F),
          P("Importante: lo que cada probador registra queda en <b>su</b> equipo. Para compartirlo, envía el archivo <font face='Mono'>app/backend/afiliaciones.json</font> al equipo.")]
    # ------------------------------------------------------------ 7
    c += [P("7. Cómo leer los números", "h1"),
          lista(["Meta publica la inversión y las impresiones como <b>rangos</b> (por ejemplo, USD 100 a 499). La cifra «estimada» es el punto medio.",
                 "Por provincia, cada anuncio cuenta en proporción a su alcance allí: es una <b>estimación</b>, no un dato reportado.",
                 "Una provincia se cuenta de dos maneras, siempre nombradas: los anuncios que <b>llegan a</b> la provincia (al menos el 5 % de su alcance; inversión repartida por ese porcentaje) "
                 "y las páginas <b>con base en</b> la provincia (su provincia principal; precio completo). Conexiones y Comparar usan la misma regla, así que sus cifras coinciden.",
                 "Los anuncios que Meta retiró (aparecen sin descargo de responsabilidad: por incumplir sus normas o de cuentas inhabilitadas) <b>no se cuentan ni se dibujan</b>; el icono de información (i) indica cuántos son.",
                 "Un texto repetido o un pagador compartido es un <b>indicador</b>, no una acusación. Hay explicaciones legítimas (un partido y sus candidatos, una agencia).",
                 "Con <b>Solo activos</b> las cifras cuentan únicamente los anuncios sin fecha de fin; la inversión y las impresiones son las de esos anuncios, no las acumuladas de la campaña.",
                 "Con <b>Fechas</b> elegidas cuentan los anuncios que circularon esos días, con sus montos completos (no los de esos días).",
                 "Con <b>Filtros</b> activos (o algo seleccionado en la red), los totales del Resumen suman las páginas seleccionadas a <b>precio completo</b>. Por eso «solo Pichincha» en Filtros (páginas con base allí) "
                 "no da la misma cifra que elegir Pichincha en el selector de alcance (anuncios que llegan allí, repartidos por su porcentaje).",
                 "Los datos se guardan en caché unos 30 minutos; cada vista indica la fecha de actualización."]),
          P("Flujo sugerido para una verificación", "h2"),
          pasos(["En <b>Conexiones</b>, activa <b>Ocultar CNE</b> y, si quieres, enfoca una provincia.", "Haz clic en una página sospechosa y lee su detalle: pagador, inversión, alcance, edades, texto.",
                 "Mira sus conexiones: ¿otro pagador, un texto repetido, un enlace compartido?", "Abre <b>Mensajes repetidos</b> y <b>Buscar</b> para ver si el mensaje circula en prensa o ya fue verificado.",
                 "Usa «Copiar cita» o el CSV para documentar, y contrasta con otras fuentes antes de publicar."])]
    # ------------------------------------------------------------ 8
    c += [P("8. Para quien administra el paquete", "h1"),
          P("Estructura de la carpeta", "h2"),
          *codigo("NoAIVerdad-Beta/\n  INICIAR NoAIVerdad.bat      (abre todo)\n  INICIAR NoAIVerdad (red local).bat   (igual, y abre la herramienta a tu red)\n  Guia-NoAIVerdad-Beta.pdf\n  app/\n"
                  "    launcher.py              (arranca servidor y navegador)\n    instalar.py              (instala los componentes con barra de progreso)\n"
                  "    backend/                 (datos y API; .env.local con las claves; medios_locales.json)\n"
                  "      data/ads_snapshot.json (última descarga de anuncios)\n      data/archivo/          (archivo histórico; se crea solo)\n    frontend/                (la página)"),
          P("Claves de API", "h2"),
          P("Las claves están en <font face='Mono'>app/backend/.env.local</font> (se leen al iniciar). Contiene: <b>META_AD_LIBRARY_TOKEN</b> (Biblioteca de Anuncios), <b>GNEWS_API_KEY</b> (prensa), "
            "<b>GOOGLE_FACT_CHECK_API_KEY</b> (verificaciones) y <b>X_BEARER_TOKEN</b> (sin uso: X está desactivado)."),
          *caja("Seguridad durante la beta", "Este paquete incluye claves de API reales. <b>No lo reenvíes fuera del grupo de prueba, no lo subas a internet ni a repositorios.</b> "
                "Al terminar la beta se deben revocar y reemplazar las claves. El token de Meta es de larga duración pero <b>vence unos 60 días después de generarse</b> "
                "(este paquete: hacia finales de diciembre de 2026); después hay que generar uno nuevo y pegarlo en .env.local.", colors.HexColor("#b91c1c"), colors.HexColor("#fdecec")),
          P(f"Novedades de la versión {VERSION}", "h2"),
          lista(["<b>Ventana Resumen:</b> el antiguo botón «Anunciantes» es ahora «Resumen», en el extremo derecho de la barra. Abre una ventana flotante que se mueve y cambia de tamaño "
                 "y puede quedar abierta junto al panel derecho (por ejemplo, con Mensajes repetidos o con el detalle de una línea).",
                 "<b>El Resumen sigue a la red:</b> al pulsar una página, un pagador, una provincia o una línea (texto repetido, mismo enlace o partido), sus totales, su lista y su CSV cuentan solo esas páginas.",
                 "<b>Paneles que se adaptan:</b> el contenido del Resumen y del panel derecho se reorganiza según su ancho.",
                 "<b>Texto repetido en gris:</b> sus líneas y halos son grises punteados para no confundirse con el color de ningún partido, y al abrir Mensajes repetidos brillan como las demás, sin deslumbrar.",
                 "<b>Colores de partido:</b> PSC en amarillo y CREO en azul.",
                 "<b>Barras de desplazamiento discretas:</b> finas, sin flechas ni carril.",
                 "<b>Datos del paquete:</b> la copia de anuncios incluida es la más reciente al construirlo; la herramienta la renueva cada hora mientras el acceso a Meta funcione."]),
          *captura("10_grupo_texto.jpg", "Figura 10. Una línea de texto repetido pulsada: quedan encendidas las páginas que repiten el texto y el panel compara los anuncios."),
          *captura("11_linea_partido.jpg", "Figura 11. Una línea de partido pulsada (ADN): solo sus páginas quedan encendidas y el panel las lista con su inversión estimada."),
          P("De la versión 1.1.0 se mantienen: las líneas de texto repetido, mismo enlace y partido pulsables, que encienden su grupo y atenúan el resto. "
            "De la 1.0.0: el calendario de fechas de la barra superior, Partido como filtro completo, la leyenda según lo visible y el archivo histórico exportable a SQLite o CSV. "
            "De la 0.6.0: los filtros de tablero por Provincia, Conector y Entidad, los totales de Anunciantes según lo seleccionado, la lista completa de anunciantes, "
            "el CSV de la red filtrado y el archivo histórico de anuncios. De la 0.5.0: instalación, modo red local, Mapa con prensa local, Solo activos, Ocultar CNE, descargas CSV, "
            "tipo de anunciante, Validar perfiles y las afiliaciones registradas (98 entradas)."),
          P("Archivo histórico de anuncios", "h2"),
          P("La herramienta consulta a Meta los anuncios de los <b>últimos 120 días</b>. Ese límite es de la herramienta, no de Meta (que conserva los anuncios políticos varios años), "
            "pero lo que sale de esa ventana deja de verse aquí. Desde esta versión, cada descarga se fusiona en <font face='Mono'>app/backend/data/archivo/</font>: "
            "un archivo comprimido por mes con la respuesta original de Meta de cada anuncio y un índice (<font face='Mono'>manifest.json</font>). Solo añade o actualiza; nunca borra."),
          lista(["No hay que hacer nada: se llena solo mientras la herramienta está abierta. Ocupa pocos MB por mes.",
                 "Al pasar a una versión nueva, copia también la carpeta <font face='Mono'>app/backend/data/archivo</font> para no perder lo acumulado.",
                 "Quien administra puede revisarlo, exportarlo a un zip, importarlo o generar una copia cargable con <font face='Mono'>app/backend/tools/archivo_meta.py</font> "
                 "(comandos <i>estado</i>, <i>verificar</i>, <i>exportar</i>, <i>importar</i>, <i>snapshot</i>, <i>sqlite</i>, <i>csv</i> y <i>capturar</i>; se ejecuta con el Python de <font face='Mono'>app/.venv</font>).",
                 "El archivo contiene solo datos públicos de la Biblioteca de Anuncios; no guarda claves."]),
          P("Actualizar a una nueva versión", "h2"),
          P("Descomprime el zip nuevo y copia, si quieres conservarlos, <font face='Mono'>app/backend/afiliaciones.json</font> (afiliaciones registradas), "
            "<font face='Mono'>app/backend/mensajes_revisados.json</font> (grupos marcados como revisados, si existe) y la carpeta <font face='Mono'>app/backend/data/archivo</font> (archivo histórico) a la carpeta nueva antes de abrirla."),
          P("Puertos y detener", "h2"),
          P("La herramienta usa los puertos 8000 (datos) y 3000 (página). Con «INICIAR NoAIVerdad.bat» solo en tu equipo, sin exponerse a la red; con «INICIAR NoAIVerdad (red local).bat» quedan disponibles, en solo lectura, para los dispositivos de tu misma red. Se detiene al cerrar la ventana negra."),
          P("Datos y privacidad", "h2"),
          P("Los datos de anuncios son públicos (Biblioteca de Anuncios de Meta). NoAIVerdad no recoge datos personales de los probadores ni los envía a ningún servidor propio: "
            "lo que registras (afiliaciones) se guarda solo en tu carpeta.")]
    # ------------------------------------------------------------ 9
    c += [P("9. Problemas frecuentes", "h1"),
          *tabla([["<b>Problema</b>", "<b>Qué hacer</b>"],
                  ["Windows no deja abrir el .bat", "Clic en «Más información» → «Ejecutar de todas formas». Si persiste, clic derecho sobre el zip original → Propiedades → «Desbloquear», y vuelve a descomprimir."],
                  ["«No se encontró Python»", "Responde S para instalarlo con winget, o instala Python 3.12 desde python.org marcando «Add python.exe to PATH». Luego abre el .bat otra vez."],
                  ["Se queda en «Instalando componentes»", "La primera vez descarga unos 150 MB y verás una barra de progreso; espera hasta 5 minutos. Si falla, la ventana muestra el motivo (casi siempre falta de internet): reconecta y vuelve a abrir."],
                  ["«Puerto 8000 o 3000 ocupado»", "Cierra otras ventanas negras de NoAIVerdad o programas que usen esos puertos y reintenta."],
                  ["La página abre pero no hay datos", "Mira la ventana negra: si hay un AVISO de Meta, el acceso pudo vencer. Si no, recarga con Ctrl+F5."],
                  ["Pide iniciar sesión", "Abre la herramienta siempre con el .bat (entra sin cuenta). Si usas la dirección sola, agrega ?debug=1 al final."],
                  ["No abre desde el celular o la tableta", "Comprueba que usaste «INICIAR NoAIVerdad (red local).bat», que ambos dispositivos estén en la misma WiFi (no en datos móviles ni en una red de invitados) y que Windows permitió Python en «Redes privadas»."],
                  ["Algo se ve raro o falla", "Toma una captura (incluida la ventana negra), anota qué hacías y envíala al equipo."]], [5.2 * cm, 11.4 * cm]),
          P("Cómo enviar comentarios", "h2"),
          P("Para cada hallazgo anota: <b>qué intentabas</b>, <b>qué pasó</b>, <b>qué esperabas</b> y una <b>captura</b>. Nos interesa sobre todo: lo que no se entiende, lo que falta para tu flujo de trabajo "
            "y cualquier dato que parezca incorrecto. Envíalo al equipo de NoAIVerdad por el canal acordado para la prueba.")]
    # ------------------------------------------------------------ glosario
    c += [P("10. Glosario", "h1"),
          *tabla([["<b>Término</b>", "<b>Significado</b>"],
                  ["Página / pagador", "La página que publica el anuncio y la entidad que, según Meta, lo pagó. Pueden ser distintas."],
                  ["Rango", "Meta no da cifras exactas de inversión ni impresiones, solo intervalos."],
                  ["Alcance", "Parte de las personas a las que llegó un anuncio, por provincia."],
                  ["Indicador", "Una coincidencia que merece investigarse; no prueba coordinación ni mala fe."],
                  ["Verificada / Sin verificar", "Estado de una afiliación: con fuente confirmada, o propuesta pendiente."],
                  ["CNE", "Consejo Nacional Electoral, la autoridad electoral de Ecuador."]], [4.6 * cm, 12 * cm])]
    return c


def main() -> int:
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    doc = BaseDocTemplate(SALIDA, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.0 * cm, bottomMargin=1.8 * cm,
                          title="NoAIVerdad (beta) · Guía del probador", author="Equipo NoAIVerdad", subject="Instalación y uso de la herramienta")
    w, h = A4
    f_portada = Frame(2.2 * cm, h * 0.62, w - 4.4 * cm, h * 0.22, id="portada", showBoundary=0)
    f_cuerpo = Frame(2 * cm, 1.8 * cm, w - 4 * cm, h - 3.9 * cm, id="cuerpo")
    doc.addPageTemplates([PageTemplate(id="Portada", frames=[f_portada], onPage=portada, autoNextPageTemplate="Cuerpo"),
                          PageTemplate(id="Cuerpo", frames=[f_cuerpo], onPage=pagina)])
    story = [P("NoAIVerdad", "portada1"), Spacer(1, 6), P(f"Versión beta {VERSION} · Guía del probador", "portada2"), Spacer(1, 12),
             P("Instalación y uso de la herramienta para el equipo de Ecuador Chequea", "portada2"), Spacer(1, 14),
             Paragraph(f"Versión {VERSION} · Edición del {date.today().strftime('%d/%m/%Y')}", ParagraphStyle("f", fontName=F, fontSize=11, textColor=colors.HexColor("#94a3b8"))),
             PageBreak()]
    story += contenido()
    doc.build(story)
    print(f"Listo: {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
