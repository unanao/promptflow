# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import pytest

from promptflow import PFClient
from promptflow._sdk._configuration import Configuration

AZUREML_RESOURCE_PROVIDER = "Microsoft.MachineLearningServices"
RESOURCE_ID_FORMAT = "/subscriptions/{}/resourceGroups/{}/providers/{}/workspaces/{}"


@pytest.fixture
def pf() -> PFClient:
    return PFClient()


@pytest.fixture
def global_config(subscription_id: str, resource_group_name: str, workspace_name: str) -> None:
    config = Configuration.get_instance()
    if Configuration.CONNECTION_PROVIDER in config._config:
        return
    config.set_config(
        Configuration.CONNECTION_PROVIDER,
        "azureml:"
        + RESOURCE_ID_FORMAT.format(subscription_id, resource_group_name, AZUREML_RESOURCE_PROVIDER, workspace_name),
    )
