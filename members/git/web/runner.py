"""Run the project's real TV1, TV2 and TV3 modules with a shared scenario."""
from __future__ import annotations

import copy
import csv
import hashlib
import importlib.metadata
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
# TV2's published QoS module imports the TV1 package under its 'ran' name.
sys.path.insert(0, str(ROOT / "members/TV1/src"))

from members.TV1.src.ran import RANSimulator
from members.TV1.src.ran.config import validate_config
from members.TV2.src.schedulers.static import StaticScheduler
from members.TV2.src.schedulers.queue_based import QueueBasedScheduler
from members.TV2.src.schedulers.qos_heuristic import QoSHeuristicScheduler
from members.TV2.src.schedulers.action_validator import validate_action as validate_tv2

SCHEDULERS = {
    "static": StaticScheduler,
    "queue_based": QueueBasedScheduler,
    "qos_heuristic": QoSHeuristicScheduler,
}


def scenario_config(spec: dict, seed: int) -> dict:
    name = spec["scenario"]
    with (ROOT / "members/TV1/configs" / f"{name}.yaml").open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    config = copy.deepcopy(config)
    config["simulation"].update(seed=seed, slots=spec["slots"])
    config["embb"]["arrival_rate_bits_per_slot"] = spec["embb_arrival"]
    config["urllc"].update(arrival_rate_packets_per_slot=spec["urllc_arrival"], deadline_ms=spec["deadline_ms"])
    config["channel"].update(embb_initial_cqi=spec["embb_cqi"], urllc_initial_cqi=spec["urllc_cqi"],
                             min_cqi=min(config["channel"]["min_cqi"], spec["embb_cqi"], spec["urllc_cqi"]),
                             max_cqi=max(config["channel"]["max_cqi"], spec["embb_cqi"], spec["urllc_cqi"]))
    config["radio"]["total_rb"] = spec["total_rb"]
    if name == "urllc_burst":
        config["urllc"]["burst_multiplier"] = spec["burst_multiplier"]
    # Same config/seed for every algorithm; scenario ID includes a short batch label.
    config["scenario"]["id"] = spec["scenario"] + "_web"
    validate_config(config)
    return config


def run_one(spec: dict, seed: int, algorithm: str, folder: Path, batch_id: str) -> dict:
    config = scenario_config(spec, seed)
    sim = RANSimulator(config)
    sim.reset(seed=seed)
    with (ROOT / "members/TV2/configs/schedulers.yaml").open(encoding="utf-8") as fh:
        scheduler_config = yaml.safe_load(fh)
    total = spec["total_rb"]
    scheduler_config["common"]["total_rb"] = total
    scheduler_config["common"]["slot_duration_ms"] = config["simulation"]["slot_duration_ms"]
    scheduler_config["static"].update(rb_embb=total // 2, rb_urllc=total - total // 2)
    if algorithm == "dqn":
        from members.TV3.dqn_scheduler import DQNScheduler
        scheduler = DQNScheduler(ROOT / "members/TV3/models/dqn_v2_best.zip", total_rb=total)
    else:
        scheduler = SCHEDULERS[algorithm]()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = []
    for slot in range(spec["slots"]):
        state = sim.get_state()
        request_id = f"{batch_id}-{algorithm}-{seed}-{slot}"
        action = (scheduler.predict(state, request_id=request_id) if algorithm == "dqn"
                  else scheduler.select_action(state, scheduler_config, request_id=request_id))
        if algorithm != "dqn":
            validate_tv2(action, state, total, require_all_rb=True)
        transition = sim.apply_action(action)
        kpi = transition["ran_kpi"]
        rows.append({"batch_id": batch_id, "seed": seed, "algorithm": algorithm,
                     "scenario": spec["scenario"], "time_slot": slot, "request_id": request_id,
                     "embb_cqi": state["embb"]["cqi"], "urllc_cqi": state["urllc"]["cqi"],
                     "embb_queue_bits": state["embb"]["queue_bits"],
                     "urllc_queue_packets": state["urllc"]["queue_packets"],
                     "embb_rb": action["rb_allocation"]["embb"],
                     "urllc_rb": action["rb_allocation"]["urllc"],
                     "action_id": action["action_id"],
                     **{key: value for key, value in kpi.items() if key not in
                        {"units", "schema_version", "seed", "algorithm", "scenario_id", "time_slot", "request_id"}}})
    with (folder / "slots.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (folder / "trace.jsonl").open("w", encoding="utf-8") as fh:
        for transition in sim.transition_log:
            fh.write(json.dumps(transition, ensure_ascii=False) + "\n")
    summary = sim.build_run_summary()
    counters = summary["urllc_packet_counters"]
    delays = summary["completed_urllc_delay_ms"]
    traffic = summary["traffic_and_service"]
    aggregates = {
        "throughput_e": traffic["served_embb_mbps"],
        "delay_u": delays["mean"] if delays["sample_count"] else None,
        "delay_p95": delays["p95_nearest_rank"] if delays["sample_count"] else None,
        "delay_samples": delays["sample_count"],
        "arrived": counters["arrived"], "completed": counters["completed"],
        "dropped": counters["dropped"], "unresolved": counters["unresolved_at_end"],
        "packet_conservation_ok": counters["conservation_ok"],
        "drop_rate_total": summary["urllc_run_rates"]["drop_rate_total"] if counters["arrived"] else None,
        "fairness": round(statistics.mean(float(x["fairness"]) for x in rows), 6),
        "sla_violation": round(statistics.mean(float(x["sla_violation"]) for x in rows), 6),
        "rb_utilization": round(statistics.mean(float(x["rb_utilization"]) for x in rows), 6),
    }
    result = {"algorithm": algorithm, "seed": seed, "slots": spec["slots"], "metrics": aggregates,
              "run_summary": summary, "series": [{key: row[key] for key in
               ("time_slot", "embb_rb", "urllc_rb", "throughput_e", "delay_u", "drop_u", "fairness", "sla_violation")}
               for row in rows]}
    (folder / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    checkpoint = ROOT / "members/TV3/models/dqn_v2_best.zip"
    try:
        git_result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
        git_commit = git_result.stdout.strip() if git_result.returncode == 0 else None
    except OSError:
        git_commit = None
    packages = {}
    for name in ("fastapi", "pydantic", "stable-baselines3", "gymnasium", "torch", "PyYAML"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    (folder / "manifest.json").write_text(json.dumps({
        "run_id": batch_id, "scenario": spec["scenario"], "algorithm": algorithm,
        "seed": seed, "slots": spec["slots"], "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "python_version": sys.version, "dependencies": packages,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "dqn_checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest() if checkpoint.is_file() else None,
        "trace": "trace.jsonl", "slots_csv": "slots.csv",
        "note": "Each trace row contains the TV1 State, TV2/TV3 Action, Transition and RAN KPI."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def aggregate(results: list[dict]) -> list[dict]:
    output = []
    for algorithm in ["static", "queue_based", "qos_heuristic", "dqn"]:
        group = [r for r in results if r["algorithm"] == algorithm]
        if not group:
            continue
        metrics = [r["metrics"] for r in group]
        total_arrived = sum(m["arrived"] for m in metrics)
        total_delays = sum(m["delay_samples"] for m in metrics)
        means = {key: round(statistics.mean(m[key] for m in metrics), 6)
                 for key in ("throughput_e", "fairness", "sla_violation", "rb_utilization")}
        means["delay_u"] = (round(sum(m["delay_u"] * m["delay_samples"] for m in metrics if m["delay_u"] is not None)
                                    / total_delays, 6) if total_delays else None)
        means["drop_rate_total"] = (round(sum(m["dropped"] for m in metrics) / total_arrived, 6)
                                     if total_arrived else None)
        deviations = {}
        for key in ("throughput_e", "delay_u", "drop_rate_total"):
            values = [m[key] for m in metrics if m[key] is not None]
            deviations[key + "_sd"] = round(statistics.stdev(values), 6) if len(values) > 1 else None
        output.append({"algorithm": algorithm, "runs": len(group), **means, **deviations,
                       "arrived": total_arrived, "completed": sum(m["completed"] for m in metrics),
                       "dropped": sum(m["dropped"] for m in metrics),
                       "unresolved": sum(m["unresolved"] for m in metrics),
                       "delay_samples": total_delays,
                       "packet_conservation_ok": all(m["packet_conservation_ok"] for m in metrics)})
    return output
