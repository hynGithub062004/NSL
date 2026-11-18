from .base_scheduler import BaseScheduler
from .qos_heuristic import QoSHeuristicScheduler
from .random_scheduler import RandomScheduler
from .queue_based import QueueBasedScheduler
from .static import StaticScheduler


SCHEDULERS = {
    "static": StaticScheduler(),
    "queue_based": QueueBasedScheduler(),
    "random": RandomScheduler(),
    "qos_heuristic": QoSHeuristicScheduler(),
}


__all__ = [
    "BaseScheduler",
    "QoSHeuristicScheduler",
    "QueueBasedScheduler",
    "RandomScheduler",
    "SCHEDULERS",
    "StaticScheduler",
]
