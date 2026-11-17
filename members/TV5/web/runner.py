"""Run the project's real TV1, TV2 and TV3 modules with a shared scenario."""
from __future__ import annotations

import copy
import csv
import json
import statistics
import sys
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
    summary = sim.build_run_summary()
    aggregates = {
        "throughput_e": round(statistics.mean(float(x["throughput_e"]) for x in rows), 6),
        "delay_u": round(statistics.mean(float(x["delay_u"]) for x in rows), 6),
        "drop_rate_total": summary["urllc_run_rates"]["drop_rate_total"],
        "fairness": round(statistics.mean(float(x["fairness"]) for x in rows), 6),
        "sla_violation": round(statistics.mean(float(x["sla_violation"]) for x in rows), 6),
        "rb_utilization": round(statistics.mean(float(x["rb_utilization"]) for x in rows), 6),
    }
    result = {"algorithm": algorithm, "seed": seed, "slots": spec["slots"], "metrics": aggregates,
              "run_summary": summary, "series": [{key: row[key] for key in
               ("time_slot", "embb_rb", "urllc_rb", "throughput_e", "delay_u", "drop_u", "fairness", "sla_violation")}
               for row in rows]}
    (folder / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def aggregate(results: list[dict]) -> list[dict]:
    output = []
    for algorithm in ["static", "queue_based", "qos_heuristic", "dqn"]:
        group = [r for r in results if r["algorithm"] == algorithm]
        if not group:
            continue
        means = {key: round(statistics.mean(r["metrics"][key] for r in group), 6)
                 for key in group[0]["metrics"]}
        deviations = {key + "_sd": round(statistics.stdev(r["metrics"][key] for r in group), 6)
                      if len(group) > 1 else 0.0
                      for key in ("throughput_e", "delay_u", "drop_rate_total")}
        output.append({"algorithm": algorithm, "runs": len(group), **means, **deviations})
    return output
