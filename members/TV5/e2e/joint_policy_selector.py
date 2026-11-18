"""TV5 phase D: pure, auditable offline scheduler + SRv6 route selector.

Consumes estimates from INDEPENDENT calibration runs, NEVER evaluation results.
No Core API calls and no GNS3 changes occur in this module.

Goal: maximize estimated URLLC on-time delivery rate subject to
estimated eMBB goodput >= G_min, healthy paths, and sufficient evidence.
This is a decision mechanism, NOT a proof of End-to-End optimization.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SCHEDULERS = frozenset({"static", "qos_heuristic", "queue_based", "dqn"})
POLICIES = frozenset({"high_bandwidth", "low_latency"})
ROUTE_FOR_POLICY = {"high_bandwidth": "r2", "low_latency": "r3"}


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def select_joint_policy(spec: dict) -> dict:
    """Return a non-actuating decision with the supporting candidate audit.

    Input keys: scenario, evaluation_seed, g_min_mbps, core_health (r2/r3 bool),
    candidates: [{scheduler, embb_policy, urllc_policy,
      urllc_on_time_rate_est, embb_goodput_mbps_est,
      calibration_scenario, calibration_seeds, evidence_id}].

    Every candidate must derive from the same independent calibration seeds.
    If no feasible candidate exists, return NO_FEASIBLE_CANDIDATE, no decision.
    """
    if not isinstance(spec, dict):
        raise ValueError("Input must be a JSON object")
    scenario = spec.get("scenario")
    if not isinstance(scenario, str) or not scenario.strip():
        raise ValueError("scenario is required")
    eval_seed = spec.get("evaluation_seed")
    if isinstance(eval_seed, bool) or not isinstance(eval_seed, int) or eval_seed < 0:
        raise ValueError("evaluation_seed must be a nonnegative integer")
    g_min = _finite(spec.get("g_min_mbps"), "g_min_mbps")
    if g_min < 0:
        raise ValueError("g_min_mbps cannot be negative")
    health = spec.get("core_health")
    if not isinstance(health, dict) or not all(isinstance(health.get(p), bool) for p in ("r2", "r3")):
        raise ValueError("core_health must contain boolean r2 and r3")
    candidates = spec.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidates must be a nonempty list")

    accepted = []
    audit = []
    calibration_key = None
    unique_pairs = set()
    for i, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"candidate[{i}] must be an object")
        scheduler = candidate.get("scheduler")
        e_policy = candidate.get("embb_policy")
        u_policy = candidate.get("urllc_policy")
        if scheduler not in SCHEDULERS or e_policy not in POLICIES or u_policy not in POLICIES:
            raise ValueError(f"candidate[{i}] has an unknown scheduler or policy")
        if u_policy != "low_latency":
            raise ValueError(f"candidate[{i}]: URLLC policy must remain low_latency in this lab")
        key = (scheduler, e_policy, u_policy)
        if key in unique_pairs:
            raise ValueError(f"duplicate pair: {key}")
        unique_pairs.add(key)
        rate = _finite(candidate.get("urllc_on_time_rate_est"), f"candidate[{i}].urllc_on_time_rate_est")
        goodput = _finite(candidate.get("embb_goodput_mbps_est"), f"candidate[{i}].embb_goodput_mbps_est")
        if not 0 <= rate <= 1 or goodput < 0:
            raise ValueError(f"candidate[{i}] invalid QoS estimates")
        if candidate.get("calibration_scenario") != scenario:
            raise ValueError(f"candidate[{i}] scenario differs from evaluation scenario")
        seeds = candidate.get("calibration_seeds")
        if not isinstance(seeds, list) or len(seeds) < 2 or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in seeds):
            raise ValueError(f"candidate[{i}] requires at least two nonnegative calibration seeds")
        if len(set(seeds)) != len(seeds):
            raise ValueError(f"candidate[{i}] repeats calibration seeds")
        seeds_key = tuple(sorted(seeds))
        if eval_seed in seeds_key:
            raise ValueError(f"candidate[{i}] has evaluation-seed leakage")
        if calibration_key is None:
            calibration_key = seeds_key
        elif calibration_key != seeds_key:
            raise ValueError("All candidates must share exactly the same calibration seeds")
        evidence = candidate.get("evidence_id")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"candidate[{i}] must provide evidence_id")
        paths_ok = health[ROUTE_FOR_POLICY[e_policy]] and health[ROUTE_FOR_POLICY[u_policy]]
        meets_g_min = goodput >= g_min
        feasible = paths_ok and meets_g_min
        item = {
            "scheduler": scheduler,
            "embb_policy": e_policy,
            "urllc_policy": u_policy,
            "urllc_on_time_rate_est": rate,
            "embb_goodput_mbps_est": goodput,
            "evidence_id": evidence,
            "feasible": feasible,
            "reasons": ([] if paths_ok else ["core_path_unhealthy"]) + ([] if meets_g_min else ["goodput_below_g_min"]),
        }
        audit.append(item)
        if feasible:
            accepted.append(item)

    # Stable, deterministic tie-breaking: on-time rate, goodput, then candidate name.
    best = None
    if accepted:
        best = sorted(accepted, key=lambda x: (-x["urllc_on_time_rate_est"], -x["embb_goodput_mbps_est"], x["scheduler"], x["embb_policy"]))[0]
    return {
        "status": "SELECTED_OFFLINE_NOT_APPLIED" if best else "NO_FEASIBLE_CANDIDATE",
        "mode": "OFFLINE_CALIBRATION_DECISION_ONLY",
        "scenario": scenario,
        "evaluation_seed": eval_seed,
        "calibration_seeds": list(calibration_key or ()),
        "g_min_mbps": g_min,
        "core_health_snapshot": {"r2": health["r2"], "r3": health["r3"]},
        "selected": {k: best[k] for k in ("scheduler", "embb_policy", "urllc_policy", "evidence_id", "urllc_on_time_rate_est", "embb_goodput_mbps_est")} if best else None,
        "candidate_audit": audit,
        "limitations": [
            "Predictions require independently measured calibration; this module does not estimate them.",
            "Selected policy has NOT been applied to TV4 and E2E performance has NOT been measured.",
            "Do not treat a calibration or demonstration input as an evaluation result.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="TV5 joint scheduler/SRv6 selector - offline only")
    ap.add_argument("--input", required=True, type=Path, help="Independent calibration JSON")
    ap.add_argument("--out", type=Path, help="Optional JSON audit output")
    args = ap.parse_args()
    result = select_joint_policy(json.loads(args.input.read_text(encoding="utf-8-sig")))
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
