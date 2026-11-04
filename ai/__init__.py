"""AI recommendation module for fyp-SleepMonitor.

Separate and supplementary: it never modifies the QoS framework, publisher, MQTT,
or ingest worker. It produces non-diagnostic guidance bands only.
"""

from .classifier import Phase2Classifier, load as load_classifier
from .config import AI_RECOMMENDATION_DISCLAIMER
from .features import NIGHTLY_FEATURES
from .nightly_adapter import (
    get_recommendation,
    session_to_nightly_features,
)

__all__ = [
    "AI_RECOMMENDATION_DISCLAIMER",
    "Phase2Classifier",
    "load_classifier",
    "get_recommendation",
    "session_to_nightly_features",
    "NIGHTLY_FEATURES",
]
