# TV1 RAN Model Assumptions and KPI Definitions

This document is the technical authority for the simplified RAN model. The
model is deterministic and intended for scheduler, reinforcement-learning and
integration experiments. It is not a full 3GPP-compliant physical-layer
implementation and its synthetic traffic is not presented as a measured
operator trace.

## Slot order and observation boundary

For slot `t`, TV1 performs these steps in order:

1. Generate traffic for slot `t` and update CQI.
2. Publish `State(t)` before the scheduler decision.
3. Receive and validate `Action(t)`.
4. Convert RB allocation and CQI to service capacity.
5. Serve eMBB and URLLC FIFO queues.
6. Age unfinished URLLC packets and drop packets whose age reaches deadline.
7. Record `RAN_KPI(t)` and prepare `State(t+1)`.

Therefore, `State(t)` contains no traffic or CQI from slot `t+1`. A transition
is exactly `State(t), Action(t), RAN_KPI(t), State(t+1), done`.

## RB capacity abstraction

For a slice in one slot:

```text
capacity_bits = floor(N_RB * N_RE * eta_CQI * overhead_factor)
```

where:

- `N_RB` is the RB allocation supplied by the scheduler.
- `N_RE = 168 = 12 subcarriers * 14 OFDM symbols` is the gross RE count used by
  this simplified RB-slot abstraction.
- `eta_CQI` is the spectral-efficiency value for CQI 1 through 15 from 3GPP TS
  38.214, Table 5.2.2.1-2, 4-bit CQI Table 1.
- `overhead_factor = 0.75` reserves 25 percent of gross RE capacity for an
  aggregate abstraction of pilots, control, guard and implementation overhead.
- `floor` guarantees an integer number of serviceable bits.

The 3GPP source defines the CQI table and a resource block of 12 consecutive
subcarriers. The choice of 14 symbols and a single aggregate 0.75 factor is a
declared project simplification. The model does not calculate DMRS, PDCCH,
transport-block-size or numerology-specific overhead explicitly.

Primary references:

- 3GPP TS 38.214 Release 18, clause 5.2.2.1, Table 5.2.2.1-2:
  https://www.etsi.org/deliver/etsi_ts/138200_138299/138214/18.09.00_60/ts_138214v180900p.pdf
- 3GPP TS 38.211 Release 18, clause 4.4.4.1, resource block definition:
  https://www.etsi.org/deliver/etsi_ts/138200_138299/138211/18.05.00_60/ts_138211v180500p.pdf

## Baseline parameter choices

| Parameter | Value | Reason and limitation |
|---|---:|---|
| Seed | 42 | Fixed reproducibility key. It has no physical or statistical significance. |
| Slots | 500 | Equals 0.5 s at 1 ms per slot and contains five complete burst windows. It is an integration dataset, not a claim of long-run convergence. |
| Slot duration | 1 ms | Clear scheduling time unit and makes a 5 ms deadline equal five slots. Real NR slot duration depends on numerology; this simulator intentionally fixes it. |
| Total RB | 50 | Normalized resource budget that supports a transparent 25/25 smoke-test split. It is not mapped to a declared channel bandwidth. |
| Baseline action | 25 eMBB, 25 URLLC | Neutral fixed split used only to generate comparable handoff data. TV2 and TV3 replace it with their algorithms. |
| URLLC packet | 2,560 bits | Fixed packet size keeps FIFO service and deadline accounting auditable. It is a synthetic test value. |
| URLLC deadline | 5 ms | Creates observable deadline pressure while remaining easy to verify at one-millisecond resolution. It is a project SLA, not a universal 3GPP requirement. |
| RE per RB-slot | 168 | Gross `12 * 14` grid before aggregate overhead. |
| Overhead factor | 0.75 | Conservative project assumption; effective count is `168 * 0.75 = 126` RE-equivalents per RB-slot. |
| CQI step | at most 1 | Bounded random walk avoids physically implausible one-slot jumps in this abstraction. |

With the 25-RB baseline, initial one-slot capacities are:

| Scenario/slice | Initial CQI | Efficiency | Capacity bits/slot | Capacity Mbps |
|---|---:|---:|---:|---:|
| Stable eMBB | 11 | 3.3223 | 10,465 | 10.465 |
| Stable URLLC | 8 | 1.9141 | 6,029 | 6.029 |
| Burst URLLC | 7 | 1.4766 | 4,651 | 4.651 |
| Poor-channel eMBB | 5 | 0.8770 | 2,762 | 2.762 |
| Poor-channel URLLC | 4 | 0.6016 | 1,895 | 1.895 |

These values follow directly from the capacity formula and are intentionally
lower than selected offered loads in stressed cases so that queueing, deadline
drops and scheduler trade-offs are visible.

## Scenario offered loads

Expected offered load is based on the configured means, before random sampling:

| Scenario | eMBB mean | URLLC mean | Purpose |
|---|---:|---:|---|
| Stable load | 18.000 Mbps | `1.5 * 2,560 = 3.840 Mbps` | Persistent eMBB pressure with serviceable average URLLC load at the initial CQI. |
| URLLC burst outside burst | 16.000 Mbps | `1.0 * 2,560 = 2.560 Mbps` | Low base URLLC load. |
| URLLC burst inside burst | 16.000 Mbps | `6.0 * 2,560 = 15.360 Mbps` | Strong temporary URLLC overload. |
| URLLC burst long-run mean | 16.000 Mbps | `0.8 * 2.560 + 0.2 * 15.360 = 5.120 Mbps` | Twenty burst slots in every 100-slot period. |
| Poor channel | 12.000 Mbps | `1.5 * 2,560 = 3.840 Mbps` | Offered load exceeds low-CQI baseline capacity for both slices. |

Burst windows are `[50,70)`, `[150,170)`, `[250,270)`, `[350,370)` and
`[450,470)`. Gaussian eMBB arrivals are clamped at zero. URLLC packet counts
use a Poisson distribution. All random streams are deterministic for a given
seed.

## Per-slot KPI formulas

Let `T_slot` be slot duration in seconds, `S_e` and `S_u` served bits,
`D_e` and `D_u` pre-action queue demand, `R_used` used RB and `R_total` total RB.

```text
throughput_e = S_e / T_slot / 1,000,000
delay_u = mean(completion_delay_ms of URLLC packets completed in the slot)
drop_u = dropped / (completed + dropped)
sla_violation = (dropped + late_completed) / (completed + dropped)
s_e = S_e / D_e, with s_e = 1 when D_e = 0
s_u = S_u / D_u, with s_u = 1 when D_u = 0
fairness = (s_e + s_u)^2 / (2 * (s_e^2 + s_u^2))
rb_utilization = (used_embb_rb + used_urllc_rb) / total_rb
```

`drop_u` is deliberately a per-slot resolved-packet ratio. It must not be
averaged across slots to estimate run-level packet loss. When a denominator is
zero, the corresponding per-slot ratio is reported as zero.

## Run-level URLLC statistics

`run_summary.json` aggregates raw counters:

```text
drop_rate_total = total_dropped / total_arrived
completion_rate = total_completed / total_arrived
unresolved_rate = unresolved_at_end / total_arrived
total_arrived = total_completed + total_dropped + unresolved_at_end
```

Delay mean, p50, p95 and maximum use completed packets only. Percentiles use the
nearest-rank method. Dropped packets are excluded from delay and counted in the
drop/SLA statistics instead.

## Deadline boundary

Service occurs before aging in each slot. A packet completed with delay equal
to the deadline is on time. If a packet remains unfinished and its age reaches
the deadline after the slot, it is dropped. Partial service does not reset age.
The test suite covers completion exactly at 5 ms and partial service followed
by a drop at 5 ms.

## Reproducibility metadata

`run_manifest.json` contains the full normalized configuration, Python version,
model assumptions, `config_sha256` and a deterministic `run_id` derived from
the configuration, seed and complete action trace. The identifiers are for
traceability; they do not prove statistical generalization.
