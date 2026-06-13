#!/usr/bin/env bash
set -euo pipefail

VERSION="v2.0.0"

if [[ "${CONFIRM_PUBLISH:-}" != "1" ]]; then
  echo "Dry run only. No git tag, push, or GitHub release was created."
  echo "Review RELEASE-v2.0.md and checksums.sha256 first."
  echo "To publish manually from a prepared git repository:"
  echo "  CONFIRM_PUBLISH=1 ./publish.sh"
  exit 0
fi

git status --short
git tag -a "$VERSION" -m "Skill Sublation $VERSION"
git push origin HEAD
git push origin "$VERSION"

if command -v gh >/dev/null 2>&1; then
  gh release create "$VERSION" --title "Skill Sublation $VERSION" --notes-file RELEASE-v2.0.md
else
  echo "gh CLI not found; create the GitHub release manually using RELEASE-v2.0.md."
fi
