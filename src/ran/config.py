"""Configuration loading with no mandatory third-party dependency.

The project configuration intentionally uses a conservative YAML subset:
nested mappings, booleans, nulls, strings and numeric scalars.  PyYAML is used
when installed; otherwise the built-in parser below handles all supplied files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a scenario configuration is invalid."""


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return {}
    if value.startswith(("{", "[")):
        return json.loads(value)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _load_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line_number, original in enumerate(text.splitlines(), 1):
        if not original.strip() or original.lstrip().startswith("#"):
            continue
        if "\t" in original[: len(original) - len(original.lstrip())]:
            raise ConfigError(f"Line {line_number}: use spaces, not tabs")
        indent = len(original) - len(original.lstrip(" "))
        content = original.strip()
        if ":" not in content:
            raise ConfigError(f"Line {line_number}: expected 'key: value'")
        key, raw_value = content.split(":", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"Line {line_number}: empty key")
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        value = _parse_scalar(raw_value)
        parent[key] = value
        if isinstance(value, dict):
            stack.append((indent, value))
    return root


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ImportError:
        data = _load_simple_yaml(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError("Top-level YAML value must be a mapping")
    validate_config(data)
    return data


def validate_config(config: dict[str, Any]) -> None:
    required_sections = {"simulation", "scenario", "embb", "urllc", "channel", "radio"}
    missing = sorted(required_sections - config.keys())
    if missing:
        raise ConfigError(f"Missing configuration sections: {', '.join(missing)}")

    simulation = config["simulation"]
    radio = config["radio"]
    urllc = config["urllc"]
    channel = config["channel"]
    positive = {
        "simulation.slots": simulation.get("slots"),
        "simulation.slot_duration_ms": simulation.get("slot_duration_ms"),
        "radio.total_rb": radio.get("total_rb"),
        "radio.resource_elements_per_rb": radio.get("resource_elements_per_rb"),
        "urllc.packet_size_bits": urllc.get("packet_size_bits"),
        "urllc.deadline_ms": urllc.get("deadline_ms"),
    }
    for name, value in positive.items():
        if not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"{name} must be a positive number")
    for name in ("embb_initial_cqi", "urllc_initial_cqi", "min_cqi", "max_cqi"):
        value = channel.get(name)
        if not isinstance(value, int):
            raise ConfigError(f"channel.{name} must be an integer")
    if not 1 <= channel["min_cqi"] <= channel["max_cqi"] <= 15:
        raise ConfigError("channel CQI range must be within 1..15")

