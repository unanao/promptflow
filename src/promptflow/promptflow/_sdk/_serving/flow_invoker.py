# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
import logging
from pathlib import Path
from typing import Callable, Union

from promptflow import PFClient
from promptflow._constants import LINE_NUMBER_KEY
from promptflow._sdk._constants import LOGGER_NAME
from promptflow._sdk._load_functions import load_flow
from promptflow._sdk._serving._errors import UnexpectedConnectionProviderReturn, UnsupportedConnectionProvider
from promptflow._sdk._serving.utils import validate_request_data
from promptflow._sdk._utils import (
    dump_flow_result,
    get_local_connections_from_executable,
    override_connection_config_with_environment_variable,
    print_yellow_warning,
    resolve_connections_environment_variable_reference,
    update_environment_variables_with_connections,
)
from promptflow._sdk.entities._connection import _Connection
from promptflow._sdk.entities._flow import Flow
from promptflow._sdk.operations._flow_operations import FlowOperations
from promptflow._utils.multimedia_utils import convert_multimedia_data_to_base64, persist_multimedia_data
from promptflow.contracts.flow import Flow as ExecutableFlow
from promptflow.executor import FlowExecutor
from promptflow.storage._run_storage import DefaultRunStorage

logger = logging.getLogger(LOGGER_NAME)


class FlowInvoker:
    """
    The invoker of a flow.

    :param flow: The path of the flow, or the flow loaded by load_flow().
    :type flow: [str, ~promptflow._sdk.entities._flow.Flow]
    :param connection_provider: The connection provider, defaults to None
    :type connection_provider: [str, Callable], optional
    :param streaming: The function or bool to determine enable streaming or not, defaults to lambda: False
    :type streaming: Union[Callable[[], bool], bool], optional
    :param connections: Pre-resolved connections used when executing, defaults to None
    :type connections: dict, optional
    """

    def __init__(
        self,
        flow: [str, Flow],
        connection_provider: [str, Callable] = None,
        streaming: Union[Callable[[], bool], bool] = False,
        connections: dict = None,
        **kwargs,
    ):
        self.flow_entity = flow if isinstance(flow, Flow) else load_flow(source=flow)
        self._executable_flow = ExecutableFlow._from_dict(
            flow_dag=self.flow_entity.dag, working_dir=self.flow_entity.code
        )
        self.connections = connections or {}
        self.streaming = streaming if isinstance(streaming, Callable) else lambda: streaming
        # Pass dump_to path to dump flow result for extension.
        self._dump_to = kwargs.get("dump_to", None)

        self._init_connections(connection_provider)
        self._init_executor()
        self.flow = self.executor._flow
        self._dump_file_prefix = "chat" if self._is_chat_flow else "flow"

    def _init_connections(self, connection_provider):
        self._is_chat_flow, _, _ = FlowOperations._is_chat_flow(self._executable_flow)
        connection_provider = "local" if connection_provider is None else connection_provider
        if isinstance(connection_provider, str):
            logger.info(f"Getting connections from pf client with provider {connection_provider}...")
            # Note: The connection here could be local or workspace, depends on the connection.provider in pf.yaml.
            connections = get_local_connections_from_executable(
                executable=self._executable_flow,
                client=PFClient(config={"connection.provider": connection_provider}),
                connections_to_ignore=list(self.connections.keys()),
            )
            self.connections.update(connections)
        elif isinstance(connection_provider, Callable):
            logger.info("Getting connections from custom connection provider...")
            connection_list = connection_provider()
            if not isinstance(connection_list, list):
                raise UnexpectedConnectionProviderReturn(
                    f"Connection provider {connection_provider} should return a list of connections."
                )
            if any(not isinstance(item, _Connection) for item in connection_list):
                raise UnexpectedConnectionProviderReturn(
                    f"All items returned by {connection_provider} should be connection type, got {connection_list}."
                )
            # TODO(2824058): support connection provider when executing function
            self.connections = {item.name: item.to_execution_connection_dict() for item in connection_list}
        else:
            raise UnsupportedConnectionProvider(connection_provider)

        override_connection_config_with_environment_variable(self.connections)
        resolve_connections_environment_variable_reference(self.connections)
        update_environment_variables_with_connections(self.connections)
        logger.info(f"Promptflow get connections successfully. keys: {self.connections.keys()}")

    def _init_executor(self):
        logger.info("Promptflow executor starts initializing...")
        storage = None
        if self._dump_to:
            storage = DefaultRunStorage(base_dir=self._dump_to, sub_dir=Path(".promptflow/intermediate"))
        self.executor = FlowExecutor._create_from_flow(
            flow=self._executable_flow,
            working_dir=self.flow_entity.code,
            connections=self.connections,
            raise_ex=True,
            storage=storage,
        )
        self.executor.enable_streaming_for_llm_flow(self.streaming)
        logger.info("Promptflow executor initiated successfully.")

    def _invoke(self, data: dict):
        """
        Process a flow request in the runtime.

        :param data: The request data dict with flow input as keys, for example: {"question": "What is ChatGPT?"}.
        :type data: dict
        :return: The result of executor.
        :rtype: ~promptflow.executor._result.LineResult
        """
        logger.info(f"PromptFlow invoker received data: {data}")

        logger.info(f"Validating flow input with data {data!r}")
        validate_request_data(self.flow, data)
        logger.info(f"Execute flow with data {data!r}")
        # Pass index 0 as extension require for dumped result.
        # TODO: Remove this index after extension remove this requirement.
        result = self.executor.exec_line(data, index=0, allow_generator_output=self.streaming())
        if LINE_NUMBER_KEY in result.output:
            # Remove line number from output
            del result.output[LINE_NUMBER_KEY]
        return result

    def invoke(self, data: dict):
        """
        Process a flow request in the runtime and return the output of the executor.

        :param data: The request data dict with flow input as keys, for example: {"question": "What is ChatGPT?"}.
        :type data: dict
        :return: The flow output dict, for example: {"answer": "ChatGPT is a chatbot."}.
        :rtype: dict
        """
        result = self._invoke(data)
        # Get base64 for multi modal object
        resolved_outputs = self._convert_multimedia_data_to_base64(result)
        self._dump_invoke_result(result)
        print_yellow_warning(f"Result: {result.output}")
        return resolved_outputs

    def _convert_multimedia_data_to_base64(self, invoke_result):
        resolved_outputs = {
            k: convert_multimedia_data_to_base64(v, with_type=True, dict_type=True)
            for k, v in invoke_result.output.items()
        }
        return resolved_outputs

    def _dump_invoke_result(self, invoke_result):
        if self._dump_to:
            invoke_result.output = persist_multimedia_data(
                invoke_result.output, base_dir=self._dump_to, sub_dir=Path(".promptflow/output")
            )
            dump_flow_result(flow_folder=self._dump_to, flow_result=invoke_result, prefix=self._dump_file_prefix)
