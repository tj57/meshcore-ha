# Development rules (mandatory)

These rules apply to **mcrpc**, **MeshCore** (`mcrpc` branch), and **meshcore-ha**.

## Git

- Author is always **`tj57 <tj57@users.noreply.github.com>`**.
- Never add **`Co-authored-by: Cursor`** (or any Cursor / cursoragent trailer).
- Never rewrite the **complete** history of a fork.
- History cleanup is allowed **only** for:
  - `upstream/main..feature_branch`, or
  - `git format-patch` + `git am` onto a fresh branch from real `upstream/main`.
- Never run **`git filter-repo`** or **`git filter-branch`** against the complete
  upstream history.

See also: [COMMIT.md](COMMIT.md).

## Configuration (production HA)

Developer must **NEVER** modify the production Home Assistant configuration.

Developer must **NEVER** rename during development or automated tests:

- Home Assistant node
- production channels
- production PSKs

| Production field | Value |
|------------------|-------|
| Node name | **mcYogi** |
| Private channel | **mcYogi** |

Development tests must never leave production modified.

If temporary changes are required:

```text
backup → test → restore automatically
```

### Config Entry title vs device name

Do **not** rename the existing Config Entry. Keep the cosmetic title **`mcCtrl`**
for backward compatibility.

| Concept | Example | Notes |
|---------|---------|--------|
| Device / node name on air | `mcYogi` | Production identity |
| Config Entry title in HA | `mcCtrl` | Cosmetic; may differ — no migration |

Document only; no schema change required.

## QA

- Developer never generates prompts.
- Developer never modifies QA prompts.
- Developer only fixes code.

## Protocol / channels

- **Public is completely out of scope** for mcRPC.
- mcRPC does not use Public.
- QA must not transmit protocol commands on Public.
- Public Chat behaviour belongs to **MeshCore Chat**, not mcRPC.
- All mcRPC protocol testing uses the private channel / Config Entry setup
  (entry title may be `mcCtrl`; production node/channel names stay `mcYogi`).

See [QA_CHANNEL_POLICY.md](QA_CHANNEL_POLICY.md).

## Protocol errors (SPEC §18)

| Situation | Wire reply |
|-----------|------------|
| No handler registered | `err unknown_command` |
| Handler registered, feature unavailable | `err unsupported` |

## Release

**`release-check` is mandatory** before:

- git tag
- GitHub Release
- HACS publication

| Repo | Command |
|------|---------|
| mcrpc | `./scripts/release-check` |
| meshcore-ha | `./scripts/release-check` |

After the tag exists, a **GitHub Release** (Latest, not Draft, not Pre-release)
must be published so HACS **Latest** matches **Installed**.

See [RELEASE_PROCESS.md](RELEASE_PROCESS.md).

## Config entry migrations

Commits that change `CONFIG_ENTRY_VERSION` / `MINOR_VERSION` are
**migration-affecting changes**: include migration tests and keep HACS-installable
tips on the new schema ([CONFIG_ENTRY_MIGRATION.md](CONFIG_ENTRY_MIGRATION.md)).

## Stress

Use the **realistic stress methodology** only — never a 100-ping burst as a
pass/fail RF gate. See [STRESS_METHODOLOGY.md](STRESS_METHODOLOGY.md) and
MeshCore `doc/MCRPC_STRESS_TX_ANALYSIS.md`.
