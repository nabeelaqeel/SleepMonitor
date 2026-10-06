# =============================================================
# Sleep Monitor — Makefile
# Common development tasks
# =============================================================

ENV_FILE ?= .env.development

.PHONY: help up down logs build clean mqtt-passwd ps

help:
	@echo "Sleep Monitor — available targets:"
	@echo "  make up            Start all services (builds if needed)"
	@echo "  make down          Stop all services (keep volumes)"
	@echo "  make down-v        Stop all services AND delete volumes (wipes local DB)"
	@echo "  make build         Rebuild all images"
	@echo "  make logs          Tail logs for all services"
	@echo "  make logs-mqtt     Tail Mosquitto logs only"
	@echo "  make logs-pub      Tail Python publisher logs only"
	@echo "  make ps            Show service status and health"
	@echo "  make mqtt-passwd   Create/update the Mosquitto password file"
	@echo "  make clean         Remove stopped containers and dangling images"

up:
	docker compose --env-file $(ENV_FILE) up --build -d
	@echo ""
	@echo "Services started:"
	@echo "  MQTT broker  → mqtt://localhost:1883  (TCP)"
	@echo "  MQTT broker  → ws://localhost:9001    (WebSocket — React Native)"
	@echo "  Backend API  → http://localhost:3000"
	@echo "  PostgreSQL   → localhost:5432"

down:
	docker compose --env-file $(ENV_FILE) down

down-v:
	docker compose --env-file $(ENV_FILE) down -v

build:
	docker compose --env-file $(ENV_FILE) build --no-cache

logs:
	docker compose --env-file $(ENV_FILE) logs -f

logs-mqtt:
	docker compose --env-file $(ENV_FILE) logs -f mosquitto

logs-pub:
	docker compose --env-file $(ENV_FILE) logs -f python-publisher

logs-api:
	docker compose --env-file $(ENV_FILE) logs -f backend-api

ps:
	docker compose --env-file $(ENV_FILE) ps

# Generate the Mosquitto password file.
# Prompts for a password interactively.
mqtt-passwd:
	@echo "Creating mosquitto/passwd — you will be prompted for a password."
	@echo "Use the same password you set for MQTT_PASSWORD in $(ENV_FILE)."
	docker run --rm -it \
		-v $(PWD)/mosquitto:/mosquitto/config \
		eclipse-mosquitto:2.0.18 \
		mosquitto_passwd -c /mosquitto/config/passwd admin
	@echo "passwd file created at mosquitto/passwd"

clean:
	docker system prune -f
