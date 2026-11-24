FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar aplicación completa
COPY . .

# Variables de entorno para showcase público
ENV PORT=8000 \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    NOAI_SOLO_LECTURA=true \
    AD_LIBRARY_SNAPSHOT=backend/data/ads_snapshot.jsonl.gz \
    AD_LIBRARY_SOLO_COPIA=true \
    AD_LIBRARY_SEGUNDO_PLANO=false \
    META_INTEGRATION_ENABLED=false \
    CORS_ORIGINS=*

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
