# ─────────────────────────────────────────────────────────────────
#  Schedula — Multi-Year AI Timetable Scheduling System (CMPN)
#  Production Dockerfile (Multi-stage, Python 3.11-slim)
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: Build & Dependencies ────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Stage 2: Lean Runtime ────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="Schedula Team"
LABEL description="Schedula Multi-Year AI Timetable Scheduling System"
LABEL version="2.8"

WORKDIR /app

# Install curl for reliable container healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed dependencies from builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application source code
COPY . /app

# Ensure data directory exists and has full read/write permissions
RUN mkdir -p /app/data && chmod -R 777 /app/data

# Expose web service port
EXPOSE 5000

# Environment variables
ENV HOST=0.0.0.0 \
    PORT=5000 \
    FLASK_DEBUG=0 \
    SECRET_KEY=schedula_cmpn_2026_secret_key \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Container healthcheck: pings API endpoint
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/api/timetable || exit 1

# Production WSGI server using Gunicorn with gthread workers for streaming support
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "8", \
     "--worker-class", "gthread", \
     "--timeout", "300", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "app:app"]
