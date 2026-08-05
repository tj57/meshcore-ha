# Development rules (mandatory)

These rules apply to **mcrpc**, **MeshCore** (`mcrpc` branch), and **meshcore-ha**.

## Git history

- Author must always be **`tj57 <tj57@users.noreply.github.com>`**.
- Never add **`Co-authored-by: Cursor`** (or any Cursor / cursoragent trailer).
- Never rewrite the **entire** history of a fork.
- If commit cleanup is required, rewrite **only**:
  - `upstream/main..feature_branch`, or
  - `git format-patch` + `git am` onto a fresh branch from real `upstream/main`.
- Never run **`git filter-repo`** or **`git filter-branch`** against the complete
  upstream history (that makes GitHub show hundreds of fake “ahead” commits).

See also: [COMMIT.md](COMMIT.md) (meshcore-ha) / [development/COMMIT.md](../mcrpc/docs/development/COMMIT.md).

## Release

Every release requires **`release-check` PASS** before:

- git tag
- GitHub Release
- HACS publication

| Repo | Command |
|------|---------|
| mcrpc | `./scripts/release/check.sh` (alias: `./scripts/release-check`) |
| meshcore-ha | `./scripts/release-check` |

After tag push, a **GitHub Release** for that tag must exist so HACS
**Latest** matches **Installed**.

## Protocol / QA channels

- **Public** (channel index 0) is **never** used for positive testing.
- Exactly **one** negative Public test is allowed (secure-default deny).
- All protocol testing uses **`mcCtrl`** (typically channel index 1).

See [QA_CHANNEL_POLICY.md](QA_CHANNEL_POLICY.md).

## Protocol errors (SPEC §18)

| Situation | Wire reply |
|-----------|------------|
| No handler registered | `err unknown_command` |
| Handler registered, feature unavailable | `err unsupported` |

Examples: `battery` / `gps` on HA (no radio sensors) → `err unsupported`.
Truly unknown verbs → `err unknown_command`.

## Config entry migrations

Commits that change `CONFIG_ENTRY_VERSION` / `MINOR_VERSION` are
**migration-affecting changes**: include migration tests and keep HACS-installable
tips on the new schema (see [CONFIG_ENTRY_MIGRATION.md](CONFIG_ENTRY_MIGRATION.md)).
