#!/usr/bin/env bash
# =============================================================
# Sleep Monitor — deployment update (DEPLOYMENT.md §6.1, automated)
#
#   ./deploy/deploy-update.sh                 # git pull → compose up → verify
#   ./deploy/deploy-update.sh --skip-pull     # no git step (bootstrap uses this)
#   ./deploy/deploy-update.sh --allow-dirty   # proceed despite uncommitted edits
#   ./deploy/deploy-update.sh --ai-demo       # also run the AI demo band publisher
#                                             #   (compose profile ai-demo; sleep-ai-demo
#                                             #   joins the verified container list)
#   ./deploy/deploy-update.sh --repair-postgres-password
#                                             # TEST: point the postgres volume's
#                                             #   stored password at .env.development's
#                                             #   DSN (rows + MQTT creds untouched),
#                                             #   then continue with compose up + verify
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
REPAIR_PG=0
AI_DEMO=0
for arg in "$@"; do
  case "$arg" in
    --skip-pull)  SKIP_PULL=1 ;;
    --allow-dirty) ALLOW_DIRTY=1 ;;
    --ai-demo)    AI_DEMO=1 ;;
    --repair-postgres-password) REPAIR_PG=1 ;;
    -h|--help)    sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg (see header)"; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }

# DSN userinfo → raw bytes (URI %XX decode). The api's SQLAlchemy client
# unquotes the DSN password, so every value tested or patched against the
# volume must be the DECODED form. '+' stays LITERAL (RFC 3986 userinfo
# grammar — no x-www-form-urlencoded); invalid sequences ("%zz", trailing
# "%q") pass through untouched; a bare '\' survives the round-trip (it is
# doubled first, so printf %b cannot reinterpret the password's own bytes
# as \n/\t/... escape sequences).
decode_percent() {
  local s
  s="$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' \
                 -e 's/%\([0-9A-Fa-f][0-9A-Fa-f]\)/\\x\1/g')"
  printf '%b' "$s"
}

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
# --ai-demo: APPEND the demo profile to the mode's profile (never replace —
# TEST needs local-db alongside it, and dropping an enabled profile makes the
# next `compose up` REMOVE that profile's containers).
[ "$AI_DEMO" = 1 ] && PROFILE+=(--profile ai-demo)
say "── mode: $MODE (profile: ${PROFILE[*]:-none})"

# ── --repair-postgres-password (TEST): point the VOLUME at .env.development ──
# The reverse edit — rewriting .env.development to match the volume — would
# silently strand this server's app-side values (the printed MQTT/JWT block
# the phone was configured from). Instead the volume's role password becomes
# the CURRENT DSN password: rows, MQTT creds and the phone config all stay
# valid. ALTER runs on the pg container's socket (trust inside the container,
# by design of postgres:16-alpine) — the pw is never echoed, never rides any
# argv (the SQL reaches psql via stdin), and never crosses the network path
# the coherence check replays below.
# The extracted DSN password is percent-decoded first — the api replays the
# DSN with %XX unquoted, so the volume must store the decoded bytes — and the
# SQL literal is ' -doubled: even a hand-edited password carrying quotes /
# semicolons / $ ` \ bytes cannot terminate or extend the ALTER statement.
if [ "$REPAIR_PG" = 1 ]; then
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would ALTER sleep_user to the .env.development DSN password (inside sleep-postgres)"
  else
    [ "$MODE" = TEST ] || die "--repair-postgres-password applies to TEST mode only (DEMO/RDS passwords change at RDS — runbook §5)"
    docker ps -q --filter name='^sleep-postgres$' | grep -q . \
      || die "--repair-postgres-password needs sleep-postgres running — compose up first, then re-run"
    dbpw="$(sed -n 's#^DATABASE_URL=postgresql://sleep_user:\([^@]*\)@postgres:5432/sleep_monitor.*#\1#p' .env.development)"
    [ -n "$dbpw" ] || die "no TEST-shape DATABASE_URL password in .env.development — nothing to repair"
    dbpw="$(decode_percent "$dbpw")"
    q="'"; r="''"   # ' doubling inline (${dbpw//'/''}) misparses on bash 5.2+
    printf "ALTER USER sleep_user PASSWORD '%s';\n" "${dbpw//$q/$r}" \
      | docker exec -i sleep-postgres psql -U sleep_user -d sleep_monitor
    say "✔ postgres now accepts the .env.development DSN password (volume data untouched)"
  fi
fi

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
  say "[dry-run] would now verify: containers Up${pgcheck}, postgres DSN coherence (TEST), broker listener lines + websocket 101 + one MQTT read, and a /auth/login round-trip"
  exit 0
fi

# ── .env.development ⇆ initialized volume coherence (TEST only) ──
# The postgres_data volume stores the password of the bootstrap that FIRST
# initialized it; a server-side clone move (~/SleepMonitor → elsewhere) or a
# regenerated .env ships a DSN the volume rejects — the api then crash-loops
# at startup (psycopg2 "password authentication failed") and the deploy
# concludes with a confusing ✗ /auth/login unreachable. One readable line up
# front instead. The check replays the API'S OWN connection class — a psql
# client on the compose network reaching the `postgres` service name — since
# a shell inside the pg container reaches itself over 127.0.0.1/its socket
# where postgres:16-alpine is trust-auth (accepts ANY password; verified
# empirically) — only the network path discriminates.
postgres_dsn_coherence() {
  local dbpw="" pg_net=""
  dbpw="$(sed -n 's#^DATABASE_URL=postgresql://sleep_user:\([^@]*\)@postgres:5432/sleep_monitor.*#\1#p' .env.development)"
  if [ -z "$dbpw" ]; then
    say "⚠ DATABASE_URL is not the expected TEST shape — DSN coherence check skipped"
    return 0
  fi
  # the api replays the DSN with %XX unquoted — probe the DECODED value
  # ('+' stays literal: the userinfo grammar has no form-encoding):
  dbpw="$(decode_percent "$dbpw")"
  pg_net="$(docker inspect sleep-postgres --format '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || true)"
  if [ -z "$pg_net" ]; then
    say "⚠ sleep-postgres has no compose network — DSN coherence check skipped"
    return 0
  fi
  # the pw crosses by stdin only — the injected sh reads it straight into the
  # probe's own PGPASSWORD env; no argv, -e flag or inspect surface carries it:
  if printf '%s\n' "$dbpw" | docker run --rm -i --network "$pg_net" postgres:16-alpine \
       sh -c 'IFS= read -r pw || true; PGPASSWORD="$pw" psql -h postgres -U sleep_user -d sleep_monitor -tAc "SELECT 1"' \
       >/dev/null 2>&1; then
    say "✓ .env.development DSN accepted by the postgres volume (the api's auth path)"
    return 0
  fi
  say "✗ postgres REJECTED the .env.development DSN password — the postgres_data volume keeps the password of the bootstrap that FIRST initialized it;"
  say "  the api will crash-loop on psycopg2 'password authentication failed'. Data-preserving fix (rows + MQTT creds unchanged):"
  say "  ./deploy/deploy-update.sh --repair-postgres-password"
  return 1
}

# ── verify (matches runbook §6.1's checks) ───────────────────
EXPECTED=(sleep-broker sleep-api sleep-ingest sleep-publisher sleep-echo)
[ "$MODE" = TEST ] && EXPECTED+=(sleep-postgres)
[ "$AI_DEMO" = 1 ] && EXPECTED+=(sleep-ai-demo)

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
  postgres_dsn_coherence || die "postgres coherence failed — see the ✗ above (runbook §7)"
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
  # creds travel by stdin as the sub's config file — `-o` is mosquitto
  # 2.1's documented no-argv auth path ("…without the need to show the
  # username and password on the command line"), and the pinned sub has NO
  # --pwfile (verified). docker -i streams the two option lines, so no argv
  # / -e / inspect surface ever holds the value. .env values are line-based,
  # so the fed line is exactly one: whole-line value, taken verbatim.
  # -R drops retained messages: a retained sleep/recommendation would make a
  # silenced sleep-publisher look like live data flow on first (-C 1) read.
  data="$(printf '%s\n%s\n' "-u sm" "-P $mqpw" \
          | docker run --rm -i --network "container:$container" "$image" \
          timeout 6 mosquitto_sub -o /dev/stdin -h localhost -p 1883 -t 'sleep/#' \
          -R -C 1 -W 5 2>/dev/null || true)"
  if [ -n "$data" ]; then
    say "✓ MQTT data flowing (sample: ${data:0:56}…)"
  else
    say "✗ subscriber got no MQTT data in 5 s — publisher quiet or broker creds rejected; publisher log tail:"
    printf '%s\n' "$(docker logs sleep-publisher --tail 5 2>&1 || true)" | sed 's/^/      /'
    return 1
  fi
}

verify_broker || fail=1

# /auth/login round-trip — windowed for a COLD 1-vCPU server: all four python
# containers start together and uvicorn can lag behind that start burst for
# tens of seconds. 12 × (max-time 5 s + 3 s) ≈ a two-minute ceiling; fast
# exits stay: the FIRST structured response settles the probe (token →
# green). With the default SEED_DEMO_USERS=true a token proves bcrypt → api →
# ACTIVE database; with seeding off the demo account may not exist, so ANY
# structured response (a 401 body, say) already proves the api is up and the
# token check is skipped. sed -n ... p exits 0 even when the key is absent
# (grep under set -e would abort): a missing or empty SEED_DEMO_USERS then
# falls through to enabled, matching api/config.py's default — explicit
# false-like values disable.
login_roundtrip() {
  local container="${1:-sleep-api}" port="${2:-8000}"
  local resp="" rc=0

  # seed-aware (reads .env.development from the clone root — cwd contract);
  # like above, missing/empty key ⇒ enabled (api/config.py's default):
  seed="$(sed -n 's/^SEED_DEMO_USERS=//p' .env.development | tr -d ' ' | tr '[:upper:]' '[:lower:]')"
  case "$seed" in 1|true|yes|"") seeded=1 ;; *) seeded=0 ;; esac

  for _ in $(seq 1 12); do
    # every attempt starts verdict-clean: an early failure's rc must not
    # survive into the final diagnostic ("rc 7 refused" from a stale curl
    # would misname the transport cause of a later round)
    resp=""; rc=0
    resp="$(curl -sS --max-time 5 -X POST "http://localhost:$port/auth/login" \
              -H 'Content-Type: application/json' \
              -d '{"email":"patient@sleep.com","password":"1234"}' 2>/dev/null)" || rc=$?
    [ -n "$resp" ] && break
    sleep 3
  done

  if [ -n "$resp" ]; then
    if [ "$seeded" = 1 ]; then
      if printf '%s' "$resp" | grep -q '"token"'; then
        say "✓ /auth/login returned a token (bcrypt → api → active database OK)"
      else
        say "✗ /auth/login gave no token — check: docker logs $container --tail 20 (runbook §7)"
        return 1
      fi
    else
      say "✓ api reachable (SEED_DEMO_USERS disabled — token round-trip skipped)"
    fi
    return 0
  fi

  # nothing structured — say why from the transport's own verdict:
  case "$rc" in
    7)
      say "✗ /auth/login refused (curl rc 7): $container is down or restart-looping; state:"
      say "      $(docker inspect --format '{{.State.Status}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}' "$container" 2>/dev/null || echo '(inspect failed)')"
      if docker logs "$container" 2>&1 | grep -q 'password authentication failed for user'; then
        say "  (psycopg2 DSN mismatch — the postgres volume keeps the FIRST bootstrap's password;"
        say "   fix: ./deploy/deploy-update.sh --repair-postgres-password)"
      fi
      ;;
    28)
      say "✗ /auth/login timed out (curl rc 28): the port accepts TCP but never answered in 5 s × 12 tries — see the log tail"
      ;;
    *)
      say "✗ /auth/login unreachable (curl rc $rc)"
      ;;
  esac
  say "  $container log tail:"
  printf '%s\n' "$(docker logs "$container" --tail 6 2>&1 || true)" | sed 's/^/      /'
  return 1
}

login_roundtrip || fail=1

say ""
if [ "$fail" = 0 ]; then
  say "✔ deploy verified — every sleep-* container is Up, broker and auth respond."
else
  die "deploy verification FAILED (details above)"
fi
