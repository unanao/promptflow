# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

ENVIRON_TEST_MODE = "PROMPT_FLOW_TEST_MODE"


class TestMode:
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"


FILTER_HEADERS = [
    "aml-user-token",
    "authorization",
    "date",
    "etag",
    "request-context",
    "x-aml-cluster",
    "x-ms-access-tier",
    "x-ms-access-tier-inferred",
    "x-ms-client-request-id",
    "x-ms-client-session-id",
    "x-ms-client-user-type",
    "x-ms-correlation-request-id",
    "x-ms-file-permission-key",
    "x-ms-lease-state",
    "x-ms-lease-status",
    "x-ms-server-encrypted",
    "x-ms-ratelimit-remaining-subscription-reads",
    "x-ms-ratelimit-remaining-subscription-writes",
    "x-ms-response-type",
    "x-ms-request-id",
    "x-ms-routing-request-id",
    "x-msedge-ref",
]


class SanitizedValues:
    SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
    RESOURCE_GROUP_NAME = "00000"
    WORKSPACE_NAME = "00000"
    WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"
    TENANT_ID = "00000000-0000-0000-0000-000000000000"
    USER_OBJECT_ID = "00000000-0000-0000-0000-000000000000"
    # workspace
    DISCOVERY_URL = "https://eastus.api.azureml.ms/discovery"
    # datastore
    FAKE_KEY = "this is fake key"
    FAKE_ACCOUNT_NAME = "fake_account_name"
    FAKE_CONTAINER_NAME = "fake-container-name"
    FAKE_FILE_SHARE_NAME = "fake-file-share-name"
    # aoai connection
    FAKE_API_BASE = "https://fake.openai.azure.com"
    # storage
    UPLOAD_HASH = "000000000000000000000000000000000000"
    BLOB_STORAGE_REQUEST_HOST = "fake_account_name.blob.core.windows.net"
    # trick: "unknown_user" is the value when client fails to get username
    #        use this value so that we don't do extra logic when replay
    USERNAME = "unknown_user"


class AzureMLResourceTypes:
    CONNECTION = "Microsoft.MachineLearningServices/workspaces/connections"
    DATASTORE = "Microsoft.MachineLearningServices/workspaces/datastores"
    WORKSPACE = "Microsoft.MachineLearningServices/workspaces"


TEST_CLASSES_FOR_RUN_INTEGRATION_TEST_RECORDING = [
    "TestCliWithAzure",
    "TestFlowRun",
    "TestFlow",
]
