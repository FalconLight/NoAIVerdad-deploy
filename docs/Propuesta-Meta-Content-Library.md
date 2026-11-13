# Propuesta de investigación para acceder a Meta Content Library

27 de octubre de 2026

## Resumen del proyecto

Ecuador Chequea y el equipo de NoAIVerdad solicitan acceso a Meta Content Library y a su API para estudiar, durante seis meses, cómo circulan en Facebook e Instagram los mensajes políticos de las elecciones seccionales de Ecuador, y si lo que se paga como publicidad coincide con lo que se difunde de forma orgánica. Se piden únicamente publicaciones públicas y sus métricas de interacción, sin datos privados. Los resultados se publicarán como análisis agregados, sin exportar datos de Meta y conforme a sus términos.

## Organización solicitante y equipo

La solicitante es Ecuador Chequea, una organización sin fines de lucro. Meta pide que una persona actúe como investigadora principal y presente la solicitud; las demás se suman después de que esa solicitud sea aprobada. Los campos entre corchetes los completa Ecuador Chequea.

| Campo | Dato |
| --- | --- |
| Organización | Ecuador Chequea \[razón social y sede\] |
| Naturaleza jurídica | ONG sin fines de lucro \[número de registro y fecha de constitución\] |
| Misión | \[propósito principal; destacar la investigación de interés público y la verificación de información\] |
| Investigador/a principal | \[nombre, cargo y correo institucional\] |
| Colaboradores | \[nombre y rol de cada persona\] |
| Apoyo técnico | Equipo de NoAIVerdad \[nombre de la persona responsable\] |
| Sitio web y contacto | \[dirección y correo de contacto\] |

## Problema y justificación de interés público

La Biblioteca de Anuncios de Meta muestra quién paga publicidad política, pero solo en rangos de inversión e impresiones, y no dice nada de lo que esas mismas páginas publican sin pagar. Para un verificador, la pregunta clave queda sin respuesta: si un mensaje se impulsa con dinero, ¿también circula por canales orgánicos, y quiénes lo repiten?

Ejemplo de lo que ya se ve con datos públicos: en una prueba de la herramienta NoAIVerdad con 526 anuncios políticos (27 de octubre de 2026), 38 declaraban un pagador distinto de la página que los publicaba. Es una pista para investigar, no una prueba de coordinación, y hoy no puede contrastarse con la difusión orgánica.

El proyecto es de interés público porque apoya la transparencia de un proceso electoral, ayuda a la ciudadanía a distinguir publicidad política de contenido espontáneo y produce métodos reutilizables por otras organizaciones de verificación.

## Preguntas de investigación

1. ¿Qué mensajes políticos que se pautan con anuncios en Ecuador circulan también de forma orgánica, y con qué nivel de interacción?
2. ¿Qué páginas publican contenido casi idéntico en momentos cercanos, y coincide con pagadores o enlaces compartidos en la Biblioteca de Anuncios?
3. ¿Cómo se difunden, en el tiempo, los mensajes que Ecuador Chequea ya verificó como falsos o engañosos, frente a los no verificados?
4. ¿Qué parte de la inversión publicitaria se concentra en pocas páginas, y qué páginas actúan como intermediarias de terceros?

Cada respuesta se expresa como indicador con su límite, nunca como acusación contra una persona u organización.

## Datos que se solicitan y por qué

Solo contenido público de Facebook e Instagram, limitado a una lista acotada de entidades políticas de Ecuador. Antes de enviar, confirmar con la documentación de Meta qué campos están disponibles.

| Dato | Para qué se necesita |
| --- | --- |
| Publicaciones públicas de páginas y cuentas de candidatos, partidos, medios y páginas políticas (texto, fecha, enlaces) | Comparar lo que se publica con lo que se paga y detectar mensajes repetidos (preguntas 1 y 2) |
| Vistas e interacciones por publicación | Medir si un mensaje pagado también tiene difusión orgánica (pregunta 1) |
| Datos públicos de la página o cuenta (nombre, categoría, verificación) | Identificar a qué entidad pertenece cada publicación y conectarla con la Biblioteca de Anuncios (preguntas 2 y 4) |
| Comentarios públicos, solo si el diseño final lo exige y están disponibles \[confirmar con Meta\] | Medir cómo se recibe un mensaje verificado (pregunta 3); se analizarían en conjunto, sin citar personas |

Período y ámbito: \[fechas de inicio y fin\], contenido relacionado con Ecuador. No se solicitan mensajes privados ni datos de usuarios que no sean públicos.

## Metodología y plan de análisis

1. **Lista de entidades.** Se parte de las páginas y pagadores que ya aparecen en la Biblioteca de Anuncios, y se completa a mano con sus cuentas oficiales. Cada afiliación política se registra solo con una fuente pública.
2. **Recolección.** Dentro del entorno seguro de Meta, sin sacar datos.
3. **Mensajes repetidos.** Se compara el texto de las publicaciones y de los anuncios por similitud (secuencias de tres palabras, umbral de 80 %) y por enlaces compartidos.
4. **Análisis en el tiempo y por zona.** Se cruza la fecha y la interacción de cada publicación con el alcance por provincia que publica la Biblioteca de Anuncios.
5. **Contraste con verificaciones.** Se compara con las verificaciones ya publicadas por Ecuador Chequea.
6. **Revisión editorial.** Ningún hallazgo se publica sin revisión humana y sin contrastar con otras fuentes.

NoAIVerdad es una herramienta abierta, ya en prueba con Ecuador Chequea. Se usa fuera del entorno seguro y solo con datos de la Biblioteca de Anuncios, para elegir qué páginas y mensajes estudiar. No recibe datos de Meta Content Library.

## Protección de datos personales y ética

El proyecto se rige por la Ley Orgánica de Protección de Datos Personales de Ecuador y por los términos de Meta. Revisar el texto final con asesoría legal de Ecuador Chequea antes de enviar.

- **Solo contenido público**, de entidades políticas y páginas públicas; nada de mensajes privados.
- **Mínimo necesario.** Se piden solo los campos de la tabla anterior y solo para la lista acotada de entidades.
- **Sin identificar personas.** No se intentará reidentificar ni perfilar a usuarios que comentan o reaccionan; los comentarios, si se usan, se analizan en conjunto.
- **Datos sensibles.** La afiliación política se registra solo para figuras públicas y organizaciones, con fuente pública explícita y nunca deducida del nombre ni del contenido de una página.
- **Menores de edad.** No se analiza contenido dirigido a menores ni se publican datos de ellos.
- **Derecho a réplica.** Antes de publicar, se da a las páginas nombradas la posibilidad de responder.
- **Revisión ética:** \[comité de ética o revisión interna de Ecuador Chequea, con fecha y responsable\].

## Gestión y seguridad de los datos

Según las preguntas frecuentes de Meta, el trabajo se hace dentro de su entorno seguro de investigación y los datos de la API no pueden exportarse ([Meta, preguntas frecuentes](https://developers.secure.facebook.com/docs/content-library-api/disclosures)). El plan lo asume así:

- **Sin exportación ni carga de datos.** Solo se llevan al entorno código y modelos propios; los resultados salen como cifras agregadas redactadas en los informes.
- **Borrado mensual.** Meta elimina los archivos de salida el día 1 de cada mes; el código y la metodología se guardan fuera, y cada análisis se puede repetir.
- **Límites de uso.** Hasta 500.000 registros por ventana de 7 días y 60 llamadas por minuto; las consultas se diseñan para caber en ellos.
- **Acceso nominal.** Solo las personas aprobadas entran; las credenciales no se comparten.
- **Fin del proyecto.** Se notifica a Meta cualquier cambio de organización o de objetivo y se solicita una nueva aprobación si el proyecto cambia de forma sustancial.

## Publicación y difusión

Los resultados se publicarán en español, con un resumen para el público general y una nota metodológica que explique límites y margen de error. Meta no revisa los manuscritos basados solo en sus herramientas, pero exige atribución y un aviso al publicar ([Meta, solicitud de acceso](https://developers.secure.facebook.com/docs/content-library-api/get-access)); el proyecto cumplirá ambos.

El código de análisis se publicará abierto, sin datos. Si se detecta un error después de publicar, se corrige de forma visible.

## Cronograma

Los meses cuentan desde la aprobación de Meta, que según su página tarda unas 4 a 6 semanas desde la solicitud.

1. **Antes del mes 1.** Solicitud, revisión de elegibilidad y procesamiento por Meta.
2. **Mes 1.** Configuración del entorno, lista final de entidades y consultas de prueba dentro de los límites.
3. **Meses 2 y 3.** Recolección y análisis de mensajes repetidos, interacción y cruce con la Biblioteca de Anuncios.
4. **Mes 4.** Contraste con verificaciones, revisión editorial y derecho a réplica.
5. **Mes 5.** Publicación de resultados y aviso a Meta.
6. **Mes 6.** Cierre, borrado de archivos y balance del proyecto.

## Financiamiento e independencia

Este proyecto no tiene fines comerciales ni vende datos o análisis. Ecuador Chequea declarará sus fuentes de financiamiento y cualquier vínculo con partidos, campañas o empresas de publicidad: \[lista de donantes y financiadores del proyecto, y declaración de que no hay vínculos comerciales ni partidarios\].

NoAIVerdad es una herramienta cívica de código abierto \[el equipo de NoAIVerdad confirma sus fuentes de financiamiento y que no recibe pagos de organizaciones políticas\].

## Documentos por adjuntar

- [ ] Constancia de registro legal de Ecuador Chequea como organización sin fines de lucro
- [ ] Estatutos o declaración de misión que muestre su propósito de interés público
- [ ] Hoja de vida de la persona investigadora principal
- [ ] Carta de respaldo de la dirección de la organización
- [ ] Plan de protección de datos, revisado por asesoría legal
- [ ] Declaración de financiamiento y de ausencia de vínculos comerciales
- [ ] Lista de entidades cuyo contenido público se analizará
- [ ] Constancia de la revisión ética

### Fuentes

Consultadas el 27 de octubre de 2026; Meta puede haber cambiado los requisitos desde entonces.

- [Meta: solicitud de acceso a Content Library y API](https://developers.secure.facebook.com/docs/content-library-api/get-access): elegibilidad, pasos, plazos y costo.
- [Meta: preguntas frecuentes de Content Library API](https://developers.secure.facebook.com/docs/content-library-api/disclosures): límites, borrado mensual y términos de publicación.
- [ICPSR: acceso a las API de Meta](https://www.icpsr.umich.edu/sites/icpsr/news/icpsr-to-facilitate-researcher-access-to-metas-api-products): revisión de solicitudes. La página actual de Meta nombra a otro centro de revisión (CASD); confirmar cuál aplica.
