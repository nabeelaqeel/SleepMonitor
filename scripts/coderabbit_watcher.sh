#!/usr/bin/env bash
# CodeRabbit review watcher — no-gh fallback for the CodeRabbit review loop
# (AGENTS.md). Polls the public GitHub API for new comments authored by
# coderabbitai on one PR and prints them as they arrive, so review rounds on
# a laptop without gh/token are still detected.
#
# Unauthenticated API allows 60 req/h; the watcher walks 1 page per endpoint
# per poll while the thread fits one page (longer threads walk up to 10),
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

# ── python payload: walk the endpoint's pages, report new coderabbitai ───────
# comments, bump the per-endpoint watermark file.
# Note: script goes via -c (bash keeps no stdin), requests carry a single
# socket-level time bound so a stalled call can't block the poll, and any
# transient/rate-limit error is swallowed — state stays untouched and the next
# interval retries.
PY_MAIN='
import json, os, sys, textwrap, urllib.request

state_path = sys.argv[2]
picker = os.environ.get("REMOTE_PICKER", "")

def http_get_json(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "sleepmonitor-coderabbit-watcher",
    })
    with urllib.request.urlopen(req, timeout=25) as r:  # connect + read ≤ 25 s
        return json.load(r)

items, page = [], 0
try:
    while page < 10:  # cap: 10 pages x 100 comments — more than any PR thread
        page_url = sys.argv[1] if page == 0 else "%s&page=%d" % (sys.argv[1], page + 1)
        got = http_get_json(page_url)
        items.extend(got if isinstance(got, list) else [])
        if len(got) < 100:
            break
        page += 1
except Exception:
    sys.exit(0)

new = [c for c in items
       if c.get("user", {}).get("login", "").startswith("coderabbitai")
       and c.get("id", 0) > int(open(state_path).read().strip())]

max_id = max([c.get("id", 0) for c in items] + [int(open(state_path).read().strip())])
open(state_path, "w").write(str(max_id))

for c in sorted(new, key=lambda x: x["id"]):
    body = (c.get("body") or "").strip()
    head = "\n".join(body.splitlines()[:45])
    print("[%s] %s id=%s — %s" % (c.get("created_at", ""), picker, c["id"], c.get("html_url", "")))
    print(textwrap.indent(head[:4000], "  | "))
    print()
'

# ── per-endpoint watermarks: one state file each, so one endpoint can never ──
# advance the other's id past a comment it has not reported.
state_dir="$(mktemp -d -t codrabit.XXXXXX)"
trap 'rm -rf "$state_dir"' EXIT

init_state() {
  if [ "${WATCHER_SHOW_ALL:-0}" = "1" ]; then
    echo 0 > "$1"
  else
    echo 999999999999 > "$1"  # high seed: first successful response records the
  fi                           # current max id and reports nothing historic
}
init_state "$state_dir/issue"
init_state "$state_dir/review"

new_for_kind() {
  # $1 = watermark state file, $2 = report label, $3 = collection URL
  REMOTE_PICKER="$2" python3 -c "$PY_MAIN" "$3" "$1"
}

while true; do
  # commentary + walkthrough/review summary posts land as issue comments
  new_for_kind "$state_dir/issue" "review comment" \
    "https://api.github.com/repos/$REPO_SLUG/issues/$NAMESPACE/comments?per_page=100"
  # inline path-tagged findings land as PR review comments
  new_for_kind "$state_dir/review" "inline finding" \
    "https://api.github.com/repos/$REPO_SLUG/pulls/$NAMESPACE/comments?per_page=100"
  sleep "$INTERVAL"
done
