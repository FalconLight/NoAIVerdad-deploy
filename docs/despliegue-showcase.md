# Despliegue del showcase en Vercel (sin costo)

**Sitio:** https://noaiverdad-showcase.vercel.app (v1.2.0 + rama `deploy/showcase`; proyecto `noaiverdad-showcase` en Vercel, plan Hobby).

```
Visitante ──► Vercel ── /            frontend estático (public/)
                     └─ /api/*       backend FastAPI como función Python (api/index.py), mismo dominio
```

- **Sin cuenta:**
  - En el dominio publicado la app arranca en modo debug (`frontend/js/despliegue-config.js`).
  - El botón «Iniciar sesión» sigue visible pero es opcional.
- **El backend queda cerrado:**
  - No tiene dirección propia: solo existe como `/api/*` del sitio.
  - Con `NOAI_SOLO_LECTURA`, solo responde a GET en las rutas de datos que usa la app.
  - Escrituras, `/docs`, diagnósticos y la raíz con el estado de los servicios dan 403/404.
  - No permite CORS, así que otros sitios web no pueden usar la API.
  - El código y la copia de anuncios no se publican como archivos: `/backend/...` da 404.
  - Las páginas internas (`afiliaciones-check.html`, `login.html`) redirigen al inicio.
- **Sin costos:**
  - Plan Hobby de Vercel, sin tarjeta: si se superan sus límites, se pausa y no cobra.
  - Los anuncios salen de la copia incluida (`AD_LIBRARY_SOLO_COPIA`), sin llamar a Meta.
  - Sin API de X (es de pago) y sin Firebase Admin.
  - Las respuestas de `/api` se guardan 5 minutos en la CDN.

> Hugging Face quedó descartado: en noviembre de 2026 los Spaces Docker exigen el plan PRO.

## Desde GitHub (repositorio privado conectado a Vercel)

Cada `git push` a la rama `main` publica el sitio solo. Vercel usa los archivos de la raíz:

- `vercel.json`: no instala nada de Node; arma `public/` con `deploy/vercel/armar_public.sh` y sirve `/api/*` con `api/index.py`.
- `requirements.txt` (raíz): dependencias de la función, sin `firebase-admin`, `uvloop` ni `watchfiles`. El servidor local sigue usando `backend/requirements.txt`.
- `backend/data/ads_snapshot.json`: la copia de anuncios va en el repositorio. Para actualizar los datos, reemplázala, haz commit y push (cada versión suma unos 53 MB al historial).

La publicación con la CLI (abajo) sigue funcionando como alternativa.

## Volver a publicar (p. ej. con datos más recientes)

Desde la carpeta `NoAIVerdad-deploy`:

```bash
python deploy/preparar_vercel.py
```

```bash
cd dist-vercel && npx -y vercel@latest deploy --prod --yes --name noaiverdad-showcase --global-config ../dist-vercel-cli
```

- `preparar_vercel.py` arma `dist-vercel/` y toma la copia de anuncios más reciente (NoAIVerdad-v06, NoAIVerdad-release o la propia). También puedes indicar una con `--snapshot`.
- `dist-vercel-cli/` guarda la sesión de la CLI de Vercel. No va a Git (está en `dist-*/`).
  - Se usa `--global-config` porque en esta máquina la CLI no puede escribir su configuración en AppData.
  - Si la sesión caduca, vuelve a iniciarla con este comando y autoriza el código en el navegador:

```bash
npx -y vercel@latest login --global-config ../dist-vercel-cli
```

## Comprobaciones

| Prueba | Esperado |
|---|---|
| Abrir el sitio | Red y mapa sin pedir cuenta |
| `/api/ads/mapa` | JSON con provincias |
| `/api/ads/diagnostico`, `/api/docs` | 404 |
| `POST /api/ads/afiliaciones` | 403 |
| `/backend/main.py` | 404 |

## Notas

- **Primera visita.** Tras un rato sin visitas, la primera petición tarda unos segundos (arranque en frío más la carga de la copia, unos 6 s).
- **Inicio de sesión con Google (opcional).** Solo funciona si añades `noaiverdad-showcase.vercel.app` en Firebase Console → Authentication → Settings → Authorized domains.
- **Volver a pedir cuenta.** Quita `requireLogin: false` en `frontend/js/despliegue-config.js` y vuelve a publicar.

## Archivos

- `deploy/vercel/vercel.json`: salida `public/`, función `api/index.py` con `backend/**`, reescritura de `/api/*`, redirecciones y cabeceras de seguridad.
- `deploy/vercel/api/index.py`: fija las variables del showcase y expone la app FastAPI.
- `deploy/preparar_vercel.py`: arma `dist-vercel/` sin `.env` ni credenciales, y quita de los requisitos `firebase-admin`, `uvloop` y `watchfiles`.
- `backend/main.py`: modo `NOAI_SOLO_LECTURA`. Sin esa variable, todo funciona como antes en local.
- `frontend/js/despliegue-config.js` y `frontend/js/app.js`: modo debug y API en el propio dominio, solo en dominios publicados.
