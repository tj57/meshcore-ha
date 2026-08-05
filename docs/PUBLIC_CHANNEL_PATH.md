# Public channel packet path

## Symptom

QA saw `all ping` appear in **Public** Chat history even when Mesh Node Requests
was configured with `listen_channels=[1]` (mcCtrl only).

## Layers

```
Phone / MeshCore Android Chat (channel 0 Public)
  → companion radio CMD_SEND_CHANNEL_TXT_MSG (channel_idx=0)
  → LoRa GRP_TXT on Public PSK
  → companion RX → MeshCore HA Chat / logbook (UI history)
  → bus event meshcore_message {channel_idx: 0, message: "all ping"|…}
  → McRpcBridge._on_meshcore_message
```

## Who creates the Chat line?

| Component | Role |
|-----------|------|
| **MeshCore Chat / companion** | Persists TX/RX channel text for **every** channel the radio decrypts. This is **not** mcRPC. Typing or receiving `all ping` on Public shows in Public history by design of Chat. |
| **meshcore-ha logbook** | Forwards companion channel messages onto `meshcore_message` for all channels. |
| **mcRPC / McRpcBridge** | Must **not** parse, dispatch, trace, answer, or emit node-request events for channels outside `listen_channels`. |

## Required mcRPC behaviour (`listen=[1]`)

On `channel_idx=0` (Public):

1. Return immediately in `_on_meshcore_message` / `_on_message_sent` / `_maybe_answer_inbound`
2. No `strip_sender_prefix` / parse / classify
3. No `recent_traces` append
4. No `rx_count` bump
5. No answer TX
6. No `meshcore_response` / `meshcore_event` from the bridge

Chat UI history on Public may still show the line — that traffic never entered mcRPC.

## Negative test only

Public remains allowed solely for one secure-default negative QA case
(see `QA_CHANNEL_POLICY.md`). Positive protocol traffic uses **mcCtrl** only.
