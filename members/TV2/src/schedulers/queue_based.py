from __future__ import annotations

from typing import Any

from .base_scheduler import BaseScheduler


class QueueBasedScheduler(BaseScheduler):
    """Phân bổ RB theo tỷ lệ queue_bits của eMBB và URLLC."""

    name = "queue_based"

    def select_action(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Tạo Action dựa trên trạng thái hàng đợi của hai slice."""

        common_config = config.get("common", {})
        scheduler_config = config.get("queue_based", config)

        total_rb = self._read_non_negative_integer(
            common_config.get("total_rb", 50),
            "total_rb",
        )
        min_rb_embb = self._read_non_negative_integer(
            scheduler_config.get("min_rb_embb", 5),
            "min_rb_embb",
        )
        min_rb_urllc = self._read_non_negative_integer(
            scheduler_config.get("min_rb_urllc", 5),
            "min_rb_urllc",
        )
        action_id = self._read_non_negative_integer(
            scheduler_config.get("action_id", 1),
            "action_id",
        )

        self._validate_config(
            total_rb=total_rb,
            min_rb_embb=min_rb_embb,
            min_rb_urllc=min_rb_urllc,
        )

        embb_queue_bits = self._read_queue_bits(
            state=state,
            slice_name="embb",
        )
        urllc_queue_bits = self._read_queue_bits(
            state=state,
            slice_name="urllc",
        )

        rb_embb, rb_urllc = self._allocate_rb(
            embb_queue_bits=embb_queue_bits,
            urllc_queue_bits=urllc_queue_bits,
            total_rb=total_rb,
            min_rb_embb=min_rb_embb,
            min_rb_urllc=min_rb_urllc,
        )

        return self.build_action(
            state=state,
            rb_embb=rb_embb,
            rb_urllc=rb_urllc,
            action_id=action_id,
            request_id=request_id,
        )

    @staticmethod
    def _read_non_negative_integer(
        value: Any,
        field_name: str,
    ) -> int:
        """Đọc một giá trị số nguyên không âm từ cấu hình."""

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{field_name} must be an integer"
            )

        if value < 0:
            raise ValueError(
                f"{field_name} must not be negative"
            )

        return value

    @classmethod
    def _read_queue_bits(
        cls,
        state: dict[str, Any],
        slice_name: str,
    ) -> int:
        """Đọc queue_bits của một slice từ State."""

        try:
            slice_state = state[slice_name]
            queue_bits = slice_state["queue_bits"]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"Missing queue_bits for slice {slice_name}"
            ) from exc

        return cls._read_non_negative_integer(
            queue_bits,
            f"{slice_name}.queue_bits",
        )

    @staticmethod
    def _validate_config(
        total_rb: int,
        min_rb_embb: int,
        min_rb_urllc: int,
    ) -> None:
        """Kiểm tra tính hợp lệ của cấu hình phân bổ."""

        if total_rb <= 0:
            raise ValueError(
                "total_rb must be greater than 0"
            )

        minimum_total = min_rb_embb + min_rb_urllc

        if minimum_total > total_rb:
            raise ValueError(
                "The sum of minimum RB values must not exceed "
                "total_rb"
            )

    @staticmethod
    def _allocate_rb(
        embb_queue_bits: int,
        urllc_queue_bits: int,
        total_rb: int,
        min_rb_embb: int,
        min_rb_urllc: int,
    ) -> tuple[int, int]:
        """Chia RB còn lại theo tỷ lệ queue_bits."""

        remaining_rb = (
            total_rb
            - min_rb_embb
            - min_rb_urllc
        )

        total_queue_bits = (
            embb_queue_bits
            + urllc_queue_bits
        )

        if total_queue_bits == 0:
            extra_embb = remaining_rb // 2
            extra_urllc = remaining_rb - extra_embb

            return (
                min_rb_embb + extra_embb,
                min_rb_urllc + extra_urllc,
            )

        embb_numerator = (
            remaining_rb * embb_queue_bits
        )
        urllc_numerator = (
            remaining_rb * urllc_queue_bits
        )

        extra_embb = (
            embb_numerator // total_queue_bits
        )
        extra_urllc = (
            urllc_numerator // total_queue_bits
        )

        unallocated_rb = (
            remaining_rb
            - extra_embb
            - extra_urllc
        )

        embb_remainder = (
            embb_numerator % total_queue_bits
        )
        urllc_remainder = (
            urllc_numerator % total_queue_bits
        )

        if unallocated_rb > 0:
            if embb_remainder >= urllc_remainder:
                extra_embb += unallocated_rb
            else:
                extra_urllc += unallocated_rb

        rb_embb = min_rb_embb + extra_embb
        rb_urllc = min_rb_urllc + extra_urllc

        if rb_embb + rb_urllc != total_rb:
            raise RuntimeError(
                "Queue-Based allocation does not preserve total_rb"
            )

        return rb_embb, rb_urllc