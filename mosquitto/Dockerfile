# ── Mosquitto MQTT Broker ─────────────────────────────────────
# eclipse-mosquitto 2.x ships with WebSocket support compiled in.
# No custom build step is required.
FROM eclipse-mosquitto:2.0.18

LABEL maintainer="nabeelaqeel67@gmail.com"
LABEL service="sleep-monitor-mqtt-broker"
LABEL description="Mosquitto MQTT broker with TCP (1883) and WebSocket (9001) listeners"

# Create expected directories and set ownership
RUN mkdir -p /mosquitto/config \
             /mosquitto/data \
             /mosquitto/log \
    && chown -R mosquitto:mosquitto /mosquitto

# Copy broker configuration
COPY mosquitto.conf /mosquitto/config/mosquitto.conf

# passwd is NOT copied — it is mounted at runtime via a Docker volume.
# This prevents credentials from being baked into the image.

EXPOSE 1883
EXPOSE 9001

# Healthcheck: connect as a subscriber and read the uptime system topic.
# Exits 0 if the broker is accepting connections, 1 otherwise.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD mosquitto_sub \
        -h localhost \
        -p 1883 \
        -t '$SYS/broker/uptime' \
        -u "${MQTT_USER:-admin}" \
        -P "${MQTT_PASSWORD:-changeme}" \
        -C 1 \
        -W 5 \
        || exit 1

# Default CMD is inherited from the official image:
# CMD ["/usr/sbin/mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]
