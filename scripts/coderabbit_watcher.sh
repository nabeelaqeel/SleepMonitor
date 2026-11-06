#!/usr/bin/env bash
# CodeRabbit review watcher — no-gh fallback for the CodeRabbit review loop
# (AGENTS.md). Polls the public GitHub API for new comments authored by
# coderabbitai on one PR and prints them as they arrive, so review rounds on
# a laptop without gh/token are still detected.
#
# Unauthenticated API allows 60 req/h; the watcher spends 2 req per poll,
# so the default interval of 150 s stays well inside the limit.
#
# Usage:
#   scripts/coderabbit_watcher.sh                 # watch PR for the current branch
#   scripts/coderabbit_watcher.sh 11              # watch PR #11
#   scripts/coderabbit_watcher.sh 11 120          # custom poll interval (s)
#
# Environment:
#   WATCHER_SHOW_ALL=1  print the existing coderabbit comment stream once
#                       at startup instead of only future comments.
#
# Stop with Ctrl-C.

set -u

INTERVAL="${2:-150}"
NAMESPACE="${1:-}"

# ── resolve owner/repo from any GitHub remote ────────────────────────────────
REPO_SLUG=""
for REMOTE in $(git remote); do
  URL="$(git remote get-url "$REMOTE")"
  SLUG="$(printf '%s' "$URL" | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+?)(\.git)?$#\1#')"
  case "$URL" in
    *github.com*) REPO_SLUG="$SLUG" ;;
  esac
done
if [ -z "$REPO_SLUG" ]; then
  echo "error: no GitHub remote found" >&2
  exit 1
fi

# ── resolve the PR number if not given (first open PR with this head branch) ─
if [ -z "$NAMESPACE" ]; then
  BRANCH="$(git branch --show-current)"
  PR_JSON="$(curl -s "https://api.github.com/repos/$REPO_SLUG/pulls?head=${REPO_SLUG%%/*}:${BRANCH}&state=open")"
  NAMESPACE="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["number"] if d else "")')"
  if [ -z "$NAMESPACE" ]; then
    echo "error: no open PR for branch '$BRANCH' on $REPO_SLUG" >&2
    exit 1
  fi
fi

echo "watching https://github.com/$REPO_SLUG/pull/$NAMESPACE for coderabbitai comments (every ${INTERVAL}s)"
echo "stop with Ctrl-C; a fresh review round prints here the moment it posts."
echo

# ── python payload: report new coderabbitai comments, bump the id state file ─
# Note: script goes via -c so stdin stays free for the curl data, and a
# transient API hiccup is swallowed (state untouched, retried next poll).
PY_MAIN='
import json, os, sys, textwrap

state_path = sys.argv[1]
picker = os.environ.get("REMOTE_PICKER", "")

try:
    raw = sys.stdin.read()
    items = json.loads(raw) if raw.strip() else []
    items = items if isinstance(items, list) else []
except Exception:
    sys.exit(0)  # transient API hiccup — retry next poll

last = int(open(state_path).read().strip())
new = [c for c in items
       if c.get("user", {}).get("login", "").startswith("coderabbitai")
       and c.get("id", 0) > last]

max_id = max([c.get("id", 0) for c in items] + [last])
open(state_path, "w").write(str(max_id))

for c in sorted(new, key=lambda x: x["id"]):
    body = (c.get("body") or "").strip()
    head = "\n".join(body.splitlines()[:45])
    print("[%s] %s id=%s — %s" % (c.get("created_at", ""), picker, c["id"], c.get("html_url", "")))
    print(textwrap.indent(head[:4000], "  | "))
    print()
'

# ── collect new coderabbitai comments for one collection endpoint ────────────
# State file holds the highest comment id already reported.
state_file="$(mktemp -t codrabit.XXXXXX)"
trap 'rm -f "$state_file"' EXIT

if [ "${WATCHER_SHOW_ALL:-0}" = "1" ]; then
  echo 0 > "$state_file"
else
  echo 999999999999 > "$state_file"  # high seed: first poll reports nothing
fi

new_for_kind() {
  # $1 = API collection URL, $2 = label for the report header
  curl -s "$1" | REMOTE_PICKER="$2" python3 -c "$PY_MAIN" "$state_file"
}

while true; do
  # commentary + walkthrough/review summary posts land as issue comments
  new_for_kind "https://api.github.com/repos/$REPO_SLUG/issues/$NAMESPACE/comments?per_page=100" "review comment"
  # inline path-tagged findings land as PR review comments
  new_for_kind "https://api.github.com/repos/$REPO_SLUG/pulls/$NAMESPACE/comments?per_page=100" "inline finding"
  sleep "$INTERVAL"
done
