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
## MeshCore HA ${TAG} — mcRPC Protocol 1.2

### mcRPC 1.2
- Pin \`mcrpc@v1.2.1\` (wire \`v=1.2\`)
- Slim discovery: \`id=\` 8-hex, \`v=\`, \`up=\`, \`tag=\` — no protocol*/sdk/features on discover
- Rich status: \`id_full=\`, \`transport=\`, human \`up=\`
- Inbound \`call ns.action\` → CallResult (\`ok\` / \`err …\` kv-only); flat procs rejected
- Vendored Python SDK synced to 1.2

### Policy (unchanged)
- Public channel out of scope for mcRPC QA
- Default listen/TX = mcCtrl (1)

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
