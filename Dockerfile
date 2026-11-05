# Sleep Monitor — ONE image for the four Python services
# (api, ingest, publisher, echo — compose assigns the command per service).
#
# Built from the repo root after each `git pull` — layer caching means
# nothing rebuilds unless code/requirements actually changed. No registry:
# the image is built on the server itself (one-host deployment, runbook §6.1).
#
# Base per project standard: Python 3.12 (matches the previous host venv)

FROM python:3.12-slim

WORKDIR /app

# Dependencies first (largest cacheable layer):
COPY api/requirements.txt api/requirements.txt
COPY ingest/requirements.txt ingest/requirements.txt
COPY publisher/requirements.txt publisher/requirements.txt
RUN pip install --no-cache-dir \
    -r api/requirements.txt \
    -r ingest/requirements.txt \
    -r publisher/requirements.txt

# Then the code:
COPY api/ api/
COPY ingest/ ingest/
COPY publisher/ publisher/

# The publisher reads the demo CSV at runtime (CSV_PATH env var):
COPY data/sleep_data_realistic.csv data/sleep_data_realistic.csv

# Container logs stream straight to stdout (visible via docker logs):
ENV PYTHONUNBUFFERED=1
