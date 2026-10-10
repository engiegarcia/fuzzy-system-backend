FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# NumPy, SciPy y matplotlib publican wheels para python:3.11-slim: no hacen falta
# dependencias de sistema (compiladores ni libfreetype).
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Usuario no root
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, sys, urllib.request; port = os.environ.get('PORT', '10000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=4).status == 200 else 1)"

# Render inyecta PORT (10000 por defecto). El shell permite conservar un valor local razonable.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
