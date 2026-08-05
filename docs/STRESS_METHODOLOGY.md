# Stress methodology (mcRPC / MeshCore HA)

## Do not use

A **100-ping burst** as a pass/fail RF gate. That scenario is unrealistic for
MeshCore flood GRP_TXT (airtime budget, packet pools, companion queue) and
produces misleading failure rates.

## Supported operating envelope

| Profile | Pattern | Purpose |
|---------|---------|---------|
| Warm-up | 5 requests, **1 s** interval | Sanity / RTT baseline |
| Light load | 10 requests, **2 s** interval | Sustained light traffic |
| Continuous short | ~1 request / 2–5 s for **5 minutes** | Stability |
| Continuous long | ~1 request / 5–10 s for **30 minutes** | Soak / memory |

Always on the **private** channel / Config Entry path — **never Public**.

No expectation of **100% RF delivery**. Success is measured statistically.

## Metrics to record

| Metric | Source |
|--------|--------|
| Reply success rate | matched replies / requests sent |
| Average RTT | diagnostics `average_rtt_ms` |
| Queue drops | firmware `tx_drop_queue_full` / HA timeouts |
| Packet / companion drops | `tx_errors_table_full`, `tx_errors_not_found` |
| Memory growth | process / firmware heap (lab tooling) |
| CPU | host / companion lab tooling |

Download HA diagnostics after each profile (`node_requests.tx_pipeline`,
`packet_loss_percent`, `recent_traces`, `pending_requests`).

## Saturation is not an unexpected failure

When the stack is saturated, treat these as **expected backpressure**:

| Signal | Meaning |
|--------|---------|
| `err busy` | Feature/host busy |
| companion `ERR_CODE_TABLE_FULL` / HA `table_full` | Send queue / pool full |
| firmware `tx_drop_queue_full` | Reply queue full |
| HA request timeout | No correlated reply in window |

Report them as backpressure / envelope limits in the stress report — not as
protocol defects — unless they occur under the **warm-up** profile with idle RF.

## Automation hooks

- Unit / Chat E2E: cover policy and error contracts (no RF).
- Lab stress: follow this methodology manually or via paced `meshcore.request`
  automations on the private channel only.
- `release-check` verifies docs and offline suites; it does **not** require a
  live 100-burst.

## Related

- MeshCore `doc/MCRPC_STRESS_TX_ANALYSIS.md` — TX pipeline root causes
- [COMMAND_COVERAGE.md](https://github.com/tj57/mcrpc/blob/master/docs/protocol/COMMAND_COVERAGE.md) Stress column
