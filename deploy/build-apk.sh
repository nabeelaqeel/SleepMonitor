#!/usr/bin/env bash
# =============================================================
# Sleep Monitor — local APK build, no EAS
#
#   ./deploy/build-apk.sh                       # release APK → app/builds/
#   ./deploy/build-apk.sh --debug               # dev-client APK instead (pairs with `npx expo start`)
#   ./deploy/build-apk.sh --staging             # staging variant: applicationId com.aqeel.sleepmonitor.staging +
#                                               #   label "SleepMonitor Staging", baked env from eas.json build.staging.env
#   ./deploy/build-apk.sh --install             # adb install the built APK (may uninstall first)
#   ./deploy/build-apk.sh --env-file <file>     # bake EXPO_PUBLIC_* from a dotenv instead of eas.json preview
#   ./deploy/build-apk.sh --clean               # ./gradlew clean first (stale-cache rabbit holes)
#   ./deploy/build-apk.sh --yes                 # don't ask before uninstalling a mismatched install
#   ./deploy/build-apk.sh --dry-run             # pre-flight only: SDK check, baked endpoints, gradle plan
#
# Same artifact class as an EAS preview build, assembled on this machine —
# no queue, no credits, and the APK is kept in app/builds/ (named with its
# version + build time). EAS stays untouched: production later is still
# `eas build --profile production` → `eas submit`.
#
# Baked endpoints: EXPO_PUBLIC_* values are frozen into the APK's JS bundle
# at build time — the same mechanism app.config.js guards for EAS builds.
# Default source is the `preview` profile of app/eas.json, i.e. exactly
# what `eas build --profile preview` would bake. --env-file swaps in a
# dotenv file for LAN/dev-broker experiments (shell values override dotenv).
# JS-source freshness: gradle's up-to-date check misses JS-only edits in the
#   generated project — the app's JS/JSON sources are fingerprinted too and
#   force-invalidate the bundler outputs when that fingerprint moves.
#
# Staging variant (--staging): the same app built under applicationId
# com.aqeel.sleepmonitor.staging with launcher label "SleepMonitor Staging",
# so prod and staging APKs install SIDE-BY-SIDE on one device, each pointed
# at its own server (eas.json → build.staging.env). Mechanism: an idempotent
# gradle patch (productFlavors { staging { applicationIdSuffix ".staging" } }
# + app/src/staging res) applied to the GENERATED app/android/ right before
# the build and removed again for prod builds — `npx expo prebuild --clean`
# regenerates unflavored, and the next --staging run re-applies the patch.
#
# ⚠ app/android/ is a GENERATED, gitignored folder (root .gitignore line
#   "app/android"). `npx expo prebuild --clean` regenerates it INCLUDING a
#   fresh debug keystore — every phone running an older local build would
#   then need a one-off uninstall before installing again.
#   Keystore pinning: the registered SHA-1 (Google Android OAuth client) is
#   pinned by deploy/debug.keystore — copy it back over
#   app/android/app/debug.keystore after any prebuild (never regenerate).
#
# First build is slow (NDK C++ across 4 ABIs, gradle warms its cache);
# later rebuilds are minutes. Script never creates or rotates secrets —
# it READS the environment values that are already the EAS deploy source.
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/app"
ANDROID="$APP/android"
DRY=0; INSTALL=0; VARIANT="release"; VARIANT_CAP="Release"; CLEAN=0; ASSUME_YES=0; ENV_FILE=""
FLAVOR=""; FLAVOR_CAP=""   # staging variant (--staging); empty = prod/unflavored

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     DRY=1; shift ;;
    --install)     INSTALL=1; shift ;;
    --debug)       VARIANT="debug"; VARIANT_CAP="Debug"; shift ;;
    --staging)     FLAVOR="staging"; FLAVOR_CAP="Staging"; shift ;;
    --clean)       CLEAN=1; shift ;;
    --yes)         ASSUME_YES=1; shift ;;
    --env-file)    [ $# -ge 2 ] || { echo "--env-file needs a path argument" >&2; exit 2; }
                   ENV_FILE="$2"; shift 2 ;;
    --env-file=*)  ENV_FILE="${1#*=}"; shift ;;
    -h|--help)     sed -n '2,35p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }

# Mask secrets in the pre-flight print (same class of value app.config.js
# refuses to leak under EAS_BUILD — only keys whose name says PASSWORD).
mask_val() {
  local key="$1" value="$2"
  case "$key" in
    *PASSWORD*) printf '%s' "***" ;;
    *)          printf '%s' "$value" ;;
  esac
}

# ── staging flavor patch (see header) — idempotent, prebuild-safe ──
# `npx expo prebuild --clean` regenerates app/android/ unflavored, so the
# patch is (re-)applied before every --staging build and removed again for
# prod builds: :app:assembleRelease must keep existing unflavored.
ensure_staging_flavor() {
  python3 - "$ANDROID/app/build.gradle" <<'PY'
import re, sys
path = sys.argv[1]
src = open(path).read()

B_GRADLE = "// >>> staging flavor (deploy/build-apk.sh --staging): managed block"
E_GRADLE = "// <<< staging flavor (deploy/build-apk.sh): managed block end"
B_RNGP = "// >>> staging flavor rngp (deploy/build-apk.sh --staging): managed block"
E_RNGP = "// <<< staging flavor rngp (deploy/build-apk.sh): managed block end"

GRADLE_BLOCK = B_GRADLE + """
// `npx expo prebuild --clean` regenerates this file unflavored; the next
// --staging build re-applies this and prod builds remove it again so
// :app:assembleRelease keeps existing. Side-by-side install key: the
// staging applicationId is the prod package + ".staging".
flavorDimensions "server"
productFlavors {
    staging {
        dimension "server"
        applicationIdSuffix ".staging"
    }
}
""" + E_GRADLE

RNGP_BLOCK = B_RNGP + """
// RNGP only skips JS bundling for variants listed here; its default
// ("debug") matches no variant once flavors exist, which would bake a
// release bundle into stagingDebug as well.
debuggableVariants = ["stagingDebug"]
""" + E_RNGP

todo = []
for tag, b, e, anchor, block in [
    ("gradle", B_GRADLE, E_GRADLE, r"^android \{$", GRADLE_BLOCK),
    ("rngp", B_RNGP, E_RNGP, r"^react \{$", RNGP_BLOCK),
]:
    if b in src:
        if e not in src:
            sys.exit(f"staging flavor {tag} begin-marker without end-marker — fix build.gradle by hand")
        continue
    m = re.search(anchor, src, re.M)
    if not m:
        sys.exit(f"no {anchor!r} in build.gradle — prebuild template changed? not patching")
    src = src[:m.end()] + "\n" + block + src[m.end():]
    todo.append(tag)

if not todo:
    print("   staging flavor already applied to build.gradle — nothing to insert")
    sys.exit(0)
open(path, "w").write(src)
print(f"   patched app/android/app/build.gradle ({', '.join(todo)}): staging productFlavor + RNGP debuggableVariants [stagingDebug]")
PY
  mkdir -p "$ANDROID/app/src/staging/res/values"
  cat > "$ANDROID/app/src/staging/res/values/strings.xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<!-- staging flavor: overrides src/main app_name so the launcher shows
     "SleepMonitor Staging" next to the prod icon. Written by the
     build-apk.sh staging flow; a clean expo prebuild deletes it. -->
<resources>
    <string name="app_name">SleepMonitor Staging</string>
</resources>
XML
  say "   wrote app/src/staging/res/values/strings.xml (launcher label: SleepMonitor Staging)"
}

remove_staging_flavor() {
  [ -f "$ANDROID/app/build.gradle" ] || return 0
  python3 - "$ANDROID/app/build.gradle" <<'PY'
import sys
path = sys.argv[1]
src = open(path).read()
pairs = [
    ("// >>> staging flavor (deploy/build-apk.sh --staging): managed block",
     "// <<< staging flavor (deploy/build-apk.sh): managed block end"),
    ("// >>> staging flavor rngp (deploy/build-apk.sh --staging): managed block",
     "// <<< staging flavor rngp (deploy/build-apk.sh): managed block end"),
]
removed = 0
for b, e in pairs:
    while b in src:
        i = src.index(b)
        j = src.find(e, i)
        if j == -1:
            sys.exit("staging flavor begin-marker without end-marker — fix build.gradle by hand")
        j += len(e)
        nl = src.find("\n", j)
        j = nl + 1 if nl != -1 else len(src)
        src = src[:i] + src[j:]
        removed += 1
if removed:
    open(path, "w").write(src)
    print(f"   removed staging flavor patch ({removed} block(s)) from app/android/app/build.gradle")
PY
  rm -rf "$ANDROID/app/src/staging"
}

# ── sanity: tooling + the Expo project present ───────────────
[ -f "$APP/package.json" ] || die "app/package.json missing — wrong checkout?"
[ -d "$APP/node_modules" ] || die "app/node_modules missing — run 'npm install' in app/ first"
# app/android/ must exist BEFORE anything below touches it (the local.properties
# write would die with a raw redirect error under set -e, and the gradlew
# check further down would never be reached):
[ -d "$ANDROID" ] || die "app/android/ missing — generate it with 'npx expo prebuild --platform android' first (⚠ see the header note about the debug keystore)"
for tool in node python3 java; do
  command -v $tool >/dev/null 2>&1 || die "$tool not found on PATH — needed for this build"
done

# ── Android SDK discovery (private SDK, no sudo) ─────────────
SDK_ROOT="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
if [ ! -d "$SDK_ROOT/platforms" ]; then
  die "no Android SDK at $SDK_ROOT — bootstrap it with the cmdline-tools + sdkmanager, or ANDROID_HOME to point elsewhere"
fi
if [ ! -f "$ANDROID/local.properties" ] && [ "$DRY" = 0 ]; then
  printf 'sdk.dir=%s\n' "$SDK_ROOT" > "$ANDROID/local.properties"
  say "── wrote app/android/local.properties (sdk.dir=$SDK_ROOT)"
elif [ -f "$ANDROID/local.properties" ]; then
  say "── app/android/local.properties present ($(sed -n 's/^sdk.dir=//p' "$ANDROID/local.properties"))"
fi
[ -f "$SDK_ROOT/platforms/android-36/android.jar" ] || die "$SDK_ROOT misses platforms;android-36 — install the components this project pins (RN 0.81: build-tools 36.0.0, NDK 27.1.12297006)"

# ── baked environment: eas.json preview by default, --env-file to swap ──
declare -A BAKED=()
if [ -n "$ENV_FILE" ]; then
  [ -f "$ENV_FILE" ] || die "--env-file: $ENV_FILE not found"
  say "── baked EXPO_PUBLIC_* source: $ENV_FILE"
  while IFS= read -r line; do
    line="${line%$'\r'}"
    case "$line" in ''|\#*) continue ;; esac
    key="${line%%=*}"; value="${line#*=}"
    # dotenv files routinely quote values — strip EXACTLY ONE matching outer
    # pair so `EXPO_PUBLIC_API_URL="http://…"` bakes the bare URL instead of
    # literal quotes (which would poison the frozen endpoint + credentials).
    # Unquoted values pass through untouched.
    if [ "${#value}" -ge 2 ]; then
      fc="${value:0:1}"; lc="${value: -1}"
      if [ "$fc" = "$lc" ]; then
        case "$fc" in
          \"|\') value="${value:1:${#value}-2}" ;;
        esac
      fi
    fi
    case "$key" in EXPO_PUBLIC_*) BAKED[$key]="$value" ;; esac
  done < "$ENV_FILE"
else
  [ -f "$APP/eas.json" ] || die "app/eas.json missing (it is gitignored — restore it from eas.example.json, or use --env-file)"
  case "$FLAVOR" in
    staging) PROFILE="staging"; say "── baked EXPO_PUBLIC_* source: app/eas.json → build.staging.env (staging server)" ;;
    *)       PROFILE="preview"; say "── baked EXPO_PUBLIC_* source: app/eas.json → build.preview.env (same as an EAS preview build)" ;;
  esac
  while IFS=$'\t' read -r key value; do
    BAKED[$key]="$value"
  done < <(python3 - "$APP/eas.json" "$PROFILE" <<'PY'
import json, sys
src = json.load(open(sys.argv[1]))
env = src.get("build", {}).get(sys.argv[2], {}).get("env", {})
for k, v in env.items():
    if not isinstance(v, str):
        sys.exit(f"{k} is not a string — fix eas.json")
    print(f"{k}\t{v}")
PY
     )
fi
# a missing staging profile is its own error — the generic required-keys die
# below would bury it under a list of "misses":
if [ "$FLAVOR" = staging ] && [ "${#BAKED[@]}" -eq 0 ]; then
  die "app/eas.json has no build.staging.env — seed it (mirror eas.example.json's shape) or pass --env-file"
fi
if [ -n "$ENV_FILE" ]; then BAKED_SOURCE="$ENV_FILE"; else BAKED_SOURCE="app/eas.json build.${PROFILE}.env"; fi

# validate exactly what app.config.js enforces for EAS builds — a local
# build has NO EAS_BUILD, so the guard there never fires for us:
missing=""
for key in EXPO_PUBLIC_BROKER_IP EXPO_PUBLIC_API_URL EXPO_PUBLIC_MQTT_USER EXPO_PUBLIC_MQTT_PASSWORD EXPO_PUBLIC_ALLOW_PLAIN_HTTP; do
  [ -n "${BAKED[$key]:-}" ] || { missing="$missing $key"; }
done
[ -z "$missing" ] || die "baked env misses:$missing — fill the source (eas.json preview.env or the --env-file) before building"
for key in "${!BAKED[@]}"; do
  case "${BAKED[$key]}" in
    SET_ME_GOOGLE_CLIENT_ID)
      # a truthy-but-bogus client id must not bake: GOOGLE_CONFIGURED is
      # Boolean(GOOGLE_CLIENT_ID), so it would enable the Google button and
      # OAuth would fail at runtime — refuse until the real value lands.
      if [ "$DRY" = 1 ]; then
        say "   ⚠ EXPO_PUBLIC_GOOGLE_CLIENT_ID is the placeholder ('${BAKED[$key]}') — the REAL run will refuse:"
        say "     in Google Cloud Console create an OAuth client (Web application) with"
        say "     authorized redirect URI sleepmonitor:// and paste that client ID into"
        say "     ${BAKED_SOURCE} (the server .env must carry the SAME GOOGLE_CLIENT_ID),"
        say "     or remove the key from the profile to build email-only"
      else
        die "EXPO_PUBLIC_GOOGLE_CLIENT_ID is the placeholder ('${BAKED[$key]}') — in Google Cloud Console create an OAuth client (Web application) with authorized redirect URI sleepmonitor:// and paste that client ID into ${BAKED_SOURCE} (the server .env must carry the SAME GOOGLE_CLIENT_ID) — or remove the key from the profile to build email-only"
      fi
    ;;
    *SET_ME*|*SET\ ME*|"")
      die "$key is still a placeholder ('${BAKED[$key]}') — a locally built APK with dummy endpoints is useless"
    ;;
    *FROM_BOOTSTRAP*)
      # staged secrets are generated by bootstrap.sh on the server, never here;
      # dry-run still prints its plan, the real build refuses:
      if [ "$DRY" = 1 ]; then
        say "   ⚠ $key is the bootstrap placeholder ('${BAKED[$key]}') — the REAL run will refuse:"
        say "     run ./deploy/bootstrap.sh on the staging server and paste the value it"
        say "     prints into ${BAKED_SOURCE}, then rebuild"
      else
        die "$key is the bootstrap placeholder ('${BAKED[$key]}') — run ./deploy/bootstrap.sh on the staging server and paste the value it prints into ${BAKED_SOURCE}, then rebuild"
      fi
    ;;
  esac
done
# exported here: shell env beats any .env file the bundler loads, so these
# values are what actually gets frozen into the APK's JS bundle:
for key in "${!BAKED[@]}"; do
  say "   $key = $(mask_val "$key" "${BAKED[$key]}")"
done
for key in "${!BAKED[@]}"; do
  export "$key=${BAKED[$key]}"
done
say "── (exported — these exact values will be baked into the APK)"

# ── baked-env + JS-source fingerprint guards ─────────────────
# Endpoints are NOT gradle task inputs: editing eas.json alone leaves
# :app:createBundleReleaseJsAndAssets UP-TO-DATE (observed live: after the
# server IP change the APK still baked the old bundle). The fingerprint of
# the exact exported values is the validity signal — when it moves, the
# bundler's outputs AND its caches are force-invalidated so the new values
# re-bake; when it matches, none of this runs and rebuilds stay cheap.
# Same hazard for the JS SOURCES: gradle's up-to-date check misses JS-only
# edits in this generated-project flow (observed live: a context edit
# shipped the previous session's bundle until app/android/app/build was
# wiped by hand) — so the sources are fingerprinted too, with the same
# write-after-success stamp discipline, and invalidate the same outputs.
invalidate_bundle_outputs() {
  say "   (${1} — invalidating bundler outputs + metro cache:"
  say "    without this, the previously baked JS bundle ships again)"
  rm -rf "$ANDROID/app/build/generated/assets/createBundle${FLAVOR_CAP}${VARIANT_CAP}JsAndAssets"
  rm -rf "$ANDROID/app/build/intermediates/sourcemaps/react"
  rm -rf "$APP/node_modules/.cache"
  say "   ✓ bundler outputs and node_modules/.cache cleared — this assemble re-bakes your JS"
}
STAMP_FILE="$ANDROID/.baked-env-stamp"
CURRENT_FP="$(for key in $(printf '%s\n' "${!BAKED[@]}" | sort); do
                printf '%s=%s\n' "$key" "${BAKED[$key]}"
              done | sha256sum | cut -d' ' -f1)"
PREV_FP="$(cat "$STAMP_FILE" 2>/dev/null || true)"

# JS-source fingerprint: the tracked .js/.json files under app/ (node_modules/,
# android/, builds/ and the other ignored dirs hold no bundle inputs), plus
# app.json / app.config.js / package.json — already covered by the globs.
# NUL-delimited and sorted so the hash is order-stable; not a git checkout,
# fall back to find with the same artifact dirs pruned.
js_src_fingerprint() {
  (
    cd "$APP" || exit 1
    { if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git ls-files -z -- '*.js' '*.json'
      else
        find . \( -path ./node_modules -o -path ./android -o -path ./builds \
                  -o -path ./dist -o -path ./web-build -o -path ./.expo \) -prune \
            -o \( -name '*.js' -o -name '*.json' \) -type f -print0 \
            | sed -z 's|^\./||'
      fi; } | sort -z | xargs -0 -r sha256sum -- | sha256sum | cut -d' ' -f1
  )
}
STAMP_JS_FILE="$ANDROID/.baked-js-src-stamp"
CURRENT_JS_FP="$(js_src_fingerprint)" || die "could not fingerprint the app's JS/JSON sources — fix the checkout state, then re-run"
PREV_JS_FP="$(cat "$STAMP_JS_FILE" 2>/dev/null || true)"

if [ "$DRY" = 1 ]; then
  say "── baked-env fingerprint: ${CURRENT_FP:0:16}…"
  if [ -z "$PREV_FP" ]; then
    say "   no stamp yet — the real run invalidates the JS bundle BEFORE building:"
    say "   existing outputs here may have been baked with different env values"
  elif [ "$PREV_FP" != "$CURRENT_FP" ]; then
    say "   differs from the last build — the real run will invalidate the JS bundle so the new endpoints re-bake"
  else
    say "   matches the last build — no JS invalidation needed"
  fi
  say "── js-source fingerprint: ${CURRENT_JS_FP:0:16}…"
  if [ -z "$PREV_JS_FP" ]; then
    say "   no stamp yet — the real run invalidates the JS bundle BEFORE building:"
    say "   existing outputs here may have been baked from different JS sources"
  elif [ "$PREV_JS_FP" != "$CURRENT_JS_FP" ]; then
    say "   differs from the last build — the real run will invalidate the JS bundle so the edited sources re-bake"
  else
    say "   matches the last build — no JS invalidation needed"
  fi
else
  # Stamps are written only after a successful, artifact-producing build:
  # writing them up-front would record the new fingerprints even when Gradle
  # failed after the bundler outputs were cleared, and the next run would
  # then consider the (possibly stale) baked bundle valid.
  INVAL_REASON=""
  if [ "$PREV_FP" != "$CURRENT_FP" ]; then
    if [ -z "$PREV_FP" ]; then
      # No stamp does NOT mean a clean state: this android dir may pre-date
      # this script (EAS/hand builds, a stamp lost with app/android being
      # regenerated). Its bundle could carry OTHER values — invalidate it,
      # same recipe as the fingerprint-changed case.
      say "── no fingerprint stamp on this app/android — invalidating defensively before the first tracked build"
      INVAL_REASON="no baked-env stamp on this app/android"
    else
      say "── baked EXPO_PUBLIC_* changed since the last build (…${PREV_FP:0:16} → …${CURRENT_FP:0:16})"
      INVAL_REASON="baked EXPO_PUBLIC_* values are not gradle inputs"
    fi
  fi
  if [ "$PREV_JS_FP" != "$CURRENT_JS_FP" ]; then
    if [ -z "$PREV_JS_FP" ]; then
      say "── no JS-source stamp on this app/android — invalidating defensively before the first tracked build"
      INVAL_REASON="${INVAL_REASON:+$INVAL_REASON; }no JS-source stamp on this app/android"
    else
      say "── app JS sources changed since the last build (…${PREV_JS_FP:0:16} → …${CURRENT_JS_FP:0:16})"
      INVAL_REASON="${INVAL_REASON:+$INVAL_REASON; }app JS sources changed (gradle's up-to-date check misses JS edits in the generated project)"
    fi
  fi
  if [ -n "$INVAL_REASON" ]; then
    invalidate_bundle_outputs "$INVAL_REASON"
  fi
fi

# ── artifact naming + output dir ─────────────────────────────
VERSION="$(python3 -c "import json;print(json.load(open('$APP/app.json'))['expo']['version'])")" \
  || die "could not read expo.version from app/app.json"
PACKAGE="$(python3 -c "import json;print(json.load(open('$APP/app.json'))['expo']['android']['package'])")" \
  || die "could not read expo.android.package from app/app.json"
STAMP="$(date +%Y%m%d-%H%M)"
OUT_DIR="$APP/builds"
NAME="SleepMonitor-${VERSION}-${FLAVOR:+$FLAVOR-}${VARIANT}-${STAMP}.apk"
APK_SRC="$ANDROID/app/build/outputs/apk/${FLAVOR:+$FLAVOR/}$VARIANT/app-${FLAVOR:+$FLAVOR-}$VARIANT.apk"
GRADLE_TASK=":app:assemble${FLAVOR_CAP}${VARIANT_CAP}"
LATEST="SleepMonitor-latest.apk"; if [ -n "$FLAVOR" ]; then LATEST="SleepMonitor-${FLAVOR}-latest.apk"; fi
# the uninstall-on-mismatch path must target the variant actually installed:
INSTALL_PACKAGE="$PACKAGE"; if [ "$FLAVOR" = staging ]; then INSTALL_PACKAGE="${PACKAGE}.staging"; fi

if [ "$DRY" = 1 ]; then
  say "── [dry-run] plan:"
  say "   gradle task : $GRADLE_TASK  (variant $VARIANT$([ -n "$FLAVOR" ] && echo ", flavor $FLAVOR")$([ "$CLEAN" = 1 ] && echo ', with ./gradlew clean first'))"
  say "   APK source  : $APK_SRC"
  say "   saved copy  : $OUT_DIR/$NAME  (+ $OUT_DIR/$LATEST)"
  say "   install     : $(if [ "$INSTALL" = 1 ]; then echo "adb install -r (${ANDROID_SERIAL:-first connected device}, package $INSTALL_PACKAGE)"; else echo "skipped (no --install)"; fi)"
  if [ -n "$FLAVOR" ]; then
    if [ -f "$ANDROID/app/build.gradle" ] && grep -q "staging flavor (deploy/build-apk.sh" "$ANDROID/app/build.gradle"; then
      say "   flavor patch: already applied to the generated app/android — nothing to insert"
    else
      say "   flavor patch: will insert staging productFlavor + app/src/staging res before assembling"
    fi
  elif [ -f "$ANDROID/app/build.gradle" ] && grep -q "staging flavor (deploy/build-apk.sh" "$ANDROID/app/build.gradle"; then
    say "   flavor patch: staging flavor present in app/android — the real run removes it first (prod stays unflavored)"
  fi
  exit 0
fi

mkdir -p "$OUT_DIR"

# ── variant patch: insert for --staging, strip leftovers for prod ──
if [ -n "$FLAVOR" ]; then
  say "── staging variant: applying flavor patch to the generated app/android"
  ensure_staging_flavor
elif [ -f "$ANDROID/app/build.gradle" ] && grep -q "staging flavor (deploy/build-apk.sh" "$ANDROID/app/build.gradle"; then
  say "── prod build: removing leftover staging flavor patch (keeps :app:assembleRelease unflavored)"
  remove_staging_flavor
fi

# ── build ────────────────────────────────────────────────────
cd "$ANDROID"
[ ! -f gradlew ] && die "app/android/gradlew missing — regenerate with \`npx expo prebuild --platform android\` (⚠ see header note about the debug keystore)"
TO_RUN=(./gradlew "$GRADLE_TASK")
if [ "$CLEAN" = 1 ]; then
  say "── ./gradlew clean (.Clearing stale build outputs before the assemble)"
  run ./gradlew clean || die "gradlew clean failed"
fi
say "── building: ${TO_RUN[*]}  (first build compiles NDK C++ for 4 ABIs — be patient)"
run "${TO_RUN[@]}" || die "gradle build FAILED — the error above names the missing piece; re-run with the same command for the same logs"

[ -f "$APK_SRC" ] || die "gradle reported success but $APK_SRC is absent — inspect app/android/app/build/outputs/"

# fingerprint stamps: NOW (a real APK exists at $APK_SRC), not before Gradle ran
printf '%s\n' "$CURRENT_FP" > "$STAMP_FILE"
printf '%s\n' "$CURRENT_JS_FP" > "$STAMP_JS_FILE"

cp "$APK_SRC" "$OUT_DIR/$NAME"
cp "$APK_SRC" "$OUT_DIR/$LATEST"                  # stable name for adb install commands
SIZE="$(du -h "$OUT_DIR/$NAME" | cut -f1)"
SHA="$(sha256sum "$OUT_DIR/$NAME" | cut -c1-16)"
say "✔ built  $OUT_DIR/$NAME  ($SIZE, sha256 ${SHA}…)"
say "         also refreshed $OUT_DIR/$LATEST"

# ── optional install over adb ────────────────────────────────
if [ "$INSTALL" = 1 ]; then
  command -v adb >/dev/null 2>&1 || die "adb not on PATH — install/dk or add $SDK_ROOT/platform-tools"
  # `-s <serial>` is adb's GLOBAL option and must precede the subcommand —
  # `get-state -s` is invalid (and would leave $state empty under `|| true`);
  # adb also reads ANDROID_SERIAL on its own, so the guard is only for
  # disambiguating several connected devices:
  state="$(adb ${ANDROID_SERIAL:+-s "$ANDROID_SERIAL"} get-state 2>/dev/null || true)"
  [ "$state" = "device" ] || die "no connected android device (adb: ${state:-none}) — plug in with USB debugging, or skip --install"
  say "── installing over adb (device: ${ANDROID_SERIAL:-default})"
  if ! apk_install_out="$(adb install -r "$OUT_DIR/$NAME" 2>&1)"; then
    say "✗ adb install failed:"
    printf '%s\n' "$apk_install_out" | sed 's/^/      /'
    case "$apk_install_out" in
      *INSTALL_FAILED_UPDATE_INCOMPATIBLE*|*INSTALL_FAILED_VERSION_DOWNGRADE*)
        say "  (an existing install carries a different signing key / higher versionCode —"
        say "   e.g. the EAS-built app, or a build from a regenerated keystore)"
        if [ "$ASSUME_YES" = 1 ]; then
          say "── --yes used: uninstalling $INSTALL_PACKAGE then installing"
          run adb uninstall "$INSTALL_PACKAGE" || die "adb uninstall failed — uninstall the current app on the device once by hand, then re-run --install"
        else
          read -r -p "    uninstall app \"$INSTALL_PACKAGE\" (deletes its app-local data; login will be re-requested) [y/N]? " reply
          case "$reply" in
            [yY]*) run adb uninstall "$INSTALL_PACKAGE" || die "adb uninstall failed — remove the app once by hand, then re-run --install" ;;
            *) die "declined — refusing to uninstall without consent (use --yes to skip the ask in scripts)" ;;
          esac
        fi
        run adb install -r "$OUT_DIR/$NAME" || die "install failed even after uninstalling"
        ;;
      *) die "install failed with an unclassified error — see lines above (runbook §7)" ;;
    esac
  fi
  say "✔ installed on device"
else
  say "── install step skipped (pass --install to adb install right after)"
fi
