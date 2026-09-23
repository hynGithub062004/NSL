# Contract Usage

## Producer and consumer matrix

| Contract | Producer | Consumer |
|---|---|---|
| `config.schema.json` | Team configuration | TV1, TV5 |
| `state.schema.json` | TV1 | TV2, TV3, TV5 |
| `action.schema.json` | TV2 or TV3 | TV1, TV5 |
| `ran_kpi.schema.json` | TV1 | TV3 reward, TV5 reporting |
| `transition.schema.json` | TV1 | TV3, TV5 |
| `run_summary.schema.json` | TV1 | TV5 reporting and audit |
| `run_manifest.schema.json` | TV1 | TV5 reproducibility audit |
| `core_handoff.schema.json` | TV5 | TV4 |

## Compatibility

Every payload contains `schema_version`. Consumers must reject an unsupported
major version rather than silently guessing field meanings.

TV2 and TV3 return the same Action shape. `action_id` is scheduler-specific;
`rb_allocation` is the canonical physical decision consumed by TV1.

TV5 forwards the original `request_id` into the policy request for TV4. This
makes the later RAN KPI and Core KPI join deterministic.

`data_dictionary.csv` is the compact field and unit reference. JSON Schema is
the machine-readable authority when the two differ.
