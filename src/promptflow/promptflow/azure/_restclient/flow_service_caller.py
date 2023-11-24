# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
"""service_caller.py, module for interacting with the AzureML service."""
import json
import logging
import os
import sys
import time
import uuid
from functools import wraps, cached_property

import pydash

from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.core.pipeline.policies import RetryPolicy

from promptflow._telemetry.telemetry import TelemetryMixin
from promptflow.azure._constants._flow import AUTOMATIC_RUNTIME, SESSION_CREATION_TIMEOUT_ENV_VAR
from promptflow.azure._restclient.flow import AzureMachineLearningDesignerServiceClient
from promptflow.exceptions import ValidationException, UserErrorException, PromptflowException

logger = logging.getLogger(__name__)


class FlowRequestException(PromptflowException):
    """FlowRequestException."""

    def __init__(self, message, **kwargs):
        super().__init__(message, **kwargs)


class RequestTelemetryMixin(TelemetryMixin):

    def __init__(self):
        super().__init__()
        self._request_id = str(uuid.uuid4())
        self._from_cli = False

    def _get_telemetry_values(self, *args, **kwargs):
        return {'request_id': self._request_id, 'from_cli': self._from_cli}

    def _set_from_cli_for_telemetry(self):
        self._from_cli = True

    def _refresh_request_id_for_telemetry(self):
        self._request_id = str(uuid.uuid4())


def _request_wrapper():
    """Wrapper for request. Will refresh request id and pretty print exception."""
    def exception_wrapper(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not isinstance(self, RequestTelemetryMixin):
                raise PromptflowException(f"Wrapped function is not RequestTelemetryMixin, got {type(self)}")
            # refresh request before each request
            self._refresh_request_id_for_telemetry()
            try:
                return func(self, *args, **kwargs)
            except HttpResponseError as e:
                raise FlowRequestException(
                    f"Calling {func.__name__} failed with request id: {self._request_id} \n"
                    f"Status code: {e.status_code} \n"
                    f"Reason: {e.reason} \n"
                    f"Error message: {e.message} \n"
                )
        return wrapper

    return exception_wrapper


class FlowServiceCaller(RequestTelemetryMixin):
    """FlowServiceCaller.
    :param workspace: workspace
    :type workspace: Workspace
    :param base_url: base url
    :type base_url: Service URL

    """

    # The default namespace placeholder is used when namespace is None for get_module API.
    DEFAULT_COMPONENT_NAMESPACE_PLACEHOLDER = '-'
    DEFAULT_MODULE_WORKING_MECHANISM = 'OutputToDataset'
    DEFAULT_DATATYPE_MECHANISM = 'RegisterBuildinDataTypeOnly'
    FLOW_CLUSTER_ADDRESS = 'FLOW_CLUSTER_ADDRESS'
    WORKSPACE_INDEPENDENT_ENDPOINT_ADDRESS = 'WORKSPACE_INDEPENDENT_ENDPOINT_ADDRESS'
    DEFAULT_BASE_URL = 'https://{}.api.azureml.ms'
    MASTER_BASE_API = 'https://master.api.azureml-test.ms'
    DEFAULT_BASE_REGION = 'westus2'
    AML_USE_ARM_TOKEN = 'AML_USE_ARM_TOKEN'

    def __init__(self, workspace, credential, operation_scope, base_url=None, region=None, **kwargs):
        """Initializes DesignerServiceCaller."""
        if 'get_instance' != sys._getframe().f_back.f_code.co_name:
            raise UserErrorException(
                'Please use `_FlowServiceCallerFactory.get_instance()` to get service caller '
                'instead of creating a new one.'
            )
        super().__init__()

        # self._service_context = workspace.service_context
        if base_url is None:
            # handle vnet scenario, it's discovery url will have workspace id after discovery
            base_url = workspace.discovery_url.split("discovery")[0]
            # for dev test, change base url with environment variable
            base_url = os.environ.get(self.FLOW_CLUSTER_ADDRESS, default=base_url)

        self._workspace = workspace
        self._operation_scope = operation_scope
        self._service_endpoint = base_url
        self._credential = credential
        retry_policy = RetryPolicy()
        # stop retry 500 since it will cause 409 for run creation scenario
        retry_policy._retry_on_status_codes.remove(500)
        self.caller = AzureMachineLearningDesignerServiceClient(base_url=base_url, retry_policy=retry_policy, **kwargs)

    def _get_headers(self):
        token = self._credential.get_token("https://management.azure.com/.default")
        custom_header = {"Authorization": "Bearer " + token.token, "x-ms-client-request-id": self._request_id}
        return custom_header

    def _set_headers_with_user_aml_token(self, headers):
        # NOTE: this copied from https://github.com/Azure/azure-sdk-for-python/blob/05f1438ad0a5eb536e5c49d8d9d44b798445044a/sdk/ml/azure-ai-ml/azure/ai/ml/operations/_job_operations.py#L1495C12-L1495C12
        from azure.ai.ml._azure_environments import _get_aml_resource_id_from_metadata
        from azure.ai.ml._azure_environments import _resource_to_scopes
        import jwt

        aml_resource_id = _get_aml_resource_id_from_metadata()
        azure_ml_scopes = _resource_to_scopes(aml_resource_id)
        logger.debug("azure_ml_scopes used: `%s`\n", azure_ml_scopes)
        aml_token = self._credential.get_token(*azure_ml_scopes).token
        # validate token has aml audience
        decoded_token = jwt.decode(
            aml_token,
            options={"verify_signature": False, "verify_aud": False},
        )
        if decoded_token.get("aud") != aml_resource_id:
            msg = """AAD token with aml scope could not be fetched using the credentials being used.
            Please validate if token with {0} scope can be fetched using credentials provided to PFClient.
            Token with {0} scope can be fetched using credentials.get_token({0})
            """

            raise ValidationException(
                message=msg.format(*azure_ml_scopes),
            )

        headers["aml-user-token"] = aml_token

    def _get_user_identity_info(self):
        import jwt

        token = self._credential.get_token("https://management.azure.com/.default")
        decoded_token = jwt.decode(token.token, options={"verify_signature": False})
        user_object_id, user_tenant_id = decoded_token["oid"], decoded_token["tid"]
        return user_object_id, user_tenant_id

    @cached_property
    def _common_azure_url_pattern(self):
        operation_scope = self._operation_scope
        pattern = (
            f"/subscriptions/{operation_scope.subscription_id}"
            f"/resourceGroups/{operation_scope.resource_group_name}"
            f"/providers/Microsoft.MachineLearningServices"
            f"/workspaces/{operation_scope.workspace_name}"
        )
        return pattern

    @_request_wrapper()
    def create_flow(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        experiment_id=None,  # type: Optional[str]
        body=None,  # type: Optional["_models.CreateFlowRequest"]
        **kwargs  # type: Any
    ):
        headers = self._get_headers()
        return self.caller.flows.create_flow(
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            workspace_name=workspace_name,
            experiment_id=experiment_id,
            body=body,
            headers=headers,
            **kwargs
        )

    @_request_wrapper()
    def create_component_from_flow(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        body=None,  # type: Optional["_models.LoadFlowAsComponentRequest"]
        **kwargs  # type: Any
    ):
        headers = self._get_headers()
        try:
            return self.caller.flows.load_as_component(
                    subscription_id=subscription_id,
                    resource_group_name=resource_group_name,
                    workspace_name=workspace_name,
                    body=body,
                    headers=headers,
                    **kwargs
                )
        except ResourceExistsError:
            return f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}" \
                   f"/providers/Microsoft.MachineLearningServices/workspaces/{workspace_name}" \
                   f"/components/{body.component_name}/versions/{body.component_version}"

    @_request_wrapper()
    def list_flows(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        experiment_id=None,  # type: Optional[str]
        owned_only=None,  # type: Optional[bool]
        flow_type=None,  # type: Optional[Union[str, "_models.FlowType"]]
        list_view_type=None,  # type: Optional[Union[str, "_models.ListViewType"]]
        **kwargs  # type: Any
    ):
        headers = self._get_headers()
        return self.caller.flows.list_flows(
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            workspace_name=workspace_name,
            experiment_id=experiment_id,
            owned_only=owned_only,
            flow_type=flow_type,
            list_view_type=list_view_type,
            headers=headers,
            **kwargs,
        )

    @_request_wrapper()
    def submit_flow(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        experiment_id,  # type: str
        endpoint_name=None,  # type: Optional[str]
        body=None,  # type: Optional["_models.SubmitFlowRequest"]
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.flows.submit_flow(
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            workspace_name=workspace_name,
            experiment_id=experiment_id,
            endpoint_name=endpoint_name,
            body=body,
            headers=headers,
            **kwargs
        )

    @_request_wrapper()
    def get_flow(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        flow_id,  # type: str
        experiment_id,  # type: str
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.flows.get_flow(
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            workspace_name=workspace_name,
            experiment_id=experiment_id,
            flow_id=flow_id,
            headers=headers,
            **kwargs
        )

    @_request_wrapper()
    def create_connection(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        connection_name,  # type: str
        body=None,  # type: Optional["_models.CreateOrUpdateConnectionRequest"]
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.connections.create_connection(
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            workspace_name=workspace_name,
            connection_name=connection_name,
            body=body,
            headers=headers,
            **kwargs
        )

    @_request_wrapper()
    def update_connection(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        connection_name,  # type: str
        body=None,  # type: Optional["_models.CreateOrUpdateConnectionRequestDto"]
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.connections.update_connection(
                subscription_id=subscription_id,
                resource_group_name=resource_group_name,
                workspace_name=workspace_name,
                connection_name=connection_name,
                body=body,
                headers=headers,
                **kwargs
            )


    @_request_wrapper()
    def get_connection(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        connection_name,  # type: str
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.connections.get_connection(
                subscription_id=subscription_id,
                resource_group_name=resource_group_name,
                workspace_name=workspace_name,
                connection_name=connection_name,
                headers=headers,
                **kwargs
            )

    @_request_wrapper()
    def delete_connection(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        connection_name,  # type: str
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.connections.delete_connection(
                subscription_id=subscription_id,
                resource_group_name=resource_group_name,
                workspace_name=workspace_name,
                connection_name=connection_name,
                headers=headers,
                **kwargs
            )


    @_request_wrapper()
    def list_connections(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.connections.list_connections(
                subscription_id=subscription_id,
                resource_group_name=resource_group_name,
                workspace_name=workspace_name,
                headers=headers,
                **kwargs
            )


    @_request_wrapper()
    def list_connection_specs(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        **kwargs  # type: Any
    ):
        
        headers = self._get_headers()
        return self.caller.connections.list_connection_specs(
                subscription_id=subscription_id,
                resource_group_name=resource_group_name,
                workspace_name=workspace_name,
                headers=headers,
                **kwargs
            )


    @_request_wrapper()
    def submit_bulk_run(
            self,
            subscription_id,  # type: str
            resource_group_name,  # type: str
            workspace_name,  # type: str
            body=None,  # type: Optional["_models.SubmitBulkRunRequest"]
            **kwargs  # type: Any
    ):
        """submit_bulk_run.

        :param subscription_id: The Azure Subscription ID.
        :type subscription_id: str
        :param resource_group_name: The Name of the resource group in which the workspace is located.
        :type resource_group_name: str
        :param workspace_name: The name of the workspace.
        :type workspace_name: str
        :param body:
        :type body: ~flow.models.SubmitBulkRunRequest
        :keyword callable cls: A custom type or function that will be passed the direct response
        :return: str, or the result of cls(response)
        :rtype: str
        :raises: ~azure.core.exceptions.HttpResponseError
        """
        
        headers = self._get_headers()
        # pass user aml token to flow run submission
        self._set_headers_with_user_aml_token(headers)
        return self.caller.bulk_runs.submit_bulk_run(
                subscription_id=subscription_id,
                resource_group_name=resource_group_name,
                workspace_name=workspace_name,
                headers=headers,
                body=body,
                **kwargs
            )


    @_request_wrapper()
    def create_flow_session(
        self,
        subscription_id,  # type: str
        resource_group_name,  # type: str
        workspace_name,  # type: str
        session_id,  # type: str
        body,  # type: Optional["_models.CreateFlowSessionRequest"]
        **kwargs  # type: Any
    ):
        from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceExistsError, \
            ResourceNotFoundError, map_error
        from promptflow.azure._restclient.flow.operations._flow_sessions_operations import (
            build_create_flow_session_request,
            _convert_request,
            _models
        )
        from promptflow.azure._constants._flow import SESSION_CREATION_TIMEOUT_SECONDS
        from promptflow.azure._restclient.flow.models import SetupFlowSessionAction

        
        headers = self._get_headers()
        # pass user aml token to session create so user don't need to do authentication again in CI
        self._set_headers_with_user_aml_token(headers)
        # did not call self.caller.flow_sessions.create_flow_session because it does not support return headers
        cls = kwargs.pop('cls', None)  # type: ClsType[Any]
        error_map = {
            401: ClientAuthenticationError, 404: ResourceNotFoundError, 409: ResourceExistsError
        }
        error_map.update(kwargs.pop('error_map', {}))

        content_type = kwargs.pop('content_type', "application/json")  # type: Optional[str]

        _json = self.caller.flow_sessions._serialize.body(body, 'CreateFlowSessionRequest')

        request = build_create_flow_session_request(
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            workspace_name=workspace_name,
            session_id=session_id,
            content_type=content_type,
            json=_json,
            template_url=self.caller.flow_sessions.create_flow_session.metadata['url'],
            headers=headers
        )
        request = _convert_request(request)
        request.url = self.caller.flow_sessions._client.format_url(request.url)
        pipeline_response = self.caller.flow_sessions._client._pipeline.run(request, stream=False, **kwargs)

        response = pipeline_response.http_response

        if response.status_code not in [200, 202]:
            map_error(status_code=response.status_code, response=response, error_map=error_map)
            error = self.caller.flow_sessions._deserialize.failsafe_deserialize(_models.ErrorResponse,
                                                                                pipeline_response)
            raise HttpResponseError(response=response, model=error)
        if response.status_code == 200:
            return
        action = body.action or SetupFlowSessionAction.INSTALL.value
        if action == SetupFlowSessionAction.INSTALL.value:
            action = "creation"
        else:
            action = "reset"

        logger.info(f"Start polling until session {action} is completed...")
        # start polling status here.
        if "azure-asyncoperation" not in response.headers:
            raise FlowRequestException(
                "No polling url found in response headers. "
                f"Request id: {headers['x-ms-client-request-id']}. "
                f"Response headers: {response.headers}."
            )
        polling_url = response.headers["azure-asyncoperation"]
        time_run = 0
        sleep_period = 5
        status = None
        timeout_seconds = SESSION_CREATION_TIMEOUT_SECONDS
        # polling timeout, if user set SESSION_CREATION_TIMEOUT_SECONDS in environment var, use it
        if os.environ.get(SESSION_CREATION_TIMEOUT_ENV_VAR):
            try:
                timeout_seconds = float(os.environ.get(SESSION_CREATION_TIMEOUT_ENV_VAR))
            except ValueError:
                raise UserErrorException(
                    "Environment variable {} with value {} set but failed to parse. "
                    "Please reset the value to a number.".format(
                        SESSION_CREATION_TIMEOUT_ENV_VAR, os.environ.get(SESSION_CREATION_TIMEOUT_ENV_VAR)
                    )
                )
        # InProgress is only known non-terminal status for now.
        while status in [None, "InProgress"]:
            if time_run + sleep_period > timeout_seconds:
                message = f"Polling timeout for session {session_id} {action} " \
                          f"for {AUTOMATIC_RUNTIME} after {timeout_seconds} seconds.\n" \
                          f"To proceed the {action} for {AUTOMATIC_RUNTIME}, you can retry using the same flow, " \
                          "and we will continue polling status of previous session. \n"
                raise Exception(message)
            time_run += sleep_period
            time.sleep(sleep_period)
            response = self.poll_operation_status(url=polling_url, **kwargs)
            status = response["status"]
            logger.debug(f"Current polling status: {status}")
            if time_run % 30 == 0:
                # print the message every 30 seconds to avoid users feeling stuck during the operation
                print(f"Waiting for session {action}, current status: {status}")
            else:
                logger.debug(f"Waiting for session {action}, current status: {status}")

        if status == "Succeeded":
            error_msg = pydash.get(response, "error.message", None)
            if error_msg:
                logger.warning(
                    f"Session {action} finished with status {status}. "
                    f"But there are warnings when installing the packages: {error_msg}."
                )
            else:
                logger.info(f"Session {action} finished with status {status}.")
        else:
            # refine response error message
            try:
                response["error"]["message"] = json.loads(response["error"]["message"])
            except Exception:
                pass
            raise FlowRequestException(
                f"Session {action} failed for {session_id}. \n"
                f"Session {action} status: {status}. \n"
                f"Request id: {headers['x-ms-client-request-id']}. \n"
                f"{json.dumps(response, indent=2)}."
            )


    @_request_wrapper()
    def poll_operation_status(
        self,
        url,
        **kwargs  # type: Any
    ):
        from azure.core.rest import HttpRequest
        from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceExistsError, \
            ResourceNotFoundError, map_error
        from promptflow.azure._restclient.flow.operations._flow_sessions_operations import _models

        
        headers = self._get_headers()
        request = HttpRequest(
            method="GET",
            url=url,
            headers=headers,
            **kwargs
        )
        pipeline_response = self.caller.flow_sessions._client._pipeline.run(request, stream=False, **kwargs)
        response = pipeline_response.http_response
        error_map = {
            401: ClientAuthenticationError, 404: ResourceNotFoundError, 409: ResourceExistsError
        }
        if response.status_code not in [200]:
            map_error(status_code=response.status_code, response=response, error_map=error_map)
            error = self.caller.flow_sessions._deserialize.failsafe_deserialize(_models.ErrorResponse,
                                                                                pipeline_response)
            raise HttpResponseError(response=response, model=error)

        deserialized = self.caller.flow_sessions._deserialize('object', pipeline_response)
        if "status" not in deserialized:
            raise FlowRequestException(
                f"Status not found in response. Request id: {headers['x-ms-client-request-id']}. "
                f"Response headers: {response.headers}."
            )
        return deserialized

    @_request_wrapper()
    def get_child_runs(
            self,
            subscription_id,  # type: str
            resource_group_name,  # type: str
            workspace_name,  # type: str
            flow_run_id,  # type: str
            index=None,  # type: Optional[int]
            start_index=None,  # type: Optional[int]
            end_index=None,  # type: Optional[int]
            **kwargs  # type: Any
        ):
        """Get child runs of a flow run."""
        headers = self._get_headers()
        return self.caller.bulk_runs.get_flow_child_runs(
            subscription_id=subscription_id,
            resource_group_name=resource_group_name,
            workspace_name=workspace_name,
            flow_run_id=flow_run_id,
            index=index,
            start_index=start_index,
            end_index=end_index,
            headers=headers,
            **kwargs
        )
