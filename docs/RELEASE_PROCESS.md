# Release process (meshcore-ha fork)

## Gate

1. **`./scripts/release-check` must PASS**
2. Then tag
3. Then **GitHub Release** (Latest — not Draft, not Pre-release)
4. Then HACS users update (Installed == Latest)

## Version consistency

| Artifact | Must match |
|----------|------------|
| `custom_components/meshcore/manifest.json` → `version` | e.g. `2.10.1` |
| Git tag | `v2.10.1` |
| GitHub Release title/tag | `v2.10.1` |
| HACS Latest / Installed | `v2.10.1` |

## Steps

```bash
cd /data/projects/meshcore-ha
./scripts/release-check
# bump manifest if needed
git tag -a vX.Y.Z -m "meshcore-ha vX.Y.Z"
git push origin mcrpc main
git push origin vX.Y.Z
./scripts/create-github-release.sh   # requires gh auth / GH_TOKEN
```

Or rely on `.github/workflows/release.yml` **if Actions are enabled** on the fork.

## Checklist before calling Latest

- [ ] `release-check` PASS
- [ ] Tag exists on the intended commit
- [ ] GitHub Release published, Latest, not draft/prerelease
- [ ] Schema floor: ConfigEntry VERSION ≥ 4 on installable tips
- [ ] Stress methodology documented (no 100-burst gate)
- [ ] Public out of scope for mcRPC QA

## Related

- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md)
- [STRESS_METHODOLOGY.md](STRESS_METHODOLOGY.md)
- [CONFIG_ENTRY_MIGRATION.md](CONFIG_ENTRY_MIGRATION.md)
