#!/usr/bin/env python3
"""Run TV1 independently with a deterministic smoke-test RB allocation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ran import RANSimulator  # noqa: E402
from ran.schemas import SCHEMA_VERSION  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Scenario YAML path")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--embb-rb", type=int, default=25)
    parser.add_argument("--urllc-rb", type=int, default=25)
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    simulator = RANSimulator.from_yaml(args.config)
    simulator.reset(args.seed)
    while not simulator.done:
        slot = simulator.time_slot
        action = {
            "schema_version": SCHEMA_VERSION,
            "request_id": f"smoke-{slot:06d}",
            "time_slot": slot,
            "scheduler": "tv1_smoke_fixed",
            "action_id": 0,
            "rb_allocation": {"embb": args.embb_rb, "urllc": args.urllc_rb},
        }
        simulator.apply_action(action)
    simulator.export_results(args.output)
    summary = {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "scenario_id": simulator.scenario_id,
        "seed": simulator.seed,
        "slots": len(simulator.metrics_log),
        "output": str(Path(args.output).resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

