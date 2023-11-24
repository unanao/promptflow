from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FeatureState(Enum):
    """The enum of feature state.

    READY: The feature is ready to use.
    E2ETEST: The feature is not ready to be shipped to customer and is in e2e testing.
    """

    READY = "Ready"
    E2ETEST = "E2ETest"


@dataclass
class Feature:
    """The dataclass of feature."""

    name: str
    description: str
    state: FeatureState
    component: Optional[str] = "executor"


def get_feature_list():
    feature_list = [
        Feature(
            name="ActivateConfig",
            description="Bypass node execution when the node does not meet activate condition.",
            state=FeatureState.READY,
        ),
        Feature(
            name="Image",
            description="Support image input and output.",
            state=FeatureState.READY,
        ),
    ]

    return feature_list
