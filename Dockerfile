# ─────────────────────────────────────────────────────────────────
#  Schedula — Multi-Year AI Timetable Scheduling System
#  Python 3.11-slim base, Gunicorn WSGI production server
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: dependency cache layer ──────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /deps

# Install build tools only in this layer (not in final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: lean runtime image ──────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="Schedula"
LABEL description="Multi-Year AI College Timetable Scheduling System (CMPN)"
LABEL version="2.8"

# Non-root user for security
RUN groupadd --gid 1001 schedula \
 && useradd  --uid 1001 --gid schedula --shell /bin/bash --create-home schedula

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /install /usr/local

# Copy application source
COPY --chown=schedula:schedula . .

# Remove dev/test-only files that don't belong in the image
RUN rm -rf \
        venv \
        .pytest_cache \
        __pycache__ \
        tests \
        "*.zip" \
        data/checkpoints.db \
        data/schedula.db \
        data/backups \
        data/audit_logs.json \
        data/scheduling_logs.json \
    && find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null; true \
    && find . -name "*.pyc"       -delete 2>/dev/null; true

# Persistent data lives in a Docker volume mounted at /app/data
# (The COPY above seeds the volume with demo JSON files on first run)
VOLUME ["/app/data"]

# Expose the application port
EXPOSE 5000

# Runtime environment variables (override in docker-compose or docker run)
ENV HOST=0.0.0.0 \
    PORT=5000 \
    FLASK_DEBUG=0 \
    SECRET_KEY=change_me_in_production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Drop to non-root user
USER schedula

# Health-check: hits the lightweight timetable list endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/timetable')" || exit 1

# Launch with Gunicorn (4 workers, gevent-safe threads)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile",  "-", \
     "--log-level", "info", \
     "app:app"]
