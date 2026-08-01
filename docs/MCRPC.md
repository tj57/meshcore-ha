# Mesh node requests (Home Assistant)

Optional extension of the MeshCore integration. **Disabled by default**.

The wire protocol (mcRPC) is an **internal transport**. Automations use Home Assistant
services and events — not protocol details.

| Doc | Topic |
|-----|-------|
| This file | Services, events, cache, examples |
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
                    │  broadcast buckets    │
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

### Node Registry

Each node keeps: id, name, profile, capabilities, firmware, protocol, sdk, battery,
last_seen, RSSI, channel, discovered time, last status, extra fields.

Updated from **discover / status / battery / events**. Unknown keys → `extra`.

### Device Mapper

`NodeDeviceMapper.to_device_info(node)` builds a future HA `DeviceInfo` dict.
**No devices or entities are created yet.**

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

Fresh discover/status/battery/caps answers may be served from the **cache** (no radio).

### `meshcore.broadcast`

When `wait=true`, returns:

```yaml
responses:
  - source: tracker
    request_id: 7
    latency_ms: 312.5
    parsed: { ... }
    raw: "status name=tracker ..."
count: 2
success: true
```

### `meshcore.raw` / `meshcore.send_mcrpc` (Advanced)

Arbitrary channel text for debugging.

### Cache helpers

- `meshcore.list_nodes` — registry + device-mapper preview  
- `meshcore.has_capability` — capability check without parsing text  

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

Includes: connected, transport, channel, last RX/TX, known nodes, capabilities,
pending requests, timeouts, recent errors, parser statistics.

(Screenshots depend on your HA UI theme — use Download diagnostics.)

---

## Examples

See [`examples/automations/`](../examples/automations/):

| File | Purpose |
|------|---------|
| `ping.yaml` | Sync ping + notify |
| `gps.yaml` | GPS once + coordinates |
| `battery.yaml` | Periodic low-battery warn |
| `broadcast_status.yaml` | Multi-node `responses[]` |
| `capability_check.yaml` | discover → has gps → request |

### Sync GPS (inline)

```yaml
- action: meshcore.request
  data:
    target: lw010
    command: gps
    args: once
  response_variable: gps
- condition: template
  value_template: "{{ gps.success }}"
```

---

## Compatibility

- Existing MeshCore messaging/entities unchanged when node requests are off.
- Public service names unchanged; new fields (`parse`) are optional with defaults.
- Broadcast wait now returns `responses[]` (first reply still mirrored at top level).
