#!/usr/bin/env bash
# check_proposal_ref.sh — Verify PR description contains valid Approved-Proposal reference
# Usage: ./tools/check_proposal_ref.sh "<PR body>"

set -euo pipefail

BODY="${1:-}"

if echo "$BODY" | grep -qi "Approved-Proposal: UD-[0-9]\+"; then
  echo "✓ Found valid Approved-Proposal reference"
  echo "$BODY" | grep -i "Approved-Proposal:"
  exit 0
else
  echo "✗ PR description must contain 'Approved-Proposal: UD-###' (e.g., UD-001)"
  exit 1
fi