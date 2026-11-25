"""Module 2: event study and insider-trade screening."""

from .event_study import EventStudyConfig
from .report import DetectionResult, run_detection, write_detection_report
from .screening import ScreeningConfig

__all__ = [
    "DetectionResult",
    "EventStudyConfig",
    "ScreeningConfig",
    "run_detection",
    "write_detection_report",
]
