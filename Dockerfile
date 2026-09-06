FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Copy the complete repository, including .git.
# Make sure .git is NOT excluded by .dockerignore.
COPY . /app

# Git refuses repositories whose directory ownership does not match
# the executing user. Docker COPY/chown combinations can trigger this.
RUN git config --global --add safe.directory /app \
    && git config --global core.autocrlf true

# Fail early with a useful error if the Git metadata is incomplete.
RUN git rev-parse --verify HEAD \
    && git describe --tags --always --dirty

RUN python -m pip install --upgrade pip build \
    && python -m build --wheel


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/state /app/output \
    && chown -R appuser:appuser /app

COPY --from=builder /app/dist/*.whl /tmp/

RUN pip install /tmp/*.whl \
    && rm -f /tmp/*.whl

USER appuser

VOLUME ["/app/state", "/app/output"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2)" || exit 1

CMD ["uvicorn", "siriconsumer.main:app", "--host", "0.0.0.0", "--port", "8080"]