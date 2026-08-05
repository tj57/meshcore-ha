# Release checklist — meshcore-ha (mcRPC fork)

Mandatory before tag, GitHub Release, or HACS publication.

## Gate

- [ ] `./scripts/release-check` PASS
- [ ] Author `tj57` only (no Cursor co-author)
- [ ] Production HA config untouched (`mcYogi` node/channel unchanged)
- [ ] Public out of scope for mcRPC QA (no Public protocol TX)
- [ ] Stress uses [STRESS_METHODOLOGY.md](STRESS_METHODOLOGY.md) (no 100-burst gate)
- [ ] Config Entry title remains **mcCtrl** (cosmetic; may differ from device **mcYogi**)

## Version consistency

- [ ] `custom_components/meshcore/manifest.json` `version` matches intended release
- [ ] Git tag `vX.Y.Z` points at the intended commit
- [ ] GitHub Release published: **Latest**, not Draft, not Pre-release
- [ ] HACS Latest / Installed can match that tag

## Docs

- [ ] [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md)
- [ ] [QA_CHANNEL_POLICY.md](QA_CHANNEL_POLICY.md)
- [ ] [STRESS_METHODOLOGY.md](STRESS_METHODOLOGY.md)
- [ ] [RELEASE_PROCESS.md](RELEASE_PROCESS.md)
- [ ] [MCRPC.md](MCRPC.md) / README mcRPC section current

## Related

- mcrpc: `docs/RELEASE_CHECKLIST.md` + `./scripts/release-check`
- MeshCore: `doc/MCRPC_STRESS_TX_ANALYSIS.md`
