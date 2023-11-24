from types import GeneratorType

import pytest

from promptflow.contracts.run_info import Status
from promptflow.exceptions import UserErrorException
from promptflow.executor import FlowExecutor
from promptflow.executor._errors import ConnectionNotFound, InputTypeError, ResolveToolError

from ..utils import FLOW_ROOT, get_flow_sample_inputs, get_yaml_file

SAMPLE_FLOW = "web_classification_no_variants"


@pytest.mark.usefixtures("use_secrets_config_file", "dev_connections")
@pytest.mark.e2etest
class TestExecutor:
    def get_line_inputs(self, flow_folder=""):
        if flow_folder:
            inputs = self.get_bulk_inputs(flow_folder)
            return inputs[0]
        return {
            "url": "https://www.apple.com/shop/buy-iphone/iphone-14",
            "text": "some_text",
        }

    def get_bulk_inputs(self, nlinee=4, flow_folder="", sample_inputs_file="", return_dict=False):
        if flow_folder:
            if not sample_inputs_file:
                sample_inputs_file = "samples.json"
            inputs = get_flow_sample_inputs(flow_folder, sample_inputs_file=sample_inputs_file)
            if isinstance(inputs, list) and len(inputs) > 0:
                return inputs
            elif isinstance(inputs, dict):
                if return_dict:
                    return inputs
                return [inputs]
            else:
                raise Exception(f"Invalid type of bulk input: {inputs}")
        return [self.get_line_inputs() for _ in range(nlinee)]

    def skip_serp(self, flow_folder, dev_connections):
        serp_required_flows = ["package_tools"]
        #  Real key is usually more than 32 chars
        serp_key = dev_connections.get("serp_connection", {"value": {"api_key": ""}})["value"]["api_key"]
        if flow_folder in serp_required_flows and len(serp_key) < 32:
            pytest.skip("serp_connection is not prepared")

    @pytest.mark.parametrize(
        "flow_folder",
        [
            SAMPLE_FLOW,
            "prompt_tools",
            "script_with___file__",
            "script_with_import",
            "package_tools",
            "connection_as_input",
            "async_tools",
            "async_tools_with_sync_tools",
        ],
    )
    def test_executor_exec_line(self, flow_folder, dev_connections):
        self.skip_serp(flow_folder, dev_connections)
        executor = FlowExecutor.create(get_yaml_file(flow_folder), dev_connections)
        flow_result = executor.exec_line(self.get_line_inputs())
        assert not executor._run_tracker._flow_runs, "Flow runs in run tracker should be empty."
        assert not executor._run_tracker._node_runs, "Node runs in run tracker should be empty."
        assert isinstance(flow_result.output, dict)
        assert flow_result.run_info.status == Status.Completed
        node_count = len(executor._flow.nodes)
        assert isinstance(flow_result.run_info.api_calls, list) and len(flow_result.run_info.api_calls) == node_count
        assert len(flow_result.node_run_infos) == node_count
        for node, node_run_info in flow_result.node_run_infos.items():
            assert node_run_info.status == Status.Completed
            assert node_run_info.node == node
            assert isinstance(node_run_info.api_calls, list)  # api calls is set

    @pytest.mark.parametrize(
        "flow_folder, node_name, flow_inputs, dependency_nodes_outputs",
        [
            ("web_classification_no_variants", "summarize_text_content", {}, {"fetch_text_content_from_url": "Hello"}),
            ("prompt_tools", "summarize_text_content_prompt", {"text": "text"}, {}),
            ("script_with___file__", "node1", {"text": "text"}, None),
            ("script_with___file__", "node2", None, {"node1": "text"}),
            ("script_with___file__", "node3", None, None),
            ("package_tools", "search_by_text", {"text": "elon mask"}, None),  # Skip since no api key in CI
            ("connection_as_input", "conn_node", None, None),
            ("simple_aggregation", "accuracy", {"text": "A"}, {"passthrough": "B"}),
            ("script_with_import", "node1", {"text": "text"}, None),
        ],
    )
    def test_executor_exec_node(self, flow_folder, node_name, flow_inputs, dependency_nodes_outputs, dev_connections):
        self.skip_serp(flow_folder, dev_connections)
        yaml_file = get_yaml_file(flow_folder)
        run_info = FlowExecutor.load_and_exec_node(
            yaml_file,
            node_name,
            flow_inputs=flow_inputs,
            dependency_nodes_outputs=dependency_nodes_outputs,
            connections=dev_connections,
            raise_ex=True,
        )
        assert run_info.output is not None
        assert run_info.status == Status.Completed
        assert isinstance(run_info.api_calls, list)
        assert run_info.node == node_name
        assert run_info.system_metrics["duration"] >= 0

    def test_executor_node_overrides(self, dev_connections):
        inputs = self.get_line_inputs()
        executor = FlowExecutor.create(
            get_yaml_file(SAMPLE_FLOW),
            dev_connections,
            node_override={"classify_with_llm.deployment_name": "dummy_deployment"},
            raise_ex=True,
        )
        with pytest.raises(UserErrorException) as e:
            executor.exec_line(inputs)
        assert type(e.value).__name__ == "WrappedOpenAIError"
        assert "The API deployment for this resource does not exist." in str(e.value)

        with pytest.raises(ResolveToolError) as e:
            executor = FlowExecutor.create(
                get_yaml_file(SAMPLE_FLOW),
                dev_connections,
                node_override={"classify_with_llm.connection": "dummy_connection"},
                raise_ex=True,
            )
        assert isinstance(e.value.inner_exception, ConnectionNotFound)
        assert "Connection 'dummy_connection' not found" in str(e.value)

    @pytest.mark.parametrize(
        "flow_folder",
        [
            "no_inputs_outputs",
        ],
    )
    def test_flow_with_no_inputs_and_output(self, flow_folder, dev_connections):
        executor = FlowExecutor.create(get_yaml_file(flow_folder, FLOW_ROOT), dev_connections)
        flow_result = executor.exec_line({})
        assert flow_result.output == {}
        assert flow_result.run_info.status == Status.Completed
        node_count = len(executor._flow.nodes)
        assert isinstance(flow_result.run_info.api_calls, list) and len(flow_result.run_info.api_calls) == node_count
        assert len(flow_result.node_run_infos) == node_count
        for node, node_run_info in flow_result.node_run_infos.items():
            assert node_run_info.status == Status.Completed
            assert node_run_info.node == node
            assert isinstance(node_run_info.api_calls, list)  # api calls is set

    @pytest.mark.parametrize(
        "flow_folder",
        [
            "simple_flow_with_python_tool",
        ],
    )
    def test_convert_flow_input_types(self, flow_folder, dev_connections) -> None:
        executor = FlowExecutor.create(get_yaml_file(flow_folder, FLOW_ROOT), dev_connections)
        ret = executor.convert_flow_input_types(inputs={"num": "11"})
        assert ret == {"num": 11}
        ret = executor.convert_flow_input_types(inputs={"text": "12", "num": "11"})
        assert ret == {"text": "12", "num": 11}
        with pytest.raises(InputTypeError):
            ret = executor.convert_flow_input_types(inputs={"num": "hello"})
            executor.convert_flow_input_types(inputs={"num": "hello"})

    def test_chat_flow_stream_mode(self, dev_connections) -> None:
        executor = FlowExecutor.create(get_yaml_file("python_stream_tools", FLOW_ROOT), dev_connections)

        # To run a flow with stream output, we need to set this flag to run tracker.
        # TODO: refine the interface

        inputs = {"text": "hello", "chat_history": []}
        line_result = executor.exec_line(inputs, allow_generator_output=True)

        # Assert there's only one output
        assert len(line_result.output) == 1
        assert set(line_result.output.keys()) == {"output_echo"}

        # Assert the only output is a generator
        output_echo = line_result.output["output_echo"]
        assert isinstance(output_echo, GeneratorType)
        assert list(output_echo) == ["Echo: ", "hello "]

        # Assert the flow is completed and no errors are raised
        flow_run_info = line_result.run_info
        assert flow_run_info.status == Status.Completed
        assert flow_run_info.error is None

    @pytest.mark.parametrize(
        "flow_folder",
        [
            "web_classification",
        ],
    )
    def test_executor_creation_with_default_variants(self, flow_folder, dev_connections):
        executor = FlowExecutor.create(get_yaml_file(flow_folder), dev_connections)
        flow_result = executor.exec_line(self.get_line_inputs())
        assert flow_result.run_info.status == Status.Completed

    def test_executor_creation_with_default_input(self):
        # Assert for single node run.
        default_input_value = "input value from default"
        yaml_file = get_yaml_file("default_input")
        executor = FlowExecutor.create(yaml_file, {})
        node_result = executor.load_and_exec_node(yaml_file, "test_print_input")
        assert node_result.status == Status.Completed
        assert node_result.output == default_input_value

        # Assert for flow run.
        flow_result = executor.exec_line({})
        assert flow_result.run_info.status == Status.Completed
        assert flow_result.output["output"] == default_input_value
        aggr_results = executor.exec_aggregation({}, aggregation_inputs={})
        flow_aggregate_node = aggr_results.node_run_infos["aggregate_node"]
        assert flow_aggregate_node.status == Status.Completed
        assert flow_aggregate_node.output == [default_input_value]

        # Assert for exec
        exec_result = executor.exec({})
        assert exec_result["output"] == default_input_value

    def test_executor_for_script_tool_with_init(self, dev_connections):
        executor = FlowExecutor.create(get_yaml_file("script_tool_with_init"), dev_connections)
        flow_result = executor.exec_line({"input": "World"})
        assert flow_result.run_info.status == Status.Completed
        assert flow_result.output["output"] == "Hello World"
