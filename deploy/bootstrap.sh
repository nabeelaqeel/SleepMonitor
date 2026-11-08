#!/usr/bin/env bash
# =============================================================
# Sleep Monitor — one-shot bootstrap (server or laptop, TEST mode default)
#
# Replaces the hand-typed DEPLOYMENT.md §2.7–§2.10 (one command instead):
#   • .env.development rendered from an embedded template + generated secrets
#   • mosquitto/passwd built BEFORE the locked broker's first start (§2.9)
#   • 2 GiB swap, only on hosts that need it (t3.micro, §2.8)
#   • start + verify through ./deploy/deploy-update.sh --skip-pull
#   • prints the app-side values (app/.env.development + mosquitto_sub tap)
#
# Idempotent and credential-safe: an existing .env.development is NEVER
# overwritten (pass --force to deliberately regenerate ALL secrets — the
# mosquitto/passwd file is rebuilt to match, and the running broker restarted).
#
#   ./deploy/bootstrap.sh                      # TEST mode (local postgres)
#   ./deploy/bootstrap.sh --demo               # RDS mode: prompts endpoint +
#                                               #   password, applies the schema,
#                                               #   flips DATABASE_URL (runbook §2.5/§2.6)
#   ./deploy/bootstrap.sh --force              # regenerate .env.development + passwd
#   ./deploy/bootstrap.sh --rotate-mqtt-password
#   ./deploy/bootstrap.sh --no-start           # generate + passwd only
#   ./deploy/bootstrap.sh --ai-demo            # also start the AI demo band
#                                              #   publisher (compose profile ai-demo)
#   ./deploy/bootstrap.sh --dry-run            # print every action, write nothing
#   ./deploy/bootstrap.sh --ip 54.10.20.30     # override the printed broker IP
#
# Still manual by design: AWS console clicks (runbook §1, §2.1–§2.6) and the
# mobile EAS build (§4).
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY=0 FORCE=0 ROTATE=0 DEMO=0 NO_START=0 AI_DEMO=0 IP_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --force)FORCE=1 ;;
    --rotate-mqtt-password) ROTATE=1 ;;
    --demo) DEMO=1 ;;
    --no-start) NO_START=1 ;;
    --ai-demo) AI_DEMO=1 ;;
    --dry-run) DRY=1 ;;
    --ip) IP_OVERRIDE="${2:?--ip needs a value}"; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1 (see header)"; exit 2 ;;
  esac
  shift
done

say()  { printf '%s\n' "$*"; }
ok()   { printf '✔ %s\n' "$*"; }
warn() { printf '⚠ %s\n' "$*"; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }

# ── 0. sanity (mirrors runbook §2.1–§2.4 preconditions) ─────
command -v openssl >/dev/null || die "openssl missing — sudo apt-get install -y openssl"
command -v docker  >/dev/null || die "Docker missing — run runbook §2.1: sudo apt update && sudo apt install -y docker.io docker-compose-v2 postgresql-client"
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing — sudo apt install -y docker-compose-v2"
docker ps >/dev/null 2>&1 || die "docker unusable for this user — repeat runbook §2.2 (usermod -aG docker) and RE-SSH, or run with sudo"
[ -f docker-compose.aws.yml ] || die "docker-compose.aws.yml missing — not inside a full clone"
[ -f mosquitto/mosquitto.conf ] || die "mosquitto/mosquitto.conf missing — not inside a full clone"

# port holders: our own broker container is fine; a SYSTEM mosquitto would make
# compose fail later — say so now (README's one-time setup step 0):
own_broker="$(docker ps -q --filter name='^sleep-broker$' 2>/dev/null || true)"
if [ -z "$own_broker" ] && command -v ss >/dev/null 2>&1 && \
   ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE ':(1883|9001)$'; then
  warn "something already listens on 1883/9001 (a system mosquitto?):
         sudo systemctl disable --now mosquitto   — then re-run"
fi

# ── 1. .env.development: keep or generate (AWS §2.7) ─────────
MQPW=""
if [ -f .env.development ] && [ "$FORCE" != 1 ]; then
  say "── .env.development exists — keeping it (--force regenerates ALL secrets)"
  MQPW="$(grep '^MQTT_PASSWORD=' .env.development | cut -d= -f2- || true)"
  [ -n "$MQPW" ] || die "existing .env.development has no MQTT_PASSWORD — regenerate with --force"
  # --ai-demo on a kept env: append-only addition of the demo publisher's
  # MISSING keys (the same pair ships in the template for fresh bootstraps).
  # Idempotent — a second --ai-demo run appends nothing. Key-scoped on
  # purpose: appending the whole pair whenever only PATIENT_ID was missing
  # would clobber an already-configured AI_DEMO_INTERVAL (e.g. a faster
  # 15 s demo beat) with the 60 s default.
  if [ "$AI_DEMO" = 1 ]; then
    need_patient=1;  grep -q '^AI_DEMO_PATIENT_ID=' .env.development && need_patient=0
    need_interval=1; grep -q '^AI_DEMO_INTERVAL='   .env.development && need_interval=0
    need_list=""
    [ "$need_patient" = 1 ]  && need_list="AI_DEMO_PATIENT_ID"
    [ "$need_interval" = 1 ] && need_list="${need_list:+$need_list / }AI_DEMO_INTERVAL"
    if [ "$DRY" = 1 ]; then
      if [ -n "$need_list" ]; then
        say "[dry-run] would append $need_list to .env.development"
      fi
    elif [ -n "$need_list" ]; then
      {
        printf '\n# AI demo band publisher (compose profile ai-demo) — bootstrap --ai-demo added.\n'
        if [ "$need_patient" = 1 ]; then
          printf "# Must equal the app login's UUID (the seeded patient@sleep.com account).\n"
          printf 'AI_DEMO_PATIENT_ID=00000000-0000-0000-0000-000000000002\n'
        fi
        if [ "$need_interval" = 1 ]; then
          printf 'AI_DEMO_INTERVAL=60\n'
        fi
      } >> .env.development
      ok "$need_list appended to .env.development"
    fi
  fi
else
  DB_PW="$(openssl rand -hex 12)"
  JWT_SECRET="$(openssl rand -hex 32)"
  MQPW="$(openssl rand -hex 12)"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would write .env.development from the embedded template with generated secrets"
  else
    # Embedded template = the runbook's notes/deployment/env.template, minus
    # its prose (notes/ is author-local and NOT part of a clone). Markers are
    # replaced below; active lines must end marker-free (verified next step).
    cat > .env.development <<'SM_ENV'
# =============================================================
# Sleep Monitor — server runtime environment (generated by deploy/bootstrap.sh)
# The literal filename .env.development is hardcoded into every Python
# service (load_dotenv(".env.development")). Gitignored — never commit.
#
# MODES — exactly ONE active DATABASE_URL line:
#   TEST (default, below): the compose-network Postgres (host name `postgres`,
#     NEVER localhost). Runs from the --profile local-db container.
#   DEMO: AWS RDS over TLS — created per session (runbook §2.5), flipped by
#     ./deploy/bootstrap.sh --demo or by hand in §5.
# Secrets were generated at bootstrap time; rotate the broker one via
# ./deploy/bootstrap.sh --rotate-mqtt-password (rebuilds mosquitto/passwd).
# =============================================================

COMPOSE_PROJECT_NAME=sleep-monitor

DATABASE_URL=postgresql://sleep_user:<FILL_LOCAL_PASSWORD>@postgres:5432/sleep_monitor
# DATABASE_URL=postgresql://sleep_user:<FILL_RDS_PASSWORD>@<FILL_RDS_ENDPOINT>:5432/sleep_monitor?sslmode=require

# TEST-mode local database credentials (compose interpolation, --profile local-db)
# — POSTGRES_PASSWORD must equal <FILL_LOCAL_PASSWORD> in the active DATABASE_URL
POSTGRES_DB=sleep_monitor
POSTGRES_USER=sleep_user
POSTGRES_PASSWORD=<FILL_LOCAL_PASSWORD>

# >= 32 chars, NOT a change_me* placeholder — api/config.py refuses those (§7)
JWT_SECRET=<FILL_JWT_SECRET>
# demo accounts (patient@sleep.com / 1234) are seeded for evaluations; flip to
# false and provision your own via api.security.hash_password beyond the demo
SEED_DEMO_USERS=true

# the compose-network broker service name — python services run as
# containers; NEVER localhost inside a container (runbook §2.7)
MQTT_HOST=broker
MQTT_PORT=1883
# broker is LOCKED (allow_anonymous false) — parity with the AWS deployment
MQTT_USER=sm
MQTT_PASSWORD=<FILL_MQTT_PASSWORD>

INGEST_CLIENT_ID=sleep-ingest-001
SESSION_EXPIRY=3600
FLUSH_INTERVAL=1.0
FLUSH_MAX=50

PATIENT_ID=patient-001
PATIENT_UUID=00000000-0000-0000-0000-000000000002
DEVICE_ID=sleepband-001

# AI demo band publisher (compose profile ai-demo — ./deploy/deploy-update.sh
# --ai-demo starts it). AI_DEMO_PATIENT_ID must equal the app login's UUID —
# PATIENT_UUID above, the seeded patient@sleep.com account.
AI_DEMO_PATIENT_ID=00000000-0000-0000-0000-000000000002
AI_DEMO_INTERVAL=60

CSV_PATH=data/sleep_data_realistic.csv
PUBLISH_INTERVAL=1.0
LOOP_CSV=true
SM_ENV
    sed -i \
      -e "s/<FILL_LOCAL_PASSWORD>/$DB_PW/g" \
      -e "s/<FILL_JWT_SECRET>/$JWT_SECRET/g" \
      -e "s/<FILL_MQTT_PASSWORD>/$MQPW/g" \
      .env.development
    # commented DEMO line may carry markers (§2.5 flip later); ACTIVE lines may not:
    leftover="$(grep -c '^[^#]*<FILL' .env.development || true)"
    [ "$leftover" = "0" ] || die "$leftover marker(s) survived on active lines — aborting"
    chmod 600 .env.development
  fi
  if [ "$DRY" = 1 ]; then
    say "[dry-run] .env.development would be rendered (TEST mode; secrets generated, not committed)"
  else
    ok ".env.development written (TEST mode; secrets generated, not committed)"
  fi
fi

# ── 2. broker MQTT password rotation (only when asked) ───────
if [ "$ROTATE" = 1 ]; then
  old="$MQPW"; new="$(openssl rand -hex 12)"
  run sed -i "s|^MQTT_PASSWORD=$old$|MQTT_PASSWORD=$new|" .env.development
  MQPW="$new"
  ok "MQTT_PASSWORD rotated in .env.development (new value took effect above)"
fi

# ── 3. --demo: fill + flip DATABASE_URL to RDS (AWS §2.5/§2.6) ──
if [ "$DEMO" = 1 ]; then
  say "── DEMO mode: needs the RDS instance from runbook §2.5 (console) first"
  read -rp 'RDS endpoint (from the §2.5 console): ' RDS_ENDPOINT
  read -rsp 'RDS master password (§2.5): ' RDS_PW; say ""
  [ -n "$RDS_ENDPOINT" ] && [ -n "$RDS_PW" ] || die "endpoint + password are both required (--demo)"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] fill <FILL_RDS_*> markers, comment the TEST line, activate the RDS line"
    say "[dry-run] PGSSLMODE=require psql -h <endpoint> -U sleep_user -d sleep_monitor -f postgres/init/01_schema.sql"
  else
    # percent-encode the DSN password: a raw @ / or : inside the URL breaks
    # postgres URL parsing entirely; PGPASSWORD + the schema psql below keep
    # the RAW value (env vars and arguments are not URLs — do not encode there)
    enc_pw=""
    for ((i = 0; i < ${#RDS_PW}; i++)); do
      c="${RDS_PW:i:1}"
      case "$c" in
        [a-zA-Z0-9._~-]) enc_pw+="$c" ;;
        *) enc_pw+=$(printf '%%%02X' "'$c") ;;
      esac
    done
    # single-quoted | delimiter + encoded pw (only % and hex survive) and a
    # plain hostname → no sed metacharacters can corrupt either replacement:
    sed -i \
      -e "s|<FILL_RDS_ENDPOINT>|$RDS_ENDPOINT|g" \
      -e "s|<FILL_RDS_PASSWORD>|$enc_pw|g" \
      .env.development
    # swap the two DATABASE_URL lines (§5 flip block, automated):
    sed -i 's|^\(DATABASE_URL=postgresql://sleep_user:[^@]*\)@postgres:5432/sleep_monitor$|# \1@postgres:5432/sleep_monitor|' .env.development
    sed -i 's|^# \(DATABASE_URL=postgresql://sleep_user:[^@]*@[^@]*:5432/sleep_monitor?sslmode=require\)$|\1|' .env.development
    grep '^DATABASE_URL=' .env.development | grep -q '?sslmode=require' || die "DATABASE_URL flip failed — fix .env.development by hand (§2.7 cheat sheet)"
    leftover="$(grep -c '^[^#]*<FILL' .env.development || true)"
    [ "$leftover" = "0" ] || die "$leftover marker(s) on active lines after the RDS fill — aborting"
    chmod 600 .env.development
    command -v psql >/dev/null || die "psql missing — sudo apt install -y postgresql-client"
    PGSSLMODE=require PGPASSWORD="$RDS_PW" \
      psql -h "$RDS_ENDPOINT" -U sleep_user -d sleep_monitor \
      -f postgres/init/01_schema.sql >/dev/null
    ok "schema applied to $RDS_ENDPOINT (every fresh RDS gets it exactly once — §2.6)"
  fi
fi

# ── 4. mosquitto/passwd BEFORE the locked broker starts (§2.9) ──
if [ -f mosquitto/passwd ] && [ "$FORCE" != 1 ] && [ "$ROTATE" != 1 ]; then
  say "── mosquitto/passwd exists — keeping it (assumed to match MQTT_PASSWORD; --rotate-mqtt-password rebuilds)"
else
  [ -n "$MQPW" ] || die "no MQTT_PASSWORD available to write into mosquitto/passwd"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] docker run --rm -v mosquitto eclipse-mosquitto:2.1.2-alpine mosquitto_passwd -c -b /mosquitto/config/passwd sm <hidden>"
    say "[dry-run] chown 1883:1883 + chmod 600 mosquitto/passwd (via a throwaway container, so no sudo)"
  else
    # same pinned broker build as compose (passwd must stay in lockstep with
    # the image that will read it — see the pin rationale in docker-compose.aws.yml):
    docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2.1.2-alpine \
      mosquitto_passwd -c -b /mosquitto/config/passwd sm "$MQPW" >/dev/null
    # broker drops to its internal non-root user (uid 1883) and 2.1+ warns on
    # other ownership — validated recipe, done via container so it works on
    # the laptop (no sudoer requirement) AND the server (§2.9):
    docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2.1.2-alpine \
      sh -c 'chown 1883:1883 /mosquitto/config/passwd && chmod 600 /mosquitto/config/passwd'
  fi
  if [ "$DRY" = 1 ]; then
    say "[dry-run] mosquitto/passwd would be built via a throwaway container (owner=1883 mode=600)"
  else
    ok "mosquitto/passwd built (sm/<a real MQPW>; owner=1883 mode=600)"
  fi
fi

# ── 5. swap for 1 GiB hosts (§2.8 — the ONLY sudo in this script) ──
ram_mb="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 4096)"
swap_mb="$(free -m 2>/dev/null | awk '/^Swap/ {print $2; exit}' || echo 0)"
if [ "${ram_mb:-4096}" -ge 2000 ] || [ "${swap_mb:-0}" -ge 1900 ]; then
  say "── swap skipped (RAM ${ram_mb}MiB, swap ${swap_mb}MiB — enough)"
elif [ "$DRY" = 1 ]; then
  say "[dry-run] would create 2G /swapfile (fallocate+mkswap+swapon+fstab) via sudo"
else
  if \
    sudo fallocate -l 2G /swapfile      && \
    sudo chmod 600 /swapfile            && \
    sudo mkswap /swapfile    >/dev/null && \
    sudo swapon /swapfile               && \
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  then
    ok "2 GiB swapfile active (image-build headroom — §2.8)"
  else
    warn "swap could NOT be created (no sudo?) — if image builds OOM, run §2.8's five lines by hand"
  fi
fi

# ── 6. broker restart when rotation/force touched live creds ──
if [ "$ROTATE" = 1 ] || [ "$FORCE" = 1 ]; then
  if [ "$DRY" = 1 ]; then
    say "[dry-run] docker compose restart broker (a running broker keeps reading the OLD passwd file until restarted)"
  elif docker ps -q --filter name='^sleep-broker$' | grep -q .; then
    docker compose -f docker-compose.aws.yml --env-file .env.development restart broker >/dev/null
    ok "sleep-broker restarted (picked up its new password)"
  fi
fi

# ── 7. start + verify (single implementation lives in deploy-update.sh) ──
UP_FLAGS=()
[ "$AI_DEMO" = 1 ] && UP_FLAGS+=(--ai-demo)
# "${UP_FLAGS[@]}" on an EMPTY array errors under set -u on Bash 4.3 and
# older — the `[@]+"…[@]"` guard expands to nothing when empty and to the
# quoted list when non-empty, so both prints and both exec paths stay safe.
if [ "$NO_START" = 1 ]; then
  say "── start skipped (--no-start): ./deploy/deploy-update.sh --skip-pull${UP_FLAGS:+ --ai-demo} whenever you want it"
elif [ "$DRY" = 1 ]; then
  say "[dry-run] SM_BOOTSTRAP_DRY=1 ./deploy/deploy-update.sh --skip-pull${UP_FLAGS:+ --ai-demo} (compose up + verify)"
  SM_BOOTSTRAP_DRY=1 ./deploy/deploy-update.sh --skip-pull ${UP_FLAGS[@]+"${UP_FLAGS[@]}"}
else
  ./deploy/deploy-update.sh --skip-pull ${UP_FLAGS[@]+"${UP_FLAGS[@]}"}
fi

# ── 8. handoff: the values the *phone* side needs ─────────────
if [ -n "$IP_OVERRIDE" ]; then
  IP="$IP_OVERRIDE"
elif [ "$DRY" != 1 ] && TOKEN_PW="$(curl -fsS -m 2 -X PUT 'http://169.254.169.254/latest/api/token' -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null)" && [ -n "${TOKEN_PW:-}" ]; then
  # EC2: hostname -I prints only the PRIVATE address — the app needs PUBLIC
  IP="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $TOKEN_PW" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
fi
[ -n "${IP:-}" ] || IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "${IP:-}" ] || IP="<could not detect — pass --ip>"

MASK="[generated]"
hint_pw="${MASK}"; [ "$DRY" = 1 ] || hint_pw="$MQPW"
say ""
say "═══════════════ APP-SIDE VALUES (paste into app/.env.development) ═══════════════"
say "EXPO_PUBLIC_BROKER_IP=$IP"
say "EXPO_PUBLIC_API_URL=http://$IP:8000"
say "EXPO_PUBLIC_MQTT_USER=${MQTT_USER:-sm}"
say "EXPO_PUBLIC_MQTT_PASSWORD=$hint_pw"
say "EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true"
say ""
say "Verify from any other machine:"
say "  mosquitto_sub -h $IP -p 1883 -t 'sleep/#' -u sm -P '$hint_pw'"
say ""
say "Next: laptop → 'cd app && npx expo start' (README). APK → DEPLOYMENT.md §4 (EAS)."
say "═════════════════════════════════════════════════════════════════════════════"
