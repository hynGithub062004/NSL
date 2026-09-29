"""Map CQI and allocated resource blocks to service capacity."""

from __future__ import annotations

import math


CQI_SPECTRAL_EFFICIENCY = {
    1: 0.1523,
    2: 0.2344,
    3: 0.3770,
    4: 0.6016,
    5: 0.8770,
    6: 1.1758,
    7: 1.4766,
    8: 1.9141,
    9: 2.4063,
    10: 2.7305,
    11: 3.3223,
    12: 3.9023,
    13: 4.5234,
    14: 5.1152,
    15: 5.5547,
}


def capacity_bits(rb_count: int, cqi: int, radio_config: dict) -> int:
    if not isinstance(rb_count, int) or rb_count < 0:
        raise ValueError("rb_count must be a non-negative integer")
    if cqi not in CQI_SPECTRAL_EFFICIENCY:
        raise ValueError("CQI must be an integer from 1 to 15")
    resource_elements = int(radio_config["resource_elements_per_rb"])
    overhead_factor = float(radio_config.get("overhead_factor", 1.0))
    if not 0 < overhead_factor <= 1:
        raise ValueError("overhead_factor must be within (0, 1]")
    return math.floor(
        rb_count * resource_elements * CQI_SPECTRAL_EFFICIENCY[cqi] * overhead_factor
    )

