#!/usr/bin/env bash
# check_dco.sh — Verify all commits in the PR range are signed (DCO)
# Usage: ./tools/check_dco.sh <head_sha>

set -euo pipefail

HEAD_SHA="${1:-HEAD}"
BASE_SHA="${GITHUB_BASE_REF:-main}"

# If running in GitHub Actions, get the merge-base
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  BASE_SHA=$(git merge-base origin/main "$HEAD_SHA" 2>/dev/null || echo "origin/main")
fi

echo "=== DCO Check ==="
echo "Range: $BASE_SHA..$HEAD_SHA"

# Check each commit in the range
UNSIGNED=0
while IFS= read -r commit; do
  if ! git log -1 --format="%G?" "$commit" | grep -q "^G$"; then
    # Also check for Signed-off-by trailer
    if ! git log -1 --format="%B" "$commit" | grep -qi "Signed-off-by:"; then
      echo "✗ Commit $commit is NOT signed (no Signed-off-by trailer)"
      UNSIGNED=1
    fi
  fi
done < <(git rev-list "$BASE_SHA..$HEAD_SHA" 2>/dev/null || git rev-list -n 50 "$HEAD_SHA")

if [ "$UNSIGNED" -eq 0 ]; then
  echo "✓ All commits signed (DCO)"
  exit 0
else
  echo ""
  echo "Fix: Re-sign commits with 'git commit --amend -s' or 'git rebase --signoff'"
  exit 1
fi