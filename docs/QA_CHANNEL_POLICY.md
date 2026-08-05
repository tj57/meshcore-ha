# QA channel policy (Mesh Node Requests / mcRPC)

## Hard rule

| Channel | Allowed use in QA |
|---------|-------------------|
| **mcCtrl** (typically channel index 1) | **All positive tests** — ping, status, discovery, chat E2E, stress, automations |
| **Public** (channel index 0) | **Exactly one negative test** — verify that answering / listening on Public is denied or disabled by secure defaults |

Never run happy-path Chat or `meshcore.request` traffic on Public during release QA.

## Rationale

Public is the shared mesh broadcast channel. Using it for positive tests pollutes the air, risks third-party clients treating requests as chat, and bypasses the secure-default policy the RC ships with.

## Negative-only Public checklist

1. Confirm Mesh Node Requests is **not** listening on Public by default.
2. If temporarily enabled for the negative test: send one addressed request and expect deny / no answer per policy.
3. Revert listen settings to mcCtrl-only before continuing the suite.

## Positive suite (mcCtrl only)

- Chat: `mcCtrl ping`, `mcCtrl#<id> ping`
- Services: `meshcore.request` / `broadcast` / `raw` on mcCtrl
- Stress / diagnostics capture on mcCtrl
- HACS upgrade + migration restarts with mcCtrl entry title (`mcCtrl`)
