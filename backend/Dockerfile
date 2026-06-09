FROM python:3.12-slim

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

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
