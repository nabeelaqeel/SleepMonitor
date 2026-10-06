# Docker Guide

## What Gets Containerized

| Service | Containerized | Reason |
|---|---|---|
| Mosquitto MQTT broker | Yes | Consistent config; WebSocket support |
| Python publisher/classifier | Yes | Isolated Python deps; reproducible CSV replay |
| Node.js backend API | Yes | Consistent Node version; clean production image |
| PostgreSQL (local dev) | Yes | Mirrors RDS schema locally without installing Postgres on host |
| PostgreSQL (production) | **No** — use Amazon RDS | RDS manages backups, failover, patching |
| React Native Expo app | **No** — runs on mobile | EAS Build handles mobile CI/CD separately |

---

## Prerequisites

- Docker Desktop (Mac/Windows) or Docker Engine + Compose plugin (Linux)
- `make` (optional but convenient — all commands also work without it)
- AWS CLI configured (only for ECR push / production deploy)

---

## Quick Start (Local Development)

```bash
# 1. Copy the env template and fill in passwords
cp .env.example .env.development
# Edit .env.development — set MQTT_PASSWORD, POSTGRES_PASSWORD, JWT_SECRET

# 2. Create the Mosquitto password file
make mqtt-passwd
# Enter the same password you set as MQTT_PASSWORD

# 3. Start everything
make up

# Services will be available at:
#   MQTT  (TCP)       → localhost:1883
#   MQTT  (WebSocket) → ws://localhost:9001   ← React Native app connects here
#   API               → http://localhost:3000
#   PostgreSQL        → localhost:5432
```

Without `make`:

```bash
cp .env.example .env.development
docker run --rm -it -v $(pwd)/mosquitto:/mosquitto/config \
    eclipse-mosquitto:2.0.18 mosquitto_passwd -c /mosquitto/config/passwd admin
docker compose --env-file .env.development up --build -d
```

---

## Service Descriptions

### mosquitto

Built from `mosquitto/Dockerfile` using the official `eclipse-mosquitto:2.0.18` base.
- TCP listener on 1883 (Python publisher uses this)
- WebSocket listener on 9001 (React Native Paho JS uses this)
- Password file is **mounted at runtime** (`mosquitto/passwd` → `/mosquitto/config/passwd`). It is never baked into the image.
- Persistence data stored in a named Docker volume (`mosquitto_data`)

### python-publisher

Two-stage build: a `builder` stage compiles numpy/pandas native extensions, then a `runtime` stage copies only the installed packages and source files. Runs as a non-root user.

The `sleep_data.csv` from the project root is mounted into `/app/data/sleep_data.csv` inside the container. You can swap the CSV without rebuilding.

Key environment variables:

| Variable | Default | Effect |
|---|---|---|
| `PUBLISH_INTERVAL` | `1.0` | Seconds between rows |
| `LOOP_CSV` | `true` | Restart from row 0 after the last row |
| `STATS_INTERVAL` | `10` | Publish a background stats message every N rows |
| `PATIENT_ID` | `patient-001` | Embedded in each payload |

### backend-api

Three-stage build: `deps` installs all packages, `builder` compiles TypeScript to `dist/`, `runtime` ships only `dist/` and pruned production `node_modules`. The `/health` endpoint pings the database and returns `{ status: "ok" }` or `503`.

### postgres

Standard `postgres:16-alpine`. SQL files in `postgres/init/` run alphabetically on first start (`01_schema.sql` creates all tables and seed data). Data is stored in the `postgres_data` named volume.

**This container is for local development only.** In production, set `DATABASE_URL` to your RDS endpoint — the backend API and docker-compose connect to it the same way.

---

## Common Commands

```bash
# Tail all logs
make logs

# Tail a specific service
make logs-mqtt
make logs-pub

# Check service health
make ps

# Stop everything (volumes are preserved)
make down

# Stop and DELETE local database data
make down-v

# Rebuild all images from scratch (no cache)
make build
```

---

## Docker Image Versioning

### Tag taxonomy

Every image receives three tags at build time:

| Tag | Example | Meaning |
|---|---|---|
| Semver | `v1.3.0` | Immutable release tag — use this in staging and production |
| Git SHA | `sha-a1b2c3d` | Exactly which commit built this image |
| `latest` | `latest` | Most recent build on `main` — **local dev only, never deploy this** |

### Rule: never deploy `latest`

`latest` is mutable. Pulling it on two different days can give different code. Always pin staging and production to a semver tag.

### Tagging workflow (automatic via GitHub Actions)

```
Developer                      Git                      ECR
──────────                     ───                      ───
feature work on branch
merge to develop
merge develop → main
git tag -a v1.3.0 -m "..."
git push origin v1.3.0
                               tag pushed ──────────►  GitHub Actions builds:
                                                        - mosquitto:v1.3.0
                                                        - mosquitto:sha-a1b2c3d
                                                        - mosquitto:latest
                                                        (same for publisher + api)
                                                        Deploys to EC2
```

### Manual tagging (when not using GitHub Actions)

```bash
ECR=123456789012.dkr.ecr.ap-southeast-1.amazonaws.com
TAG=v1.3.0
SHA=$(git rev-parse --short HEAD)

docker build \
  -t ${ECR}/sleep-monitor/mosquitto:${TAG} \
  -t ${ECR}/sleep-monitor/mosquitto:sha-${SHA} \
  -t ${ECR}/sleep-monitor/mosquitto:latest \
  ./mosquitto

docker push ${ECR}/sleep-monitor/mosquitto:${TAG}
docker push ${ECR}/sleep-monitor/mosquitto:sha-${SHA}
docker push ${ECR}/sleep-monitor/mosquitto:latest
```

---

## AWS ECR Setup

### 1. Create repositories

```bash
AWS_REGION=ap-southeast-1
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

for SERVICE in mosquitto python-publisher backend-api; do
  aws ecr create-repository \
    --repository-name sleep-monitor/${SERVICE} \
    --region ${AWS_REGION} \
    --image-scanning-configuration scanOnPush=true
done
```

### 2. Add a lifecycle policy (prevents unbounded image accumulation)

```bash
POLICY='{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Keep last 10 versioned releases",
      "selection": {
        "tagStatus": "tagged",
        "tagPrefixList": ["v"],
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": { "type": "expire" }
    },
    {
      "rulePriority": 2,
      "description": "Delete untagged images after 7 days",
      "selection": {
        "tagStatus": "untagged",
        "countType": "sinceImagePushed",
        "countUnit": "days",
        "countNumber": 7
      },
      "action": { "type": "expire" }
    }
  ]
}'

for SERVICE in mosquitto python-publisher backend-api; do
  aws ecr put-lifecycle-policy \
    --repository-name sleep-monitor/${SERVICE} \
    --lifecycle-policy-text "${POLICY}" \
    --region ${AWS_REGION}
done
```

### 3. Authenticate and push

```bash
# Login (token expires after 12 hours)
aws ecr get-login-password --region ${AWS_REGION} \
  | docker login --username AWS --password-stdin \
      ${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Build and push (replace TAG with actual version)
TAG=v1.0.0
ECR=${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com

docker build -t ${ECR}/sleep-monitor/mosquitto:${TAG} ./mosquitto && \
docker push ${ECR}/sleep-monitor/mosquitto:${TAG}

docker build -t ${ECR}/sleep-monitor/python-publisher:${TAG} ./python-publisher && \
docker push ${ECR}/sleep-monitor/python-publisher:${TAG}

docker build -t ${ECR}/sleep-monitor/backend-api:${TAG} ./backend-api && \
docker push ${ECR}/sleep-monitor/backend-api:${TAG}
```

---

## CI/CD Pipeline (`.github/workflows/deploy.yml`)

The pipeline triggers when you push a git tag matching `v*.*.*`:

```bash
# Release a new version
git tag -a v1.2.0 -m "Release 1.2.0: add HRV classifier"
git push origin v1.2.0
# GitHub Actions automatically:
#   1. Builds all three images
#   2. Pushes to ECR with v1.2.0, sha-<SHA>, latest
#   3. SSHes into EC2 and runs docker compose up with the new tags
```

### Required GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user key with ECR push + EC2 SSH permissions |
| `AWS_SECRET_ACCESS_KEY` | Corresponding secret |
| `AWS_REGION` | e.g. `ap-southeast-1` |
| `AWS_ACCOUNT_ID` | Your 12-digit AWS account number |
| `EC2_HOST` | Public IP or DNS of your EC2 instance |
| `EC2_SSH_KEY` | Private SSH key (PEM) for the EC2 ubuntu user |
| `MQTT_PASSWORD` | Production MQTT broker password |
| `POSTGRES_PASSWORD` | Production database password |
| `JWT_SECRET` | Production JWT signing secret (32+ chars) |
| `DATABASE_URL` | Full RDS connection string |

---

## Rollback

### Fast rollback (incident response — no rebuild)

The previous image is already in ECR. SSH into EC2 and change the tag:

```bash
ssh ubuntu@your-ec2-host
cd /opt/sleep-monitor

# Replace v1.2.0 with the version you're rolling back from
# Replace v1.1.9 with the version you're rolling back to
sed -i 's|:v1.2.0|:v1.1.9|g' .env.production
docker compose --env-file .env.production up -d --no-build
```

### Tracked rollback (via git — rebuilds the image)

```bash
PREVIOUS_SHA=a1b2c3d   # commit SHA of the known-good version

git tag -a v1.1.9-rollback ${PREVIOUS_SHA} \
    -m "Rollback: revert to v1.1.9 due to classifier regression"
git push origin v1.1.9-rollback
# GitHub Actions builds and deploys this tag automatically
```

---

## Git Branching Strategy

```
main      ← Protected. Production deployments only.
           Never commit directly. All changes via PR.

develop   ← Integration branch. All features merged here first.
           CI runs on every push (lint, tests). No Docker build.

feature/* ← Short-lived feature branches from develop.
           e.g. feature/add-cognito-auth

hotfix/*  ← Emergency fixes branched from main.
           Merged back into both main AND develop.
```

### Semantic versioning

```
MAJOR.MINOR.PATCH

MAJOR — Breaking change to API schema or MQTT payload format.
         React Native app must be updated simultaneously.

MINOR — New feature (new endpoint, new MQTT topic). Backward compatible.

PATCH — Bug fix, config change, dependency update. No API changes.
```

---

## Environment Files

| File | Committed? | Purpose |
|---|---|---|
| `.env.example` | Yes | Documents all required keys with dummy values |
| `.env.development` | **No** | Local dev overrides — add to `.gitignore` |
| `.env.staging` | **No** | Staging environment — injected by CI |
| `.env.production` | **No** | Production on EC2 — created manually on server |

Production `.env.production` lives on the EC2 instance at `/opt/sleep-monitor/.env.production` and is never committed. The GitHub Actions pipeline updates the `*_IMAGE` lines in it on every deploy.
