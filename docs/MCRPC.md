# Mesh Node Requests (mcRPC) — Home Assistant

Optional extension of the MeshCore integration. **Disabled by default**.

The wire protocol (mcRPC) is an **internal transport**. Automations use Home Assistant
services and events — not protocol details. The protocol and public HA service API are
frozen; this document covers **configuration, security, diagnostics, and migration**.

| Doc | Topic |
|-----|-------|
| This file | Services, config, security, diagnostics, migration |
| [ARCHITECTURE_MCRPC.md](./ARCHITECTURE_MCRPC.md) | How the bridge attaches |
| [ROADMAP_MCRPC.md](./ROADMAP_MCRPC.md) | Done / next |
| [`examples/automations/`](../examples/automations/) | Ready-to-use YAML |

---

## Architecture

```
                    ┌─────────────────────────┐
                    │   Home Assistant API    │
                    │ request broadcast raw   │
                    │ list_nodes has_capability│
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼───────────┐
                    │     McRpcBridge       │
                    │  correlator · waiters │
                    │  McRpcPolicy (security)│
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
      Node Registry      Device Mapper     Diagnostics
      (in-memory)        (preview only)    (download)
              │
              ▼
         channel text  ←→  mcrpc package (internal)
```

Inbound answers use **McRpcPolicy** (listening channels, addressing, allowed senders)
and **reply identity** (which local radio sends the reply — multi-radio ready).

---

## Configuration

**Settings → Devices & Services → MeshCore → Configure → Mesh Node Requests (mcRPC)**

```
┌─ Mesh Node Requests (mcRPC) ─────────────────────────────┐
│ ☑ Enable Mesh Node Requests                              │
│ ☑ Answer inbound requests                                │
│ Listening channels:  [ Selected channels          ▾ ]    │
│ Selected channels:   ☑ Channel 1 (mcYogi)                │
│                      ☐ Channel 0 (Public)                │
│ Default TX / current channel index:  1                   │
│ ☑ Accept broadcast (all …)                               │
│ ☑ Accept addressed commands                              │
│ ☐ Accept bare commands                                   │
│ Allowed senders:     [ Any node                   ▾ ]    │
│ Allow list:          (names / IDs, one per line)         │
│ Reply identity:      [ This radio (HomeHA)        ▾ ]    │
│ Timeout / events / debug …                               │
└──────────────────────────────────────────────────────────┘
```

### Listening channels

| Mode | Behaviour |
|------|-----------|
| Disabled | Do not accept inbound mcRPC |
| Current channel | Listen on the default TX channel index |
| Selected channels | Listen on chosen indexes only (UI shows names; **indexes stored**) |
| All channels | Listen on every channel |

### Accepted addressing

| Option | Default | Meaning |
|--------|---------|---------|
| Broadcast | Enabled | `all …` requests |
| Addressed | Enabled | Named / self targets for this HA node |
| Bare | **Disabled** | Command-only lines without a target |

### Allowed senders

| Mode | Meaning |
|------|---------|
| Any node | No sender filter |
| Contacts only | Sender must be a known contact name |
| Allow list | Sender name/ID must appear in the allow list |

### Reply identity

Select which MeshCore config entry / radio identity sends answers.
Today typically **This radio**; architecture supports multiple local radios later.

---

## Security defaults

For **new** installs (or never-enabled mcRPC):

- Do **not** listen on Public (channel 0) until you select it
- Do **not** answer bare commands
- Only answer on configured private / selected channels
- Only answer addressed or broadcast (when those toggles are on)

Existing installs that already had mcRPC enabled are migrated to keep working
(see [Migration](#migration)).

---

## Services

### `meshcore.request`

| Field | Default | Notes |
|-------|---------|-------|
| `target` | — | Required unless `broadcast` |
| `command` | — | ping, gps, battery, status, discover, … |
| `args` | — | Optional |
| `timeout` | settings | Seconds |
| `request_id` | auto | |
| `broadcast` | false | |
| `channel` | settings | |
| `wait` | **true** | `false` = fire-and-forget |
| `parse` | **true** | `false` = raw fields only |

### `meshcore.broadcast` / `meshcore.raw` / `meshcore.send_mcrpc`

Unchanged public API (backward compatible).

### Cache helpers

- `meshcore.list_nodes`
- `meshcore.has_capability`

---

## Events

| Event | Meaning |
|-------|---------|
| `meshcore_response` | Reply or timeout |
| `meshcore_event` | Unsolicited device event |

Legacy `meshcore_mcrpc_*` aliases still fire.

---

## Diagnostics

**Settings → Devices & Services → MeshCore → Download diagnostics**

Includes:

| Field | Description |
|-------|-------------|
| Enabled | Feature on/off |
| Listening channels | Indexes or `all` |
| Accepted addressing | broadcast / addressed / bare |
| Allowed senders mode | any / contacts / allowlist |
| Pending requests | In-flight correlator entries |
| Known nodes | Node Registry snapshot |
| Average RTT | Mean latency of matched replies |
| Packet loss | Estimated from wait timeouts vs matches |
| Last RX / Last TX | Most recent traffic |
| Parser errors | Unparseable inbound lines |

---

## Migration

Config entry **version 4** adds the Mesh Node Requests section.

| Prior state | After migration |
|-------------|-----------------|
| `mcrpc_enabled=false` (or unset) | Secure defaults: selected channels empty, bare off |
| `mcrpc_enabled=true` | Selected channels = previous `mcrpc_channel` (even if 0); bare **on** to preserve prior behaviour |

No reconfiguration is required. Old keys (`mcrpc_enabled`, `mcrpc_timeout`,
`mcrpc_channel`, …) remain valid.

---

## Examples

See [`examples/automations/`](../examples/automations/).

---

## Compatibility

- Existing MeshCore messaging/entities unchanged when node requests are off.
- Public service names unchanged; new fields (`parse`) are optional with defaults.
- Broadcast wait returns `responses[]` (first reply still mirrored at top level).
