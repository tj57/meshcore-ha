#!/usr/bin/env bash
# Requires: gh auth login   OR   GH_TOKEN set
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER=$(jq -r .version custom_components/meshcore/manifest.json)
TAG="v${VER}"
gh release delete "$TAG" --repo tj57/meshcore-ha --yes 2>/dev/null || true
gh release create "$TAG" --repo tj57/meshcore-ha --title "$TAG" --latest --notes "$(cat <<NOTES
## MeshCore HA ${TAG} (RC)

### Fixed
- battery/gps → err unsupported (SPEC §18)
- Public channel absolute silence when not in listen_channels
- Default listen/TX channel = mcCtrl (1)
- GitHub Release required for HACS Latest

See docs/DEVELOPMENT_RULES.md
NOTES
)"
echo "Release URL: https://github.com/tj57/meshcore-ha/releases/tag/${TAG}"
