# Mesh node requests (Home Assistant)

Optional extension of the MeshCore integration. **Disabled by default** — existing
users see no change until they enable **Mesh node requests** under
**Configure → Global Settings**.

The wire protocol (mcRPC) is an **internal transport**. Automations should use the
Home Assistant services and events below — not protocol details.

See also [ARCHITECTURE_MCRPC.md](./ARCHITECTURE_MCRPC.md).

---

## Services (public)

### `meshcore.request` — preferred

```yaml
service: meshcore.request
data:
  target: tracker
  command: gps
  args: once
response_variable: gps
```

Then use `{{ gps.latitude }}`, `{{ gps.success }}`, etc.

| Field | Default | Notes |
|-------|---------|-------|
| `target` | — | Node name (required unless `broadcast`) |
| `command` | — | `ping`, `gps`, `battery`, `status`, `discover`, `caps`, `help`, … |
| `args` | — | Optional (`once`, `start`, `stop`, …) |
| `timeout` | settings | Seconds |
| `request_id` | auto | Correlation id |
| `broadcast` | false | Same as `meshcore.broadcast` |
| `channel` | settings | Channel index |
| `wait` | **true** | Return parsed reply (for `response_variable`) |

### `meshcore.broadcast`

```yaml
service: meshcore.broadcast
data:
  command: discover
response_variable: first
```

### `meshcore.raw` / `meshcore.send_mcrpc` (Advanced / Debug)

Send arbitrary channel text for testing:

```yaml
service: meshcore.raw
data:
  message: "all discover"
```

Prefer `request` / `broadcast` in real automations.

### Cache helpers

| Service | Purpose |
|---------|---------|
| `meshcore.list_nodes` | Cached discover / capabilities (no mesh traffic) |
| `meshcore.has_capability` | `has: true/false` for a node + capability |

```yaml
service: meshcore.has_capability
data:
  target: tracker
  capability: gps
response_variable: check
# {{ check.has }}
```

---

## Events

| Event | When |
|-------|------|
| `meshcore_response` | Reply or timeout |
| `meshcore_event` | Unsolicited device event (`button_pressed`, …) |

Legacy aliases `meshcore_mcrpc_response` / `meshcore_mcrpc_event` are still fired.

Example payload (GPS):

```yaml
node: tracker
command: gps
success: true
latitude: 50.12
longitude: 19.93
altitude: 12.5
speed: 0.0
heading: 90
hdop: 1.2
vdop: 1.5
fix: fix
extra: {}          # unknown future keys land here
raw: "gps lat=..."
request_id: 42
```

---

## Automations

### Sync (recommended)

```yaml
alias: Get GPS
sequence:
  - service: meshcore.request
    data:
      target: lw010
      command: gps
      args: once
    response_variable: gps
  - condition: template
    value_template: "{{ gps.success }}"
  - service: notify.persistent_notification
    data:
      message: "{{ gps.latitude }}, {{ gps.longitude }}"
```

### Async (event)

```yaml
alias: On mesh event
trigger:
  - platform: event
    event_type: meshcore_event
    event_data:
      event: button_pressed
action:
  - service: light.toggle
    target:
      entity_id: light.workshop
```

### Capability-gated

```yaml
sequence:
  - service: meshcore.broadcast
    data:
      command: discover
    response_variable: _
  - service: meshcore.has_capability
    data:
      target: tracker
      capability: gps
    response_variable: check
  - condition: template
    value_template: "{{ check.has }}"
  - service: meshcore.request
    data:
      target: tracker
      command: gps
    response_variable: gps
```

---

## Discover & capability cache

1. `discover` / `caps` replies update an in-memory **capability registry**.
2. `meshcore.list_nodes` and `meshcore.has_capability` read that cache — no extra airtime.
3. Feature flags from discover (`gps=yes`) count as capabilities.

Full Device Registry / entity auto-creation remains behind the experimental
entity bridge (off by default).

---

## Configuration

| Option | Default | User-facing meaning |
|--------|---------|---------------------|
| Enable mesh node requests | off | Master switch |
| Default timeout | 15 s | Wait for replies |
| Default channel | 0 | Channel for requests |
| Event bridge | on | Fire `meshcore_response` / `meshcore_event` |
| Debug logging | off | Extra logs |
| Entity bridge | off | Future entities (noop stub) |

Install the Python package once:

```bash
pip install -e /data/projects/mcrpc/python
```

---

## Compatibility

- Existing MeshCore messaging, entities, and services are unchanged when disabled.
- `meshcore.send_mcrpc` remains as an advanced/debug alias of `meshcore.raw`.
- Protocol grammar is not redesigned — only the HA-facing API.
