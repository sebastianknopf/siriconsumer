FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# setuptools_scm needs the repository metadata and its release tags.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Install from the Git checkout so setuptools_scm can derive the package version.
RUN git config --global --add safe.directory /app \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /app/state /app/output /var/log/siri

# Run as the image's default user to support ordinary Linux bind mounts.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2)" || exit 1

CMD ["uvicorn", "siriconsumer.main:app", "--host", "0.0.0.0", "--port", "8080"]
