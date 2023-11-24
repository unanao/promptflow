import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pandas as pd
import pytest
from pytest_mock import MockerFixture

from promptflow import PFClient
from promptflow._constants import PROMPTFLOW_CONNECTIONS
from promptflow._sdk._constants import (
    FLOW_DIRECTORY_MACRO_IN_CONFIG,
    PROMPT_FLOW_DIR_NAME,
    FlowRunProperties,
    LocalStorageFilenames,
    RunStatus,
)
from promptflow._sdk._errors import (
    ConnectionNotFoundError,
    InvalidFlowError,
    InvalidRunStatusError,
    RunExistsError,
    RunNotFoundError,
)
from promptflow._sdk._load_functions import load_flow
from promptflow._sdk._run_functions import create_yaml_run
from promptflow._sdk._submitter.utils import SubmitterHelper
from promptflow._sdk._utils import _get_additional_includes
from promptflow._sdk.entities import Run
from promptflow._sdk.operations._local_storage_operations import LocalStorageOperations
from promptflow.connections import AzureOpenAIConnection
from promptflow.exceptions import UserErrorException

from ..recording_utilities import RecordStorage

PROMOTFLOW_ROOT = Path(__file__) / "../../../.."

TEST_ROOT = Path(__file__).parent.parent.parent
MODEL_ROOT = TEST_ROOT / "test_configs/e2e_samples"
CONNECTION_FILE = (PROMOTFLOW_ROOT / "connections.json").resolve().absolute().as_posix()
FLOWS_DIR = "./tests/test_configs/flows"
RUNS_DIR = "./tests/test_configs/runs"
DATAS_DIR = "./tests/test_configs/datas"


def create_run_against_multi_line_data(client) -> Run:
    return client.run(
        flow=f"{FLOWS_DIR}/web_classification",
        data=f"{DATAS_DIR}/webClassification3.jsonl",
        column_mapping={"url": "${data.url}"},
    )


def create_run_against_multi_line_data_without_llm(client: PFClient) -> Run:
    return client.run(
        flow=f"{FLOWS_DIR}/print_env_var",
        data=f"{DATAS_DIR}/env_var_names.jsonl",
    )


def create_run_against_run(client, run: Run) -> Run:
    return client.run(
        flow=f"{FLOWS_DIR}/classification_accuracy_evaluation",
        data=f"{DATAS_DIR}/webClassification3.jsonl",
        run=run.name,
        column_mapping={
            "groundtruth": "${data.answer}",
            "prediction": "${run.outputs.category}",
            "variant_id": "${data.variant_id}",
        },
    )


def assert_run_with_invalid_column_mapping(client: PFClient, run: Run) -> None:
    assert run.status == RunStatus.FAILED

    with pytest.raises(InvalidRunStatusError):
        client.stream(run.name)

    local_storage = LocalStorageOperations(run)
    assert os.path.exists(local_storage._exception_path)

    exception = local_storage.load_exception()
    assert "The input for batch run is incorrect. Couldn't find these mapping relations" in exception["message"]
    assert exception["code"] == "BulkRunException"


@pytest.mark.usefixtures(
    "use_secrets_config_file", "recording_injection", "setup_local_connection", "install_custom_tool_pkg"
)
@pytest.mark.sdk_test
@pytest.mark.e2etest
class TestFlowRun:
    def test_basic_flow_bulk_run(self, azure_open_ai_connection: AzureOpenAIConnection, pf) -> None:
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"

        pf.run(flow=f"{FLOWS_DIR}/web_classification", data=data_path)
        # Test repeated execute flow run
        pf.run(flow=f"{FLOWS_DIR}/web_classification", data=data_path)

        pf.run(flow=f"{FLOWS_DIR}/web_classification_v1", data=data_path)
        pf.run(flow=f"{FLOWS_DIR}/web_classification_v2", data=data_path)

        # TODO: check details
        # df = pf.show_details(baseline, v1, v2)

    def test_basic_run_bulk(self, azure_open_ai_connection: AzureOpenAIConnection, local_client, pf):
        result = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"url": "${data.url}"},
        )
        local_storage = LocalStorageOperations(result)
        detail = local_storage.load_detail()
        tuning_node = next((x for x in detail["node_runs"] if x["node"] == "summarize_text_content"), None)
        # used default variant config
        assert tuning_node["inputs"]["temperature"] == 0.3
        assert "variant_0" in result.name

        run = local_client.runs.get(name=result.name)
        assert run.status == "Completed"
        # write to user_dir/.promptflow/.runs
        assert ".promptflow" in run.properties["output_path"]

    def test_basic_flow_with_variant(self, azure_open_ai_connection: AzureOpenAIConnection, local_client, pf) -> None:
        result = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"url": "${data.url}"},
            variant="${summarize_text_content.variant_0}",
        )
        local_storage = LocalStorageOperations(result)
        detail = local_storage.load_detail()
        tuning_node = next((x for x in detail["node_runs"] if x["node"] == "summarize_text_content"), None)
        assert "variant_0" in result.name

        # used variant_0 config
        assert tuning_node["inputs"]["temperature"] == 0.2
        result = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"url": "${data.url}"},
            variant="${summarize_text_content.variant_1}",
        )
        local_storage = LocalStorageOperations(result)
        detail = local_storage.load_detail()
        tuning_node = next((x for x in detail["node_runs"] if x["node"] == "summarize_text_content"), None)
        assert "variant_1" in result.name
        # used variant_1 config
        assert tuning_node["inputs"]["temperature"] == 0.3

    def test_run_bulk_error(self, pf):
        # path not exist
        with pytest.raises(FileNotFoundError) as e:
            pf.run(
                flow=f"{MODEL_ROOT}/not_exist",
                data=f"{DATAS_DIR}/webClassification3.jsonl",
                column_mapping={"question": "${data.question}", "context": "${data.context}"},
                variant="${summarize_text_content.variant_0}",
            )
        assert "not exist" in str(e.value)

        # tuning_node not exist
        with pytest.raises(InvalidFlowError) as e:
            pf.run(
                flow=f"{FLOWS_DIR}/web_classification",
                data=f"{DATAS_DIR}/webClassification3.jsonl",
                column_mapping={"question": "${data.question}", "context": "${data.context}"},
                variant="${not_exist.variant_0}",
            )
        assert "Node not_exist not found in flow" in str(e.value)

        # invalid variant format
        with pytest.raises(ValueError) as e:
            pf.run(
                flow=f"{FLOWS_DIR}/web_classification",
                data=f"{DATAS_DIR}/webClassification3.jsonl",
                column_mapping={"question": "${data.question}", "context": "${data.context}"},
                variant="v",
            )
        assert "Invalid variant format: v, variant should be in format of ${TUNING_NODE.VARIANT}" in str(e.value)

    def test_basic_evaluation(self, azure_open_ai_connection: AzureOpenAIConnection, local_client, pf):
        result = pf.run(
            flow=f"{FLOWS_DIR}/print_env_var",
            data=f"{DATAS_DIR}/env_var_names.jsonl",
        )
        assert local_client.runs.get(result.name).status == "Completed"

        eval_result = pf.run(
            flow=f"{FLOWS_DIR}/classification_accuracy_evaluation",
            run=result.name,
            column_mapping={
                "prediction": "${run.outputs.output}",
                # evaluation reference run.inputs
                # NOTE: we need this value to guard behavior when a run reference another run's inputs
                "variant_id": "${run.inputs.key}",
                # can reference other columns in data which doesn't exist in base run's inputs
                "groundtruth": "${run.inputs.extra_key}",
            },
        )
        assert local_client.runs.get(eval_result.name).status == "Completed"

    def test_flow_demo(self, azure_open_ai_connection, pf):
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"

        column_mapping = {
            "groundtruth": "${data.answer}",
            "prediction": "${run.outputs.category}",
            "variant_id": "${data.variant_id}",
        }

        metrics = {}
        for flow_name, output_key in [
            ("web_classification", "baseline"),
            ("web_classification_v1", "v1"),
            ("web_classification_v2", "v2"),
        ]:
            v = pf.run(flow=f"{FLOWS_DIR}/web_classification", data=data_path)

            metrics[output_key] = pf.run(
                flow=f"{FLOWS_DIR}/classification_accuracy_evaluation",
                data=data_path,
                run=v,
                column_mapping=column_mapping,
            )

    def test_submit_run_from_yaml(self, local_client, pf):
        run_id = str(uuid.uuid4())
        run = create_yaml_run(source=f"{RUNS_DIR}/sample_bulk_run.yaml", params_override=[{"name": run_id}])

        assert local_client.runs.get(run.name).status == "Completed"

        eval_run = create_yaml_run(
            source=f"{RUNS_DIR}/sample_eval_run.yaml",
            params_override=[{"run": run_id}],
        )
        assert local_client.runs.get(eval_run.name).status == "Completed"

    def test_run_with_connection(self, local_client, local_aoai_connection, pf):
        # remove connection file to test connection resolving
        os.environ.pop(PROMPTFLOW_CONNECTIONS)
        result = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"url": "${data.url}"},
        )
        local_storage = LocalStorageOperations(result)
        detail = local_storage.load_detail()
        tuning_node = next((x for x in detail["node_runs"] if x["node"] == "summarize_text_content"), None)
        # used default variant config
        assert tuning_node["inputs"]["temperature"] == 0.3

        run = local_client.runs.get(name=result.name)
        assert run.status == "Completed"

    def test_run_with_connection_overwrite(self, local_client, local_aoai_connection, local_alt_aoai_connection, pf):
        result = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            connections={"classify_with_llm": {"connection": "new_ai_connection"}},
        )
        run = local_client.runs.get(name=result.name)
        assert run.status == "Completed"

    def test_custom_connection_overwrite(self, local_client, local_custom_connection, pf):
        result = pf.run(
            flow=f"{FLOWS_DIR}/custom_connection_flow",
            data=f"{DATAS_DIR}/env_var_names.jsonl",
            connections={"print_env": {"connection": "test_custom_connection"}},
        )
        run = local_client.runs.get(name=result.name)
        assert run.status == "Completed"

        # overwrite non-exist connection
        with pytest.raises(InvalidFlowError) as e:
            pf.run(
                flow=f"{FLOWS_DIR}/custom_connection_flow",
                data=f"{DATAS_DIR}/env_var_names.jsonl",
                connections={"print_env": {"new_connection": "test_custom_connection"}},
            )
        assert "Connection with name new_connection not found" in str(e.value)

    def test_basic_flow_with_package_tool_with_custom_strong_type_connection(
        self, install_custom_tool_pkg, local_client, pf
    ):
        # Need to reload pkg_resources to get the latest installed tools
        import importlib

        import pkg_resources

        importlib.reload(pkg_resources)

        result = pf.run(
            flow=f"{FLOWS_DIR}/flow_with_package_tool_with_custom_strong_type_connection",
            data=f"{FLOWS_DIR}/flow_with_package_tool_with_custom_strong_type_connection/data.jsonl",
            connections={"My_First_Tool_00f8": {"connection": "custom_strong_type_connection"}},
        )
        run = local_client.runs.get(name=result.name)
        assert run.status == "Completed"

    def test_basic_flow_with_script_tool_with_custom_strong_type_connection(
        self, install_custom_tool_pkg, local_client, pf
    ):
        # Prepare custom connection
        from promptflow.connections import CustomConnection

        conn = CustomConnection(name="custom_connection_2", secrets={"api_key": "test"}, configs={"api_url": "test"})
        local_client.connections.create_or_update(conn)

        result = pf.run(
            flow=f"{FLOWS_DIR}/flow_with_script_tool_with_custom_strong_type_connection",
            data=f"{FLOWS_DIR}/flow_with_script_tool_with_custom_strong_type_connection/data.jsonl",
        )
        run = local_client.runs.get(name=result.name)
        assert run.status == "Completed"

    def test_run_with_connection_overwrite_non_exist(self, local_client, local_aoai_connection, pf):
        # overwrite non_exist connection
        with pytest.raises(ConnectionNotFoundError):
            pf.run(
                flow=f"{FLOWS_DIR}/web_classification",
                data=f"{DATAS_DIR}/webClassification1.jsonl",
                connections={"classify_with_llm": {"connection": "Not_exist"}},
            )

    def test_run_reference_failed_run(self, pf):
        failed_run = pf.run(
            flow=f"{FLOWS_DIR}/failed_flow",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"text": "${data.url}"},
        )
        # "update" run status to failed since currently all run will be completed unless there's bug
        pf.runs.update(
            name=failed_run.name,
            status="Failed",
        )

        run_name = str(uuid.uuid4())
        with pytest.raises(ValueError) as e:
            pf.run(
                name=run_name,
                flow=f"{FLOWS_DIR}/custom_connection_flow",
                run=failed_run,
                connections={"print_env": {"connection": "test_custom_connection"}},
            )
        assert "is not completed, got status" in str(e.value)

        # run should not be created
        with pytest.raises(RunNotFoundError):
            pf.runs.get(name=run_name)

    def test_referenced_output_not_exist(self, pf: PFClient) -> None:
        # failed run won't generate output
        failed_run = pf.run(
            flow=f"{FLOWS_DIR}/failed_flow",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"text": "${data.url}"},
        )

        run_name = str(uuid.uuid4())
        run = pf.run(
            name=run_name,
            run=failed_run,
            flow=f"{FLOWS_DIR}/failed_flow",
            column_mapping={"text": "${run.outputs.text}"},
        )
        assert_run_with_invalid_column_mapping(pf, run)

    def test_connection_overwrite_file(self, local_client, local_aoai_connection):
        run = create_yaml_run(
            source=f"{RUNS_DIR}/run_with_connections.yaml",
        )
        run = local_client.runs.get(name=run.name)
        assert run.status == "Completed"

    def test_connection_overwrite_model(self, local_client, local_aoai_connection):
        run = create_yaml_run(
            source=f"{RUNS_DIR}/run_with_connections_model.yaml",
        )
        run = local_client.runs.get(name=run.name)
        assert run.status == "Completed"

    def test_resolve_connection(self, local_client, local_aoai_connection):
        flow = load_flow(f"{FLOWS_DIR}/web_classification_no_variants")
        connections = SubmitterHelper.resolve_connections(flow, local_client)
        assert local_aoai_connection.name in connections

    def test_run_with_env_overwrite(self, local_client, local_aoai_connection):
        run = create_yaml_run(
            source=f"{RUNS_DIR}/run_with_env.yaml",
        )
        outputs = local_client.runs._get_outputs(run=run)
        assert outputs["output"][0] == local_aoai_connection.api_base

    def test_pf_run_with_env_overwrite(self, local_client, local_aoai_connection, pf):
        run = pf.run(
            flow=f"{FLOWS_DIR}/print_env_var",
            data=f"{DATAS_DIR}/env_var_names.jsonl",
            environment_variables={"API_BASE": "${azure_open_ai_connection.api_base}"},
        )
        outputs = local_client.runs._get_outputs(run=run)
        assert outputs["output"][0] == local_aoai_connection.api_base

    def test_eval_run_not_exist(self, pf):
        name = str(uuid.uuid4())
        with pytest.raises(RunNotFoundError) as e:
            pf.runs.create_or_update(
                run=Run(
                    name=name,
                    flow=Path(f"{FLOWS_DIR}/classification_accuracy_evaluation"),
                    run="not_exist",
                    column_mapping={
                        "groundtruth": "${data.answer}",
                        "prediction": "${run.outputs.category}",
                        # evaluation reference run.inputs
                        "url": "${run.inputs.url}",
                    },
                )
            )
        assert "Run name 'not_exist' cannot be found" in str(e.value)
        # run should not be created
        with pytest.raises(RunNotFoundError):
            pf.runs.get(name=name)

    def test_eval_run_data_deleted(self, pf):
        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copy(f"{DATAS_DIR}/env_var_names.jsonl", temp_dir)

            result = pf.run(
                flow=f"{FLOWS_DIR}/print_env_var",
                data=f"{temp_dir}/env_var_names.jsonl",
            )
            assert pf.runs.get(result.name).status == "Completed"

            # delete original run's input data
            os.remove(f"{temp_dir}/env_var_names.jsonl")

            with pytest.raises(UserErrorException) as e:
                pf.run(
                    flow=f"{FLOWS_DIR}/classification_accuracy_evaluation",
                    run=result.name,
                    column_mapping={
                        "prediction": "${run.outputs.output}",
                        # evaluation reference run.inputs
                        # NOTE: we need this value to guard behavior when a run reference another run's inputs
                        "variant_id": "${run.inputs.key}",
                        # can reference other columns in data which doesn't exist in base run's inputs
                        "groundtruth": "${run.inputs.extra_key}",
                    },
                )
            assert "Please make sure it exists and not deleted." in str(e.value)

    def test_eval_run_data_not_exist(self, pf):

        base_run = pf.run(
            flow=f"{FLOWS_DIR}/print_env_var",
            data=f"{DATAS_DIR}/env_var_names.jsonl",
        )
        assert pf.runs.get(base_run.name).status == "Completed"

        eval_run = pf.run(
            flow=f"{FLOWS_DIR}/classification_accuracy_evaluation",
            run=base_run.name,
            column_mapping={
                "prediction": "${run.outputs.output}",
                # evaluation reference run.inputs
                # NOTE: we need this value to guard behavior when a run reference another run's inputs
                "variant_id": "${run.inputs.key}",
                # can reference other columns in data which doesn't exist in base run's inputs
                "groundtruth": "${run.inputs.extra_key}",
            },
        )

        with pytest.raises(UserErrorException) as e:
            pf.run(
                flow=f"{FLOWS_DIR}/classification_accuracy_evaluation",
                run=eval_run.name,
                column_mapping={
                    "prediction": "${run.outputs.output}",
                    # evaluation reference run.inputs
                    # NOTE: we need this value to guard behavior when a run reference another run's inputs
                    "variant_id": "${run.inputs.key}",
                    # can reference other columns in data which doesn't exist in base run's inputs
                    "groundtruth": "${run.inputs.extra_key}",
                },
            )
        assert "Please make sure it exists and not deleted" in str(e.value)

    def test_create_run_with_tags(self, pf):
        name = str(uuid.uuid4())
        display_name = "test_run_with_tags"
        tags = {"key1": "tag1"}
        run = pf.run(
            name=name,
            display_name=display_name,
            tags=tags,
            flow=f"{FLOWS_DIR}/print_env_var",
            data=f"{DATAS_DIR}/env_var_names.jsonl",
            environment_variables={"API_BASE": "${azure_open_ai_connection.api_base}"},
        )
        assert run.name == name
        assert "test_run_with_tags" == run.display_name
        assert run.tags == tags

    def test_run_display_name(self, pf):
        # use folder name if not specify display_name
        run = pf.runs.create_or_update(
            run=Run(
                flow=Path(f"{FLOWS_DIR}/print_env_var"),
                data=f"{DATAS_DIR}/env_var_names.jsonl",
                environment_variables={"API_BASE": "${azure_open_ai_connection.api_base}"},
            )
        )
        assert run.display_name == run.name
        assert "print_env_var" in run.display_name

        # will respect if specified in run
        base_run = pf.runs.create_or_update(
            run=Run(
                flow=Path(f"{FLOWS_DIR}/print_env_var"),
                data=f"{DATAS_DIR}/env_var_names.jsonl",
                environment_variables={"API_BASE": "${azure_open_ai_connection.api_base}"},
                display_name="my_run",
            )
        )
        assert base_run.display_name == "my_run"

        run = pf.runs.create_or_update(
            run=Run(
                flow=Path(f"{FLOWS_DIR}/print_env_var"),
                data=f"{DATAS_DIR}/env_var_names.jsonl",
                environment_variables={"API_BASE": "${azure_open_ai_connection.api_base}"},
                display_name="my_run_${variant_id}_${run}",
                run=base_run,
            )
        )
        assert run.display_name == f"my_run_variant_0_{base_run.name}"

        run = pf.runs.create_or_update(
            run=Run(
                flow=Path(f"{FLOWS_DIR}/print_env_var"),
                data=f"{DATAS_DIR}/env_var_names.jsonl",
                environment_variables={"API_BASE": "${azure_open_ai_connection.api_base}"},
                display_name="my_run_${timestamp}",
                run=base_run,
            )
        )
        assert "${timestamp}" not in run.display_name

    def test_run_dump(self, azure_open_ai_connection: AzureOpenAIConnection, pf) -> None:
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        run = pf.run(flow=f"{FLOWS_DIR}/web_classification", data=data_path)
        # in fact, `pf.run` will internally query the run from db in `RunSubmitter`
        # explicitly call ORM get here to emphasize the dump operatoin
        # if no dump operation, a RunNotFoundError will be raised here
        pf.runs.get(run.name)

    def test_run_list(self, azure_open_ai_connection: AzureOpenAIConnection, pf) -> None:
        # create a run to ensure there is at least one run in the db
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        pf.run(flow=f"{FLOWS_DIR}/web_classification", data=data_path)
        # not specify `max_result` here, so that if there are legacy runs in the db
        # list runs API can collect them, and can somehow cover legacy schema
        runs = pf.runs.list()
        assert len(runs) >= 1

    def test_stream_run_summary(self, azure_open_ai_connection: AzureOpenAIConnection, local_client, capfd, pf) -> None:
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        run = pf.run(flow=f"{FLOWS_DIR}/web_classification", data=data_path)
        local_client.runs.stream(run.name)
        out, _ = capfd.readouterr()
        print(out)
        assert 'Run status: "Completed"' in out
        assert "Output path: " in out

    def test_stream_incomplete_run_summary(
        self, azure_open_ai_connection: AzureOpenAIConnection, local_client, capfd, pf
    ) -> None:
        # use wrong data to create a failed run
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        name = str(uuid.uuid4())
        run = pf.run(
            flow=f"{FLOWS_DIR}/failed_flow",
            data=data_path,
            column_mapping={"text": "${data.url}"},
            name=name,
        )
        local_client.runs.stream(run.name)
        # assert error message in stream API
        out, _ = capfd.readouterr()
        assert 'Run status: "Completed"' in out
        # won't print exception, use can get it from run._to_dict()
        # assert "failed with exception" in out

    def test_run_data_not_provided(self, pf):
        with pytest.raises(ValueError) as e:
            pf.run(
                flow=f"{FLOWS_DIR}/web_classification",
            )
        assert "at least one of data or run must be provided" in str(e)

    def test_get_details(self, azure_open_ai_connection: AzureOpenAIConnection, pf) -> None:
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        run = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=data_path,
            column_mapping={"url": "${data.url}"},
        )

        from promptflow._sdk.operations._local_storage_operations import LocalStorageOperations

        local_storage = LocalStorageOperations(run)
        # there should be line_number in original DataFrame, but not in details DataFrame
        # as we will set index on line_number to ensure the order
        outputs = pd.read_json(local_storage._outputs_path, orient="records", lines=True)
        details = pf.get_details(run)
        assert "line_number" in outputs and "line_number" not in details

    def test_visualize_run(self, azure_open_ai_connection: AzureOpenAIConnection, pf) -> None:
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        run1 = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=data_path,
            column_mapping={"url": "${data.url}"},
        )
        run2 = pf.run(
            flow=f"{FLOWS_DIR}/classification_accuracy_evaluation",
            data=data_path,
            run=run1.name,
            column_mapping={
                "groundtruth": "${data.answer}",
                "prediction": "${run.outputs.category}",
                "variant_id": "${data.variant_id}",
            },
        )
        pf.visualize([run1, run2])

    def test_incomplete_run_visualize(
        self, azure_open_ai_connection: AzureOpenAIConnection, pf, capfd: pytest.CaptureFixture
    ) -> None:
        failed_run = pf.run(
            flow=f"{FLOWS_DIR}/failed_flow",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"text": "${data.url}"},
        )
        # "update" run status to failed since currently all run will be completed unless there's bug
        pf.runs.update(
            name=failed_run.name,
            status="Failed",
        )

        # patch logger.error to print, so that we can capture the error message using capfd
        from promptflow._sdk.operations import _run_operations

        _run_operations.logger.error = print

        pf.visualize(failed_run)
        captured = capfd.readouterr()
        expected_error_message = (
            f"Cannot visualize non-completed run. Run {failed_run.name!r} is not completed, the status is 'Failed'."
        )
        assert expected_error_message in captured.out

    def test_flow_bulk_run_with_additional_includes(self, azure_open_ai_connection: AzureOpenAIConnection, pf):
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        run = pf.run(flow=f"{FLOWS_DIR}/web_classification_with_additional_include", data=data_path)

        additional_includes = _get_additional_includes(run.flow / "flow.dag.yaml")
        snapshot_path = Path.home() / ".promptflow" / ".runs" / run.name / "snapshot"
        for item in additional_includes:
            assert (snapshot_path / Path(item).name).exists()
        # Addition includes in snapshot is removed
        additional_includes = _get_additional_includes(snapshot_path / "flow.dag.yaml")
        assert not additional_includes

    def test_input_mapping_source_not_found_error(self, azure_open_ai_connection: AzureOpenAIConnection, pf):
        # input_mapping source not found error won't create run
        name = str(uuid.uuid4())
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        run = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=data_path,
            column_mapping={"not_exist": "${data.not_exist_key}"},
            name=name,
        )
        assert_run_with_invalid_column_mapping(pf, run)

    def test_input_mapping_with_dict(self, azure_open_ai_connection: AzureOpenAIConnection, pf):
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"

        run = pf.run(
            flow=f"{FLOWS_DIR}/flow_with_dict_input",
            data=data_path,
            column_mapping={"key": {"value": "1"}, "url": "${data.url}"},
        )
        outputs = pf.runs._get_outputs(run=run)
        assert "dict" in outputs["output"][0]

    def test_run_exist_error(self, pf):
        name = str(uuid.uuid4())
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"

        pf.run(
            name=name,
            flow=f"{FLOWS_DIR}/flow_with_dict_input",
            data=data_path,
            column_mapping={"key": {"value": "1"}, "url": "${data.url}"},
        )

        # create a new run won't affect original run
        with pytest.raises(RunExistsError):
            pf.run(
                name=name,
                flow=f"{FLOWS_DIR}/flow_with_dict_input",
                data=data_path,
                column_mapping={"key": {"value": "1"}, "url": "${data.url}"},
            )
        run = pf.runs.get(name)
        assert run.status == RunStatus.COMPLETED
        assert not os.path.exists(run._output_path / LocalStorageFilenames.EXCEPTION)

    def test_run_local_storage_structure(self, local_client, pf) -> None:
        run = create_run_against_multi_line_data(pf)
        local_storage = LocalStorageOperations(local_client.runs.get(run.name))
        run_output_path = local_storage.path
        assert (Path(run_output_path) / "flow_outputs").is_dir()
        assert (Path(run_output_path) / "flow_outputs" / "output.jsonl").is_file()
        assert (Path(run_output_path) / "flow_artifacts").is_dir()
        # 3 line runs for webClassification3.jsonl
        assert len([_ for _ in (Path(run_output_path) / "flow_artifacts").iterdir()]) == 3
        assert (Path(run_output_path) / "node_artifacts").is_dir()
        # 5 nodes web classification flow DAG
        assert len([_ for _ in (Path(run_output_path) / "node_artifacts").iterdir()]) == 5

    def test_run_snapshot_with_flow_tools_json(self, local_client, pf) -> None:
        run = create_run_against_multi_line_data(pf)
        local_storage = LocalStorageOperations(local_client.runs.get(run.name))
        assert (local_storage._snapshot_folder_path / ".promptflow").is_dir()
        assert (local_storage._snapshot_folder_path / ".promptflow" / "flow.tools.json").is_file()

    def test_get_metrics_format(self, local_client, pf) -> None:
        run1 = create_run_against_multi_line_data(pf)
        run2 = create_run_against_run(pf, run1)
        # ensure the result is a flatten dict
        assert local_client.runs.get_metrics(run2.name).keys() == {"accuracy"}

    def test_get_detail_format(self, local_client, pf) -> None:
        run = create_run_against_multi_line_data(pf)
        # data is a jsonl file, so we can know the number of line runs
        with open(f"{DATAS_DIR}/webClassification3.jsonl", "r") as f:
            data = f.readlines()
        number_of_lines = len(data)

        local_storage = LocalStorageOperations(local_client.runs.get(run.name))
        detail = local_storage.load_detail()

        assert isinstance(detail, dict)
        # flow runs
        assert "flow_runs" in detail
        assert isinstance(detail["flow_runs"], list)
        assert len(detail["flow_runs"]) == number_of_lines
        # node runs
        assert "node_runs" in detail
        assert isinstance(detail["node_runs"], list)

    def test_run_logs(self, pf):
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"

        run = pf.run(
            flow=f"{FLOWS_DIR}/flow_with_user_output",
            data=data_path,
            column_mapping={"key": {"value": "1"}, "url": "${data.url}"},
        )
        local_storage = LocalStorageOperations(run=run)
        logs = local_storage.logger.get_logs()
        # For Batch run, the executor uses bulk logger to print logs, and only prints the error log of the nodes.
        existing_keywords = ["execution", "execution.bulk", "WARNING", "error log"]
        assert all([keyword in logs for keyword in existing_keywords])
        non_existing_keywords = ["execution.flow", "user log"]
        assert all([keyword not in logs for keyword in non_existing_keywords])

    def test_get_detail_against_partial_fail_run(self, pf) -> None:
        run = pf.run(
            flow=f"{FLOWS_DIR}/partial_fail",
            data=f"{FLOWS_DIR}/partial_fail/data.jsonl",
        )
        detail = pf.runs.get_details(name=run.name)
        detail.fillna("", inplace=True)
        assert len(detail) == 3

    def test_flow_with_only_static_values(self, pf):
        name = str(uuid.uuid4())
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"

        with pytest.raises(UserErrorException) as e:
            pf.run(
                flow=f"{FLOWS_DIR}/flow_with_dict_input",
                data=data_path,
                column_mapping={"key": {"value": "1"}},
                name=name,
            )

        assert "Column mapping must contain at least one mapping binding" in str(e.value)
        # run should not be created
        with pytest.raises(RunNotFoundError):
            pf.runs.get(name=name)

    def test_error_message_dump(self, pf):
        failed_run = pf.run(
            flow=f"{FLOWS_DIR}/failed_flow",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"text": "${data.url}"},
        )
        # even if all lines failed, the bulk run's status is completed.
        assert failed_run.status == "Completed"
        # error messages will store in local
        local_storage = LocalStorageOperations(failed_run)

        assert os.path.exists(local_storage._exception_path)
        exception = local_storage.load_exception()
        assert "Failed to run 1/1 lines. First error message is" in exception["message"]
        # line run failures will be stored in additionalInfo
        assert len(exception["additionalInfo"][0]["info"]["errors"]) == 1

        # show run will get error message
        run = pf.runs.get(name=failed_run.name)
        run_dict = run._to_dict()
        assert "error" in run_dict
        assert run_dict["error"] == exception

    @pytest.mark.skipif(RecordStorage.is_replaying_mode(), reason="System metrics not supported in replaying mode")
    def test_system_metrics_in_properties(self, pf) -> None:
        run = create_run_against_multi_line_data(pf)
        assert FlowRunProperties.SYSTEM_METRICS in run.properties
        assert isinstance(run.properties[FlowRunProperties.SYSTEM_METRICS], dict)
        assert "total_tokens" in run.properties[FlowRunProperties.SYSTEM_METRICS]

    def test_run_get_inputs(self, pf):
        # inputs should be persisted when defaults are used
        run = pf.run(
            flow=f"{FLOWS_DIR}/default_input",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
        )
        inputs = pf.runs._get_inputs(run=run)
        assert inputs == {
            "line_number": [0],
            "input_bool": [False],
            "input_dict": [{}],
            "input_list": [[]],
            "input_str": ["input value from default"],
        }

        # inputs should be persisted when data value are used
        run = pf.run(
            flow=f"{FLOWS_DIR}/flow_with_dict_input",
            data=f"{DATAS_DIR}/dictInput1.jsonl",
        )
        inputs = pf.runs._get_inputs(run=run)
        assert inputs == {"key": [{"key": "value in data"}], "line_number": [0]}

        # inputs should be persisted when column-mapping are used
        run = pf.run(
            flow=f"{FLOWS_DIR}/flow_with_dict_input",
            data=f"{DATAS_DIR}/webClassification1.jsonl",
            column_mapping={"key": {"value": "value in column-mapping"}, "url": "${data.url}"},
        )
        inputs = pf.runs._get_inputs(run=run)
        assert inputs == {
            "key": [{"value": "value in column-mapping"}],
            "line_number": [0],
            "url": ["https://www.youtube.com/watch?v=o5ZQyXaAv1g"],
        }

    def test_executor_logs_in_batch_run_logs(self, pf) -> None:
        run = create_run_against_multi_line_data_without_llm(pf)
        local_storage = LocalStorageOperations(run=run)
        logs = local_storage.logger.get_logs()
        # below warning is printed by executor before the batch run executed
        # the warning message results from we do not use column mapping
        # so it is expected to be printed here
        assert "Starting run without column mapping may lead to unexpected results." in logs

    def test_basic_image_flow_bulk_run(self, pf, local_client) -> None:
        image_flow_path = f"{FLOWS_DIR}/python_tool_with_simple_image"
        data_path = f"{image_flow_path}/image_inputs/inputs.jsonl"

        result = pf.run(flow=image_flow_path, data=data_path, column_mapping={"image": "${data.image}"})
        run = local_client.runs.get(name=result.name)
        assert run.status == "Completed"
        assert "error" not in run._to_dict()

    def test_python_tool_with_composite_image(self, pf) -> None:
        image_flow_path = f"{FLOWS_DIR}/python_tool_with_composite_image"
        data_path = f"{image_flow_path}/inputs.jsonl"

        result = pf.run(
            flow=image_flow_path,
            data=data_path,
            column_mapping={
                "image_list": "${data.image_list}",
                "image_dict": "${data.image_dict}",
            },
        )
        run = pf.runs.get(name=result.name)
        assert run.status == "Completed"
        # no error when processing lines
        assert "error" not in run._to_dict()

        # test input from output
        result = pf.run(
            run=result,
            flow=image_flow_path,
            column_mapping={
                "image_list": "${run.outputs.output}"
                # image dict will use default value, which is relative to flow's folder
            },
        )
        run = pf.runs.get(name=result.name)
        assert run.status == "Completed"
        # no error when processing lines
        assert "error" not in run._to_dict()

    def test_image_without_default(self, pf):
        image_flow_path = f"{FLOWS_DIR}/python_tool_with_simple_image_without_default"
        data_path = f"{DATAS_DIR}/image_inputs"

        result = pf.run(
            flow=image_flow_path,
            data=data_path,
            column_mapping={
                "image_1": "${data.image}",
                "image_2": "${data.image}",
            },
        )
        run = pf.runs.get(name=result.name)
        assert run.status == "Completed", run.name
        # no error when processing lines
        assert "error" not in run._to_dict(), run.name

    def test_get_details_for_image_in_flow(self, pf) -> None:
        image_flow_path = f"{FLOWS_DIR}/python_tool_with_simple_image"
        data_path = f"{image_flow_path}/image_inputs/inputs.jsonl"
        run = pf.run(
            flow=image_flow_path,
            data=data_path,
            column_mapping={"image": "${data.image}"},
        )
        details = pf.get_details(run.name)
        for i in range(len(details)):
            input_image_path = details["inputs.image"][i]["data:image/png;path"]
            assert Path(input_image_path).is_absolute()
            output_image_path = details["outputs.output"][i]["data:image/png;path"]
            assert Path(output_image_path).is_absolute()

    def test_stream_raise_on_error_false(self, pf: PFClient, capfd: pytest.CaptureFixture) -> None:
        data_path = f"{DATAS_DIR}/webClassification3.jsonl"
        run = pf.run(
            flow=f"{FLOWS_DIR}/web_classification",
            data=data_path,
            column_mapping={"not_exist": "${data.not_exist_key}"},
            name=str(uuid.uuid4()),
        )
        # raise_on_error=False, will print error message in stdout
        pf.stream(run.name, raise_on_error=False)
        out, _ = capfd.readouterr()
        assert "The input for batch run is incorrect. Couldn't find these mapping relations" in out

    def test_stream_canceled_run(self, pf: PFClient, capfd: pytest.CaptureFixture) -> None:
        run = create_run_against_multi_line_data_without_llm(pf)
        pf.runs.update(name=run.name, status=RunStatus.CANCELED)
        # (default) raise_on_error=True
        with pytest.raises(InvalidRunStatusError):
            pf.stream(run.name)
        # raise_on_error=False
        pf.stream(run.name, raise_on_error=False)
        out, _ = capfd.readouterr()
        assert "Run is canceled." in out

    def test_specify_run_output_path(self, pf: PFClient, mocker: MockerFixture) -> None:
        # mock to imitate user specify config run.output_path
        specified_run_output_path = (Path.home() / PROMPT_FLOW_DIR_NAME / ".mock").resolve().as_posix()
        with mocker.patch(
            "promptflow._sdk._configuration.Configuration.get_run_output_path",
            return_value=specified_run_output_path,
        ):
            run = create_run_against_multi_line_data_without_llm(pf)
            local_storage = LocalStorageOperations(run=run)
            expected_output_path_prefix = (Path(specified_run_output_path) / run.name).resolve().as_posix()
            assert local_storage.outputs_folder.as_posix().startswith(expected_output_path_prefix)

    def test_override_run_output_path_in_pf_client(self) -> None:
        specified_run_output_path = (Path.home() / PROMPT_FLOW_DIR_NAME / ".another_mock").resolve().as_posix()
        pf = PFClient(config={"run.output_path": specified_run_output_path})
        run = create_run_against_multi_line_data_without_llm(pf)
        local_storage = LocalStorageOperations(run=run)
        expected_output_path_prefix = (Path(specified_run_output_path) / run.name).resolve().as_posix()
        assert local_storage.outputs_folder.as_posix().startswith(expected_output_path_prefix)

    def test_specify_run_output_path_with_macro(self, pf: PFClient, mocker: MockerFixture) -> None:
        # mock to imitate user specify invalid config run.output_path
        with mocker.patch(
            "promptflow._sdk._configuration.Configuration.get_run_output_path",
            return_value=f"{FLOW_DIRECTORY_MACRO_IN_CONFIG}/.promptflow",
        ):
            for _ in range(3):
                run = create_run_against_multi_line_data_without_llm(pf)
                local_storage = LocalStorageOperations(run=run)
                expected_path_prefix = Path(FLOWS_DIR) / "print_env_var" / ".promptflow" / run.name
                expected_path_prefix = expected_path_prefix.resolve().as_posix()
                assert local_storage.outputs_folder.as_posix().startswith(expected_path_prefix)

    def test_specify_run_output_path_with_invalid_macro(self, pf: PFClient, mocker: MockerFixture) -> None:
        # mock to imitate user specify invalid config run.output_path
        with mocker.patch(
            "promptflow._sdk._configuration.Configuration.get_run_output_path",
            # this case will happen when user manually modifies ~/.promptflow/pf.yaml
            return_value=f"{FLOW_DIRECTORY_MACRO_IN_CONFIG}",
        ):
            run = create_run_against_multi_line_data_without_llm(pf)
            # as the specified run output path is invalid
            # the actual run output path will be the default value
            local_storage = LocalStorageOperations(run=run)
            expected_output_path_prefix = (Path.home() / PROMPT_FLOW_DIR_NAME / ".runs" / run.name).resolve().as_posix()
            assert local_storage.outputs_folder.as_posix().startswith(expected_output_path_prefix)

    # Will remove this test before PR is merged
    @pytest.mark.skip(reason="C# executor is not ready")
    def test_csharp_flow(self, pf):
        image_flow_path = "D:/csharp_flow/flow.dag.yaml"
        data_path = "D:/inputs.jsonl"

        result = pf.run(
            flow=image_flow_path,
            data=data_path,
            column_mapping={
                "question": "${data.question}",
            },
        )
        run = pf.runs.get(name=result.name)
        assert run.status == "Completed", run.name
        # no error when processing lines
        assert "error" not in run._to_dict(), run.name
