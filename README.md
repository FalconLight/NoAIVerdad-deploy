# NoAIVerdad - Plataforma Cívica para Monitoreo Electoral en Ecuador 🇪🇨

**NoAIVerdad** es una plataforma cívica de código abierto para consultar cobertura periodística, revisiones de verificadores y publicaciones sociales relacionadas con Ecuador. Integra **Leaflet.js**, **OpenStreetMap**, feeds externos y un backend **FastAPI**. Las fuentes aportan referencias; la plataforma no certifica que cada afirmación sea verdadera.

---

## 📁 Estructura del Proyecto

```text
NoAIVerdad/
├── backend/
│   ├── main.py              # Servidor principal FastAPI y endpoints de la API
│   ├── meta_service.py      # Consultas externas a prensa, verificadores y redes sociales
│   ├── .env.example         # Plantilla de variables de entorno (Token Meta, Puerto, Host)
│   └── requirements.txt     # Dependencias del backend (FastAPI, Uvicorn, Requests, Python-Dotenv)
├── frontend/
│   ├── index.html           # Interfaz HTML principal (OpenStreetMap + Leaflet.js + Sidebar)
│   ├── css/
│   │   └── styles.css       # Estilos CSS modernos (Glassmorphism, Responsive, UI/UX prémium)
│   ├── js/
│   │   └── app.js           # Lógica JavaScript (Leaflet map, L.geoJSON, eventos y fetch backend)
│   └── data/
│       └── ecuador_provincias.geojson # Polígonos GeoJSON de las 24 provincias de Ecuador
└── README.md                # Guía de instalación y ejecución local
```

---

## 📌 Ubicación del Archivo GeoJSON

El archivo `ecuador_provincias.geojson` debe ir dentro de la subcarpeta `data` del frontend:
👉 `frontend/data/ecuador_provincias.geojson`

El código en `frontend/js/app.js` lo consume de forma asíncrona mediante la ruta relativa `data/ecuador_provincias.geojson`.

---

## 🚀 Guía de Instalación y Ejecución Local

### 1. Configuración del Backend (Python / FastAPI)

1. **Accede al directorio del backend:**
   ```bash
   cd backend
   ```

2. **Crea y activa un entorno virtual de Python:**
   - En Linux/macOS:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```
   - En Windows (PowerShell):
     ```powershell
     py -3.12 -m venv .venv   # o: python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```

3. **Instala las dependencias necesarias:**
   ```bash
   pip install -r requirements.txt
   ```
   Repite este comando cuando actualices los requisitos del backend.

4. **Configura el archivo de variables de entorno `.env`:**
   ```bash
   cp .env.example .env
   ```
   Edita el archivo `.env` con las credenciales privadas del servidor:
   ```env
   GOOGLE_APPLICATION_CREDENTIALS=C:/ruta/privada/firebase-service-account.json
   FIREBASE_DATABASE_URL=https://noaiverdad-72aba-default-rtdb.firebaseio.com
   PORT=8000
   HOST=0.0.0.0
   ```
   La cuenta de servicio se crea en Firebase Console → Configuración del proyecto → Cuentas de servicio → Generar clave privada. Guarda el JSON en una ruta privada local y apunta `GOOGLE_APPLICATION_CREDENTIALS` a ese archivo. No lo subas a Git ni lo compartas por el chat. El Admin SDK del servidor la usa para leer las claves y escribir en Realtime Database.

   Las credenciales de proveedores se editan en Firebase Console → Realtime Database → `config` → `api_keys`. Crea este objeto con las claves disponibles:
   ```json
   {
     "GNEWS_API_KEY": "tu-clave",
     "GOOGLE_FACT_CHECK_API_KEY": "tu-clave",
     "FB_META_ACCESS_TOKEN": "tu-token",
     "FB_META_API_ENABLED": "false",
     "GROK_API_KEY": "tu-clave-xai",
     "BLUESKY_HANDLE": "opcional",
     "BLUESKY_APP_PASSWORD": "opcional"
   }
   ```
   X permanece desactivado: el colector no consulta su API ni usa scrapers, aunque queden credenciales antiguas en Firebase.
   Bluesky usa la búsqueda pública gratuita: combina ocho términos electorales con la provincia y sus principales localidades, valida que cada post mencione una localidad y vocabulario electoral, y guarda hasta 200 resultados únicos. No requiere iniciar sesión ni configurar credenciales Bluesky. Los resultados amplios anteriores se conservan en `bluesky_posts_nacionales`.
   Meta (Biblioteca de Anuncios) está **apagada por defecto**. Para encenderla: `META_INTEGRATION_ENABLED=true` en `backend/.env.local` (o `FB_META_API_ENABLED=true` en Firebase) y un token en `META_AD_LIBRARY_TOKEN`. Sin interruptor encendido, el backend no hace ninguna consulta a Meta.
   Las reglas niegan la lectura y escritura desde clientes; el backend Admin puede leerlas y los administradores del proyecto pueden editarlas en la consola. El colector las vuelve a leer al iniciar cada ciclo. Para aplicar un cambio inmediatamente: `python sync_firebase.py` desde `backend`. Si una fuente no devuelve resultados verificables, se guarda una lista vacía; el colector no repone contenido de demostración.

5. **Inicia el servidor backend:**
   ```bash
   python main.py
   ```
   - API corriendo en: `http://localhost:8000`
   - Documentación Swagger en: `http://localhost:8000/docs`
   - Al iniciar, el colector consulta las fuentes en el servidor, guarda datos para las 24 provincias y vuelve a sincronizar cada 6 horas. También guarda estadísticas y palabras clave en Firebase.
   - Para una sincronización puntual: `python sync_firebase.py`.

---

### 2. Ejecutar el Frontend (Leaflet.js + OpenStreetMap)

1. **No requiere clave de API**: Al usar OpenStreetMap y Leaflet.js, no necesitas ninguna API Key de terceros ni tarjeta de crédito.

2. **Servir el Frontend localmente:**
   Para evitar bloqueos de Origen Cruzado (CORS / `file://`), sirve la carpeta `frontend` mediante un servidor local básico:

   - **Usando Python en el directorio `frontend`:**
     ```bash
     cd frontend
     python3 -m http.server 3000
     ```
     Abre tu navegador en: `http://localhost:3000`

---

## 🎯 Funcionalidades e Interacción

1. El mapa se inicializa centrado en Ecuador (`Lat: -1.8312, Lng: -78.1834`, Zoom: 7) con la capa base de OpenStreetMap.
2. Se cargan los polígonos de las **24 provincias de Ecuador** desde `frontend/data/ecuador_provincias.geojson`.
3. **Hover**: Al pasar el ratón, la provincia se ilumina suavemente.
4. **Clic**:
   - El mapa realiza un **zoom suave** hacia los límites de la provincia (`map.fitBounds`).
   - La provincia cambia a color de selección activada.
   - El título del panel lateral (Sidebar) se actualiza dinámicamente a `"Noticias en: [Nombre de la Provincia]"`.
   - La aplicación lee en Firebase las noticias que guardó el colector. No consulta las APIs de noticias al seleccionar una provincia.

## Backend local

El backend debe permanecer ejecutándose para refrescar y guardar datos. Si no hay credenciales Firebase Admin, el colector se desactiva y la app mostrará que aún no existen datos guardados.

---

## Rediseño v6 y análisis de anuncios (rama de integración)

Esta versión combina el trabajo del repositorio original (Firebase, colector, acceso con cuenta, YouTube, Reddit, CNE,
aplicación de escritorio Electron) con un rediseño de la interfaz y el análisis de la Biblioteca de Anuncios de Meta.

**Vistas (cada una tiene su URL):** Provincias (`#/mapa/{provincia}/{fuente}/{período}`), Conexiones (`#/resumen/{alcance}/{pestaña}`: la ruta conserva el nombre anterior de la pestaña, «Resumen», para no romper enlaces),
Comparar (`#/comparar/{a}/{b}/{c}`) y Método (`#/metodo`).

**Cifras por provincia.** Una provincia se cuenta de dos maneras y la interfaz siempre las nombra: *llegan a* la provincia (los
anuncios con al menos el 5 % de su alcance allí, `AD_LIBRARY_MIN_REGION_PCT`; inversión e impresiones prorrateadas por ese
porcentaje: burbujas del mapa, totales de Conexiones y Comparar) y *con base en* la provincia (las páginas cuya provincia principal
es esa: lo que agrupa cada sol de la red; precio completo de sus anuncios). `GET /api/ads/anuncios` lista los anuncios de una
provincia (`alcance`), de las páginas con base allí (`region`), de una página, un pagador o una entidad, con `orden`,
`desde`/`limite`, `dias` (período) y `sin_cne`. Conexiones arranca en «todas» (todo el país) y solo se enfoca una provincia a propósito: con su selector, con «Ver solo X» en el detalle de un sol o con el botón «Conexiones» del panel del Mapa. Al abrir el Mapa desde Conexiones se lleva la provincia enfocada. Al recargar la página vuelve a «todas»; un enlace con provincia abierto de cero la conserva.

**Configuración local.** Los secretos van en `backend/.env.local` (ignorado por git; tiene prioridad sobre Firebase):

```env
META_INTEGRATION_ENABLED=true      # interruptor de Meta (apagado por defecto)
META_AD_LIBRARY_TOKEN=...          # token de usuario con identidad confirmada
GNEWS_API_KEY=...                  # opcional
GOOGLE_FACT_CHECK_API_KEY=...      # opcional
```

- **Acceso con cuenta:** obligatorio por defecto (como en el original). Para hacerlo opcional: `requireLogin: false` en `frontend/js/app-config.js`.
- **Token de Meta de 60 días:** `python tools/renovar_token_meta.py` (necesita `META_APP_ID` y `META_APP_SECRET` en `.env.local`).
- **Copia local de anuncios:** el último resultado completo se guarda en `backend/data/ads_snapshot.json` (ignorado por git) y se muestra, marcado como "Datos guardados", si Meta no responde. Tras reiniciar el backend, la app arranca al instante con esa copia y la renueva en segundo plano.
- **Descarga de anuncios de Meta:** por defecto se baja *todo* lo que Meta publica como anuncios políticos y de temas sociales de Ecuador en los últimos 120 días (búsqueda `*`: unos 22 mil anuncios, en unas 65 consultas de hasta 500 anuncios y unos 8 minutos; si Meta rechaza una página pesada, la app la pide más pequeña), no solo los que contienen ciertas palabras. Se renueva como mucho una vez por hora y en segundo plano: mientras tanto se siguen mostrando los datos anteriores, y una renovación fallida o incompleta no los pisa. Con ese volumen el backend usa unos 500 MB de memoria. Los ajustes (`AD_LIBRARY_TERMS`, `AD_LIBRARY_LIMIT`, `AD_LIBRARY_PAGES`, `AD_LIBRARY_TIMEOUT`, `AD_LIBRARY_CACHE_MIN`, `AD_LIBRARY_SEGUNDO_PLANO`) están documentados en `backend/.env.example`.
- **X (Twitter):** la integración existe (`backend/x_service.py`) pero está desactivada: la API oficial es de pago.
- **Mensajes repetidos:** el método (textos casi idénticos entre páginas distintas, sin enlaces, hashtags ni menciones, y sin contar plantillas donde solo cambia un nombre o una cifra) y su revisión están en `docs/mensajes-repetidos-revision-2026-11-05.md`. Para revisar los grupos con la copia local, sin llamar a Meta: `cd backend && python tools/revisar_mensajes_repetidos.py` (`--todos`, `--aisladas`, `--umbral 0.9`). En la red, la línea de texto repetido es amarilla y se puede pulsar: el panel lateral muestra todos los mensajes duplicados entre esas dos páginas, cada uno con sus dos anuncios lado a lado (texto completo, fechas, pagador, rangos y el enlace propio de cada anuncio a la Biblioteca de Meta; si los textos difieren, se marcan las palabras que cambian). Los grupos esperables se marcan como **revisados** desde esa pestaña («Marcar como revisado», con motivo y nota; se protege igual que editar afiliaciones) y se guardan en `backend/mensajes_revisados.json`: dejan de contarse como señal, de dibujarse en la red y de sumarse en Comparar, y vuelven a mostrarse si se suma una página que la revisión no cubría.
- **Pruebas:** `cd backend && python -m unittest discover -s tests -t .`
- **Aplicación de escritorio:** `npm install` y `npm start` en la raíz (Electron incluye su propio servidor para prensa y YouTube; los anuncios de Meta requieren el backend).

Las notas de diseño y la auditoría de UX están en `docs/`.
