import os
from pathlib import Path
from tempfile import mkdtemp

import pytest

from promptflow._utils.multimedia_utils import MIME_PATTERN, _create_image_from_file, is_multimedia_dict
from promptflow.batch._batch_engine import OUTPUT_FILE_NAME, BatchEngine
from promptflow.batch._result import BatchResult
from promptflow.contracts.multimedia import Image
from promptflow.contracts.run_info import FlowRunInfo, RunInfo, Status
from promptflow.executor import FlowExecutor
from promptflow.storage._run_storage import DefaultRunStorage

from ..utils import get_flow_folder, get_yaml_file, is_image_file, is_jsonl_file, load_jsonl

SIMPLE_IMAGE_FLOW = "python_tool_with_simple_image"
SAMPLE_IMAGE_FLOW_WITH_DEFAULT = "python_tool_with_simple_image_with_default"
SIMPLE_IMAGE_WITH_INVALID_DEFAULT_VALUE_FLOW = "python_tool_with_invalid_default_value"
COMPOSITE_IMAGE_FLOW = "python_tool_with_composite_image"
CHAT_FLOW_WITH_IMAGE = "chat_flow_with_image"
EVAL_FLOW_WITH_SIMPLE_IMAGE = "eval_flow_with_simple_image"
EVAL_FLOW_WITH_COMPOSITE_IMAGE = "eval_flow_with_composite_image"
NESTED_API_CALLS_FLOW = "python_tool_with_image_nested_api_calls"

IMAGE_URL = (
    "https://raw.githubusercontent.com/microsoft/promptflow/main/src/promptflow/tests/test_configs/datas/logo.jpg"
)


def get_test_cases_for_simple_input(flow_folder):
    working_dir = get_flow_folder(flow_folder)
    image = _create_image_from_file(working_dir / "logo.jpg")
    inputs = [
        {"data:image/jpg;path": str(working_dir / "logo.jpg")},
        {"data:image/jpg;base64": image.to_base64()},
        {"data:image/jpg;url": IMAGE_URL},
        str(working_dir / "logo.jpg"),
        image.to_base64(),
        IMAGE_URL,
    ]
    return [(flow_folder, {"image": input}) for input in inputs]


def get_test_cases_for_composite_input(flow_folder):
    working_dir = get_flow_folder(flow_folder)
    image_1 = _create_image_from_file(working_dir / "logo.jpg")
    image_2 = _create_image_from_file(working_dir / "logo_2.png")
    inputs = [
        [
            {"data:image/jpg;path": str(working_dir / "logo.jpg")},
            {"data:image/png;path": str(working_dir / "logo_2.png")},
        ],
        [{"data:image/jpg;base64": image_1.to_base64()}, {"data:image/png;base64": image_2.to_base64()}],
        [{"data:image/jpg;url": IMAGE_URL}, {"data:image/png;url": IMAGE_URL}],
    ]
    return [
        (flow_folder, {"image_list": input, "image_dict": {"image_1": input[0], "image_2": input[1]}})
        for input in inputs
    ]


def get_test_cases_for_node_run():
    image = {"data:image/jpg;path": str(get_flow_folder(SIMPLE_IMAGE_FLOW) / "logo.jpg")}
    simple_image_input = {"image": image}
    image_list = [{"data:image/jpg;path": "logo.jpg"}, {"data:image/png;path": "logo_2.png"}]
    image_dict = {
        "image_dict": {
            "image_1": {"data:image/jpg;path": "logo.jpg"},
            "image_2": {"data:image/png;path": "logo_2.png"},
        }
    }
    composite_image_input = {"image_list": image_list, "image_dcit": image_dict}

    return [
        (SIMPLE_IMAGE_FLOW, "python_node", simple_image_input, None),
        (SIMPLE_IMAGE_FLOW, "python_node_2", simple_image_input, {"python_node": image}),
        (COMPOSITE_IMAGE_FLOW, "python_node", composite_image_input, None),
        (COMPOSITE_IMAGE_FLOW, "python_node_2", composite_image_input, None),
        (
            COMPOSITE_IMAGE_FLOW,
            "python_node_3",
            composite_image_input,
            {"python_node": image_list, "python_node_2": image_dict},
        ),
    ]


def contain_image_reference(value):
    if isinstance(value, (FlowRunInfo, RunInfo)):
        assert contain_image_reference(value.api_calls)
        assert contain_image_reference(value.inputs)
        assert contain_image_reference(value.output)
        return True
    assert not isinstance(value, Image)
    if isinstance(value, list):
        return any(contain_image_reference(item) for item in value)
    if isinstance(value, dict):
        if is_multimedia_dict(value):
            v = list(value.values())[0]
            assert isinstance(v, str)
            return True
        return any(contain_image_reference(v) for v in value.values())
    return False


def contain_image_object(value):
    if isinstance(value, list):
        return any(contain_image_object(item) for item in value)
    elif isinstance(value, dict):
        assert not is_multimedia_dict(value)
        return any(contain_image_object(v) for v in value.values())
    else:
        return isinstance(value, Image)


@pytest.mark.usefixtures("dev_connections")
@pytest.mark.e2etest
class TestExecutorWithImage:
    @pytest.mark.parametrize(
        "flow_folder, inputs",
        get_test_cases_for_simple_input(SIMPLE_IMAGE_FLOW)
        + get_test_cases_for_composite_input(COMPOSITE_IMAGE_FLOW)
        + [(CHAT_FLOW_WITH_IMAGE, {}), (NESTED_API_CALLS_FLOW, {})],
    )
    def test_executor_exec_line_with_image(self, flow_folder, inputs, dev_connections):
        working_dir = get_flow_folder(flow_folder)
        os.chdir(working_dir)
        storage = DefaultRunStorage(base_dir=working_dir, sub_dir=Path("./temp"))
        executor = FlowExecutor.create(get_yaml_file(flow_folder), dev_connections, storage=storage)
        flow_result = executor.exec_line(inputs)
        assert isinstance(flow_result.output, dict)
        assert contain_image_object(flow_result.output)
        # Assert output also contains plain text.
        assert any(isinstance(v, str) for v in flow_result.output)
        assert flow_result.run_info.status == Status.Completed
        assert contain_image_reference(flow_result.run_info)
        for _, node_run_info in flow_result.node_run_infos.items():
            assert node_run_info.status == Status.Completed
            assert contain_image_reference(node_run_info)

    @pytest.mark.parametrize(
        "flow_folder, node_name, flow_inputs, dependency_nodes_outputs", get_test_cases_for_node_run()
    )
    def test_executor_exec_node_with_image(
        self, flow_folder, node_name, flow_inputs, dependency_nodes_outputs, dev_connections
    ):
        working_dir = get_flow_folder(flow_folder)
        os.chdir(working_dir)
        run_info = FlowExecutor.load_and_exec_node(
            get_yaml_file(flow_folder),
            node_name,
            flow_inputs=flow_inputs,
            dependency_nodes_outputs=dependency_nodes_outputs,
            connections=dev_connections,
            output_sub_dir=("./temp"),
            raise_ex=True,
        )
        assert run_info.status == Status.Completed
        assert contain_image_reference(run_info)

    @pytest.mark.parametrize(
        "flow_folder, node_name, flow_inputs, dependency_nodes_outputs",
        [
            (
                SIMPLE_IMAGE_WITH_INVALID_DEFAULT_VALUE_FLOW,
                "python_node_2",
                {},
                {
                    "python_node": {
                        "data:image/jpg;path": str(
                            get_flow_folder(SIMPLE_IMAGE_WITH_INVALID_DEFAULT_VALUE_FLOW) / "logo.jpg"
                        )
                    }
                },
            )
        ],
    )
    def test_executor_exec_node_with_invalid_default_value(
        self, flow_folder, node_name, flow_inputs, dependency_nodes_outputs, dev_connections
    ):
        working_dir = get_flow_folder(flow_folder)
        os.chdir(working_dir)
        run_info = FlowExecutor.load_and_exec_node(
            get_yaml_file(flow_folder),
            node_name,
            flow_inputs=flow_inputs,
            dependency_nodes_outputs=dependency_nodes_outputs,
            connections=dev_connections,
            output_sub_dir=("./temp"),
            raise_ex=True,
        )
        assert run_info.status == Status.Completed
        assert contain_image_reference(run_info)

    @pytest.mark.parametrize(
        "flow_folder, input_dirs, inputs_mapping, output_key, expected_outputs_number, has_aggregation_node",
        [
            (
                SIMPLE_IMAGE_FLOW,
                {"data": "."},
                {"image": "${data.image}"},
                "output",
                4,
                False,
            ),
            (
                SAMPLE_IMAGE_FLOW_WITH_DEFAULT,
                {"data": "."},
                {"image_2": "${data.image_2}"},
                "output",
                4,
                False,
            ),
            (
                COMPOSITE_IMAGE_FLOW,
                {"data": "inputs.jsonl"},
                {"image_list": "${data.image_list}", "image_dict": "${data.image_dict}"},
                "output",
                2,
                False,
            ),
            (
                CHAT_FLOW_WITH_IMAGE,
                {"data": "inputs.jsonl"},
                {"question": "${data.question}", "chat_history": "${data.chat_history}"},
                "answer",
                2,
                False,
            ),
            (
                EVAL_FLOW_WITH_SIMPLE_IMAGE,
                {"data": "inputs.jsonl"},
                {"image": "${data.image}"},
                "output",
                2,
                True,
            ),
            (
                EVAL_FLOW_WITH_COMPOSITE_IMAGE,
                {"data": "inputs.jsonl"},
                {"image_list": "${data.image_list}", "image_dict": "${data.image_dict}"},
                "output",
                2,
                True,
            ),
        ],
    )
    def test_batch_engine_with_image(
        self, flow_folder, input_dirs, inputs_mapping, output_key, expected_outputs_number, has_aggregation_node
    ):
        flow_file = get_yaml_file(flow_folder)
        working_dir = get_flow_folder(flow_folder)
        output_dir = Path(mkdtemp())
        batch_result = BatchEngine(flow_file, working_dir).run(
            input_dirs, inputs_mapping, output_dir, max_lines_count=4
        )

        assert isinstance(batch_result, BatchResult)
        assert batch_result.completed_lines == expected_outputs_number
        assert all(is_jsonl_file(output_file) or is_image_file(output_file) for output_file in output_dir.iterdir())

        outputs = load_jsonl(output_dir / OUTPUT_FILE_NAME)
        assert len(outputs) == expected_outputs_number
        for i, output in enumerate(outputs):
            assert isinstance(output, dict)
            assert "line_number" in output, f"line_number is not in {i}th output {output}"
            assert output["line_number"] == i, f"line_number is not correct in {i}th output {output}"
            result = output[output_key][0] if isinstance(output[output_key], list) else output[output_key]
            assert all(MIME_PATTERN.search(key) for key in result), f"image is not in {i}th output {output}"

    @pytest.mark.parametrize(
        "flow_folder, inputs",
        get_test_cases_for_simple_input(EVAL_FLOW_WITH_SIMPLE_IMAGE)
        + get_test_cases_for_composite_input(EVAL_FLOW_WITH_COMPOSITE_IMAGE),
    )
    def test_executor_exec_aggregation_with_image(self, flow_folder, inputs, dev_connections):
        working_dir = get_flow_folder(flow_folder)
        os.chdir(working_dir)
        storage = DefaultRunStorage(base_dir=working_dir, sub_dir=Path("./temp"))
        executor = FlowExecutor.create(get_yaml_file(flow_folder), dev_connections, storage=storage)
        flow_result = executor.exec_line(inputs, index=0)
        flow_inputs = {k: [v] for k, v in inputs.items()}
        aggregation_inputs = {k: [v] for k, v in flow_result.aggregation_inputs.items()}
        aggregation_results = executor.exec_aggregation(flow_inputs, aggregation_inputs=aggregation_inputs)
        for _, node_run_info in aggregation_results.node_run_infos.items():
            assert node_run_info.status == Status.Completed
            assert contain_image_reference(node_run_info)
