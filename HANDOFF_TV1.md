# TV1 Delivery Checklist

## Delivered source

- [x] Traffic generation for eMBB and URLLC
- [x] FIFO URLLC packet queue with deadline and drop
- [x] eMBB bit queue
- [x] Deterministic CQI model
- [x] CQI to RB capacity mapping
- [x] State generation
- [x] Action validation
- [x] RAN KPI generation
- [x] Result export to CSV, JSON and JSONL
- [x] `reset`, `get_state`, `apply_action`
- [x] JSON Lines integration bridge

## Delivered contracts

- [x] State JSON Schema
- [x] Action JSON Schema
- [x] RAN KPI JSON Schema
- [x] Transition JSON Schema
- [x] TV5 to TV4 core-policy handoff schema
- [x] Schema version and common join keys
- [x] Units and empty-slot conventions

## Delivered evidence

- [x] Automated tests
- [x] Stable-load sample run
- [x] URLLC-burst sample run
- [x] Poor-channel sample run
- [x] State and transition samples
- [x] Traffic, CQI and KPI logs
- [x] Run-level packet conservation and delay percentiles
- [x] Configuration hash and deterministic run identifier
- [x] Handoff validation command

## Acceptance conditions

The delivery is accepted when:

1. `python -m unittest discover -s tests -v` passes.
2. Three sample scenarios run to completion.
3. `scripts/validate_handoff.py` accepts each generated result directory.
4. Same configuration and seed produce identical transitions.
5. No queue, capacity or service count becomes negative.
6. Served data never exceeds available queue data.
7. Invalid RB allocations and stale actions are rejected.
8. KPI values are finite and bounded where applicable.
9. URLLC arrivals equal completed plus dropped plus unresolved packets.
10. Deadline-boundary, partial-service, burst-window and state-snapshot tests pass.

## Change-control rule

Fields in `contracts/*.schema.json` are frozen for schema version `1.0.0`.
Adding an optional field requires team notification. Removing or renaming a
field, changing its type, unit or meaning requires a new major schema version.
