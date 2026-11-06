from __future__ import annotations

import math
from typing import Any

from ran.rb_capacity import CQI_SPECTRAL_EFFICIENCY

from .base_scheduler import BaseScheduler


class QoSHeuristicScheduler(BaseScheduler):
    """Phan bo RB theo backlog, CQI va urgency cua URLLC."""

    name = "qos_heuristic"

    def select_action(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Tao Action QoS theo State va cau hinh hien tai."""

        common_config = config.get("common", {})
        scheduler_config = config.get("qos_heuristic", {})

        parameters = self._read_config(
            common_config=common_config,
            scheduler_config=scheduler_config,
        )
        state_values = self._read_state(state)

        rb_embb, rb_urllc = self._allocate_rb(
            embb_queue_bits=int(state_values["embb_queue_bits"]),
            urllc_queue_bits=int(state_values["urllc_queue_bits"]),
            embb_cqi=int(state_values["embb_cqi"]),
            urllc_cqi=int(state_values["urllc_cqi"]),
            oldest_delay_ms=float(state_values["oldest_delay_ms"]),
            deadline_ms=float(state_values["deadline_ms"]),
            total_rb=int(parameters["total_rb"]),
            slot_duration_ms=float(parameters["slot_duration_ms"]),
            min_rb_embb=int(parameters["min_rb_embb"]),
            min_rb_urllc=int(parameters["min_rb_urllc"]),
            embb_queue_weight=float(parameters["embb_queue_weight"]),
            embb_cqi_weight=float(parameters["embb_cqi_weight"]),
            urllc_queue_weight=float(parameters["urllc_queue_weight"]),
            urllc_urgency_weight=float(parameters["urllc_urgency_weight"]),
            urllc_cqi_weight=float(parameters["urllc_cqi_weight"]),
            low_cqi_compensation_weight=float(
                parameters["low_cqi_compensation_weight"]
            ),
            urgency_power=float(parameters["urgency_power"]),
        )

        return self.build_action(
            state=state,
            rb_embb=rb_embb,
            rb_urllc=rb_urllc,
            action_id=int(parameters["action_id"]),
            request_id=request_id,
        )

    @staticmethod
    def _read_non_negative_integer(value: Any, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} must be an integer")
        if value < 0:
            raise ValueError(f"{field_name} must not be negative")
        return value

    @staticmethod
    def _read_finite_number(
        value: Any,
        field_name: str,
        *,
        allow_zero: bool = True,
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field_name} must be a finite number")

        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{field_name} must be a finite number")

        if allow_zero:
            if result < 0:
                raise ValueError(f"{field_name} must not be negative")
        elif result <= 0:
            raise ValueError(f"{field_name} must be greater than 0")

        return result

    @classmethod
    def _read_cqi(cls, value: Any, field_name: str) -> int:
        cqi = cls._read_non_negative_integer(value, field_name)
        if cqi not in CQI_SPECTRAL_EFFICIENCY:
            raise ValueError(f"{field_name} must be within 1..15")
        return cqi

    @classmethod
    def _read_state(cls, state: dict[str, Any]) -> dict[str, int | float]:
        if not isinstance(state, dict):
            raise ValueError("state must be a dictionary")

        try:
            time_slot = state["time_slot"]
            embb_state = state["embb"]
            urllc_state = state["urllc"]
            embb_queue_bits = embb_state["queue_bits"]
            embb_cqi = embb_state["cqi"]
            urllc_queue_bits = urllc_state["queue_bits"]
            urllc_cqi = urllc_state["cqi"]
            oldest_delay_ms = urllc_state["oldest_packet_delay_ms"]
            deadline_ms = urllc_state["deadline_ms"]
        except (KeyError, TypeError) as exc:
            raise ValueError("State is missing a required QoS field") from exc

        cls._read_non_negative_integer(time_slot, "time_slot")

        return {
            "embb_queue_bits": cls._read_non_negative_integer(
                embb_queue_bits, "embb.queue_bits"
            ),
            "embb_cqi": cls._read_cqi(embb_cqi, "embb.cqi"),
            "urllc_queue_bits": cls._read_non_negative_integer(
                urllc_queue_bits, "urllc.queue_bits"
            ),
            "urllc_cqi": cls._read_cqi(urllc_cqi, "urllc.cqi"),
            "oldest_delay_ms": cls._read_finite_number(
                oldest_delay_ms, "urllc.oldest_packet_delay_ms"
            ),
            "deadline_ms": cls._read_finite_number(
                deadline_ms, "urllc.deadline_ms", allow_zero=False
            ),
        }

    @classmethod
    def _read_config(
        cls,
        *,
        common_config: dict[str, Any],
        scheduler_config: dict[str, Any],
    ) -> dict[str, int | float]:
        if not isinstance(common_config, dict):
            raise ValueError("common configuration must be a dictionary")
        if not isinstance(scheduler_config, dict):
            raise ValueError("qos_heuristic configuration must be a dictionary")

        total_rb = cls._read_non_negative_integer(
            common_config.get("total_rb", 50), "total_rb"
        )
        if total_rb <= 0:
            raise ValueError("total_rb must be greater than 0")

        slot_duration_ms = cls._read_finite_number(
            common_config.get("slot_duration_ms"),
            "slot_duration_ms",
            allow_zero=False,
        )
        min_rb_embb = cls._read_non_negative_integer(
            scheduler_config.get("min_rb_embb", 5), "min_rb_embb"
        )
        min_rb_urllc = cls._read_non_negative_integer(
            scheduler_config.get("min_rb_urllc", 5), "min_rb_urllc"
        )
        if min_rb_embb + min_rb_urllc > total_rb:
            raise ValueError(
                "The sum of minimum RB values must not exceed total_rb"
            )

        parameters: dict[str, int | float] = {
            "total_rb": total_rb,
            "slot_duration_ms": slot_duration_ms,
            "min_rb_embb": min_rb_embb,
            "min_rb_urllc": min_rb_urllc,
            "action_id": cls._read_non_negative_integer(
                scheduler_config.get("action_id", 2), "action_id"
            ),
        }

        weight_fields = {
            "embb_queue_weight": 0.70,
            "embb_cqi_weight": 0.30,
            "urllc_queue_weight": 0.45,
            "urllc_urgency_weight": 1.25,
            "urllc_cqi_weight": 0.10,
            "low_cqi_compensation_weight": 0.0,
            "urgency_power": 2.0,
        }
        for field_name, default_value in weight_fields.items():
            parameters[field_name] = cls._read_finite_number(
                scheduler_config.get(field_name, default_value),
                field_name,
                allow_zero=(field_name != "urgency_power"),
            )

        return parameters

    @staticmethod
    def _calculate_urgency(
        *,
        urllc_queue_bits: int,
        oldest_delay_ms: float,
        deadline_ms: float,
        slot_duration_ms: float,
        urgency_power: float,
    ) -> float:
        if urllc_queue_bits == 0:
            return 0.0
        if deadline_ms <= 0:
            raise ValueError("deadline_ms must be greater than 0")
        if slot_duration_ms <= 0:
            raise ValueError("slot_duration_ms must be greater than 0")
        if urgency_power <= 0:
            raise ValueError("urgency_power must be greater than 0")

        effective = (oldest_delay_ms + slot_duration_ms) / deadline_ms
        effective = min(max(effective, 0.0), 1.0)
        return effective**urgency_power

    @staticmethod
    def _normalize_cqi_efficiency(cqi: int) -> float:
        if (
            isinstance(cqi, bool)
            or not isinstance(cqi, int)
            or cqi not in CQI_SPECTRAL_EFFICIENCY
        ):
            raise ValueError("cqi must be an integer within 1..15")

        return (
            CQI_SPECTRAL_EFFICIENCY[cqi]
            / CQI_SPECTRAL_EFFICIENCY[15]
        )

    @staticmethod
    def _backlog_pressure(queue_bits: int) -> float:
        if (
            isinstance(queue_bits, bool)
            or not isinstance(queue_bits, int)
            or queue_bits < 0
        ):
            raise ValueError("queue_bits must be a non-negative integer")
        return math.log1p(queue_bits)

    @classmethod
    def _allocate_rb(
        cls,
        *,
        embb_queue_bits: int,
        urllc_queue_bits: int,
        embb_cqi: int,
        urllc_cqi: int,
        oldest_delay_ms: float,
        deadline_ms: float,
        total_rb: int,
        slot_duration_ms: float,
        min_rb_embb: int,
        min_rb_urllc: int,
        embb_queue_weight: float,
        embb_cqi_weight: float,
        urllc_queue_weight: float,
        urllc_urgency_weight: float,
        urllc_cqi_weight: float,
        low_cqi_compensation_weight: float,
        urgency_power: float,
    ) -> tuple[int, int]:
        if embb_queue_bits == 0 and urllc_queue_bits == 0:
            rb_embb = total_rb // 2
            return rb_embb, total_rb - rb_embb
        if urllc_queue_bits == 0:
            return total_rb, 0
        if embb_queue_bits == 0:
            return 0, total_rb

        remaining_rb = total_rb - min_rb_embb - min_rb_urllc

        embb_backlog = cls._backlog_pressure(embb_queue_bits)
        urllc_backlog = cls._backlog_pressure(urllc_queue_bits)
        embb_efficiency = cls._normalize_cqi_efficiency(embb_cqi)
        urllc_efficiency = cls._normalize_cqi_efficiency(urllc_cqi)
        urgency = cls._calculate_urgency(
            urllc_queue_bits=urllc_queue_bits,
            oldest_delay_ms=oldest_delay_ms,
            deadline_ms=deadline_ms,
            slot_duration_ms=slot_duration_ms,
            urgency_power=urgency_power,
        )

        score_embb = (
            embb_queue_weight * embb_backlog
            + embb_cqi_weight * embb_efficiency
        )
        score_urllc = (
            urllc_queue_weight * urllc_backlog
            + urllc_urgency_weight * urgency
            + urllc_cqi_weight * urllc_efficiency
            + low_cqi_compensation_weight
            * urgency
            * (1.0 - urllc_efficiency)
        )
        total_score = score_embb + score_urllc

        if total_score <= 0:
            rb_embb = total_rb // 2
            return rb_embb, total_rb - rb_embb

        embb_real = remaining_rb * score_embb / total_score
        urllc_real = remaining_rb * score_urllc / total_score
        extra_embb = math.floor(embb_real)
        extra_urllc = math.floor(urllc_real)
        unallocated_rb = remaining_rb - extra_embb - extra_urllc
        embb_remainder = embb_real - extra_embb
        urllc_remainder = urllc_real - extra_urllc

        for _ in range(unallocated_rb):
            if embb_remainder > urllc_remainder:
                extra_embb += 1
            elif urllc_remainder > embb_remainder:
                extra_urllc += 1
            elif urgency > 0:
                extra_urllc += 1
            else:
                extra_embb += 1

        rb_embb = min_rb_embb + extra_embb
        rb_urllc = min_rb_urllc + extra_urllc

        if rb_embb + rb_urllc != total_rb:
            raise RuntimeError("QoS allocation does not preserve total_rb")

        return rb_embb, rb_urllc
