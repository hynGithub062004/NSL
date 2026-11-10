#!/usr/bin/env python3
"""TV4 SRv6 Core - repeatable two-slice ICMPv6 RTT measurement.

Runs on the GNS3 VM (not inside a Docker node). Uses only Python stdlib
and the existing Docker Client. Does not change interfaces, routes or qdiscs.
"""

import argparse
import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import subprocess
import sys
import time

TARGET = "2001:db8:40::2"
SOURCES = {
    "embb": "2001:db8:10::2",
    "urllc": "2001:db8:10::3",
}
FIELDS = [
    "timestamp_utc", "scenario_id", "run_id", "slice_id", "source_ipv6",
    "destination_ipv6", "sent", "received", "packet_loss_pct",
    "rtt_min_ms", "rtt_avg_ms", "rtt_p95_ms", "rtt_max_ms", "rtt_mdev_ms",
    "sample_count", "exit_code", "raw_log",
]


def run_cmd(args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def find_client():
    ids = run_cmd([
        "sudo", "docker", "ps", "--filter", "name=GNS3.Client.",
        "--format", "{{.ID}}",
    ]).strip().splitlines()
    if len(ids) != 1:
        raise RuntimeError(f"Expected exactly one running GNS3.Client container; found {len(ids)}.")
    container_id = ids[0]
    addresses = run_cmd([
        "sudo", "docker", "exec", container_id,
        "ip", "-6", "addr", "show", "dev", "eth0",
    ])
    missing = [addr for addr in SOURCES.values() if addr not in addresses]
    if missing:
        raise RuntimeError(
            "Client is missing IPv6 address(es): " + ", ".join(missing)
            + ". Check GNS3 Client configuration before running the benchmark."
        )
    return container_id, addresses


def parse_log(text, *, exit_code, slice_id, source, scenario_id, run_id, raw_log):
    # iputils ping standard English-language output; force LC_ALL=C in each process.
    stat = re.search(
        r"(?m)^(\d+) packets transmitted, (\d+) received, ([0-9.]+)% packet loss",
        text,
    )
    if not stat:
        raise RuntimeError(f"Could not parse ping packet statistics for {slice_id}: {raw_log}")
    sent, received, loss = int(stat.group(1)), int(stat.group(2)), float(stat.group(3))
    samples = [float(x) for x in re.findall(r"\btime=([0-9.]+)\s*ms", text)]
    samples.sort()
    if len(samples) != received:
        raise RuntimeError(
            f"{slice_id}: received={received}, but parsed RTT samples={len(samples)}; "
            f"inspect {raw_log}"
        )
    summary = re.search(
        r"(?m)^rtt min/avg/max/mdev = "
        r"([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+) ms",
        text,
    )
    if received and not summary:
        raise RuntimeError(f"Could not parse RTT summary for {slice_id}: {raw_log}")
    # Nearest-rank p95 among successfully received replies.
    p95 = samples[max(0, math.ceil(0.95 * len(samples)) - 1)] if samples else None
    min_rtt, avg_rtt, max_rtt, mdev = (
        (float(summary.group(i)) for i in range(1, 5)) if summary else (None,) * 4
    )
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenario_id": scenario_id,
        "run_id": run_id,
        "slice_id": slice_id,
        "source_ipv6": source,
        "destination_ipv6": TARGET,
        "sent": sent,
        "received": received,
        "packet_loss_pct": loss,
        "rtt_min_ms": min_rtt,
        "rtt_avg_ms": avg_rtt,
        "rtt_p95_ms": p95,
        "rtt_max_ms": max_rtt,
        "rtt_mdev_ms": mdev,
        "sample_count": len(samples),
        "exit_code": exit_code,
        "raw_log": str(raw_log),
    }


def write_csv(filepath, rows, fields):
    with filepath.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description="Automate two-slice SRv6 ping RTT and save CSV on GNS3 VM.")
    p.add_argument("--runs", type=int, default=5, help="Repeats (default: 5)")
    p.add_argument("--count", type=int, default=300, help="ICMP requests per slice per run (default: 300)")
    p.add_argument("--interval", type=float, default=0.2, help="Seconds between ping requests (default: 0.2)")
    p.add_argument("--scenario-id", default="core_tc_qos", help="Label for this Core test setup")
    p.add_argument("--output-dir", type=Path, default=Path.home() / "TV4_KPI_Benchmark")
    args = p.parse_args()
    if args.runs < 1 or args.count < 1 or args.interval < 0.2:
        p.error("--runs and --count must be >=1; --interval must be >=0.2 seconds")

    container_id, addresses = find_client()
    output = args.output_dir.expanduser()
    logs_dir = output / "logs"
    result_dir = output / "results"
    logs_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = logs_dir / batch_id
    batch_dir.mkdir(exist_ok=False)
    (batch_dir / "client_ipv6_snapshot.txt").write_text(addresses, encoding="utf-8")
    print(f"Docker Client: {container_id}")
    print(f"Saving logs to: {batch_dir}", flush=True)

    rows = []
    for number in range(1, args.runs + 1):
        run_id = f"{batch_id}_run{number:02d}"
        print(f"\n=== Run {number}/{args.runs} - parallel eMBB + URLLC ===", flush=True)
        processes = {}
        for slice_id, source in SOURCES.items():
            logpath = batch_dir / f"{run_id}_{slice_id}.log"
            handle = logpath.open("w", encoding="utf-8")
            command = [
                "sudo", "docker", "exec", "-e", "LC_ALL=C", container_id,
                "ping", "-6", "-n", "-I", source,
                "-i", str(args.interval), "-c", str(args.count), TARGET,
            ]
            proc = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)
            processes[slice_id] = (proc, handle, logpath, source)

        for slice_id, (proc, handle, logpath, source) in processes.items():
            exit_code = proc.wait()
            handle.close()
            text = logpath.read_text(encoding="utf-8", errors="replace")
            row = parse_log(text, exit_code=exit_code, slice_id=slice_id,
                            source=source, scenario_id=args.scenario_id,
                            run_id=run_id, raw_log=logpath)
            rows.append(row)
            print(
                f"{slice_id:<5} sent={row['sent']} received={row['received']} "
                f"loss={row['packet_loss_pct']:.2f}% "
                f"avg={row['rtt_avg_ms']} ms p95={row['rtt_p95_ms']} ms",
                flush=True,
            )

    results_path = result_dir / f"core_rtt_results_{batch_id}.csv"
    write_csv(results_path, rows, FIELDS)
    aggregate = []
    for slice_id in SOURCES:
        sub = [r for r in rows if r["slice_id"] == slice_id]
        pooled_rtts = []
        for r in sub:
            log_text = Path(r["raw_log"]).read_text(encoding="utf-8", errors="replace")
            pooled_rtts.extend(float(x) for x in re.findall(r"\btime=([0-9.]+)\s*ms", log_text))
        pooled_rtts.sort()
        total_sent = sum(r["sent"] for r in sub)
        total_received = sum(r["received"] for r in sub)
        pooled_p95 = (pooled_rtts[math.ceil(0.95 * len(pooled_rtts)) - 1]
                      if pooled_rtts else "")
        aggregate.append({
            "scenario_id": args.scenario_id,
            "batch_id": batch_id,
            "slice_id": slice_id,
            "runs": len(sub),
            "total_sent": total_sent,
            "total_received": total_received,
            "overall_packet_loss_pct": round(100 * (1 - total_received / total_sent), 5),
            "mean_rtt_ms": round(sum(pooled_rtts) / len(pooled_rtts), 4)
                if pooled_rtts else "",
            "pooled_rtt_p95_ms": pooled_p95,
        })
    aggregate_path = result_dir / f"core_rtt_aggregate_{batch_id}.csv"
    write_csv(aggregate_path, aggregate, list(aggregate[0]))
    print("\nSaved:")
    print(f"  {results_path}")
    print(f"  {aggregate_path}")
    print(f"  Raw logs: {batch_dir}")
    print("NOTE: pooled_rtt_p95_ms is p95 over all successfully received RTT samples.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
