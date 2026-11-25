#!/usr/bin/env bash
# check_file_sizes.sh — Enforce size gates:
# - No single file > 20 MB
# - No binary > 5 MB without LFS pointer

set -euo pipefail

echo "=== Size Gate ==="

MAX_FILE_MB=20
MAX_BINARY_MB=5
FAIL=0

# Files tracked by Git LFS
LFS_FILES=$(git lfs ls-files 2>/dev/null | awk '{print $3}' | sort -u || true)

# Check every file Git actually tracks (untracked and ignored paths - node_modules,
# build output - can never reach the repository, so scanning them only wastes time
# and produces false failures).
while IFS= read -r -d '' file; do
  # Skip if it's an LFS pointer (the actual file is small)
  if echo "$LFS_FILES" | grep -qxF "$file"; then
    continue
  fi

  SIZE=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
  SIZE_MB=$((SIZE / 1024 / 1024))

  # Check absolute max
  if [ "$SIZE_MB" -gt "$MAX_FILE_MB" ]; then
    echo "✗ File exceeds ${MAX_FILE_MB} MB: $file (${SIZE_MB} MB)"
    FAIL=1
    continue
  fi

  # Check binary threshold (heuristic: not text)
  if [ "$SIZE_MB" -gt "$MAX_BINARY_MB" ]; then
    if file "$file" | grep -qi "text\|script\|source\|json\|xml\|yaml\|markdown"; then
      : # Text file, OK
    else
      echo "✗ Binary file > ${MAX_BINARY_MB} MB without LFS: $file (${SIZE_MB} MB)"
      echo "  Fix: 'git lfs track \"$file\"' and commit the .gitattributes change"
      FAIL=1
    fi
  fi
done < <(git ls-files -z)

if [ "$FAIL" -eq 0 ]; then
  echo "✓ All files within size limits"
  exit 0
else
  exit 1
fi