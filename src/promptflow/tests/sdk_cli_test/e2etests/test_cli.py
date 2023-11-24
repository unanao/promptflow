import importlib
import importlib.util
import json
import logging
import os
import os.path
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

import mock
import pytest
import yaml

from promptflow._cli._pf.entry import main
from promptflow._sdk._constants import LOGGER_NAME, SCRUBBED_VALUE
from promptflow._sdk._errors import RunNotFoundError
from promptflow._sdk.operations._local_storage_operations import LocalStorageOperations
from promptflow._sdk.operations._run_operations import RunOperations
from promptflow._utils.context_utils import _change_working_dir

FLOWS_DIR = "./tests/test_configs/flows"
RUNS_DIR = "./tests/test_configs/runs"
CONNECTIONS_DIR = "./tests/test_configs/connections"
DATAS_DIR = "./tests/test_configs/datas"


# TODO: move this to a shared utility module
def run_pf_command(*args, cwd=None):
    """Run a pf command with the given arguments and working directory.

    There have been some unknown issues in using subprocess on CI, so we use this function instead, which will also
    provide better debugging experience.
    """
    origin_argv, origin_cwd = sys.argv, os.path.abspath(os.curdir)
    try:
        sys.argv = ["pf"] + list(args)
        if cwd:
            os.chdir(cwd)
        main()
    finally:
        sys.argv = origin_argv
        os.chdir(origin_cwd)


@pytest.mark.usefixtures(
    "use_secrets_config_file", "recording_injection", "setup_local_connection", "install_custom_tool_pkg"
)
@pytest.mark.cli_test
@pytest.mark.e2etest
class TestCli:
    def test_pf_version(self, capfd):
        run_pf_command("--version")
        out, _ = capfd.readouterr()
        assert "0.0.1\n" in out

    def test_basic_flow_run(self, capfd) -> None:
        # fetch std out
        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--name",
            str(uuid.uuid4()),
        )
        out, _ = capfd.readouterr()
        assert "Completed" in out

    def test_basic_flow_run_batch_and_eval(self, capfd) -> None:
        run_id = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--name",
            run_id,
        )
        out, _ = capfd.readouterr()
        assert "Completed" in out

        # Check the CLI works correctly when the parameter is surrounded by quotation, as below shown:
        # --param "key=value" key="value"
        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/classification_accuracy_evaluation",
            "--column-mapping",
            "'groundtruth=${data.answer}'",
            "prediction='${run.outputs.category}'",
            "variant_id=${data.variant_id}",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--run",
            run_id,
        )
        out, _ = capfd.readouterr()
        assert "Completed" in out

    def test_submit_run_with_yaml(self, capfd):
        run_id = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--file",
            "./sample_bulk_run.yaml",
            "--name",
            run_id,
            cwd=f"{RUNS_DIR}",
        )
        out, _ = capfd.readouterr()
        assert "Completed" in out

        run_pf_command(
            "run",
            "create",
            "--file",
            "./sample_eval_run.yaml",
            "--run",
            run_id,
            cwd=f"{RUNS_DIR}",
        )
        out, _ = capfd.readouterr()
        assert "Completed" in out

    def test_submit_batch_variant(self, local_client):
        run_id = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--name",
            run_id,
            "--variant",
            "${summarize_text_content.variant_0}",
        )
        run = local_client.runs.get(name=run_id)
        local_storage = LocalStorageOperations(run)
        detail = local_storage.load_detail()
        tuning_node = next((x for x in detail["node_runs"] if x["node"] == "summarize_text_content"), None)
        # used variant_0 config, defaults using variant_1
        assert tuning_node["inputs"]["temperature"] == 0.2

    def test_environment_variable_overwrite(self, local_client, local_aoai_connection):
        run_id = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--name",
            run_id,
            "--flow",
            f"{FLOWS_DIR}/print_env_var",
            "--data",
            f"{DATAS_DIR}/env_var_names.jsonl",
            "--environment-variables",
            "API_BASE=${azure_open_ai_connection.api_base}",
        )
        outputs = local_client.runs._get_outputs(run=run_id)
        assert outputs["output"][0] == local_aoai_connection.api_base

    def test_connection_overwrite(self, local_alt_aoai_connection, capfd):
        # CLi command will fail with SystemExit
        with pytest.raises(SystemExit):
            run_pf_command(
                "run",
                "create",
                "--flow",
                f"{FLOWS_DIR}/web_classification",
                "--data",
                f"{DATAS_DIR}/webClassification3.jsonl",
                "--connection",
                "classify_with_llm.connection=not_exist",
            )

        out, _ = capfd.readouterr()
        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--connection",
            "classify_with_llm.connection=new_ai_connection",
        )
        out, _ = capfd.readouterr()
        assert "Completed" in out

        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--connection",
            "classify_with_llm.model=new_model",
        )
        out, _ = capfd.readouterr()
        assert "Completed" in out

    def test_create_with_set(self, local_client):
        run_id = str(uuid.uuid4())
        display_name = "test_run"
        description = "test description"
        run_pf_command(
            "run",
            "create",
            "--name",
            run_id,
            "--flow",
            f"{FLOWS_DIR}/print_env_var",
            "--data",
            f"{DATAS_DIR}/env_var_names.jsonl",
            "--environment-variables",
            "API_BASE=${azure_open_ai_connection.api_base}",
            "--set",
            f"display_name={display_name}",
            "tags.key=val",
            f"description={description}",
        )
        run = local_client.runs.get(run_id)
        assert display_name in run.display_name
        assert run.tags == {"key": "val"}
        assert run.description == description

        run_id = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--file",
            "./sample_bulk_run.yaml",
            "--name",
            run_id,
            "--set",
            f"display_name={display_name}",
            "tags.key=val",
            f"description={description}",
            cwd=f"{RUNS_DIR}",
        )
        assert display_name in run.display_name
        assert run.tags == {"key": "val"}
        assert run.description == description

    def test_pf_flow_test(self):
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--inputs",
            "url=https://www.youtube.com/watch?v=o5ZQyXaAv1g",
            "answer=Channel",
            "evidence=Url",
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / "flow.output.json"
        assert output_path.exists()
        log_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / "flow.log"
        with open(log_path, "r") as f:
            previous_log_content = f.read()

        # Test without input
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / "flow.output.json"
        assert output_path.exists()
        log_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / "flow.log"
        with open(log_path, "r") as f:
            log_content = f.read()
        assert previous_log_content not in log_content

    def test_pf_flow_test_with_non_english_input_output(self, capsys):
        question = "什么是 chat gpt"
        run_pf_command("flow", "test", "--flow", f"{FLOWS_DIR}/chat_flow", "--inputs", f'question="{question}"')
        stdout, _ = capsys.readouterr()
        output_path = Path(FLOWS_DIR) / "chat_flow" / ".promptflow" / "flow.output.json"
        assert output_path.exists()
        with open(output_path, "r", encoding="utf-8") as f:
            outputs = json.load(f)
            assert outputs["answer"] in json.loads(stdout)["answer"]

        detail_path = Path(FLOWS_DIR) / "chat_flow" / ".promptflow" / "flow.detail.json"
        assert detail_path.exists()
        with open(detail_path, "r", encoding="utf-8") as f:
            detail = json.load(f)
            assert detail["flow_runs"][0]["inputs"]["question"] == question
            assert detail["flow_runs"][0]["output"]["answer"] == outputs["answer"]

    def test_pf_flow_with_variant(self, capsys):
        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copytree((Path(FLOWS_DIR) / "web_classification").resolve().as_posix(), temp_dir, dirs_exist_ok=True)

            with open(Path(temp_dir) / "flow.dag.yaml", "r") as f:
                flow_dict = yaml.safe_load(f)

            node_name = "summarize_text_content"
            node = next(filter(lambda item: item["name"] == node_name, flow_dict["nodes"]))
            flow_dict["nodes"].remove(node)
            flow_dict["nodes"].append({"name": node_name, "use_variants": True})
            with open(Path(temp_dir) / "flow.dag.yaml", "w") as f:
                yaml.safe_dump(flow_dict, f)

            run_pf_command(
                "flow",
                "test",
                "--flow",
                temp_dir,
                "--inputs",
                "url=https://www.youtube.com/watch?v=o5ZQyXaAv1g",
                "answer=Channel",
                "evidence=Url",
            )
            output_path = Path(temp_dir) / ".promptflow" / "flow.output.json"
            assert output_path.exists()

            run_pf_command(
                "flow",
                "test",
                "--flow",
                temp_dir,
                "--inputs",
                "url=https://www.youtube.com/watch?v=o5ZQyXaAv1g",
                "answer=Channel",
                "evidence=Url",
                "--variant",
                "'${summarize_text_content.variant_1}'",
            )
            output_path = Path(temp_dir) / ".promptflow" / "flow-summarize_text_content-variant_1.output.json"
            assert output_path.exists()

            # Test flow dag with invalid format
            node_name = flow_dict["nodes"][0]["name"]
            flow_dict["nodes"][0]["use_variants"] = True
            flow_dict["node_variants"][node_name] = {
                "default_variant_id": "invalid_variant",
                "variants": [{"variant_0": {}}],
            }
            with open(Path(temp_dir) / "flow.dag.yaml", "w") as f:
                yaml.safe_dump(flow_dict, f)
            with pytest.raises(SystemExit):
                run_pf_command(
                    "flow",
                    "test",
                    "--flow",
                    temp_dir,
                    "--inputs",
                    "url=https://www.youtube.com/watch?v=o5ZQyXaAv1g",
                    "answer=Channel",
                    "evidence=Url",
                    "--variant",
                    "${summarize_text_content.variant_1}",
                )
            outerr = capsys.readouterr()
            assert f"Cannot find the variant invalid_variant for {node_name}." in outerr.out

    def test_pf_flow_test_single_node(self):
        node_name = "fetch_text_content_from_url"
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--inputs",
            "inputs.url="
            "https://www.microsoft.com/en-us/d/xbox-wireless-controller-stellar-shift-special-edition/94fbjc7h0h6h",
            "--node",
            node_name,
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / f"flow-{node_name}.node.detail.json"
        assert output_path.exists()

        node_name = "fetch_text_content_from_url"
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--inputs",
            "url="
            "https://www.microsoft.com/en-us/d/xbox-wireless-controller-stellar-shift-special-edition/94fbjc7h0h6h",
            "--node",
            node_name,
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / f"flow-{node_name}.node.detail.json"
        assert output_path.exists()

        # Test node with node reference input
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--inputs",
            'input_str={"category": "App", "evidence": "URL"}',
            "--node",
            "convert_to_dict",
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / "flow-convert_to_dict.node.detail.json"
        assert output_path.exists()

        # Test without input
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--node",
            node_name,
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / f"flow-{node_name}.node.detail.json"
        assert output_path.exists()

        # Test with input file
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--node",
            node_name,
            "--input",
            f"{FLOWS_DIR}/web_classification/{node_name}_input.jsonl",
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / f"flow-{node_name}.node.detail.json"
        assert output_path.exists()

        # Test with input file
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--node",
            node_name,
            "--inputs",
            f"{FLOWS_DIR}/web_classification/{node_name}_input.jsonl",
        )
        output_path = Path(FLOWS_DIR) / "web_classification" / ".promptflow" / f"flow-{node_name}.node.detail.json"
        assert output_path.exists()

    def test_pf_flow_test_debug_single_node(self):
        node_name = "fetch_text_content_from_url"
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--inputs",
            "inputs.url="
            "https://www.microsoft.com/en-us/d/xbox-wireless-controller-stellar-shift-special-edition/94fbjc7h0h6h",
            "--node",
            node_name,
            "--debug",
        )

        # Debug node with node reference input
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification",
            "--inputs",
            'classify_with_llm.output={"category": "App", "evidence": "URL"}',
            "--node",
            "convert_to_dict",
            "--debug",
        )

    def test_pf_flow_test_with_additional_includes(self):
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification_with_additional_include",
            "--inputs",
            "url=https://www.youtube.com/watch?v=o5ZQyXaAv1g",
            "answer=Channel",
            "evidence=Url",
        )
        output_path = (
            Path(FLOWS_DIR) / "web_classification_with_additional_include" / ".promptflow" / "flow.output.json"
        )
        assert output_path.exists()

        node_name = "fetch_text_content_from_url"
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification_with_additional_include",
            "--inputs",
            "inputs.url="
            "https://www.microsoft.com/en-us/d/xbox-wireless-controller-stellar-shift-special-edition/94fbjc7h0h6h",
            "--node",
            node_name,
        )

    def test_pf_flow_test_with_symbolic(self, prepare_symbolic_flow):
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification_with_symbolic",
            "--inputs",
            "url=https://www.youtube.com/watch?v=o5ZQyXaAv1g",
            "answer=Channel",
            "evidence=Url",
        )
        output_path = Path(FLOWS_DIR) / "web_classification_with_symbolic" / ".promptflow" / "flow.output.json"
        assert output_path.exists()

        node_name = "fetch_text_content_from_url"
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/web_classification_with_symbolic",
            "--inputs",
            "inputs.url="
            "https://www.microsoft.com/en-us/d/xbox-wireless-controller-stellar-shift-special-edition/94fbjc7h0h6h",
            "--node",
            node_name,
        )

    def test_flow_test_with_environment_variable(self, local_client):
        from promptflow._sdk._submitter.utils import SubmitterHelper

        def validate_stdout(detail_path):
            with open(detail_path, "r") as f:
                details = json.load(f)
                assert details["node_runs"][0]["logs"]["stdout"]

        env = {"API_BASE": "${azure_open_ai_connection.api_base}"}
        SubmitterHelper.resolve_environment_variables(env, local_client)
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/print_env_var",
            "--inputs",
            "key=API_BASE",
            "--environment-variables",
            "API_BASE=${azure_open_ai_connection.api_base}",
        )
        with open(Path(FLOWS_DIR) / "print_env_var" / ".promptflow" / "flow.output.json", "r") as f:
            outputs = json.load(f)
        assert outputs["output"] == env["API_BASE"]
        validate_stdout(Path(FLOWS_DIR) / "print_env_var" / ".promptflow" / "flow.detail.json")

        # Test log contains user printed outputs
        log_path = Path(FLOWS_DIR) / "print_env_var" / ".promptflow" / "flow.log"
        with open(log_path, "r") as f:
            log_content = f.read()
        assert env["API_BASE"] in log_content

        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/print_env_var",
            "--inputs",
            "inputs.key=API_BASE",
            "--environment-variables",
            "API_BASE=${azure_open_ai_connection.api_base}",
            "--node",
            "print_env",
        )
        with open(Path(FLOWS_DIR) / "print_env_var" / ".promptflow" / "flow-print_env.node.output.json", "r") as f:
            outputs = json.load(f)
        assert outputs["value"] == env["API_BASE"]
        validate_stdout(Path(FLOWS_DIR) / "print_env_var" / ".promptflow" / "flow-print_env.node.detail.json")

    def _validate_requirement(self, flow_path):
        with open(flow_path) as f:
            flow_dict = yaml.safe_load(f)
        assert flow_dict.get("environment", {}).get("python_requirements_txt", None)
        assert (flow_path.parent / flow_dict["environment"]["python_requirements_txt"]).exists()

    def test_flow_with_exception(self, capsys):
        with pytest.raises(SystemExit):
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/web_classification_with_exception",
            )
        captured = capsys.readouterr()
        assert "Execution failure in 'convert_to_dict': (Exception) mock exception" in captured.out
        output_path = Path(FLOWS_DIR) / "web_classification_with_exception" / ".promptflow" / "flow.detail.json"
        assert output_path.exists()

        with pytest.raises(SystemExit):
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/web_classification_with_exception",
                "--inputs",
                'classify_with_llm.output={"category": "App", "evidence": "URL"}',
                "--node",
                "convert_to_dict",
            )
        captured = capsys.readouterr()
        assert "convert_to_dict.py" in captured.out
        assert "mock exception" in captured.out
        output_path = (
            Path(FLOWS_DIR)
            / "web_classification_with_exception"
            / ".promptflow"
            / "flow-convert_to_dict.node.detail.json"
        )
        assert output_path.exists()

    def test_init_eval_flow(self):
        temp_dir = mkdtemp()
        with _change_working_dir(temp_dir):
            flow_name = "eval_flow"
            # Init standard flow
            run_pf_command(
                "flow",
                "init",
                "--flow",
                flow_name,
                "--type",
                "evaluation",
            )
            ignore_file_path = Path(temp_dir) / flow_name / ".gitignore"
            assert ignore_file_path.exists()
            ignore_file_path.unlink()
            # TODO remove variant_id & line_number in evaluate template
            run_pf_command("flow", "test", "--flow", flow_name, "--inputs", "groundtruth=App", "prediction=App")
            self._validate_requirement(Path(temp_dir) / flow_name / "flow.dag.yaml")

    def test_init_chat_flow(self):
        temp_dir = mkdtemp()
        with _change_working_dir(temp_dir):
            flow_name = "chat_flow"
            # Init standard flow
            run_pf_command(
                "flow",
                "init",
                "--flow",
                flow_name,
                "--type",
                "chat",
            )
            ignore_file_path = Path(temp_dir) / flow_name / ".gitignore"
            assert ignore_file_path.exists()
            ignore_file_path.unlink()

            # Only azure openai connection in test env
            with open(Path(temp_dir) / flow_name / "flow.dag.yaml", "r") as f:
                flow_dict = yaml.safe_load(f)
            flow_dict["nodes"][0]["provider"] = "AzureOpenAI"
            flow_dict["nodes"][0]["connection"] = "azure_open_ai_connection"
            with open(Path(temp_dir) / flow_name / "flow.dag.yaml", "w") as f:
                yaml.dump(flow_dict, f)

            run_pf_command("flow", "test", "--flow", flow_name, "--inputs", "question=hi")
            self._validate_requirement(Path(temp_dir) / flow_name / "flow.dag.yaml")

    def test_flow_init(self, capsys):
        temp_dir = mkdtemp()
        with _change_working_dir(temp_dir):
            flow_name = "standard_flow"
            # Init standard flow
            run_pf_command(
                "flow",
                "init",
                "--flow",
                flow_name,
                "--type",
                "standard",
            )
            self._validate_requirement(Path(temp_dir) / flow_name / "flow.dag.yaml")
            ignore_file_path = Path(temp_dir) / flow_name / ".gitignore"
            requirements_file_path = Path(temp_dir) / flow_name / "requirements.txt"
            assert ignore_file_path.exists()
            assert requirements_file_path.exists()
            ignore_file_path.unlink()
            run_pf_command("flow", "test", "--flow", flow_name, "--inputs", "text=value")

            jinja_name = "input1"
            run_pf_command(
                "flow",
                "init",
                "--flow",
                flow_name,
                "--entry",
                "hello.py",
                "--function",
                "my_python_tool",
                "--prompt-template",
                f"{jinja_name}=hello.jinja2",
            )
            self._validate_requirement(Path(temp_dir) / flow_name / "flow.dag.yaml")
            assert ignore_file_path.exists()
            assert requirements_file_path.exists()
            with open(Path(temp_dir) / flow_name / ".promptflow" / "flow.tools.json", "r") as f:
                tools_dict = json.load(f)["code"]
                assert jinja_name in tools_dict
                assert len(tools_dict[jinja_name]["inputs"]) == 1
                assert tools_dict[jinja_name]["inputs"]["text"]["type"] == ["string"]
                assert tools_dict[jinja_name]["source"] == "hello.jinja2"

            # Test prompt-template doesn't exist
            run_pf_command(
                "flow",
                "init",
                "--flow",
                flow_name,
                "--entry",
                "hello.py",
                "--function",
                "my_python_tool",
                "--prompt-template",
                f"{jinja_name}={jinja_name}.jinja2",
            )
            self._validate_requirement(Path(temp_dir) / flow_name / "flow.dag.yaml")
            assert (Path(temp_dir) / flow_name / f"{jinja_name}.jinja2").exists()

            # Test template name doesn't exist in python function
            jinja_name = "mock_jinja"
            with pytest.raises(ValueError) as ex:
                run_pf_command(
                    "flow",
                    "init",
                    "--flow",
                    flow_name,
                    "--entry",
                    "hello.py",
                    "--function",
                    "my_python_tool",
                    "--prompt-template",
                    f"{jinja_name}={jinja_name}.jinja2",
                )
            assert f"Template parameter {jinja_name} doesn't find in python function arguments." in str(ex.value)

            with pytest.raises(SystemExit):
                run_pf_command("flow", "init")
            _, err = capsys.readouterr()
            assert "pf flow init: error: the following arguments are required: --flow" in err

    def test_flow_init_intent_copilot(self):
        flow_path = os.path.join(FLOWS_DIR, "intent-copilot")
        run_pf_command(
            "flow",
            "init",
            "--flow",
            flow_path,
            "--entry",
            "intent.py",
            "--function",
            "extract_intent",
            "--prompt-template",
            "chat_prompt=user_intent_zero_shot.jinja2",
        )
        with open(Path(flow_path) / "flow.dag.yaml", "r") as f:
            flow_dict = yaml.safe_load(f)
            assert "chat_history" in flow_dict["inputs"]
            assert "customer_info" in flow_dict["inputs"]
            chat_prompt_node = next(filter(lambda item: item["name"] == "chat_prompt", flow_dict["nodes"]))
            assert "chat_history" in chat_prompt_node["inputs"]
            assert "customer_info" in chat_prompt_node["inputs"]

    def test_flow_init_with_connection_and_deployment(self):
        def check_connection_and_deployment(flow_folder, connection, deployment):
            with open(Path(flow_folder) / "flow.dag.yaml", "r") as f:
                flow_dict = yaml.safe_load(f)
                assert flow_dict["nodes"][0]["inputs"]["deployment_name"] == deployment
                assert flow_dict["nodes"][0]["connection"] == connection

        temp_dir = mkdtemp()
        with _change_working_dir(temp_dir):
            flow_name = "chat_flow"
            flow_folder = Path(temp_dir) / flow_name
            # When configure local connection provider, init chat flow without connection and deployment.
            run_pf_command(
                "flow",
                "init",
                "--flow",
                flow_name,
                "--type",
                "chat",
            )
            # Assert connection files created
            assert (flow_folder / "azure_openai.yaml").exists()
            assert (flow_folder / "openai.yaml").exists()

            # When configure local connection provider, init chat flow with connection and deployment.
            connection = "connection_name"
            deployment = "deployment_name"
            run_pf_command(
                "flow",
                "init",
                "--flow",
                flow_name,
                "--type",
                "chat",
                "--connection",
                connection,
                "--deployment",
                deployment,
                "--yes",
            )
            # Assert connection files created and the connection/deployment is set in flow.dag.yaml
            check_connection_and_deployment(flow_folder, connection=connection, deployment=deployment)
            connection_files = [flow_folder / "azure_openai.yaml", flow_folder / "openai.yaml"]
            for file in connection_files:
                assert file.exists()
                with open(file, "r") as f:
                    connection_dict = yaml.safe_load(f)
                    assert connection_dict["name"] == connection

            shutil.rmtree(flow_folder)
            target = "promptflow._sdk._pf_client.Configuration.get_connection_provider"
            with mock.patch(target) as mocked:
                mocked.return_value = "azureml:xx"
                # When configure azure connection provider, init chat flow without connection and deployment.
                run_pf_command(
                    "flow",
                    "init",
                    "--flow",
                    flow_name,
                    "--type",
                    "chat",
                    "--yes",
                )
                # Assert connection files not created.
                assert not (flow_folder / "azure_openai.yaml").exists()
                assert not (flow_folder / "openai.yaml").exists()

                # When configure azure connection provider, init chat flow with connection and deployment.
                connection = "connection_name"
                deployment = "deployment_name"
                run_pf_command(
                    "flow",
                    "init",
                    "--flow",
                    flow_name,
                    "--type",
                    "chat",
                    "--connection",
                    connection,
                    "--deployment",
                    deployment,
                    "--yes",
                )
                # Assert connection files not created and the connection/deployment is set in flow.dag.yaml
                check_connection_and_deployment(flow_folder, connection=connection, deployment=deployment)
                assert not (flow_folder / "azure_openai.yaml").exists()
                assert not (flow_folder / "openai.yaml").exists()

    def test_flow_chat(self, monkeypatch, capsys):
        chat_list = ["hi", "what is chat gpt?"]

        def mock_input(*args, **kwargs):
            if chat_list:
                return chat_list.pop()
            else:
                raise KeyboardInterrupt()

        monkeypatch.setattr("builtins.input", mock_input)
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/chat_flow",
            "--interactive",
        )
        output_path = Path(FLOWS_DIR) / "chat_flow" / ".promptflow" / "chat.output.json"
        assert output_path.exists()
        detail_path = Path(FLOWS_DIR) / "chat_flow" / ".promptflow" / "chat.detail.json"
        assert detail_path.exists()

        # Test streaming output
        chat_list = ["hi", "what is chat gpt?"]
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/chat_flow_with_stream_output",
            "--interactive",
        )
        output_path = Path(FLOWS_DIR) / "chat_flow_with_stream_output" / ".promptflow" / "chat.output.json"
        assert output_path.exists()
        detail_path = Path(FLOWS_DIR) / "chat_flow_with_stream_output" / ".promptflow" / "chat.detail.json"
        assert detail_path.exists()

        chat_list = ["hi", "what is chat gpt?"]
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/chat_flow_with_python_node_streaming_output",
            "--interactive",
        )
        output_path = Path(FLOWS_DIR) / "chat_flow_with_stream_output" / ".promptflow" / "chat.output.json"
        assert output_path.exists()
        detail_path = Path(FLOWS_DIR) / "chat_flow_with_stream_output" / ".promptflow" / "chat.detail.json"
        assert detail_path.exists()

        # Validate terminal output
        chat_list = ["hi", "what is chat gpt?"]
        run_pf_command("flow", "test", "--flow", f"{FLOWS_DIR}/chat_flow", "--interactive", "--verbose")
        outerr = capsys.readouterr()
        # Check node output
        assert "chat_node:" in outerr.out
        assert "show_answer:" in outerr.out
        assert "[show_answer]: print:" in outerr.out

        chat_list = ["hi", "what is chat gpt?"]
        with pytest.raises(SystemExit):
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/chat_flow_with_exception",
                "--interactive",
            )
        outerr = capsys.readouterr()
        assert "Execution failure in 'show_answer': (Exception) mock exception" in outerr.out
        output_path = Path(FLOWS_DIR) / "chat_flow" / ".promptflow" / "chat.output.json"
        assert output_path.exists()
        detail_path = Path(FLOWS_DIR) / "chat_flow" / ".promptflow" / "chat.detail.json"
        assert detail_path.exists()

        with pytest.raises(SystemExit):
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/chat_flow_with_multi_output_invalid",
                "--interactive",
            )
        outerr = capsys.readouterr()
        assert "chat flow does not support multiple chat outputs" in outerr.out

    def test_flow_test_with_default_chat_history(self):
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/chat_flow_with_default_history",
        )
        output_path = Path(FLOWS_DIR) / "chat_flow_with_default_history" / ".promptflow" / "flow.output.json"
        assert output_path.exists()
        detail_path = Path(FLOWS_DIR) / "chat_flow_with_default_history" / ".promptflow" / "flow.detail.json"
        assert detail_path.exists()
        with open(detail_path, "r") as f:
            details = json.load(f)
        expect_chat_history = [
            {"inputs": {"question": "hi"}, "outputs": {"answer": "hi"}},
            {"inputs": {"question": "who are you"}, "outputs": {"answer": "who are you"}},
        ]
        assert details["flow_runs"][0]["inputs"]["chat_history"] == expect_chat_history

    def test_flow_test_with_user_defined_chat_history(self, monkeypatch, capsys):
        chat_list = ["hi", "what is chat gpt?"]

        def mock_input(*args, **kwargs):
            if chat_list:
                return chat_list.pop()
            else:
                raise KeyboardInterrupt()

        monkeypatch.setattr("builtins.input", mock_input)
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/chat_flow_with_defined_chat_history",
            "--interactive",
        )
        output_path = Path(FLOWS_DIR) / "chat_flow_with_defined_chat_history" / ".promptflow" / "chat.output.json"
        assert output_path.exists()
        detail_path = Path(FLOWS_DIR) / "chat_flow_with_defined_chat_history" / ".promptflow" / "chat.detail.json"
        assert detail_path.exists()

        # Test is_chat_history is set False
        with pytest.raises(SystemExit):
            chat_list = ["hi", "what is chat gpt?"]
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/chat_flow_without_defined_chat_history",
                "--interactive",
            )
        outerr = capsys.readouterr()
        assert "chat_history is required in the inputs of chat flow" in outerr.out

    def test_flow_test_inputs(self, capsys, caplog):
        # Flow test missing required inputs
        with pytest.raises(SystemExit):
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/print_env_var",
                "--environment-variables",
                "API_BASE=${azure_open_ai_connection.api_base}",
            )
        stdout, _ = capsys.readouterr()
        assert "Required input(s) ['key'] are missing for \"flow\"." in stdout

        # Node test missing required inputs
        with pytest.raises(SystemExit):
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/print_env_var",
                "--node",
                "print_env",
                "--environment-variables",
                "API_BASE=${azure_open_ai_connection.api_base}",
            )
        stdout, _ = capsys.readouterr()
        assert "Required input(s) ['key'] are missing for \"print_env\"" in stdout

        # Flow test with unknown inputs
        logger = logging.getLogger(LOGGER_NAME)
        logger.propagate = True

        def validate_log(log_msg, prefix, expect_dict):
            log_inputs = json.loads(log_msg[len(prefix) :].replace("'", '"'))
            assert prefix in log_msg
            assert expect_dict == log_inputs

        with caplog.at_level(level=logging.INFO, logger=LOGGER_NAME):
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/web_classification",
                "--inputs",
                "url=https://www.youtube.com/watch?v=o5ZQyXaAv1g",
                "answer=Channel",
                "evidence=Url",
            )
            unknown_input_log = caplog.records[0]
            expect_inputs = {"answer": "Channel", "evidence": "Url"}
            validate_log(
                prefix="Unknown input(s) of flow: ", log_msg=unknown_input_log.message, expect_dict=expect_inputs
            )

            flow_input_log = caplog.records[1]
            expect_inputs = {
                "url": "https://www.youtube.com/watch?v=o5ZQyXaAv1g",
                "answer": "Channel",
                "evidence": "Url",
            }
            validate_log(prefix="flow input(s): ", log_msg=flow_input_log.message, expect_dict=expect_inputs)

            # Node test with unknown inputs
            run_pf_command(
                "flow",
                "test",
                "--flow",
                f"{FLOWS_DIR}/web_classification",
                "--inputs",
                "inputs.url="
                "https://www.microsoft.com/en-us/d/xbox-wireless-controller-stellar-shift-special-edition/94fbjc7h0h6h",
                "unknown_input=unknown_val",
                "--node",
                "fetch_text_content_from_url",
            )
            unknown_input_log = caplog.records[3]
            expect_inputs = {"unknown_input": "unknown_val"}
            validate_log(
                prefix="Unknown input(s) of fetch_text_content_from_url: ",
                log_msg=unknown_input_log.message,
                expect_dict=expect_inputs,
            )

            node_input_log = caplog.records[4]
            expect_inputs = {
                "fetch_url": "https://www.microsoft.com/en-us/d/"
                "xbox-wireless-controller-stellar-shift-special-edition/94fbjc7h0h6h",
                "unknown_input": "unknown_val",
            }
            validate_log(
                prefix="fetch_text_content_from_url input(s): ",
                log_msg=node_input_log.message,
                expect_dict=expect_inputs,
            )

    def test_flow_build(self):
        source = f"{FLOWS_DIR}/web_classification_with_additional_include/flow.dag.yaml"

        def get_node_settings(_flow_dag_path: Path):
            flow_dag = yaml.safe_load(_flow_dag_path.read_text())
            target_node = next(filter(lambda x: x["name"] == "summarize_text_content", flow_dag["nodes"]))
            target_node.pop("name")
            return target_node

        with tempfile.TemporaryDirectory() as temp_dir:
            run_pf_command(
                "flow",
                "build",
                "--source",
                source,
                "--output",
                temp_dir,
                "--format",
                "docker",
                "--variant",
                "${summarize_text_content.variant_0}",
            )

            new_flow_dag_path = Path(temp_dir, "flow", "flow.dag.yaml")
            flow_dag = yaml.safe_load(Path(source).read_text())
            assert (
                get_node_settings(new_flow_dag_path)
                == flow_dag["node_variants"]["summarize_text_content"]["variants"]["variant_0"]["node"]
            )
            assert get_node_settings(Path(source)) != get_node_settings(new_flow_dag_path)

    @pytest.mark.parametrize(
        "file_name, expected, update_item",
        [
            (
                "azure_openai_connection.yaml",
                {
                    "module": "promptflow.connections",
                    "type": "azure_open_ai",
                    "api_type": "azure",
                    "api_version": "2023-07-01-preview",
                    "api_key": SCRUBBED_VALUE,
                    "api_base": "aoai-api-endpoint",
                },
                ("api_base", "new_value"),
            ),
            (
                "custom_connection.yaml",
                {
                    "module": "promptflow.connections",
                    "type": "custom",
                    "configs": {"key1": "test1"},
                    "secrets": {"key2": SCRUBBED_VALUE},
                },
                ("configs.key1", "new_value"),
            ),
            (
                "custom_strong_type_connection.yaml",
                {
                    "module": "promptflow.connections",
                    "type": "custom",
                    "configs": {
                        "api_base": "This is my first connection.",
                        "promptflow.connection.custom_type": "MyFirstConnection",
                        "promptflow.connection.module": "my_tool_package.connections",
                        "promptflow.connection.package": "test-custom-tools",
                        "promptflow.connection.package_version": "0.0.2",
                    },
                    "secrets": {"api_key": SCRUBBED_VALUE},
                },
                ("configs.api_base", "new_value"),
            ),
        ],
    )
    def test_connection_create_update(
        self, install_custom_tool_pkg, file_name, expected, update_item, capfd, local_client
    ):
        name = f"Connection_{str(uuid.uuid4())[:4]}"
        run_pf_command("connection", "create", "--file", f"{CONNECTIONS_DIR}/{file_name}", "--name", f"{name}")
        out, err = capfd.readouterr()
        # Assert in to skip some datetime fields
        assert expected.items() <= json.loads(out).items()

        # Update with --set
        update_key, update_value = update_item
        run_pf_command("connection", "update", "--set", f"{update_key}={update_value}", "--name", f"{name}")
        out, _ = capfd.readouterr()
        assert update_value in out, f"expected updated value {update_value} not in {out}"
        connection = local_client.connections.get(name)
        # Assert secrets are not scrubbed
        assert not any(v == SCRUBBED_VALUE for v in connection._secrets.values())

    def test_input_with_dict_val(self, pf):
        run_id = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--file",
            "./input_with_dict_val.yaml",
            "--name",
            run_id,
            cwd=f"{RUNS_DIR}",
        )
        outputs = pf.runs._get_outputs(run=run_id)
        assert "dict" in outputs["output"][0]

    def test_visualize_ignore_space(self) -> None:
        names = ["a,b,c,d", "a, b, c, d", "a, b , c,  d"]
        groundtruth = ["a", "b", "c", "d"]

        def mocked_visualize(*args, **kwargs):
            runs = args[0]
            assert runs == groundtruth

        with patch.object(RunOperations, "visualize") as mock_visualize:
            mock_visualize.side_effect = mocked_visualize
            for name in names:
                run_pf_command(
                    "run",
                    "visualize",
                    "--names",
                    name,
                )

    def test_pf_run_with_stream_log(self, capfd):
        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/flow_with_user_output",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--column-mapping",
            "key=value",
            "extra=${data.url}",
            "--stream",
        )
        out, _ = capfd.readouterr()
        # For Batch run, the executor uses bulk logger to print logs, and only prints the error log of the nodes.
        existing_keywords = ["execution", "execution.bulk", "WARNING", "error log"]
        non_existing_keywords = ["execution.flow", "user log"]
        for keyword in existing_keywords:
            assert keyword in out
        for keyword in non_existing_keywords:
            assert keyword not in out

    def test_pf_run_no_stream_log(self, capfd):

        # without --stream, logs will be in the run's log file

        run_pf_command(
            "run",
            "create",
            "--flow",
            f"{FLOWS_DIR}/flow_with_user_output",
            "--data",
            f"{DATAS_DIR}/webClassification3.jsonl",
            "--column-mapping",
            "key=value",
            "extra=${data.url}",
        )
        out, _ = capfd.readouterr()
        assert "user log" not in out
        assert "error log" not in out
        # flow logs won't stream
        assert "Executing node print_val. node run id:" not in out
        # executor logs won't stream
        assert "Node print_val completes." not in out

    def test_format_cli_exception(self, capsys):
        from promptflow._sdk.operations._connection_operations import ConnectionOperations

        with patch.dict(os.environ, {"PROMPTFLOW_STRUCTURE_EXCEPTION_OUTPUT": "true"}):
            with pytest.raises(SystemExit):
                run_pf_command(
                    "connection",
                    "show",
                    "--name",
                    "invalid_connection_name",
                )
            outerr = capsys.readouterr()
            assert outerr.err
            error_msg = json.loads(outerr.err)
            assert error_msg["code"] == "ConnectionNotFoundError"

            def mocked_connection_get(*args, **kwargs):
                raise Exception("mock exception")

            with patch.object(ConnectionOperations, "get") as mock_connection_get:
                mock_connection_get.side_effect = mocked_connection_get
                with pytest.raises(Exception):
                    run_pf_command(
                        "connection",
                        "show",
                        "--name",
                        "invalid_connection_name",
                    )
                outerr = capsys.readouterr()
                assert outerr.err
                error_msg = json.loads(outerr.err)
                assert error_msg["code"] == "SystemError"

        with pytest.raises(SystemExit):
            run_pf_command(
                "connection",
                "show",
                "--name",
                "invalid_connection_name",
            )
        outerr = capsys.readouterr()
        assert not outerr.err

    def test_tool_init(self, capsys):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_name = "package_name"
            func_name = "func_name"
            run_pf_command("tool", "init", "--package", package_name, "--tool", func_name, cwd=temp_dir)
            package_folder = Path(temp_dir) / package_name
            assert (package_folder / package_name / f"{func_name}.py").exists()
            assert (package_folder / package_name / "utils.py").exists()
            assert (package_folder / package_name / "__init__.py").exists()
            assert (package_folder / "setup.py").exists()
            assert (package_folder / "README.md").exists()

            spec = importlib.util.spec_from_file_location(
                f"{package_name}.utils", package_folder / package_name / "utils.py"
            )
            utils = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(utils)

            assert hasattr(utils, "list_package_tools")
            tools_meta = utils.list_package_tools()
            assert f"{package_name}.{func_name}.{func_name}" in tools_meta
            meta = tools_meta[f"{package_name}.{func_name}.{func_name}"]
            assert meta["function"] == func_name
            assert meta["module"] == f"{package_name}.{func_name}"
            assert meta["name"] == func_name
            assert meta["description"] == f"This is {func_name} tool"
            assert meta["type"] == "python"

            # Invalid package/tool name
            invalid_package_name = "123-package-name"
            invalid_tool_name = "123_tool_name"
            with pytest.raises(SystemExit):
                run_pf_command("tool", "init", "--package", invalid_package_name, "--tool", func_name, cwd=temp_dir)
            outerr = capsys.readouterr()
            assert f"The package name {invalid_package_name} is a invalid identifier." in outerr.out
            with pytest.raises(SystemExit):
                run_pf_command("tool", "init", "--package", package_name, "--tool", invalid_tool_name, cwd=temp_dir)
            outerr = capsys.readouterr()
            assert f"The tool name {invalid_tool_name} is a invalid identifier." in outerr.out
            with pytest.raises(SystemExit):
                run_pf_command("tool", "init", "--tool", invalid_tool_name, cwd=temp_dir)
            outerr = capsys.readouterr()
            assert f"The tool name {invalid_tool_name} is a invalid identifier." in outerr.out

            # Test init package tool with extra info
            package_name = "tool_with_extra_info"
            package_folder = Path(temp_dir) / package_name
            icon_path = Path(DATAS_DIR) / "logo.jpg"
            category = "test_category"
            tags = {"tag1": "value1", "tag2": "value2"}
            run_pf_command(
                "tool",
                "init",
                "--package",
                package_name,
                "--tool",
                func_name,
                "--set",
                f"icon={icon_path.absolute()}",
                f"category={category}",
                f"tags={tags}",
                cwd=temp_dir,
            )
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.utils", package_folder / package_name / "utils.py"
            )
            utils = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(utils)

            assert hasattr(utils, "list_package_tools")
            tools_meta = utils.list_package_tools()
            meta = tools_meta[f"{package_name}.{func_name}.{func_name}"]
            assert meta["category"] == category
            assert meta["tags"] == tags
            assert meta["icon"].startswith("data:image")

            # icon doesn't exist
            with pytest.raises(SystemExit):
                run_pf_command(
                    "tool",
                    "init",
                    "--package",
                    package_name,
                    "--tool",
                    func_name,
                    "--set",
                    "icon=invalid_icon_path",
                    cwd=temp_dir,
                )
            outerr = capsys.readouterr()
            assert "Cannot find the icon path" in outerr.out

    def test_tool_list(self, capsys):
        # List package tools in environment
        run_pf_command("tool", "list")
        outerr = capsys.readouterr()
        tools_dict = json.loads(outerr.out)
        package_tool_name = "promptflow.tools.embedding.embedding"
        assert package_tool_name in tools_dict["package"]

        # List flow tools and package tools
        run_pf_command("tool", "list", "--flow", f"{FLOWS_DIR}/chat_flow")
        outerr = capsys.readouterr()
        tools_dict = json.loads(outerr.out)
        expect_flow_tools = {
            "chat.jinja2": {
                "type": "llm",
                "inputs": {"chat_history": {"type": ["string"]}, "question": {"type": ["string"]}},
                "source": "chat.jinja2",
            },
            "show_answer.py": {
                "type": "python",
                "inputs": {"chat_answer": {"type": ["string"]}},
                "source": "show_answer.py",
                "function": "show_answer",
            },
        }
        assert tools_dict["code"] == expect_flow_tools
        assert package_tool_name in tools_dict["package"]

        # Invalid flow parameter
        with pytest.raises(SystemExit):
            run_pf_command("tool", "list", "--flow", "invalid_flow_folder")
        outerr = capsys.readouterr()
        assert "invalid_flow_folder does not exist" in outerr.out

    def test_flow_test_with_image_input_and_output(self):
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/python_tool_with_simple_image",
        )
        output_path = Path(FLOWS_DIR) / "python_tool_with_simple_image" / ".promptflow" / "output"
        assert output_path.exists()
        image_path = Path(FLOWS_DIR) / "python_tool_with_simple_image" / ".promptflow" / "intermediate"
        assert image_path.exists()

    def test_flow_test_with_composite_image(self):
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/python_tool_with_composite_image",
        )
        output_path = Path(FLOWS_DIR) / "python_tool_with_composite_image" / ".promptflow" / "output"
        assert output_path.exists()
        image_path = Path(FLOWS_DIR) / "python_tool_with_composite_image" / ".promptflow" / "intermediate"
        assert image_path.exists()

    def test_run_file_with_set(self, pf) -> None:
        name = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--file",
            f"{RUNS_DIR}/run_with_env.yaml",
            "--set",
            f"name={name}",
        )
        # run exists
        pf.runs.get(name=name)

    def test_run_file_with_set_priority(self, pf) -> None:
        # --name has higher priority than --set
        name1 = str(uuid.uuid4())
        name2 = str(uuid.uuid4())
        run_pf_command(
            "run",
            "create",
            "--file",
            f"{RUNS_DIR}/run_with_env.yaml",
            "--set",
            f"name={name1}",
            "--name",
            name2,
        )
        # run exists
        try:
            pf.runs.get(name=name1)
        except RunNotFoundError:
            pass
        pf.runs.get(name=name2)

    def test_data_scrubbing(self):
        # Prepare connection
        run_pf_command(
            "connection", "create", "--file", f"{CONNECTIONS_DIR}/custom_connection.yaml", "--name", "custom_connection"
        )

        # Test flow run
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/print_secret_flow",
        )
        output_path = Path(FLOWS_DIR) / "print_secret_flow" / ".promptflow" / "flow.output.json"
        assert output_path.exists()
        log_path = Path(FLOWS_DIR) / "print_secret_flow" / ".promptflow" / "flow.log"
        with open(log_path, "r") as f:
            log_content = f.read()
            assert "**data_scrubbed**" in log_content

        # Test node run
        run_pf_command(
            "flow",
            "test",
            "--flow",
            f"{FLOWS_DIR}/print_secret_flow",
            "--node",
            "print_secret",
            "--inputs",
            "conn=custom_connection",
            "inputs.topic=atom",
        )
        output_path = Path(FLOWS_DIR) / "print_secret_flow" / ".promptflow" / "flow-print_secret.node.detail.json"
        assert output_path.exists()
        log_path = Path(FLOWS_DIR) / "print_secret_flow" / ".promptflow" / "print_secret.node.log"
        with open(log_path, "r") as f:
            log_content = f.read()
        assert "**data_scrubbed**" in log_content

    def test_config_set_pure_flow_directory_macro(self, capfd: pytest.CaptureFixture) -> None:
        run_pf_command(
            "config",
            "set",
            "run.output_path='${flow_directory}'",
        )
        out, _ = capfd.readouterr()
        expected_error_message = (
            "Invalid config value '${flow_directory}' for 'run.output_path': "
            "Cannot specify flow directory as run output path; "
            "if you want to specify run output path under flow directory, "
            "please use its child folder, e.g. '${flow_directory}/.runs'."
        )
        assert expected_error_message in out

        from promptflow._sdk._configuration import Configuration

        config = Configuration.get_instance()
        assert config.get_run_output_path() is None
