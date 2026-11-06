#!/usr/bin/env bash
# =============================================================
# Sleep Monitor — deployment update (DEPLOYMENT.md §6.1, automated)
#
#   ./scripts/deploy-update.sh                 # git pull → compose up → verify
#   ./scripts/deploy-update.sh --skip-pull     # no git step (bootstrap uses this)
#   ./scripts/deploy-update.sh --allow-dirty   # proceed despite uncommitted edits
#
# CI seam (future): a deploy job is one line and changes nothing here —
#   ssh <host> 'cd /opt/SleepMonitor && ./scripts/deploy-update.sh'
# This script NEVER creates or rotates secrets: the server keeps its
# .env.development forever (generated once by ./scripts/bootstrap.sh).
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
    die ".env.development missing — run ./scripts/bootstrap.sh once first (secrets are NOT handled here)"
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
else
  [ -d .git ] || { say "⚠ not a git checkout — skipping the pull"; }
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
  say "[dry-run] would now verify: containers Up${pgcheck}, broker socket 9001, and a /auth/login round-trip"
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

# broker socket: the log line only appears when BOTH listeners came up
if docker logs sleep-broker 2>&1 | grep -m1 -q 'Opening ipv4 listen socket on port 9001'; then
  say "✓ broker listening on 9001 (websockets) + 1883 (TCP)"
else
  say "✗ broker log lacks the port-9001 line — usually the passwd file (runbook §7)"
  fail=1
fi

# login round-trip: bcrypt-verified against the ACTIVE database, so a token
# also proves api → DB connectivity (3 attempts: uvicorn may still be booting)
token=""
for _ in 1 2 3; do
  resp="$(curl -sS --max-time 10 -X POST http://localhost:8000/auth/login \
            -H 'Content-Type: application/json' \
            -d '{"email":"patient@sleep.com","password":"1234"}' 2>/dev/null || true)"
  case "$resp" in *'"token"'*) token=1; break ;; *) sleep 3 ;; esac
done
if [ -n "$token" ]; then
  say "✓ /auth/login returned a token (api → database OK)"
else
  say "✗ /auth/login gave no token — check: docker logs sleep-api --tail 20 (runbook §7)"
  fail=1
fi

say ""
if [ "$fail" = 0 ]; then
  say "✔ deploy verified — every sleep-* container is Up, broker and auth respond."
else
  die "deploy verification FAILED (details above)"
fi
