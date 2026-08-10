#!/usr/bin/env bash
# Pull the critique artifact from the CI run that produced it, and place it
# under review/ so gate.py can read it.
#
# The CI workflow posts the critique as a PR comment and uploads the JSON as an
# artifact, but nothing commits it. PROCESS.md requires review/ to be committed,
# so without this step the record lives only in GitHub's artifact retention and
# gate.py finds nothing.
#
# Retyping the critique from the PR comment would be hand-copying, which the
# conventions forbid for exactly the reason it applies here: the artifact is the
# authoritative text and a transcription is a new, unverified object.
#
# Usage:
#   scripts/fetch_critique.sh <PR_NUMBER> [TAG] [ROUND]
#
# Example:
#   scripts/fetch_critique.sh 1 P0 1
set -euo pipefail

PR="${1:?usage: fetch_critique.sh <PR_NUMBER> [TAG] [ROUND]}"
TAG="${2:-}"
ROUND="${3:-1}"
REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[fetch] downloading gpt-critique-${PR} from ${REPO}"
gh run download --repo "$REPO" -n "gpt-critique-${PR}" -D "$tmp"

test -s "$tmp/.critique.json" || {
  echo "[fetch] artifact has no .critique.json" >&2
  ls -R "$tmp" >&2
  exit 1
}

# The tag and round are in the payload; trust it over the arguments.
read -r PTAG PROUND < <(python3 -c "
import json,sys
d=json.load(open('$tmp/.critique.json'))
print(d['tag'], d['round'])
")
if [ -n "$TAG" ] && [ "$TAG" != "$PTAG" ]; then
  echo "[fetch] tag mismatch: argument ${TAG}, payload ${PTAG}" >&2
  exit 1
fi

mkdir -p review
cp "$tmp/.critique.json" "review/CRITIQUE_${PTAG}_r${PROUND}.json"
if [ -d "$tmp/review" ]; then
  cp -a "$tmp/review/." review/ 2>/dev/null || true
fi

echo "[fetch] wrote review/CRITIQUE_${PTAG}_r${PROUND}.json"
echo "[fetch] NEXT: write review/RESPONSE_${PTAG}_r${PROUND}.md, then"
echo "        .venv/bin/python scripts/gate.py --phase ${PTAG}"
