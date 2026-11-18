from .base_scheduler import BaseScheduler
from .qos_heuristic import QoSHeuristicScheduler
from .queue_based import QueueBasedScheduler
from .static import StaticScheduler


SCHEDULERS = {
    "static": StaticScheduler(),
    "queue_based": QueueBasedScheduler(),
    "qos_heuristic": QoSHeuristicScheduler(),
}


__all__ = [
    "BaseScheduler",
    "QoSHeuristicScheduler",
    "QueueBasedScheduler",
    "SCHEDULERS",
    "StaticScheduler",
]