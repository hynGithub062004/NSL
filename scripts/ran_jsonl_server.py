#!/usr/bin/env python3
"""Zero-dependency JSON Lines bridge for the TV5 orchestrator.

One JSON request is read per stdin line and exactly one JSON response is written
to stdout. Supported commands: reset, get_state, apply_action, export, quit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ran import RANSimulator  # noqa: E402


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    simulator = RANSimulator.from_yaml(args.config)
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            command = request.get("command")
            if command == "reset":
                result = simulator.reset(request.get("seed"))
            elif command == "get_state":
                result = simulator.get_state()
            elif command == "apply_action":
                result = simulator.apply_action(request["action"])
            elif command == "export":
                simulator.export_results(request["output_dir"])
                result = {"exported": True, "output_dir": request["output_dir"]}
            elif command == "quit":
                emit({"ok": True, "result": {"stopped": True}})
                return 0
            else:
                raise ValueError(f"Unsupported command: {command!r}")
            emit({"ok": True, "result": result})
        except Exception as exc:  # protocol boundary: always return structured errors
            emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

