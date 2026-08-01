# Mesh node requests — roadmap

## Done (this stage)

- [x] Public HA API: `request` / `broadcast` / `raw` / cache helpers
- [x] Events: `meshcore_response` / `meshcore_event`
- [x] Sync `response_variable` (`wait=true` default)
- [x] Node Registry (in-memory)
- [x] Device mapper abstraction (no entity creation)
- [x] Broadcast `responses[]` with latency
- [x] `parse=false` / `wait=false`
- [x] Cache TTL for discover / caps / status / battery
- [x] Config entry Diagnostics page payload

## Next

- [ ] Optional HA Device Registry registration (via Device Mapper)
- [ ] Optional entities (sensor / device_tracker) behind entity bridge
- [ ] Persist Node Registry across restarts
- [ ] Per-node cache TTL overrides in UI
- [ ] Multi-entry inbound message scoping (`entry_id` on channel events)
- [ ] Publish `mcrpc` to PyPI and pin in `manifest.json`

## Non-goals

- Redesigning the wire protocol
- Breaking existing MeshCore messaging / entities
- Forcing mcRPC on users who never enable it
