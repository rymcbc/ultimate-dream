#!/usr/bin/env bash
# check_asset_licenses.sh — Verify every file under assets/ has a sibling LICENSE.txt
# Exits 1 if any asset folder lacks LICENSE.txt

set -euo pipefail

echo "=== Asset License Gate ==="

if [ ! -d "assets" ]; then
  echo "No assets/ directory — skipping"
  exit 0
fi

FAIL=0
# Find all directories under assets/ that contain files (non-recursive: each asset folder)
while IFS= read -r -d '' dir; do
  # Skip the root assets/ dir itself
  [ "$dir" = "assets" ] && continue

  # Check if this directory has any non-LICENSE.txt files
  if find "$dir" -maxdepth 1 -type f ! -name "LICENSE.txt" -print -quit | grep -q .; then
    if [ ! -f "$dir/LICENSE.txt" ]; then
      echo "✗ Missing LICENSE.txt in: $dir"
      FAIL=1
    else
      echo "✓ $dir has LICENSE.txt"
    fi
  fi
done < <(find assets -type d -print0)

if [ "$FAIL" -eq 0 ]; then
  echo "✓ All asset folders have LICENSE.txt"
  exit 0
else
  echo ""
  echo "Fix: Add a LICENSE.txt file to each asset folder declaring its license terms."
  exit 1
fi