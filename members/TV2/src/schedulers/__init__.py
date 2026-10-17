from .base_scheduler import BaseScheduler
from .queue_based import QueueBasedScheduler
from .static import StaticScheduler


SCHEDULERS = {
    "static": StaticScheduler(),
    "queue_based": QueueBasedScheduler(),
}


__all__ = [
    "BaseScheduler",
    "QueueBasedScheduler",
    "SCHEDULERS",
    "StaticScheduler",
]
