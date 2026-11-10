#!/usr/bin/env python3
"""TV4 Core Network: repeatable TCP/UDP iperf3 measurements for GNS3 SRv6.

Run on the GNS3 VM, not inside a Docker node. Python standard library only.
No network configuration is changed. A running iperf3 server on the GNS3 Server
container, listening on [2001:db8:40::2]:5201, is required.

For repeatability, tests run sequentially (no cross-slice contention). A
separate simultaneous-load benchmark is needed for E2E isolation tests.
"""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

DEST = "2001:db8:40::2"
PORT = 5201
SLICES = {
    "embb": {"src": "2001:db8:10::2", "policy": "high_bandwidth", "tc_rate_mbps": 100},
    "urllc": {"src": "2001:db8:10::3", "policy": "low_latency", "tc_rate_mbps": 30},
}
FIELDS = [
    "timestamp_utc", "scenario_id", "batch_id", "request_id", "run_id", "window_id",
    "slice_id", "selected_policy", "protocol", "source_ipv6", "destination_ipv6",
    "configured_tc_rate_mbps", "target_udp_mbps", "tcp_mss_bytes", "udp_datagram_bytes",
    "duration_seconds", "omit_seconds", "receiver_mbps", "sender_mbps",
    "tcp_retransmits", "udp_jitter_ms", "udp_lost_packets", "udp_total_packets",
    "udp_loss_pct", "test_status", "error", "raw_log",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def docker_cmd(*argv, timeout=20):
    return subprocess.run(
        ["sudo", "-n", "docker", *argv], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def required_docker(*argv, timeout=20):
    proc = docker_cmd(*argv, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"Docker command failed: {' '.join(argv)}\n{proc.stderr.strip()}"
        )
    return proc.stdout


def find_nodes():
    output = required_docker("ps", "--format", "{{.ID}} {{.Names}}")
    nodes = {}
    for line in output.strip().splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        cid, name = parts
        for label in ("Client", "Server", "R2", "R3"):
            if name.startswith("GNS3." + label + "."):
                if label in nodes:
                    raise RuntimeError(f"More than one GNS3.{label} container is running")
                nodes[label] = cid
    missing = [label for label in ("Client", "Server", "R2", "R3") if label not in nodes]
    if missing:
        raise RuntimeError("Missing running Docker node(s): " + ", ".join(missing))
    return nodes


def precheck(nodes, output_dir):
    snapshots = {}
    c = nodes["Client"]
    ipv6 = required_docker("exec", c, "ip", "-6", "addr", "show", "dev", "eth0")
    snapshots["client_addresses.txt"] = ipv6
    for spec in SLICES.values():
        if spec["src"] not in ipv6:
            raise RuntimeError("Client missing address " + spec["src"] + ". Check GNS3 configuration.")
    route = required_docker("exec", c, "ip", "-6", "route", "get", DEST, "from", SLICES["embb"]["src"])
    snapshots["client_route.txt"] = route
    try:
        routes = required_docker("exec", c, "ip", "-6", "route", "show", DEST + "/128")
        snapshots["client_route_mtu.txt"] = routes
        if "mtu 1420" not in routes:
            print("WARNING: Client host route does not show mtu 1420; TCP MSS 1200 will still be used.", flush=True)
    except RuntimeError as exc:
        print("WARNING: Could not read host route:", exc, flush=True)
    for label in ("R2", "R3"):
        tc = required_docker("exec", nodes[label], "tc", "qdisc", "show", "dev", "eth1")
        snapshots[label.lower() + "_tc_eth1.txt"] = tc
        if "netem" not in tc:
            raise RuntimeError(f"No netem qdisc on {label} eth1. QoS setup must be restored before comparing results.")
    for label in ("Client", "Server"):
        ver = required_docker("exec", nodes[label], "iperf3", "--version")
        snapshots[label.lower() + "_iperf3_version.txt"] = ver
    try:
        listeners = required_docker("exec", nodes["Server"], "ss", "-lnt")
        snapshots["server_tcp_listeners.txt"] = listeners
        if not re.search(r"(?m)\b5201\b", listeners):
            print("WARNING: No listener on TCP 5201 detected. Start iperf3 server in Server console.", flush=True)
    except RuntimeError:
        print("WARNING: 'ss' unavailable on Server. Verify iperf3 -s is running before test.", flush=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in snapshots.items():
        (output_dir / filename).write_text(content, encoding="utf-8")
    print("Precheck snapshots saved to:", output_dir, flush=True)
    for label in ("R2", "R3"):
        print(f"{label} eth1: {snapshots[label.lower() + '_tc_eth1.txt'].strip()}", flush=True)
    return True


def get_dict(obj, key):
    value = obj.get(key, {})
    return value if isinstance(value, dict) else {}


def extract_metrics(data, protocol):
    if "error" in data:
        raise ValueError("iperf3 error: " + str(data["error"]))
    end = get_dict(data, "end")
    received = get_dict(end, "sum_received")
    sent = get_dict(end, "sum_sent")
    if protocol == "udp" and not received:
        legacy = get_dict(end, "sum")
        if legacy and legacy.get("sender") is False:
            received = legacy
    if not received:
        raise ValueError("iperf3 JSON missing receiver summary (end.sum_received)")
    bits = received.get("bits_per_second")
    if bits is None:
        raise ValueError("iperf3 receiver summary missing bits_per_second")
    if protocol == "udp":
        missing = [x for x in ("jitter_ms", "lost_packets", "packets", "lost_percent") if x not in received]
        if missing:
            raise ValueError("iperf3 UDP JSON missing fields: " + ", ".join(missing))
    return {
        "receiver_mbps": round(float(bits) / 1e6, 5),
        "sender_mbps": round(float(sent["bits_per_second"]) / 1e6, 5) if "bits_per_second" in sent else "",
        "tcp_retransmits": sent.get("retransmits", "") if protocol == "tcp" else "",
        "udp_jitter_ms": round(float(received["jitter_ms"]), 5) if protocol == "udp" else "",
        "udp_lost_packets": received["lost_packets"] if protocol == "udp" else "",
        "udp_total_packets": received["packets"] if protocol == "udp" else "",
        "udp_loss_pct": round(float(received["lost_percent"]), 6) if protocol == "udp" else "",
    }


def run_test(nodes, *, spec, slice_id, protocol, args, run_id, batch_id, index, log_dir):
    request_id = f"tv4-{batch_id}-{index:02d}-{slice_id}-{protocol}"
    logfile = log_dir / f"{run_id}_{slice_id}_{protocol}.json"
    errfile = log_dir / f"{run_id}_{slice_id}_{protocol}.stderr.txt"
    row = dict.fromkeys(FIELDS, "")
    row.update({
        "timestamp_utc": utc_now(), "scenario_id": args.scenario_id,
        "batch_id": batch_id, "request_id": request_id, "run_id": run_id,
        "window_id": str(index), "slice_id": slice_id,
        "selected_policy": spec["policy"], "protocol": protocol,
        "source_ipv6": spec["src"], "destination_ipv6": DEST,
        "configured_tc_rate_mbps": spec["tc_rate_mbps"],
        "target_udp_mbps": args.udp_rate if protocol == "udp" else "",
        "tcp_mss_bytes": args.mss if protocol == "tcp" else "",
        "udp_datagram_bytes": args.udp_len if protocol == "udp" else "",
        "duration_seconds": args.seconds, "omit_seconds": args.omit,
        "test_status": "ERROR", "raw_log": str(logfile),
    })
    cmd = [
        "exec", nodes["Client"], "iperf3", "-6", "-c", DEST,
        "-B", spec["src"], "-p", str(PORT), "-t", str(args.seconds),
        "-O", str(args.omit), "-J",
    ]
    if protocol == "tcp":
        cmd.extend(["-M", str(args.mss)])
    else:
        cmd.extend(["-u", "-b", f"{args.udp_rate}M", "-l", str(args.udp_len)])
    try:
        proc = docker_cmd(*cmd, timeout=args.seconds + args.omit + 45)
        logfile.write_text(proc.stdout, encoding="utf-8")
        errfile.write_text(proc.stderr, encoding="utf-8")
        if proc.returncode:
            raise ValueError(f"iperf3 exited {proc.returncode}; {proc.stderr.strip()[:300]}")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid iperf3 JSON: {exc}") from exc
        metrics = extract_metrics(data, protocol)
        row.update(metrics)
        if row["receiver_mbps"] <= 0:
            raise ValueError("Receiver throughput is 0 Mbps")
        row["test_status"] = "PASS"
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        row["error"] = str(exc)[:400]
    return row


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows, scenario_id, batch_id):
    fields = [
        "scenario_id", "batch_id", "slice_id", "protocol", "runs_requested",
        "successful_tests", "failed_tests", "receiver_mbps_mean", "receiver_mbps_stdev",
        "tcp_retransmits_mean", "udp_jitter_ms_mean", "udp_loss_pct_mean",
        "udp_total_lost", "udp_total_packets", "udp_weighted_loss_pct",
    ]
    result = []
    for slice_id in SLICES:
        for protocol in ("tcp", "udp"):
            group = [r for r in rows if r["slice_id"] == slice_id and r["protocol"] == protocol]
            good = [r for r in group if r["test_status"] == "PASS"]
            def mean_of(key):
                vals = [float(x[key]) for x in good if x[key] != ""]
                return round(statistics.mean(vals), 5) if vals else ""
            mbps = [float(x["receiver_mbps"]) for x in good]
            lost = sum(int(x["udp_lost_packets"]) for x in good) if protocol == "udp" else 0
            total = sum(int(x["udp_total_packets"]) for x in good) if protocol == "udp" else 0
            result.append({
                "scenario_id": scenario_id, "batch_id": batch_id,
                "slice_id": slice_id, "protocol": protocol,
                "runs_requested": len(group), "successful_tests": len(good),
                "failed_tests": len(group) - len(good),
                "receiver_mbps_mean": mean_of("receiver_mbps"),
                "receiver_mbps_stdev": round(statistics.stdev(mbps), 5) if len(mbps) > 1 else "",
                "tcp_retransmits_mean": mean_of("tcp_retransmits") if protocol == "tcp" else "",
                "udp_jitter_ms_mean": mean_of("udp_jitter_ms") if protocol == "udp" else "",
                "udp_loss_pct_mean": mean_of("udp_loss_pct") if protocol == "udp" else "",
                "udp_total_lost": lost if protocol == "udp" else "",
                "udp_total_packets": total if protocol == "udp" else "",
                "udp_weighted_loss_pct": round(100.0 * lost / total, 6) if total > 0 else "",
            })
    return result, fields


def main():
    parser = argparse.ArgumentParser(description="TV4 benchmark: iperf3 TCP throughput, UDP jitter and loss for two SRv6 slices")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--omit", type=int, default=2, help="Warm-up seconds ignored by iperf3")
    parser.add_argument("--mss", type=int, default=1200, help="Consistent TCP MSS in bytes")
    parser.add_argument("--udp-len", type=int, default=1200, help="UDP datagram payload in bytes")
    parser.add_argument("--udp-rate", type=float, default=20.0, help="Mbps offered for both UDP tests")
    parser.add_argument("--scenario-id", default="core_tc_qos")
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "TV4_KPI_Benchmark")
    parser.add_argument("--check-only", action="store_true", help="Check nodes, qdiscs, server listener and exit without tests")
    args = parser.parse_args()
    if not (1 <= args.runs <= 30 and 3 <= args.seconds <= 3600 and 0 <= args.omit <= 20 and 536 <= args.mss <= 1400
            and 100 <= args.udp_len <= 1300 and 0.1 <= args.udp_rate <= 30.0):
        parser.error("invalid parameter range: runs 1..30, seconds 3..3600, omit 0..20, mss 536..1400, udp-len 100..1300, udp-rate 0.1..30")
    nodes = find_nodes()
    outdir = args.output_dir.expanduser()
    logs = outdir / "logs"
    results = outdir / "results"
    logs.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_log = logs / ("iperf_" + batch_id)
    batch_log.mkdir(exist_ok=False)
    print("Detected Docker nodes:", nodes, flush=True)
    precheck(nodes, batch_log)
    if args.check_only:
        print("CHECK OK — no benchmark traffic generated.", flush=True)
        return 0

    print("\nTCP uses MSS", args.mss, "; UDP uses", args.udp_rate, "Mbps and datagram", args.udp_len,
          "bytes. Tests run sequentially, without competing slice traffic.", flush=True)
    rows = []
    index = 0
    for run_number in range(1, args.runs + 1):
        run_id = batch_id + "_run" + str(run_number).zfill(2)
        print(f"\n=== Run {run_number}/{args.runs} ===", flush=True)
        for slice_id, spec in SLICES.items():
            for protocol in ("tcp", "udp"):
                index += 1
                print(f"  {slice_id.upper()} {protocol.upper()} ...", flush=True)
                row = run_test(nodes, spec=spec, slice_id=slice_id, protocol=protocol,
                               args=args, run_id=run_id, batch_id=batch_id,
                               index=index, log_dir=batch_log)
                rows.append(row)
                if row["test_status"] == "PASS":
                    metric = f"receiver={row['receiver_mbps']:.3f} Mbps"
                    if protocol == "udp":
                        metric += f" jitter={row['udp_jitter_ms']:.4f}ms loss={row['udp_loss_pct']:.4f}%"
                    else:
                        metric += f" retransmits={row['tcp_retransmits']}"
                    print("    PASS", metric, flush=True)
                else:
                    print("    ERROR", row["error"], flush=True)
                # iperf3 server may need a short idle interval to recycle resources.
                time.sleep(1)
    detailed = results / f"core_iperf_results_{batch_id}.csv"
    write_csv(detailed, rows, FIELDS)
    agg, fields = aggregate(rows, args.scenario_id, batch_id)
    aggpath = results / f"core_iperf_aggregate_{batch_id}.csv"
    write_csv(aggpath, agg, fields)
    print("\nSaved:", detailed, aggpath, "\nRaw logs:", batch_log, sep="\n", flush=True)
    print("Important: test traffic was sequential, not a simultaneous isolation benchmark.")
    failures = sum(r["test_status"] != "PASS" for r in rows)
    if failures:
        print(f"WARNING: {failures} test(s) failed. Inspect CSV/error logs; do not use failed rows as measurements.")
    return 0 if not failures else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print("ERROR:", error, file=sys.stderr)
        sys.exit(1)
