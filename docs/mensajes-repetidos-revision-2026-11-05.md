# Mensajes repetidos: revisión del método — 2026-11-05

Revisión de los grupos que reportaba la pestaña **Mensajes repetidos** (Conexiones) con la descarga completa de Meta: 22.462 anuncios sin los del CNE, 17.558 comparables. Un grupo es el mismo texto (o uno casi idéntico: similitud de Jaccard ≥ 80 % sobre trigramas de palabras) en **páginas distintas**. Para repetir la revisión cuando cambien los datos: `backend/tools/revisar_mensajes_repetidos.py` (lee la copia local; no llama a Meta ni escribe nada).

## Qué se encontró

Antes del cambio la app reportaba 76 grupos. Se leyeron todos.

| Hallazgo | Evidencia | Qué se hizo |
|---|---|---|
| **Casi todos son repeticiones reales** | 75 de 76 grupos son el mismo texto, o variantes de formato (hashtags, emojis, un enlace), en páginas distintas | Quedan idénticos: tras el cambio siguen los mismos anuncios en los mismos grupos |
| **Una plantilla se leía como un solo mensaje** | «Conoce la historia de Kelly / Gabriela / Rosa / Víctor…» (Banco del Pacífico): un grupo de 8 anuncios y 4 textos entre Datanews.ec y Dpolitik.ec, pero solo la historia de Víctor está en las dos páginas | La regla «otro nombre u otra cifra = otro mensaje» las separa: el grupo queda en 2 anuncios |
| **Coincidencias que se escapaban** | 3 grupos nuevos: Giovanna Ubidia y la página de ADN; dos páginas de Machala (Periodismo Machala IA, Boom Machala); Revolución Ciudadana El Oro y su candidato | Se compara sin enlaces, hashtags ni menciones |
| **La limpieza de enlaces nunca funcionó** | El código normalizaba el texto y después buscaba `https://…`, que ya se había convertido en «https a b c»; además los hashtags y las menciones contaban como palabras (diez hashtags eran «diez palabras») | `_texto_comparable` los quita **antes** de normalizar; el mínimo de 8 palabras cuenta solo palabras |
| **Un aviso de Meta solo se libraba del análisis por tener 7 palabras** | «This ad ran without a required disclaimer.»: 2.030 anuncios de 1.066 páginas. Con una palabra más habría armado un «grupo» de mil páginas | Se excluye de forma explícita; y todo texto que aparece en 40 páginas o más se omite y se informa en la nota |
| **Una alerta que no distinguía nada** | «Pagadores declarados distintos» aparecía en 76 de 76 grupos: cada página declara pagar sus propios anuncios | Etiqueta neutra, con su explicación |
| **La lista solo mostraba 30 grupos** | La interfaz pedía `limite=30` | Pide todos (el tope del endpoint sube a 200) |

## Lectura del resultado (interpretación, no algoritmo)

- **42 de los 79 grupos (289 de 391 anuncios) son de una misma red de cinco páginas**: PulsoDigital, Dpolitik.ec, Datanews.ec, El Emprendedor y Agencia de Publicidad y Marketing en Quito. Repiten mensajes de comunicación del Gobierno y de entidades como el Biess o Banco del Pacífico, a veces junto a las páginas de Presidencia o de la Secretaría General de Comunicación. La repetición es real; qué hay detrás (una sola mano, pauta contratada, coordinación) no lo dice el texto.
- 21 grupos se publicaron el mismo día y 43 en menos de cuatro; solo 10 se extienden más de 30 días.
- Otros patrones: medios locales que copian el mismo texto (La Lupa y Noti Guayas; La Veci y LUMS TV; Pichincha Digital y Pichincha Ciudadano), candidatos con su partido o sus aliados (candidatos de ADN en Tungurahua), y páginas anónimas que difunden un mismo ataque (el caso de Wilson Merino).
- De los 79 grupos, 56 tienen páginas que coinciden en 3 mensajes o más (un patrón) y 16 son coincidencias aisladas (las dos páginas solo repiten ese mensaje). Aislada **no** significa irrelevante: entre ellas está el ataque a Wilson Merino por tres páginas. Por eso «Ocultar coincidencias aisladas» es un filtro opcional, no el comportamiento por defecto.
- Si dos páginas son la misma persona u organización, el texto repetido es esperable: se unen en Entidades y el grupo desaparece (la unificación ya existía). `mismo_partido` solo se afirma cuando **todas** las páginas tienen el mismo partido verificado.

## Qué cambió

- `backend/ads_library.py`: `_texto_comparable` (sin enlaces, hashtags ni menciones, antes de normalizar), `_sustituye_datos` (la misma plantilla con otro nombre propio o cifra no es el mismo mensaje; no cuenta lo que solo se agrega o se quita —una firma, un hashtag—, el mismo nombre más largo o con una errata, ni la mayúscula de abrir frase), aviso de Meta «sin descargo» excluido, tope de 40 páginas por texto (`MAX_PAGINAS_POR_TEXTO`), mínimo de 8 palabras limpias (`MIN_PALABRAS_TEXTO`). Cada grupo trae ahora `n_textos`, `dias`, `coincidencias` (en cuántos grupos coinciden las mismas páginas) y `mismo_partido`; la respuesta, `plantillas_separadas` y `textos_muy_extendidos`.
- Interfaz: cada tarjeta dice «texto idéntico» o «N variantes», cuántos días abarca, «Coinciden en N mensajes» o «Coincidencia aislada» y, si aplica, «Mismo partido»; filtro «Ocultar coincidencias aisladas»; la nota informa de las plantillas separadas y de los textos omitidos; Método explica cómo se comparan.
- Pruebas: 9 nuevas (casos reales: enlaces y hashtags, plantilla con otro nombre, cifra y fecha distintas, nombre más largo, firma, aviso de Meta, texto en muchas páginas, contexto del grupo). Se comprobó que siete de ellas **fallan** al revertir su arreglo (las de limpieza de enlaces y hashtags, plantilla, cifra, fecha, nombre más largo y aviso de Meta).

## Herramientas consideradas (todas gratuitas)

| Herramienta (licencia) | Qué aportaría | Veredicto |
|---|---|---|
| MinHash + LSH, `datasketch` (MIT) | Aproximar la similitud en millones de textos | No hace falta: con ~18 mil textos el cálculo exacto con filtro por prefijo tarda 2,4 s y no aproxima nada (MinHash añadiría errores) |
| `rapidfuzz` (MIT) | Distancia de edición muy rápida | No ayuda: los falsos positivos no eran erratas sino plantillas |
| TF-IDF y coseno, `scikit-learn` (BSD) | Pesar las palabras raras y restar las frases comunes | No ahora: con 80 % no hay grupos formados por frases de relleno (las más comunes, «de nuestra gente», pesan poco en textos de 20 a 90 palabras); ~100 MB de dependencias |
| Embeddings multilingües, `sentence-transformers` (Apache-2.0) | Encontrar paráfrasis | No para marcar: empareja temas, no copias (todo anuncio sobre «Jóvenes en Acción» se parecería), así que subiría los falsos positivos; exige PyTorch (1–2 GB). Como mucho, una ayuda exploratoria fuera de la app |
| `spaCy` con `es_core_news_sm` (MIT) | Reconocer nombres propios con NER en lugar de la regla de mayúsculas | Posible más adelante si la regla falla (nombres al inicio de una frase) |
| Revisión humana registrada | Marcar un grupo como esperado o legítimo y que no vuelva a aparecer | Es lo único que resuelve el resto, que es interpretación. **Implementada** (pestaña Mensajes repetidos → «Marcar como revisado»; `backend/mensajes_revisados.json`): cubre solo ese mensaje o cualquier mensaje entre esas páginas, con motivo y nota; los grupos cubiertos dejan de contarse (lista, red y Comparar) y se ven con «Mostrar revisados»; si se suma una página que la revisión no cubría, el grupo vuelve como señal |

El backend sigue sin dependencias de texto: todo es biblioteca estándar de Python.

## Límites conocidos

- Un nombre propio que abre una frase («Kelly Sarmiento cuenta su historia…») no se reconoce como dato: dos plantillas que solo cambian eso se unen.
- El texto de un anuncio sin cuerpo es el título del enlace; los títulos genéricos de menos de 8 palabras se ignoran.
- Meta no entrega las imágenes: dos anuncios con la misma imagen y textos distintos no se detectan.
- Una persona con varias páginas cuenta como varias hasta que se unen en Entidades.
- Los umbrales (80 %, 8 palabras, 40 páginas) son decisiones: se ajustan con `--umbral` en la herramienta de revisión o con las constantes `MIN_PALABRAS_TEXTO` y `MAX_PAGINAS_POR_TEXTO`.
