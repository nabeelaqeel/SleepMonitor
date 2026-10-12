# ── Stage 1: build dependencies ───────────────────────────────
# Use a full image to compile native extensions (numpy/pandas).
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into an isolated prefix so we can copy it cleanly to the runtime stage.
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime image ─────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="nabeelaqeel67@gmail.com"
LABEL service="sleep-monitor-python-publisher"
LABEL description="Reads sleep_data.csv and publishes to Mosquitto via MQTT"

# Non-root user
RUN groupadd -r publisher && useradd -r -g publisher publisher

WORKDIR /app

# Copy installed packages from the builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY publisher.py  .
COPY classifier.py .

# CSV data is mounted as a read-only volume at /app/data so the dataset
# can be swapped without rebuilding the image.
RUN mkdir -p /app/data && chown -R publisher:publisher /app

USER publisher

# Healthcheck: confirm the publisher process is alive
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -f publisher.py || exit 1

# -u flag forces unbuffered stdout so logs appear immediately in `docker logs`
CMD ["python", "-u", "publisher.py"]
