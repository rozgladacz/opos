FROM python:3.13-slim

# Metadane wersji — wstrzykiwane przez GitHub Actions przy budowie release
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

# Nie tworzyć .pyc, nie buforować stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# gosu + natywne biblioteki przypiętego WeasyPrint 69.0
RUN apt-get update && apt-get install -y --no-install-recommends \
        gosu \
        libcairo2 \
        libfontconfig1 \
        libgdk-pixbuf-2.0-0 \
        libharfbuzz0b \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Użytkownik nieprivilegowany — UID 1000 jest zgodny z typowymi ustawieniami linuxowymi
RUN groupadd -g 1000 app && useradd -u 1000 -g app -s /bin/sh -m app

# Instalacja zależności Python jako root (szybszy cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Kopiowanie kodu aplikacji
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Entrypoint
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Volumen dla bazy danych, backupów i wygenerowanych sekretów
VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/auth/login')" \
  || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
