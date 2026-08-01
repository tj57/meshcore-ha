# mcRPC in MeshCore Home Assistant

Optional extension of the official [MeshCore](https://github.com/meshcore-dev/meshcore-ha)
integration. **Disabled by default** — existing users see no change until they enable it.

Protocol code lives in the standalone **[mcrpc](https://github.com/tj57/mcrpc)**
Python package (`python/`). This integration only bridges MeshCore channel text ↔ HA.

See also [ARCHITECTURE_MCRPC.md](./ARCHITECTURE_MCRPC.md).

---

## Architecture

```
meshcore.send_mcrpc
        → McRpcBridge (build request via mcrpc package)
        → MeshCore channel text
        → meshcore_message
        → McRpcBridge (parse via mcrpc)
        → meshcore_mcrpc_response / meshcore_mcrpc_event
```

| Piece | Responsibility |
|-------|----------------|
| `mcrpc` Python package | Parser, builder, status/discover/gps/battery helpers, correlator |
| `mcrpc_bridge.py` | Send on channel, correlate request IDs, fire HA events |
| `mcrpc_entity_bridge.py` | Future entity mapping (stub, off by default) |

---

## Configuration

**MeshCore → Configure → Global Settings**

| Option | Default | Meaning |
|--------|---------|---------|
| Enable mcRPC | off | Master switch |
| Default timeout | 15 s | Pending-request timeout |
| Default channel | 0 | Channel index for `send_mcrpc` |
| Event bridge | on (when mcRPC on) | Classify inbound channel text |
| Debug logging | off | Extra correlation logs |
| Entity bridge | off | Experimental stub — creates no entities |

Existing config entries do **not** need reconfiguration; new keys default safely.

### Dependency

```bash
pip install -e /data/projects/mcrpc/python
# or once published:
# pip install mcrpc
```

---

## Service API

### `meshcore.send_mcrpc`

| Field | Required | Notes |
|-------|----------|-------|
| `target` | unless `broadcast` | Node name |
| `command` | yes | `ping`, `status`, `discover`, `gps`, `battery`, `caps`, `help`, … |
| `arguments` | no | String or list (`once`, `start`, `stop`, `stream`, …) |
| `request_id` | no | Auto-assigned |
| `timeout` | no | Seconds |
| `broadcast` | no | Uses target `all` |
| `channel_idx` | no | Overrides default channel |
| `entry_id` | no | Multi-device |

Service response (optional): `{ raw_request, request_id, target, command, … }`.  
The **device reply** arrives as an event.

---

## Event API

### `meshcore_mcrpc_response`

Fired for replies and timeouts.

```yaml
source: tracker          # sender name when known
destination: ha          # original target when correlated
command: gps
request_id: 42
parameters: { latitude: 50.12, longitude: 19.93, ... }
timestamp: "..."
raw_message: "gps lat=..."
kind: gps                # or pong, status, discover, timeout, ...
error_code: null
channel_idx: 0
entry_id: "..."
```

### `meshcore_mcrpc_event`

Fired for unsolicited `event <name> [k=v…]` lines.

```yaml
event_name: button_pressed
parameters: { count: 3 }
raw_message: "event button_pressed count=3"
...
```

---

## Automation examples

### Ping

```yaml
alias: mcRPC ping tracker
trigger:
  - platform: time_pattern
    minutes: "/10"
action:
  - service: meshcore.send_mcrpc
    data:
      target: tracker
      command: ping
  - wait_for_trigger:
      - platform: event
        event_type: meshcore_mcrpc_response
        event_data:
          command: ping
    timeout: "00:00:15"
```

### GPS

```yaml
alias: Request GPS fix
sequence:
  - service: meshcore.send_mcrpc
    data:
      target: tracker
      command: gps
      arguments: once
  - wait_for_trigger:
      - platform: event
        event_type: meshcore_mcrpc_response
        event_data:
          command: gps
```

### Battery / status / discover

Same pattern with `command: battery`, `status`, or `discover` (often `broadcast: true` for discover).

---

## Future Entity Bridge

`mcrpc_entity_bridge.py` defines hooks (`handle_response`, `handle_event`) for later
mapping onto sensor / switch / button / device_tracker / binary_sensor. Keep disabled
until the entity model is designed for upstream.

---

## Migration

No migration required. Enabling mcRPC is opt-in via Global Settings.

---

## Upstream contribution notes

- Keep protocol implementation out of meshcore-ha (depend on `mcrpc`).
- Follow existing optional-feature patterns (`cli_console_enabled`, etc.).
- Prefer a dedicated service over overloading `execute_command`.
- Document events next to `docs/docs/events.md` when proposing upstream.
