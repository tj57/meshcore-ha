#!/usr/bin/env bash
# Create/update GitHub Release matching manifest.json version.
# Requires: gh auth login   OR   GH_TOKEN / GITHUB_TOKEN with repo scope
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER=$(jq -r .version custom_components/meshcore/manifest.json)
TAG="v${VER}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI required" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1 && [[ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]]; then
  echo "Not authenticated. Run: gh auth login" >&2
  echo "Or export GH_TOKEN with contents:write on tj57/meshcore-ha" >&2
  exit 1
fi

NOTES="$(cat <<NOTES
## MeshCore HA ${TAG} — broadcast reply jitter

### Fix
- Stagger auto-replies to \`all …\` (0.25–1.75 s + per-node slot) so the
  companion radio can RX peer answers (button) instead of TX-colliding
- Addressed replies stay near-immediate

### mcRPC 1.2 (unchanged)
- Pin \`mcrpc@v1.2.1\`, slim discovery / rich status / \`call\`

See docs/RELEASE_PROCESS.md / mcrpc RFC-0002
NOTES
)"

if gh release view "$TAG" --repo tj57/meshcore-ha >/dev/null 2>&1; then
  gh release edit "$TAG" --repo tj57/meshcore-ha --title "$TAG" --latest --notes "$NOTES"
  echo "Updated existing release $TAG"
else
  gh release create "$TAG" --repo tj57/meshcore-ha --title "$TAG" --latest --notes "$NOTES"
  echo "Created release $TAG"
fi
echo "Release URL: https://github.com/tj57/meshcore-ha/releases/tag/${TAG}"
