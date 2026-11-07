#!/usr/bin/env bash
# =============================================================
# Sleep Monitor — deployment update (DEPLOYMENT.md §6.1, automated)
#
#   ./deploy/deploy-update.sh                 # git pull → compose up → verify
#   ./deploy/deploy-update.sh --skip-pull     # no git step (bootstrap uses this)
#   ./deploy/deploy-update.sh --allow-dirty   # proceed despite uncommitted edits
#
# CI seam (future): a deploy job is one line and changes nothing here —
#   ssh <host> 'cd /opt/SleepMonitor && ./deploy/deploy-update.sh'
# This script NEVER creates or rotates secrets: the server keeps its
# .env.development forever (generated once by ./deploy/bootstrap.sh).
#
# Mode-aware: reads the ACTIVE DATABASE_URL (same dispatch as runbook §6.2b) —
#   TEST (@postgres:5432)  → compose gets --profile local-db and the script
#                            waits up to 60 s for sleep-postgres [healthy]
#   DEMO (?sslmode=require) → no profile; the database is RDS
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Set when bootstrap.sh drives this script — same [dry-run] language, no writes.
DRY="${SM_BOOTSTRAP_DRY:-0}"
SKIP_PULL=0
ALLOW_DIRTY=0
for arg in "$@"; do
  case "$arg" in
    --skip-pull)  SKIP_PULL=1 ;;
    --allow-dirty) ALLOW_DIRTY=1 ;;
    -h|--help)    sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg (see header)"; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }

# ── sanity: a real checkout with a generated env ─────────────
[ -f docker-compose.aws.yml ] || die "docker-compose.aws.yml missing — run from the clone root"
if [ ! -f .env.development ]; then
  if [ "$DRY" = 1 ]; then
    say "── .env.development absent (a bootstrap --dry-run writes nothing): plan assumes TEST mode"
    PROFILE=(--profile local-db); MODE=TEST
    DSN="plan-only"
  else
    die ".env.development missing — run ./deploy/bootstrap.sh once first (secrets are NOT handled here)"
  fi
fi

# ── mode dispatch on the ACTIVE DATABASE_URL (§6.2b pattern) ──
if [ ! -f .env.development ]; then
  :   # dry-run plan above already chose TEST
else
  DB_URL="$(sed -n 's/^DATABASE_URL=//p' .env.development)"
  case "$DB_URL" in
    *'@postgres:5432/sleep_monitor'*)
      PROFILE=(--profile local-db); MODE=TEST ;;
    *':5432/sleep_monitor?sslmode=require'*)
      PROFILE=();                   MODE=DEMO ;;
    *) die "ACTIVE DATABASE_URL must select TEST (@postgres:5432) or DEMO (?sslmode=require) — see runbook §5" ;;
  esac
fi
say "── mode: $MODE (profile: ${PROFILE[*]:-none})"

# ── git step ─────────────────────────────────────────────────
if [ "$SKIP_PULL" = 1 ]; then
  say "── git: skipped (--skip-pull)"
elif [ ! -d .git ]; then
  # tarball/Option-B deployments (git archive) have no .git — the pull step is
  # meaningless there, so it is GENUINELY skipped instead of failing later:
  say "⚠ not a git checkout — skipping the pull entirely"
else
  if [ "$DRY" = 1 ]; then
    say "[dry-run] git fetch + dirty check + git pull --ff-only"
  else
    git fetch --all --quiet 2>/dev/null || say "⚠ git fetch failed (offline): continuing with local HEAD"
    if [ -n "$(git status --porcelain)" ] && [ "$ALLOW_DIRTY" = 0 ]; then
      say "Uncommitted changes:" >&2
      git status --short >&2
      die "uncommitted work would collide with the pull — commit/push first, or re-run with --allow-dirty"
    fi
    git pull --ff-only || die "pull would need a merge (non-ff history) — resolve by hand; deploys must stay fast-forward"
  fi
fi

# ── build + start everything server-side ─────────────────────
say "── compose up -d --build (image rebuild is cached: only changed layers)"
run docker compose -f docker-compose.aws.yml --env-file .env.development \
    "${PROFILE[@]}" up -d --build

if [ "$DRY" = 1 ]; then
  pgcheck=""; [ "$MODE" = TEST ] && pgcheck=" + sleep-postgres healthy"
  say "[dry-run] would now verify: containers Up${pgcheck}, broker listener lines + websocket 101 + one MQTT read, and a /auth/login round-trip"
  exit 0
fi

# ── verify (matches runbook §6.1's checks) ───────────────────
EXPECTED=(sleep-broker sleep-api sleep-ingest sleep-publisher sleep-echo)
[ "$MODE" = TEST ] && EXPECTED+=(sleep-postgres)

# sleep-postgres must reach EXACTLY "healthy" within 60 s ("unhealthy", or
# "starting" forever, must NOT satisfy this — §6.2b's rule):
if [ "$MODE" = TEST ]; then
  say "── waiting for sleep-postgres [healthy] (up to 60 s)"
  healthy=""
  for _ in $(seq 1 12); do
    state="$(docker inspect --format '{{.State.Health.Status}}' sleep-postgres 2>/dev/null || true)"
    [ "$state" = "healthy" ] && { healthy=1; break; }
    sleep 5
  done
  [ -n "$healthy" ] || die "sleep-postgres never reached healthy in 60 s — docker logs sleep-postgres"
fi

fail=0
for name in "${EXPECTED[@]}"; do
  state="$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || true)"
  if [ "$state" = "running" ]; then say "✓ $name running"; else say "✗ $name ($state)"; fail=1; fi
done

# ── broker: proof, not paperwork ─────────────────────────────
# The §6.1 check this replaces grepped ONE log line once and walked away —
# it could run before a slow bind flushed the line (declaring a healthy
# broker broken), and it never knew WHY when the line truly never arrived.
# Three layers instead, mirroring the app's own paths (args default to the
# production stack; tests drive the same function against probe fixtures):
#   (a) listener lines for BOTH ports, with a 30 s retry window;
#   (b) a websocket handshake on the published port — the phone's only
#       broker path (HTTP 101 = listener + websockets protocol really up;
#       curl then holds the open socket, so its exit 28 at --max-time is
#       the success path — the captured first header line is the verdict);
#   (c) one MQTT read inside the broker's netns — the publisher streams the
#       band every second, so received bytes prove passwd → auth → publish
#       → subscribe end to end, independent of host port bindings.
verify_broker() {
  local container="${1:-sleep-broker}"
  local image="${2:-eclipse-mosquitto:2.1.2-alpine}"
  local ws_port="${3:-9001}"
  local log="" seen=""
  local ws=""
  local mqpw="" data=""

  # (a) both listener lines in the log (broker may lag the "running" check):
  for _ in $(seq 1 10); do
    log="$(docker logs "$container" 2>&1 || true)"
    if grep -q 'listen socket on port 1883' <<<"$log" && \
       grep -q 'listen socket on port 9001' <<<"$log"; then
      seen=1; break
    fi
    sleep 3
  done
  if [ -z "$seen" ]; then
    say "✗ listener line(s) still absent after 30 s — broker log tail:"
    printf '%s\n' "$log" | tail -6 | sed 's/^/      /'
    if grep -qiE 'password-file|Unable to open pwfile' <<<"$log"; then
      say "  (password-file error — ./deploy/bootstrap.sh --rotate-mqtt-password rebuilds it; runbook §7)"
    else
      say "  (config/startup error shown above — runbook §7)"
    fi
    return 1
  fi
  say "✓ broker bound 1883 (TCP) + 9001 (websockets)"

  # (b) the published websocket port answers the phone's handshake:
  ws="$(curl -s -i --max-time 5 \
        -H 'Upgrade: websocket' -H 'Connection: Upgrade' \
        -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
        -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Protocol: mqtt' \
        "http://localhost:$ws_port/" 2>/dev/null | head -n1 || true)"
  if grep -q ' 101' <<<"$ws"; then
    say "✓ websocket 101 handshake on :$ws_port (the phone's path)"
  else
    say "✗ no websocket 101 on :$ws_port (first line captured: ${ws:-<nothing>}) — compose ports / SG next (runbook §7)"
    return 1
  fi

  # (c) live MQTT data inside the broker's netns (no host-port coupling:
  #     the netns sees the in-container 1883 directly).
  mqpw="$(sed -n 's/^MQTT_PASSWORD=//p' .env.development)"
  data="$(docker run --rm --network "container:$container" "$image" \
          timeout 6 mosquitto_sub -h localhost -p 1883 -t 'sleep/#' \
          -u sm -P "$mqpw" -C 1 -W 5 2>/dev/null || true)"
  if [ -n "$data" ]; then
    say "✓ MQTT data flowing (sample: ${data:0:56}…)"
  else
    say "✗ subscriber got no MQTT data in 5 s — publisher quiet or broker creds rejected; publisher log tail:"
    printf '%s\n' "$(docker logs sleep-publisher --tail 5 2>&1 || true)" | sed 's/^/      /'
    return 1
  fi
}

verify_broker || fail=1

# /auth/login round-trip (3 attempts: uvicorn may still be booting). With the
# default SEED_DEMO_USERS=true a token proves bcrypt → api → ACTIVE database;
# with seeding off the demo account may not exist, so ANY structured response
# (a 401 body, say) already proves the api is up and the token check is skipped.
# sed -n ... p exits 0 even when the key is absent (grep under set -e would
# abort): a missing or empty SEED_DEMO_USERS then falls through to enabled,
# matching api/config.py's default — explicit false-like values disable.
seed="$(sed -n 's/^SEED_DEMO_USERS=//p' .env.development | tr -d ' ' | tr '[:upper:]' '[:lower:]')"
case "$seed" in 1|true|yes|"") seeded=1 ;; *) seeded=0 ;; esac
resp=""
for _ in 1 2 3; do
  resp="$(curl -sS --max-time 10 -X POST http://localhost:8000/auth/login \
            -H 'Content-Type: application/json' \
            -d '{"email":"patient@sleep.com","password":"1234"}' 2>/dev/null || true)"
  [ -n "$resp" ] && break
  sleep 3
done
if [ -n "$resp" ]; then
  if [ "$seeded" = 1 ]; then
    if printf '%s' "$resp" | grep -q '"token"'; then
      say "✓ /auth/login returned a token (bcrypt → api → database OK)"
    else
      say "✗ /auth/login gave no token — check: docker logs sleep-api --tail 20 (runbook §7)"
      fail=1
    fi
  else
    say "✓ api reachable (SEED_DEMO_USERS disabled — token round-trip skipped)"
  fi
else
  say "✗ /auth/login unreachable — check: docker logs sleep-api --tail 20 (runbook §7)"
  fail=1
fi

say ""
if [ "$fail" = 0 ]; then
  say "✔ deploy verified — every sleep-* container is Up, broker and auth respond."
else
  die "deploy verification FAILED (details above)"
fi
