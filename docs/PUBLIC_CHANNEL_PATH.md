# Public channel and mcRPC

## Policy

**Public is out of scope for mcRPC.**

mcRPC must not be QA’d, stressed, or demonstrated on Public. MeshCore Chat may
still show Public traffic; that is Chat / companion behaviour, not the node-request
bridge.

## Packet path (informational)

```
MeshCore Chat / companion (any channel the radio decrypts)
  → HA logbook / Chat history
  → meshcore_message { channel_idx, message }
  → McRpcBridge
```

When `channel_idx` is not in `listen_channels`, the bridge returns immediately:

- no parse
- no dispatcher
- no trace
- no answer
- no mcRPC events

## Do not

- Transmit `all ping` / protocol verbs on Public for QA
- Treat Public Chat lines as mcRPC failures
- Add a “negative Public” QA scenario (removed — it polluted Chat history)

## Do

- Run all mcRPC protocol tests on the private channel / Config Entry path
- Keep production node/channel **mcYogi** unchanged
