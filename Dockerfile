# Single-stage build: the app has no compiled dependencies, so a build stage
# would only add complexity without a meaningful size or security benefit.
FROM python:3.12-slim

# Fail fast if the container tries to write bytecode into a read-only layer,
# and flush stdout immediately so `docker logs` is not buffered.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY cli ./cli

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# Single worker: session state lives in process memory (InMemoryCallSessionStore).
# Scale horizontally behind a shared store (see app/services/call_session_store.py)
# rather than adding workers here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
