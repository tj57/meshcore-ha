# MeshCore HA + mcRPC — Architecture Review

**Branch:** `mcrpc`  
**Upstream:** [meshcore-dev/meshcore-ha](https://github.com/meshcore-dev/meshcore-ha)  
**Protocol library:** [/data/projects/mcrpc](https://github.com/tj57/mcrpc) (Python under `python/`)

This document is the pre-implementation architecture review. mcRPC is an **optional additive**
extension; existing MeshCore behaviour must remain unchanged when mcRPC is disabled (default).

---

## Existing integration (unchanged core)

| Layer | Module | Role |
|-------|--------|------|
| Lifecycle | `__init__.py` | Connect, platforms, global SDK→HA event forward, services |
| Coordinator | `coordinator.py` | Poll / flush messages, contacts, repeater tasks |
| Transport | `meshcore_api.py` | USB / BLE / TCP via `meshcore-py` |
| Services | `services.py` + `services.yaml` | Public automation API |
| Events | `logbook.py`, `__init__.py` | `meshcore_message`, `meshcore_raw_event`, … |
| Entities | `sensor` / `binary_sensor` / … | Hub, contacts, messages, telemetry |
| Config | `config_flow.py` | Setup + options (mostly `entry.data`) |

**Message path:** SDK `MESSAGES_WAITING` → `get_msg()` → `CONTACT_MSG_RECV` /
`CHANNEL_MSG_RECV` → logbook → `meshcore_message`.

**Send path:** services → `api.mesh_core.commands.send_msg` / `send_chan_msg`.

Optional features already use **default-off** flags (`cli_console_enabled`,
`map_upload_enabled`, self diagnostics). mcRPC follows the same pattern.

---

## How node requests attach (additive)

```
HA automation / meshcore.request | broadcast | raw
        │
        ▼
McRpcBridge (custom_components/meshcore/mcrpc_bridge.py)
        │  uses pure-Python package `mcrpc` (internal transport)
        ▼
send_chan_msg(channel_idx, "tracker#42 gps")
        │
   MeshCore radio / channel text
        │
CHANNEL_MSG_RECV → meshcore_message
        │
McRpcBridge classifies (response | event) + capability cache
        │
        ▼
meshcore_response  /  meshcore_event
(+ legacy meshcore_mcrpc_* aliases)
```

| Concern | Location |
|---------|----------|
| Wire grammar / builders / parsers | **`mcrpc` Python package** (internal) |
| Channel send + wait + cache + HA events | `mcrpc_bridge.py` |
| Optional future entities | `mcrpc_entity_bridge.py` (stub, disabled) |
| Config toggles | Global settings (“mesh node requests”) |
| Public services | `request`, `broadcast`, `raw`, `list_nodes`, `has_capability` |
| Debug | `send_mcrpc` (= `raw`) |

---

## Compatibility rules

1. Default: `mcrpc_enabled=False` — no subscriptions, no behaviour change.
2. No replacement of existing entities or services.
3. No protocol duplication inside meshcore-ha.
4. Existing users keep config entries, devices, automations, diagnostics.

---

## First command wave

`ping`, `status`, `discover`, `gps` (+ start/stop/once args), `battery`, `caps`, `help`.

Parsed fields exposed on response events; unknown `key=value` pairs preserved.
