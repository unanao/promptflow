# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
# pylint: disable=protected-access
import json
import logging
import os
import re
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional, Union

import requests
from azure.ai.ml._artifacts._artifact_utilities import _check_and_upload_path
from azure.ai.ml._scope_dependent_operations import (
    OperationConfig,
    OperationsContainer,
    OperationScope,
    _ScopeDependentOperations,
)
from azure.ai.ml.constants._common import SHORT_URI_FORMAT
from azure.ai.ml.entities import Workspace
from azure.ai.ml.operations._operation_orchestrator import OperationOrchestrator
from azure.core.exceptions import HttpResponseError

from promptflow._sdk._constants import (
    CLIENT_FLOW_TYPE_2_SERVICE_FLOW_TYPE,
    DAG_FILE_NAME,
    FLOW_TOOLS_JSON,
    LOGGER_NAME,
    MAX_LIST_CLI_RESULTS,
    PROMPT_FLOW_DIR_NAME,
    WORKSPACE_LINKED_DATASTORE_NAME,
    FlowType,
    ListViewType,
)
from promptflow._sdk._errors import FlowOperationError
from promptflow._sdk._logger_factory import LoggerFactory
from promptflow._sdk._utils import PromptflowIgnoreFile, generate_flow_tools_json
from promptflow._sdk._vendor._asset_utils import traverse_directory
from promptflow._telemetry.activity import ActivityType, monitor_operation
from promptflow._telemetry.telemetry import WorkspaceTelemetryMixin
from promptflow.azure._constants._flow import DEFAULT_STORAGE
from promptflow.azure._entities._flow import Flow
from promptflow.azure._load_functions import load_flow
from promptflow.azure._restclient.flow_service_caller import FlowServiceCaller
from promptflow.azure.operations._artifact_utilities import _get_datastore_name, get_datastore_info
from promptflow.azure.operations._fileshare_storeage_helper import FlowFileStorageClient
from promptflow.exceptions import SystemErrorException

logger = LoggerFactory.get_logger(name=LOGGER_NAME, verbosity=logging.WARNING)


class FlowOperations(WorkspaceTelemetryMixin, _ScopeDependentOperations):
    """FlowOperations that can manage flows.

    You should not instantiate this class directly. Instead, you should
    create a :class:`~promptflow.azure.PFClient` instance that instantiates it for you and
    attaches it as an attribute.
    """

    _FLOW_RESOURCE_PATTERN = re.compile(r"azureml:.*?/workspaces/(?P<experiment_id>.*?)/flows/(?P<flow_id>.*?)$")

    def __init__(
        self,
        operation_scope: OperationScope,
        operation_config: OperationConfig,
        all_operations: OperationsContainer,
        credential,
        service_caller: FlowServiceCaller,
        workspace: Workspace,
        **kwargs: Dict,
    ):
        super().__init__(
            operation_scope=operation_scope,
            operation_config=operation_config,
            workspace_name=operation_scope.workspace_name,
            subscription_id=operation_scope.subscription_id,
            resource_group_name=operation_scope.resource_group_name,
        )
        self._all_operations = all_operations
        self._service_caller = service_caller
        self._credential = credential
        self._workspace = workspace

    @cached_property
    def _workspace_id(self):
        return self._workspace._workspace_id

    @cached_property
    def _index_service_endpoint_url(self):
        """Get the endpoint url for the workspace."""
        endpoint = self._service_caller._service_endpoint
        return endpoint + "index/v1.0" + self._service_caller._common_azure_url_pattern

    def _get_flow_portal_url_from_resource_id(self, flow_resource_id: str):
        """Get the portal url for the run."""
        match = self._FLOW_RESOURCE_PATTERN.match(flow_resource_id)
        if not match or len(match.groups()) != 2:
            logger.warning("Failed to parse flow resource id '%s'", flow_resource_id)
            return None
        experiment_id, flow_id = match.groups()
        return self._get_flow_portal_url(experiment_id, flow_id)

    def _get_flow_portal_url_from_index_entity(self, entity: Dict):
        """Enrich the index entity with flow portal url."""
        result = None
        experiment_id = entity["properties"].get("experimentId", None)
        flow_id = entity["properties"].get("flowId", None)

        if experiment_id and flow_id:
            result = self._get_flow_portal_url(experiment_id, flow_id)
        return result

    def _get_flow_portal_url(self, experiment_id, flow_id):
        """Get the portal url for the run."""
        # TODO[2785705]: Handle the case when endpoint is other clouds
        workspace_kind = str(self._workspace._kind).lower()
        # default refers to azure machine learning studio
        if workspace_kind == "default":
            return (
                f"https://ml.azure.com/prompts/flow/{experiment_id}/{flow_id}/"
                f"details?wsid={self._service_caller._common_azure_url_pattern}"
            )
        # project refers to azure ai studio
        elif workspace_kind == "project":
            return (
                f"https://ai.azure.com/projectflows/{flow_id}/{experiment_id}/"
                f"details/Flow?wsid={self._service_caller._common_azure_url_pattern}"
            )
        else:
            raise FlowOperationError(f"Workspace kind {workspace_kind!r} is not supported for promptflow operations.")

    @monitor_operation(activity_name="pfazure.flows.create_or_update", activity_type=ActivityType.PUBLICAPI)
    def create_or_update(self, flow: Union[str, Path], display_name=None, type=None, **kwargs) -> Flow:
        """Create a flow to remote from local source.

        :param flow: The source of the flow to create.
        :type flow: Union[str, Path]
        :param display_name: The display name of the flow to create. Default to be flow folder name + timestamp
            if not specified. e.g. "web-classification-10-27-2023-14-19-10"
        :type display_name: str
        :param type: The type of the flow to create. One of ["standard", evaluation", "chat"].
            Default to be "standard" if not specified.
        :type type: str
        :param description: The description of the flow to create. Default to be the description in flow yaml file.
        :type description: str
        :param tags: The tags of the flow to create. Default to be the tags in flow yaml file.
        :type tags: Dict[str, str]
        """
        # validate the parameters
        azure_flow, flow_display_name, flow_type, kwargs = self._validate_flow_creation_parameters(
            flow, display_name, type, **kwargs
        )
        # upload to file share
        file_share_flow_path = self._resolve_flow_code_and_upload_to_file_share(
            flow=azure_flow, flow_display_name=flow_display_name
        )
        if not file_share_flow_path:
            raise FlowOperationError(f"File share path should not be empty, got {file_share_flow_path!r}.")

        # create flow to remote
        flow_definition_file_path = f"{file_share_flow_path}/{DAG_FILE_NAME}"
        rest_flow = self._create_remote_flow_via_file_share_path(
            flow_display_name=flow_display_name,
            flow_type=flow_type,
            flow_definition_file_path=flow_definition_file_path,
            **kwargs,
        )
        result_flow = Flow._from_pf_service(rest_flow)
        result_flow.flow_portal_url = self._get_flow_portal_url_from_resource_id(rest_flow.flow_resource_id)
        flow_dict = result_flow._to_dict()
        print(f"Flow created successfully:\n{json.dumps(flow_dict, indent=4)}")

        return result_flow

    def _validate_flow_creation_parameters(self, source, flow_display_name, flow_type, **kwargs):
        """Validate the parameters for flow creation operation."""
        flow = load_flow(source)
        # if no flow name specified, use "flow name + timestamp"
        if not flow_display_name:
            flow_display_name = f"{flow.display_name}-{datetime.now().strftime('%m-%d-%Y-%H-%M-%S')}"
        elif not isinstance(flow_display_name, str):
            raise FlowOperationError(
                f"Flow name must be a string, got {type(flow_display_name)!r}: {flow_display_name!r}."
            )

        # if no flow type specified, use default flow type "standard"
        supported_flow_types = FlowType.get_all_values()
        if not flow_type:
            flow_type = FlowType.STANDARD
        elif flow_type not in supported_flow_types:
            raise FlowOperationError(
                f"Flow type {flow_type!r} is not supported, supported types are {supported_flow_types}"
            )

        # check description type
        description = kwargs.get("description", None) or flow.description

        if isinstance(description, str):
            kwargs["description"] = description
        elif description is not None:
            raise FlowOperationError(f"Description must be a string, got {type(description)!r}: {description!r}.")

        # check if the tags type is Dict[str, str]
        tags = kwargs.get("tags", None) or flow.tags
        if isinstance(tags, dict) and all(
            isinstance(key, str) and isinstance(value, str) for key, value in tags.items()
        ):
            kwargs["tags"] = tags
        elif tags is not None:
            raise FlowOperationError(
                f"Tags type must be 'Dict[str, str]', got non-dict or non-string key/value in tags: {tags}."
            )

        return flow, flow_display_name, flow_type, kwargs

    def _resolve_flow_code_and_upload_to_file_share(
        self, flow: Flow, flow_display_name: str, ignore_tools_json=False
    ) -> str:
        ops = OperationOrchestrator(self._all_operations, self._operation_scope, self._operation_config)
        file_share_flow_path = ""

        with flow._build_code() as code:
            if code is None:
                raise FlowOperationError("Failed to build flow code.")

            # ignore flow.tools.json if needed (e.g. for flow run scenario)
            if ignore_tools_json:
                ignore_file = code._ignore_file
                if isinstance(ignore_file, PromptflowIgnoreFile):
                    ignore_file._ignore_tools_json = ignore_tools_json
                else:
                    raise FlowOperationError(
                        message=f"Flow code should have PromptflowIgnoreFile, got {type(ignore_file)}"
                    )

            code.datastore = DEFAULT_STORAGE

            datastore_name = _get_datastore_name(datastore_name=DEFAULT_STORAGE)
            datastore_operation = ops._code_assets._datastore_operation
            datastore_info = get_datastore_info(datastore_operation, datastore_name)
            storage_client = FlowFileStorageClient(
                credential=datastore_info["credential"],
                file_share_name=datastore_info["container_name"],
                account_url=datastore_info["account_url"],
                azure_cred=datastore_operation._credential,
            )
            logger.debug("Created storage client for uploading flow to file share.")

            # set storage client to flow operation, can be used in test case
            self._storage_client = storage_client

            # check if the file share directory exists
            if storage_client._check_file_share_directory_exist(flow_display_name):
                raise FlowOperationError(
                    f"Remote flow folder {flow_display_name!r} already exists under "
                    f"'{storage_client.file_share_prefix}'. Please change the flow folder name and try again."
                )

            try:
                storage_client.upload_dir(
                    source=code.path,
                    dest=flow_display_name,
                    msg="test",
                    ignore_file=code._ignore_file,
                    show_progress=False,
                )
            except Exception as e:
                raise FlowOperationError(f"Failed to upload flow to file share due to: {str(e)}.") from e

            file_share_flow_path = f"{storage_client.file_share_prefix}/{flow_display_name}"
            logger.info(f"Successfully uploaded flow to file share path {file_share_flow_path!r}.")
        return file_share_flow_path

    def _create_remote_flow_via_file_share_path(
        self, flow_display_name, flow_type, flow_definition_file_path, **kwargs
    ):
        """Create a flow to remote from file share path."""
        service_flow_type = CLIENT_FLOW_TYPE_2_SERVICE_FLOW_TYPE[flow_type]
        description = kwargs.get("description", None)
        tags = kwargs.get("tags", None)
        body = {
            "flow_name": flow_display_name,
            "flow_definition_file_path": flow_definition_file_path,
            "flow_type": service_flow_type,
            "description": description,
            "tags": tags,
        }
        rest_flow_result = self._service_caller.create_flow(
            subscription_id=self._operation_scope.subscription_id,
            resource_group_name=self._operation_scope.resource_group_name,
            workspace_name=self._operation_scope.workspace_name,
            body=body,
        )
        return rest_flow_result

    def get(self, name: str) -> Flow:
        """Get a flow from azure.

        :param name: The name of the flow to get.
        :type name: str
        :return: The flow.
        :rtype: ~promptflow.azure.entities.Flow
        """
        try:
            rest_flow = self._service_caller.get_flow(
                subscription_id=self._operation_scope.subscription_id,
                resource_group_name=self._operation_scope.resource_group_name,
                workspace_name=self._operation_scope.workspace_name,
                flow_id=name,
                experiment_id=self._workspace_id,  # for flow operations, current experiment id is workspace id
            )
        except HttpResponseError as e:
            if e.status_code == 404:
                raise FlowOperationError(f"Flow {name!r} not found.") from e
            else:
                raise FlowOperationError(f"Failed to get flow {name!r} due to: {str(e)}.") from e

        flow = Flow._from_pf_service(rest_flow)
        flow.flow_portal_url = self._get_flow_portal_url_from_resource_id(rest_flow.flow_resource_id)
        return flow

    @monitor_operation(activity_name="pfazure.flows.list", activity_type=ActivityType.PUBLICAPI)
    def list(
        self,
        max_results: int = MAX_LIST_CLI_RESULTS,
        flow_type: Optional[FlowType] = None,
        list_view_type: ListViewType = ListViewType.ACTIVE_ONLY,
        include_others: bool = False,
        **kwargs,
    ) -> List[Flow]:
        """List flows from azure.

        :param max_results: The max number of runs to return, defaults to 50, max is 100
        :type max_results: int
        :param flow_type: The flow type, defaults to None, which means all flow types. Other supported flow types are
            ["standard", "evaluation", "chat"].
        :type flow_type: Optional[FlowType]
        :param list_view_type: The list view type, defaults to ListViewType.ACTIVE_ONLY
        :type list_view_type: ListViewType
        :param include_others: Whether to list flows owned by other users in the remote workspace, defaults to False
        :type include_others: bool
        :return: The list of runs.
        :rtype: List[~promptflow.azure. entities.Run]
        """
        if not isinstance(max_results, int) or max_results < 1:
            raise FlowOperationError(f"'max_results' must be a positive integer, got {max_results!r}")

        normalized_flow_type = str(flow_type).lower()
        if flow_type is not None and normalized_flow_type not in FlowType.get_all_values():
            raise FlowOperationError(f"'flow_type' must be one of {FlowType.get_all_values()}, got {flow_type!r}.")

        headers = self._service_caller._get_headers()
        if list_view_type == ListViewType.ACTIVE_ONLY:
            filter_archived = ["false"]
        elif list_view_type == ListViewType.ARCHIVED_ONLY:
            filter_archived = ["true"]
        elif list_view_type == ListViewType.ALL:
            filter_archived = ["true", "false"]
        else:
            raise FlowOperationError(
                f"Invalid list view type: {list_view_type!r}, expecting one of ['ActiveOnly', 'ArchivedOnly', 'All']"
            )

        user_object_id, user_tenant_id = self._service_caller._get_user_identity_info()
        payload = {
            "filters": [
                {"field": "type", "operator": "eq", "values": ["flows"]},
                {"field": "annotations/isArchived", "operator": "eq", "values": filter_archived},
                {
                    "field": "properties/creationContext/createdBy/userTenantId",
                    "operator": "eq",
                    "values": [user_tenant_id],
                },
            ],
            "freeTextSearch": "",
            "order": [{"direction": "Desc", "field": "properties/creationContext/createdTime"}],
            # index service can return 100 results at most
            "pageSize": min(max_results, 100),
            "skip": 0,
            "includeTotalResultCount": True,
            "searchBuilder": "AppendPrefix",
        }

        # add flow filter to only list flows from current user
        if not include_others:
            payload["filters"].append(
                {
                    "field": "properties/creationContext/createdBy/userObjectId",
                    "operator": "eq",
                    "values": [user_object_id],
                }
            )

        endpoint = self._index_service_endpoint_url
        url = endpoint + "/entities"
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            entities = json.loads(response.text)
            flow_entities = entities["value"]
        else:
            raise FlowOperationError(
                f"Failed to get flows from index service. Code: {response.status_code}, text: {response.text}"
            )

        # transform to flow instances
        flow_instances = []
        for entity in flow_entities:
            flow = Flow._from_index_service(entity)
            # add flow portal url
            flow.flow_portal_url = self._get_flow_portal_url_from_index_entity(entity)
            flow_instances.append(flow)

        return flow_instances

    def _download(self, source, dest):
        # TODO: support download flow
        raise NotImplementedError("Not implemented yet")

    def _resolve_arm_id_or_upload_dependencies(self, flow: Flow, ignore_tools_json=False) -> None:
        ops = OperationOrchestrator(self._all_operations, self._operation_scope, self._operation_config)
        # resolve flow's code
        self._try_resolve_code_for_flow(flow=flow, ops=ops, ignore_tools_json=ignore_tools_json)

    @classmethod
    def _try_resolve_code_for_flow(cls, flow: Flow, ops: OperationOrchestrator, ignore_tools_json=False) -> None:
        if flow.path:
            # remote path
            if flow.path.startswith("azureml://datastores"):
                flow._code_uploaded = True
                return
        else:
            raise ValueError("Path is required for flow.")

        with flow._build_code() as code:
            if code is None:
                return
            if flow._code_uploaded:
                return

            # TODO(2567532): backend does not fully support generate flow.tools.json from blob storage yet
            if not (Path(code.path) / PROMPT_FLOW_DIR_NAME / FLOW_TOOLS_JSON).exists():
                generate_flow_tools_json(code.path)
            # ignore flow.tools.json if needed (e.g. for flow run scenario)
            if ignore_tools_json:
                ignore_file = code._ignore_file
                if isinstance(ignore_file, PromptflowIgnoreFile):
                    ignore_file._ignore_tools_json = ignore_tools_json
                else:
                    raise SystemErrorException(
                        message=f"Flow code should have PromptflowIgnoreFile, got {type(ignore_file)}"
                    )

            # flow directory per file upload summary
            # as the upload logic locates in azure-ai-ml, we cannot touch during the upload
            # copy the logic here to print per file upload summary
            ignore_file = code._ignore_file
            upload_paths = []
            source_path = Path(code.path).resolve()
            prefix = os.path.basename(source_path) + "/"
            for root, _, files in os.walk(source_path, followlinks=True):
                upload_paths += list(
                    traverse_directory(
                        root,
                        files,
                        prefix=prefix,
                        ignore_file=ignore_file,
                    )
                )
            logger = logging.getLogger(LOGGER_NAME)

            ignore_files = code._ignore_file._get_ignore_list()
            for file_path in ignore_files:
                logger.debug(f"will ignore file: {file_path}...")
            for file_path, _ in upload_paths:
                logger.debug(f"will upload file: {file_path}...")

            code.datastore = WORKSPACE_LINKED_DATASTORE_NAME
            # NOTE: For flow directory upload, we prefer to upload it to the workspace linked datastore,
            # therefore we will directly use _check_and_upload_path, instead of v2 SDK public API
            # CodeOperations.create_or_update, as later one will upload the code asset to another
            # container in the storage account, which may fail with vnet for MT.
            # However, we might run into list secret permission error(especially in Heron workspace),
            # in this case, we will leverage v2 SDK public API, which has solution for Heron,
            # and request MT with the blob url;
            # refer to except block for more details.
            try:
                uploaded_code_asset, _ = _check_and_upload_path(
                    artifact=code,
                    asset_operations=ops._code_assets,
                    artifact_type="Code",
                    datastore_name=WORKSPACE_LINKED_DATASTORE_NAME,  # actually not work at all
                    show_progress=True,
                )
                path = uploaded_code_asset.path
                path = path[path.find("LocalUpload") :]  # path on container
                flow.code = path
                # azureml://datastores/workspaceblobstore/paths/<path-to-flow-dag-yaml>
                flow.path = SHORT_URI_FORMAT.format(
                    WORKSPACE_LINKED_DATASTORE_NAME, (Path(path) / flow.path).as_posix()
                )
            except HttpResponseError as e:
                # catch authorization error for list secret on datastore
                if "AuthorizationFailed" in str(e) and "datastores/listSecrets/action" in str(e):
                    uploaded_code_asset = ops._code_assets.create_or_update(code)
                    path = uploaded_code_asset.path
                    path = path.replace(".blob.core.windows.net:443/", ".blob.core.windows.net/")  # remove :443 port
                    flow.code = path
                    # https://<storage-account-name>.blob.core.windows.net/<container-name>/<path-to-flow-dag-yaml>
                    flow.path = f"{path}/{flow.path}"
                else:
                    raise
            flow._code_uploaded = True

    # region deprecated but keep for runtime test dependencies
    def _resolve_arm_id_or_upload_dependencies_to_file_share(self, flow: Flow) -> None:
        ops = OperationOrchestrator(self._all_operations, self._operation_scope, self._operation_config)
        # resolve flow's code
        self._try_resolve_code_for_flow_to_file_share(flow=flow, ops=ops)

    @classmethod
    def _try_resolve_code_for_flow_to_file_share(cls, flow: Flow, ops: OperationOrchestrator) -> None:
        from azure.ai.ml._utils._storage_utils import AzureMLDatastorePathUri

        from ._artifact_utilities import _check_and_upload_path

        if flow.path:
            if flow.path.startswith("azureml://datastores"):
                # remote path

                path_uri = AzureMLDatastorePathUri(flow.path)
                if path_uri.datastore != DEFAULT_STORAGE:
                    raise ValueError(f"Only {DEFAULT_STORAGE} is supported as remote storage for now.")
                flow.path = path_uri.path
                flow._code_uploaded = True
                return
        else:
            raise ValueError("Path is required for flow.")

        with flow._build_code() as code:
            if code is None:
                return
            if flow._code_uploaded:
                return
            code.datastore = DEFAULT_STORAGE
            uploaded_code_asset = _check_and_upload_path(
                artifact=code,
                asset_operations=ops._code_assets,
                artifact_type="Code",
                show_progress=False,
            )
            if "remote_path" in uploaded_code_asset:
                path = uploaded_code_asset["remote_path"]
            elif "remote path" in uploaded_code_asset:
                path = uploaded_code_asset["remote path"]
            flow.code = path
            flow.path = (Path(path) / flow.path).as_posix()
            flow._code_uploaded = True

    # endregion
