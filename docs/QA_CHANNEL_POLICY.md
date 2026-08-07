# QA channel policy (mcRPC)

## Policy

| Channel | mcRPC / QA |
|---------|------------|
| **Private / lab-channel Config Entry path** | All protocol tests |
| **Public** (channel index 0) | **Out of scope** — do not use |

Public is completely out of scope for mcRPC.

- mcRPC does not use Public.
- QA must **not** transmit protocol commands on Public.
- Public Chat history and behaviour belong to **MeshCore Chat**, not mcRPC.

There is **no** negative Public-channel QA scenario. Such tests created
misleading Chat history and are removed from the release process.

## Production vs Config Entry title

| Field | Production value | Notes |
|-------|------------------|-------|
| Node / channel name | **ha-peer** | Never rename in tests |
| Config Entry title | **lab-channel** | Cosmetic; keep for compatibility |

Do not rename the Config Entry. Device name and entry title may differ.

## What to test on

- Chat / `meshcore.request` / stress / diagnostics on the private channel
  associated with the Config Entry (title may read `lab-channel`).
- Never change production PSKs or node names; use backup/restore if a disposable
  lab config is required.

## Related

- [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md)
- [PUBLIC_CHANNEL_PATH.md](PUBLIC_CHANNEL_PATH.md) — why Public Chat lines are not mcRPC
- [STRESS_METHODOLOGY.md](STRESS_METHODOLOGY.md)
