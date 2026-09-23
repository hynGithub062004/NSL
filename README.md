# TV1 RAN Simulator Handoff

This directory is the complete TV1 delivery for the Network Slicing project. It
is the only module that generates RAN State, mutates traffic queues, converts RB
allocations to service capacity, and calculates RAN KPI.

## What downstream members should use

- TV2 reads `State` and returns `Action`. See `examples/tv2_scheduler_usage.py`.
- TV3 wraps `RANSimulator` as its environment. See `examples/tv3_env_adapter.py`.
- TV5 calls `reset`, `get_state`, and `apply_action`, either in process or over
  the JSON Lines bridge. See `examples/tv5_orchestrator_usage.py` and
  `scripts/ran_jsonl_server.py`.
- TV4 does not call the RAN directly. TV5 forwards the common join keys using
  `contracts/core_handoff.schema.json`.

All contracts are versioned as `1.0.0`. Do not rename fields locally. Propose a
new schema version when a breaking change is required.

## Requirements

- Python 3.10 or newer.
- No mandatory runtime package outside the Python standard library.
- PyYAML is optional; the included loader supports all supplied YAML files.
- Pytest is optional. The tests also run with standard-library `unittest`.

## Quick verification on Windows

Run from `D:\NSL`:

```powershell
python -m unittest discover -s tests -v
python scripts\run_ran.py --config configs\stable_load.yaml --output results\stable_load
python scripts\validate_handoff.py --results results\stable_load --total-rb 50
```

Optional Pytest command:

```powershell
python -m pip install -r requirements-dev.txt
pytest -q
```

## Public Python interface

Add `src` to `PYTHONPATH`, or insert it in the application startup path:

```python
from ran import RANSimulator

ran = RANSimulator.from_yaml("configs/urllc_burst.yaml")
state = ran.reset(seed=42)
state = ran.get_state()
transition = ran.apply_action(action)
```

`apply_action` returns one atomic transition:

```text
schema_version
request_id
state
action
ran_kpi
next_state
done
```

The request is rejected when the action slot does not match the current RAN
slot, an RB value is negative, or allocated RB exceeds `radio.total_rb`.

## JSON Lines bridge for TV5

Start the bridge:

```powershell
python scripts\ran_jsonl_server.py --config configs\urllc_burst.yaml
```

Write one compact JSON object per line to stdin:

```json
{"command":"get_state"}
{"command":"reset","seed":42}
{"command":"apply_action","action":{"schema_version":"1.0.0","request_id":"req-000000","time_slot":0,"scheduler":"qos_heuristic","action_id":2,"rb_allocation":{"embb":20,"urllc":30}}}
{"command":"export","output_dir":"results/demo"}
{"command":"quit"}
```

Every response has either `{"ok":true,"result":...}` or
`{"ok":false,"error":"...","message":"..."}`.

## Scenario files

- `configs/stable_load.yaml`: normal baseline load.
- `configs/urllc_burst.yaml`: periodic URLLC burst scenario.
- `configs/poor_channel.yaml`: bounded low-CQI scenario.

All algorithms in one benchmark must use the same scenario file and seed.

## Data units

- Queue and service amounts: bits.
- CQI: integer 1 through 15.
- RB: non-negative integer.
- `throughput_e`: Mbps for the current slot.
- `delay_u`: ms, mean delay of URLLC packets completed in the current slot.
- `drop_u`: ratio in `[0, 1]` among packets resolved in the current slot.
- `sla_violation`: dropped plus late-completed packets divided by resolved packets.
- `fairness`: Jain index based on eMBB and URLLC demand satisfaction.
- `rb_utilization`: estimated RB that carried data divided by total RB.

When no packet is completed in a slot, `delay_u` is `0`. When no packet is
resolved, `drop_u` and `sla_violation` are `0`. Raw counters are included in the
same KPI row so downstream reports can aggregate by sums instead of averaging
ratios blindly.

## Output files

`scripts/run_ran.py` creates:

- `state_sample.json`: first State example.
- `transition_sample.json`: complete first transition example.
- `state_log.jsonl`: one State per line.
- `transitions.jsonl`: State, Action, KPI and next State together.
- `traffic_log.csv`: generated arrivals by slot.
- `cqi_log.csv`: CQI by slot.
- `ran_metrics.csv`: versioned RAN KPI and common join keys.
- `run_summary.json`: run-level raw counters, packet conservation, drop rate,
  completion rate and completed-delay mean/p50/p95/max.
- `run_manifest.json`: exact configuration, Python version, model assumptions,
  `config_sha256` and deterministic `run_id`.

CSV files use UTF-8, comma delimiters and one header row. JSON and JSONL files
use UTF-8 and JSON numbers, never `NaN` or `Infinity`.

## Integration join keys

TV5 must join RAN and Core results using all of these fields:

```text
seed + scenario_id + algorithm + time_slot + request_id
```

`request_id` identifies one scheduler decision and must be forwarded unchanged
to the TV4 policy request and Core KPI record.

## Model conventions

Each slot follows this order:

1. Traffic arrives and CQI is updated.
2. TV1 publishes State.
3. TV2 or TV3 creates Action.
4. TV1 validates Action and calculates per-slice capacity.
5. FIFO queues are served.
6. Remaining URLLC packets age and expired packets are dropped.
7. TV1 records KPI and prepares the next State.

The RB capacity model uses the documented CQI spectral-efficiency table,
`resource_elements_per_rb`, and `overhead_factor`. It is an intentionally
abstract link model and not a full PHY implementation.

The exact formulas, parameter rationale, 3GPP references, deadline boundary and
scenario offered-load calculations are specified in `MODEL_ASSUMPTIONS.md`.

## Ownership boundary

TV2 and TV3 must not generate traffic, mutate queues or compute a second RAN
model. TV5 may validate and route an Action but must call TV1 to apply it. TV4
uses only the policy handoff from TV5 and returns Core KPI.
