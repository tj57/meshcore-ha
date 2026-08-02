# Config entry migration

## Hard rule

`CONFIG_ENTRY_VERSION` in `custom_components/meshcore/const.py` is the single
source of truth for `MeshCoreConfigFlow.VERSION`.

**Never decrease this value.**

Home Assistant refuses to load a config entry when:

```text
entry.version > ConfigFlow.VERSION
```

That check runs before `async_migrate_entry()`. There is no recovery path inside
the integration if HACS (or a manual copy) installs an older build.

Deleting or recreating the user's config entry is **not** an acceptable fix.

## Why this broke twice

1. Branch `mcrpc` bumped the schema to **4** and migrated live entries to v4.
2. GitHub **default branch** stayed on `main`, and release tags such as `v2.9.0`
   still declared **VERSION = 3**.
3. HACS custom-repository updates follow the default branch and/or newest tag.
4. After an update, HA loaded VERSION=3 code against entries already at version 4
   and reported:

   `Config entry "…" for meshcore has version 4 which is higher than the current version 3.`

## Installable tips must stay consistent

These refs must always declare schema version ≥ the highest schema ever written
to field entries on this fork:

| Ref | Role |
|-----|------|
| `main` (default branch) | What HACS installs by default |
| `mcrpc` | Development branch (must match or exceed `main`) |
| Newest `v*` tag | What HACS may offer as a versioned update |

`upstream-sync` may track upstream `main` for merges; it must **not** be the
GitHub default branch and must **not** be what HACS users install.

## migration-affecting change

Every commit that changes `CONFIG_ENTRY_VERSION` or `MINOR_VERSION` is a
**migration-affecting change** and must:

1. Update `async_migrate_entry()` with a chained `if version == N` step (not
   `elif` that strands older entries).
2. Add or extend automated migration tests (see
   `tests/test_contact_discovery_migration.py` and
   `tests/test_hacs_config_entry_upgrade.py`).
3. Call out `migration-affecting change` in the commit message body.
4. Keep HACS-installable tips (`main`, newest tag) on the new schema in the
   **same** release train — never leave default branch / latest tag on an older
   schema after entries can already be at the new one.

## Release strategy (this fork)

1. Land schema changes on `mcrpc`.
2. Fast-forward `main` to `mcrpc` so the default branch never lags in schema.
3. Bump `manifest.json` `version` and tag `vX.Y.Z` from that tip so HACS cannot
   prefer an older tag with a lower schema.
4. Run `pytest tests/test_hacs_config_entry_upgrade.py` before tagging.
5. Do not publish HACS updates from upstream-only trees that still declare
   VERSION=3 after this fork has shipped VERSION=4.
