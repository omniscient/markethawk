FROM python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

RUN addgroup --system --gid 1000 appuser \
 && adduser --system --uid 1000 --ingroup appuser --no-create-home appuser

# Prometheus multiprocess metrics dir. Owned by appuser so that when the
# (non-tmpfs, root-owned) prometheus_multiproc named volume is first mounted
# here, Docker initializes the empty volume with appuser ownership — otherwise
# the non-root container user cannot write the PID-named .db files.
RUN mkdir -p /tmp/prometheus_multiproc \
 && chown appuser:appuser /tmp/prometheus_multiproc

# Copy entrypoint outside /app so the ./backend:/app:ro local-dev bind-mount
# in docker-compose.override.yml does not shadow it.
COPY --chown=appuser:appuser entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
