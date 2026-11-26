#!/usr/bin/env bash
# check_dco.sh — Verify all commits in the PR range are signed (DCO)
# Usage: ./tools/check_dco.sh <head_sha>
# Exempts: merge commits (commits with >1 parent) — they carry the merger's sign-off on squash-merge.

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
OFFENDING=()
while IFS= read -r commit; do
  # Skip merge commits (more than one parent) — they carry the merger's sign-off on squash-merge
  parent_count=$(git rev-list --parents -n 1 "$commit" | wc -w)
  if [ "$parent_count" -gt 2 ]; then
    echo "⊘ Commit $commit is a merge commit — exempt from DCO check"
    continue
  fi

  # Check for Signed-off-by trailer
  if ! git log -1 --format="%B" "$commit" | grep -qi "Signed-off-by:"; then
    # Get short sha and subject for the error message
    short_sha=$(git rev-parse --short "$commit")
    subject=$(git log -1 --format="%s" "$commit")
    OFFENDING+=("$short_sha $subject")
    UNSIGNED=1
  fi
done < <(git rev-list "$BASE_SHA..$HEAD_SHA" 2>/dev/null || git rev-list -n 50 "$HEAD_SHA")

if [ "$UNSIGNED" -eq 0 ]; then
  echo "✓ All commits signed (DCO)"
  exit 0
else
  echo ""
  echo "✗ The following commits lack a Signed-off-by trailer (DCO required):"
  for commit in "${OFFENDING[@]}"; do
    echo "  $commit"
  done
  echo ""
  echo "Fix: Re-sign commits with:"
  echo "  git rebase --signoff $BASE_SHA"
  echo ""
  echo "Note: Merge commits (with >1 parent) are exempt — they carry the merger's sign-off on squash-merge."
  exit 1
fi