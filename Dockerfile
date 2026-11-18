# syntax=docker/dockerfile:1
# Imagen de cv-server (FastAPI). Flask sigue disponible en el mismo código,
# pero el contenedor sirve la API tipada con uvicorn.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Todas las dependencias tienen wheel para linux/amd64: no hace falta compilar.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# uid 1000 = el mismo `runAsUser` que declara el chart de Helm. Si no coinciden,
# el pod arranca pero no puede leer ficheros de la app.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app

COPY --chown=app:app . .

# Sin privilegios: el contenedor no puede escribir en /app (readOnlyRootFilesystem).
USER 1000:1000

EXPOSE 8000

# Mismo endpoint que usan las probes de Kubernetes (/health de api.py).
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
