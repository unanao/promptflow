import logging
from pathlib import Path
from types import GeneratorType

import pytest

from promptflow._sdk._constants import LOGGER_NAME
from promptflow._sdk._pf_client import PFClient
from promptflow.exceptions import UserErrorException

PROMOTFLOW_ROOT = Path(__file__) / "../../../.."

TEST_ROOT = Path(__file__).parent.parent.parent
MODEL_ROOT = TEST_ROOT / "test_configs/e2e_samples"
CONNECTION_FILE = (PROMOTFLOW_ROOT / "connections.json").resolve().absolute().as_posix()
FLOWS_DIR = (TEST_ROOT / "test_configs/flows").resolve().absolute().as_posix()
FLOW_RESULT_KEYS = ["category", "evidence"]

_client = PFClient()


@pytest.mark.usefixtures(
    "use_secrets_config_file", "recording_injection", "setup_local_connection", "install_custom_tool_pkg"
)
@pytest.mark.sdk_test
@pytest.mark.e2etest
class TestFlowTest:
    def test_pf_test_flow(self):
        inputs = {"url": "https://www.youtube.com/watch?v=o5ZQyXaAv1g", "answer": "Channel", "evidence": "Url"}
        flow_path = Path(f"{FLOWS_DIR}/web_classification").absolute()

        result = _client.test(flow=flow_path, inputs=inputs)
        assert all([key in FLOW_RESULT_KEYS for key in result])

        result = _client.test(flow=f"{FLOWS_DIR}/web_classification")
        assert all([key in FLOW_RESULT_KEYS for key in result])

    def test_pf_test_flow_with_package_tool_with_custom_strong_type_connection(self, install_custom_tool_pkg):
        # Need to reload pkg_resources to get the latest installed tools
        import importlib

        import pkg_resources

        importlib.reload(pkg_resources)

        inputs = {"text": "Hello World!"}
        flow_path = Path(f"{FLOWS_DIR}/flow_with_package_tool_with_custom_strong_type_connection").absolute()

        # Test that connection would be custom strong type in flow
        result = _client.test(flow=flow_path, inputs=inputs)
        assert result == {"out": "connection_value is MyFirstConnection: True"}

        # Test node run
        result = _client.test(flow=flow_path, inputs={"input_text": "Hello World!"}, node="My_Second_Tool_usi3")
        assert result == "Hello World!This is my first custom connection."

    def test_pf_test_flow_with_package_tool_with_custom_connection_as_input_value(self, install_custom_tool_pkg):
        # Need to reload pkg_resources to get the latest installed tools
        import importlib

        import pkg_resources

        importlib.reload(pkg_resources)

        # Prepare custom connection
        from promptflow.connections import CustomConnection

        conn = CustomConnection(name="custom_connection_3", secrets={"api_key": "test"}, configs={"api_base": "test"})
        _client.connections.create_or_update(conn)

        inputs = {"text": "Hello World!"}
        flow_path = Path(f"{FLOWS_DIR}/flow_with_package_tool_with_custom_connection").absolute()

        # Test that connection would be custom strong type in flow
        result = _client.test(flow=flow_path, inputs=inputs)
        assert result == {"out": "connection_value is MyFirstConnection: True"}

    def test_pf_test_flow_with_script_tool_with_custom_strong_type_connection(self):
        # Prepare custom connection
        from promptflow.connections import CustomConnection

        conn = CustomConnection(name="custom_connection_2", secrets={"api_key": "test"}, configs={"api_url": "test"})
        _client.connections.create_or_update(conn)

        inputs = {"text": "Hello World!"}
        flow_path = Path(f"{FLOWS_DIR}/flow_with_script_tool_with_custom_strong_type_connection").absolute()

        # Test that connection would be custom strong type in flow
        result = _client.test(flow=flow_path, inputs=inputs)
        assert result == {"out": "connection_value is MyCustomConnection: True"}

        # Test node run
        result = _client.test(flow=flow_path, inputs={"input_param": "Hello World!"}, node="my_script_tool")
        assert result == "connection_value is MyCustomConnection: True"

    def test_pf_test_with_streaming_output(self):
        flow_path = Path(f"{FLOWS_DIR}/chat_flow_with_stream_output")
        result = _client.test(flow=flow_path)
        chat_output = result["answer"]
        assert isinstance(chat_output, GeneratorType)
        assert "".join(chat_output)

        flow_path = Path(f"{FLOWS_DIR}/basic_with_builtin_llm_node")
        result = _client.test(flow=flow_path)
        chat_output = result["output"]
        assert isinstance(chat_output, str)

    def test_pf_test_node(self):
        inputs = {"classify_with_llm.output": '{"category": "App", "evidence": "URL"}'}
        flow_path = Path(f"{FLOWS_DIR}/web_classification").absolute()

        result = _client.test(flow=flow_path, inputs=inputs, node="convert_to_dict")
        assert all([key in FLOW_RESULT_KEYS for key in result])

    def test_pf_test_flow_with_variant(self):
        inputs = {"url": "https://www.youtube.com/watch?v=o5ZQyXaAv1g", "answer": "Channel", "evidence": "Url"}

        result = _client.test(
            flow=f"{FLOWS_DIR}/web_classification", inputs=inputs, variant="${summarize_text_content.variant_1}"
        )
        assert all([key in FLOW_RESULT_KEYS for key in result])

    @pytest.mark.skip("TODO this test case failed in windows and Mac")
    def test_pf_test_with_additional_includes(self, caplog):
        from promptflow import VERSION

        print(VERSION)
        with caplog.at_level(level=logging.WARNING, logger=LOGGER_NAME):
            inputs = {"url": "https://www.youtube.com/watch?v=o5ZQyXaAv1g", "answer": "Channel", "evidence": "Url"}
            result = _client.test(flow=f"{FLOWS_DIR}/web_classification_with_additional_include", inputs=inputs)
        duplicate_file_content = "Found duplicate file in additional includes"
        assert any([duplicate_file_content in record.message for record in caplog.records])
        assert all([key in FLOW_RESULT_KEYS for key in result])

        inputs = {"classify_with_llm.output": '{"category": "App", "evidence": "URL"}'}
        result = _client.test(flow=f"{FLOWS_DIR}/web_classification", inputs=inputs, node="convert_to_dict")
        assert all([key in FLOW_RESULT_KEYS for key in result])

        # Test additional includes don't exist
        with pytest.raises(ValueError) as e:
            _client.test(flow=f"{FLOWS_DIR}/web_classification_with_invalid_additional_include")
        assert "Unable to find additional include ../invalid/file/path" in str(e.value)

    def test_pf_flow_test_with_symbolic(self, prepare_symbolic_flow):
        inputs = {"url": "https://www.youtube.com/watch?v=o5ZQyXaAv1g", "answer": "Channel", "evidence": "Url"}
        result = _client.test(flow=f"{FLOWS_DIR}/web_classification_with_additional_include", inputs=inputs)
        assert all([key in FLOW_RESULT_KEYS for key in result])

        inputs = {"classify_with_llm.output": '{"category": "App", "evidence": "URL"}'}
        result = _client.test(flow=f"{FLOWS_DIR}/web_classification", inputs=inputs, node="convert_to_dict")
        assert all([key in FLOW_RESULT_KEYS for key in result])

    def test_pf_flow_test_with_exception(self, capsys):
        # Test flow with exception
        inputs = {"url": "https://www.youtube.com/watch?v=o5ZQyXaAv1g", "answer": "Channel", "evidence": "Url"}
        flow_path = Path(f"{FLOWS_DIR}/web_classification_with_exception").absolute()

        with pytest.raises(UserErrorException) as exception:
            _client.test(flow=flow_path, inputs=inputs)
        assert "Execution failure in 'convert_to_dict': (Exception) mock exception" in str(exception.value)

        # Test node with exception
        inputs = {"classify_with_llm.output": '{"category": "App", "evidence": "URL"}'}
        with pytest.raises(Exception) as exception:
            _client.test(flow=flow_path, inputs=inputs, node="convert_to_dict")
        output = capsys.readouterr()
        assert "convert_to_dict.py" in output.out
        assert "mock exception" in str(exception.value)

    def test_node_test_with_connection_input(self):
        flow_path = Path(f"{FLOWS_DIR}/basic-with-connection").absolute()
        inputs = {
            "connection": "azure_open_ai_connection",
            "hello_prompt.output": "Write a simple Hello World! "
            "program that displays the greeting message when executed.",
        }
        result = _client.test(
            flow=flow_path,
            inputs=inputs,
            node="echo_my_prompt",
            environment_variables={"API_TYPE": "${azure_open_ai_connection.api_type}"},
        )
        assert result

    def test_pf_flow_with_aggregation(self):
        flow_path = Path(f"{FLOWS_DIR}/classification_accuracy_evaluation").absolute()
        inputs = {"variant_id": "variant_0", "groundtruth": "Pdf", "prediction": "PDF"}
        result = _client._flows._test(flow=flow_path, inputs=inputs)
        assert "calculate_accuracy" in result.node_run_infos
        assert result.run_info.metrics == {"accuracy": 1.0}

    def test_generate_tool_meta_in_additional_folder(self):
        flow_path = Path(f"{FLOWS_DIR}/web_classification_with_additional_include").absolute()
        flow_tools, _ = _client._flows._generate_tools_meta(flow=flow_path)
        for tool in flow_tools["code"].values():
            assert (Path(flow_path) / tool["source"]).exists()

    def test_pf_test_with_non_english_input(self):
        result = _client.test(flow=f"{FLOWS_DIR}/flow_with_non_english_input")
        assert result["output"] == "Hello 日本語"

    def test_pf_node_test_with_dict_input(self):
        flow_path = Path(f"{FLOWS_DIR}/flow_with_dict_input").absolute()
        inputs = {"get_dict_val.output.value": {"key": "value"}}
        result = _client._flows._test(flow=flow_path, node="print_val", inputs=inputs)
        assert result.status.value == "Completed"
