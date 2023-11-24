# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import copy
import datetime
import json
import logging
import shutil
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, NewType, Optional, Tuple, Union

import yaml
from filelock import FileLock

from promptflow._sdk._constants import (
    DEFAULT_ENCODING,
    HOME_PROMPT_FLOW_DIR,
    LINE_NUMBER,
    LOCAL_STORAGE_BATCH_SIZE,
    LOGGER_NAME,
    PROMPT_FLOW_DIR_NAME,
    LocalStorageFilenames,
)
from promptflow._sdk._errors import BulkRunException
from promptflow._sdk._utils import PromptflowIgnoreFile, generate_flow_tools_json
from promptflow._sdk.entities import Run
from promptflow._sdk.entities._flow import Flow
from promptflow._utils.dataclass_serializer import serialize
from promptflow._utils.exception_utils import PromptflowExceptionPresenter
from promptflow._utils.logger_utils import LogContext
from promptflow._utils.multimedia_utils import get_file_reference_encoder
from promptflow.batch._result import BatchResult
from promptflow.contracts.multimedia import Image
from promptflow.contracts.run_info import FlowRunInfo
from promptflow.contracts.run_info import RunInfo as NodeRunInfo
from promptflow.contracts.run_info import Status
from promptflow.contracts.run_mode import RunMode
from promptflow.exceptions import UserErrorException
from promptflow.storage import AbstractRunStorage

logger = logging.getLogger(LOGGER_NAME)

RunInputs = NewType("RunInputs", Dict[str, List[Any]])
RunOutputs = NewType("RunOutputs", Dict[str, List[Any]])
RunMetrics = NewType("RunMetrics", Dict[str, Any])


@dataclass
class LoggerOperations(LogContext):
    stream: bool = False

    @property
    def log_path(self) -> str:
        return str(self.file_path)

    def get_logs(self) -> str:
        with open(self.file_path, mode="r", encoding=DEFAULT_ENCODING) as f:
            return f.read()

    def _get_execute_loggers_list(cls) -> List[logging.Logger]:
        result = super()._get_execute_loggers_list()
        result.append(logger)
        return result

    def get_initializer(self):
        return partial(
            LoggerOperations,
            file_path=self.file_path,
            run_mode=self.run_mode,
            credential_list=self.credential_list,
            stream=self.stream,
        )

    def __enter__(self):
        log_path = Path(self.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.run_mode == RunMode.Batch:
            log_path.touch(exist_ok=True)
        else:
            if log_path.exists():
                # for non batch run, clean up previous log content
                try:
                    with open(log_path, mode="w", encoding=DEFAULT_ENCODING) as file:
                        file.truncate(0)
                except Exception as e:
                    logger.warning(f"Failed to clean up the previous log content because {e}")
            else:
                log_path.touch()

        for _logger in self._get_execute_loggers_list():
            for handler in _logger.handlers:
                if self.stream is False and isinstance(handler, logging.StreamHandler):
                    handler.setLevel(logging.CRITICAL)
        super().__enter__()

    def __exit__(self, *args):
        super().__exit__(*args)

        for _logger in self._get_execute_loggers_list():
            for handler in _logger.handlers:
                if self.stream is False and isinstance(handler, logging.StreamHandler):
                    handler.setLevel(logging.CRITICAL)


@dataclass
class NodeRunRecord:
    NodeName: str
    line_number: int
    run_info: str
    start_time: datetime
    end_time: datetime
    status: str

    @staticmethod
    def from_run_info(node_run_info: NodeRunInfo) -> "NodeRunRecord":
        return NodeRunRecord(
            NodeName=node_run_info.node,
            line_number=node_run_info.index,
            run_info=serialize(node_run_info),
            start_time=node_run_info.start_time.isoformat(),
            end_time=node_run_info.end_time.isoformat(),
            status=node_run_info.status.value,
        )

    def dump(self, path: Path, run_name: str) -> None:
        # for nodes in first line run and all reduce nodes, the target filename is 000000000.jsonl
        # so we need to handle concurrent write with file lock
        filename_need_lock = "0".zfill(LocalStorageOperations.LINE_NUMBER_WIDTH) + ".jsonl"
        if path.name == filename_need_lock:
            file_lock_path = (HOME_PROMPT_FLOW_DIR / f"{run_name}.{self.NodeName}.lock").resolve()
            lock = FileLock(file_lock_path)
            lock.acquire()
            try:
                with open(path, mode="w", encoding=DEFAULT_ENCODING) as f:
                    json.dump(asdict(self), f, ensure_ascii=False)
            finally:
                lock.release()
        else:
            # for normal nodes in other line runs, directly write
            with open(path, mode="w", encoding=DEFAULT_ENCODING) as f:
                json.dump(asdict(self), f, ensure_ascii=False)


@dataclass
class LineRunRecord:
    line_number: int
    run_info: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    name: str
    description: str
    status: str
    tags: str

    @staticmethod
    def from_flow_run_info(flow_run_info: FlowRunInfo) -> "LineRunRecord":
        return LineRunRecord(
            line_number=flow_run_info.index,
            run_info=serialize(flow_run_info),
            start_time=flow_run_info.start_time.isoformat(),
            end_time=flow_run_info.end_time.isoformat(),
            name=flow_run_info.name,
            description=flow_run_info.description,
            status=flow_run_info.status.value,
            tags=flow_run_info.tags,
        )

    def dump(self, path: Path) -> None:
        with open(path, mode="w", encoding=DEFAULT_ENCODING) as f:
            json.dump(asdict(self), f, ensure_ascii=False)


class LocalStorageOperations(AbstractRunStorage):
    """LocalStorageOperations."""

    LINE_NUMBER_WIDTH = 9

    def __init__(self, run: Run, stream=False, run_mode=RunMode.Test):
        self._run = run
        self.path = self._prepare_folder(self._run._output_path)

        self.logger = LoggerOperations(
            file_path=self.path / LocalStorageFilenames.LOG, stream=stream, run_mode=run_mode
        )
        # snapshot
        self._snapshot_folder_path = self._prepare_folder(self.path / LocalStorageFilenames.SNAPSHOT_FOLDER)
        self._dag_path = self._snapshot_folder_path / LocalStorageFilenames.DAG
        self._flow_tools_json_path = (
            self._snapshot_folder_path / PROMPT_FLOW_DIR_NAME / LocalStorageFilenames.FLOW_TOOLS_JSON
        )
        self._inputs_path = self.path / LocalStorageFilenames.INPUTS  # keep this for other usages
        # below inputs and outputs are dumped by SDK
        self._sdk_inputs_path = self._inputs_path
        self._sdk_output_path = self.path / LocalStorageFilenames.OUTPUTS
        # metrics
        self._metrics_path = self.path / LocalStorageFilenames.METRICS
        # legacy files: detail.json and outputs.jsonl(not the one in flow_outputs folder)
        self._detail_path = self.path / LocalStorageFilenames.DETAIL
        self._legacy_outputs_path = self.path / LocalStorageFilenames.OUTPUTS
        # for line run records, store per line
        # for normal node run records, store per node per line;
        # for reduce node run records, store centralized in 000000000.jsonl per node
        self.outputs_folder = self._prepare_folder(self.path / "flow_outputs")
        self._outputs_path = self.outputs_folder / "output.jsonl"  # dumped by executor
        self._node_infos_folder = self._prepare_folder(self.path / "node_artifacts")
        self._run_infos_folder = self._prepare_folder(self.path / "flow_artifacts")
        self._data_path = Path(run.data) if run.data is not None else None

        self._meta_path = self.path / LocalStorageFilenames.META
        self._exception_path = self.path / LocalStorageFilenames.EXCEPTION

        self._dump_meta_file()

    def _dump_meta_file(self) -> None:
        with open(self._meta_path, mode="w", encoding=DEFAULT_ENCODING) as f:
            json.dump({"batch_size": LOCAL_STORAGE_BATCH_SIZE}, f, ensure_ascii=False)

    def dump_snapshot(self, flow: Flow) -> None:
        """Dump flow directory to snapshot folder, input file will be dumped after the run."""
        patterns = [pattern for pattern in PromptflowIgnoreFile.IGNORE_FILE]
        # ignore current output parent folder to avoid potential recursive copy
        patterns.append(self._run._output_path.parent.name)
        shutil.copytree(
            flow.code.as_posix(),
            self._snapshot_folder_path,
            ignore=shutil.ignore_patterns(*patterns),
            dirs_exist_ok=True,
        )
        # replace DAG file with the overwrite one
        self._dag_path.unlink()
        shutil.copy(flow.path, self._dag_path)

    def load_dag_as_string(self) -> str:
        with open(self._dag_path, mode="r", encoding=DEFAULT_ENCODING) as f:
            return f.read()

    def load_flow_tools_json(self) -> dict:
        if not self._flow_tools_json_path.is_file():
            return generate_flow_tools_json(self._snapshot_folder_path, dump=False)
        else:
            with open(self._flow_tools_json_path, mode="r", encoding=DEFAULT_ENCODING) as f:
                return json.load(f)

    def load_io_spec(self) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
        """Load input/output spec from DAG."""
        with open(self._dag_path, mode="r", encoding=DEFAULT_ENCODING) as f:
            flow_dag = yaml.safe_load(f)
        return flow_dag["inputs"], flow_dag["outputs"]

    def load_inputs(self) -> RunInputs:
        import pandas as pd

        with open(self._sdk_inputs_path, mode="r", encoding=DEFAULT_ENCODING) as f:
            df = pd.read_json(f, orient="records", lines=True)
            return df.to_dict("list")

    def load_outputs(self) -> RunOutputs:
        import pandas as pd

        # for legacy run, simply read the output file and return as list of dict
        if not self._outputs_path.is_file():
            with open(self._legacy_outputs_path, mode="r", encoding=DEFAULT_ENCODING) as f:
                df = pd.read_json(f, orient="records", lines=True)
                return df.to_dict("list")

        with open(self._outputs_path, mode="r", encoding=DEFAULT_ENCODING) as f:
            df = pd.read_json(f, orient="records", lines=True)
            if len(df) > 0:
                df = df.set_index(LINE_NUMBER)
            return df.to_dict("list")

    def dump_inputs_and_outputs(self) -> None:
        inputs, outputs = self._collect_io_from_debug_info()
        with open(self._sdk_inputs_path, mode="w", encoding=DEFAULT_ENCODING) as f:
            inputs.to_json(f, orient="records", lines=True, force_ascii=False)
        with open(self._sdk_output_path, mode="w", encoding=DEFAULT_ENCODING) as f:
            outputs.to_json(f, orient="records", lines=True, force_ascii=False)

    def dump_metrics(self, metrics: Optional[RunMetrics]) -> None:
        metrics = metrics or dict()
        with open(self._metrics_path, mode="w", encoding=DEFAULT_ENCODING) as f:
            json.dump(metrics, f, ensure_ascii=False)

    def dump_exception(self, exception: Exception, batch_result: BatchResult) -> None:
        """Dump exception to local storage.

        :param exception: Exception raised during bulk run.
        :param batch_result: Bulk run outputs. If exception not raised, store line run error messages.
        """
        # extract line run errors
        message = ""
        errors = []
        if batch_result:
            for line_error in batch_result.error_summary.error_list:
                errors.append(line_error.to_dict())
        if errors:
            try:
                # use first line run error message as exception message if no exception raised
                error = errors[0]
                message = error["error"]["message"]
            except Exception:
                message = (
                    "Failed to extract error message from line runs. "
                    f"Please check {self._outputs_path} for more info."
                )
        elif exception and isinstance(exception, UserErrorException):
            # SystemError will be raised above and users can see it, so we don't need to dump it.
            message = str(exception)
        else:
            return

        if not isinstance(exception, BulkRunException):
            # If other errors raised, pass it into PromptflowException
            exception = BulkRunException(
                message=message,
                error=exception,
                failed_lines=batch_result.failed_lines if batch_result else "unknown",
                total_lines=batch_result.total_lines if batch_result else "unknown",
                line_errors={"errors": errors},
            )
        with open(self._exception_path, mode="w", encoding=DEFAULT_ENCODING) as f:
            json.dump(
                PromptflowExceptionPresenter.create(exception).to_dict(include_debug_info=True), f, ensure_ascii=False
            )

    def load_exception(self) -> Dict:
        try:
            with open(self._exception_path, mode="r", encoding=DEFAULT_ENCODING) as f:
                return json.load(f)
        except Exception:
            return {}

    def load_detail(self) -> Dict[str, list]:
        if self._detail_path.is_file():
            # legacy run with local file detail.json, then directly load from the file
            with open(self._detail_path, mode="r", encoding=DEFAULT_ENCODING) as f:
                return json.load(f)
        else:
            # collect from local files and concat in the memory
            flow_runs, node_runs = [], []
            for line_run_record_file in sorted(self._run_infos_folder.iterdir()):
                # In addition to the output jsonl files, there may be multimedia files in the output folder,
                # so we should skip them.
                if line_run_record_file.suffix.lower() != ".jsonl":
                    continue
                with open(line_run_record_file, mode="r", encoding=DEFAULT_ENCODING) as f:
                    flow_runs.append(json.load(f)["run_info"])
            for node_folder in sorted(self._node_infos_folder.iterdir()):
                for node_run_record_file in sorted(node_folder.iterdir()):
                    if node_run_record_file.suffix.lower() != ".jsonl":
                        continue
                    with open(node_run_record_file, mode="r", encoding=DEFAULT_ENCODING) as f:
                        node_runs.append(json.load(f)["run_info"])
            return {"flow_runs": flow_runs, "node_runs": node_runs}

    def load_metrics(self) -> Dict[str, Union[int, float, str]]:
        with open(self._metrics_path, mode="r", encoding=DEFAULT_ENCODING) as f:
            metrics = json.load(f)
        return metrics

    def persist_node_run(self, run_info: NodeRunInfo) -> None:
        """Persist node run record to local storage."""
        node_folder = self._prepare_folder(self._node_infos_folder / run_info.node)
        self._persist_run_multimedia(run_info, node_folder)
        node_run_record = NodeRunRecord.from_run_info(run_info)
        # for reduce nodes, the line_number is None, store the info in the 000000000.jsonl
        # align with AzureMLRunStorageV2, which is a storage contract with PFS
        line_number = 0 if node_run_record.line_number is None else node_run_record.line_number
        filename = f"{str(line_number).zfill(self.LINE_NUMBER_WIDTH)}.jsonl"
        node_run_record.dump(node_folder / filename, run_name=self._run.name)

    def persist_flow_run(self, run_info: FlowRunInfo) -> None:
        """Persist line run record to local storage."""
        if not Status.is_terminated(run_info.status):
            logger.info("Line run is not terminated, skip persisting line run record.")
            return
        self._persist_run_multimedia(run_info, self._run_infos_folder)
        line_run_record = LineRunRecord.from_flow_run_info(run_info)
        # calculate filename according to the batch size
        # note that if batch_size > 1, need to well handle concurrent write scenario
        lower_bound = line_run_record.line_number // LOCAL_STORAGE_BATCH_SIZE * LOCAL_STORAGE_BATCH_SIZE
        upper_bound = lower_bound + LOCAL_STORAGE_BATCH_SIZE - 1
        filename = (
            f"{str(lower_bound).zfill(self.LINE_NUMBER_WIDTH)}_"
            f"{str(upper_bound).zfill(self.LINE_NUMBER_WIDTH)}.jsonl"
        )
        line_run_record.dump(self._run_infos_folder / filename)

    def persist_result(self, result: Optional[BatchResult]) -> None:
        """Persist metrics from return of executor."""
        if result is None:
            return
        self.dump_inputs_and_outputs()
        self.dump_metrics(result.metrics)

    def _persist_run_multimedia(self, run_info: Union[FlowRunInfo, NodeRunInfo], folder_path: Path):
        if run_info.inputs:
            run_info.inputs = self._serialize_multimedia(run_info.inputs, folder_path)
        if run_info.output:
            run_info.output = self._serialize_multimedia(run_info.output, folder_path)
            run_info.result = None
        if run_info.api_calls:
            run_info.api_calls = self._serialize_multimedia(run_info.api_calls, folder_path)

    def _serialize_multimedia(self, value, folder_path: Path, relative_path: Path = None):
        pfbytes_file_reference_encoder = get_file_reference_encoder(folder_path, relative_path, use_absolute_path=True)
        serialization_funcs = {Image: partial(Image.serialize, **{"encoder": pfbytes_file_reference_encoder})}
        return serialize(value, serialization_funcs=serialization_funcs)

    @staticmethod
    def _prepare_folder(path: Union[str, Path]) -> Path:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _outputs_padding(df: "DataFrame", inputs_line_numbers: List[int]) -> "DataFrame":
        import pandas as pd

        if len(df) == len(inputs_line_numbers):
            return df
        missing_lines = []
        lines_set = set(df[LINE_NUMBER].values)
        for i in inputs_line_numbers:
            if i not in lines_set:
                missing_lines.append({LINE_NUMBER: i})
        df_to_append = pd.DataFrame(missing_lines)
        res = pd.concat([df, df_to_append], ignore_index=True)
        res = res.sort_values(by=LINE_NUMBER, ascending=True)
        return res

    def load_inputs_and_outputs(self) -> Tuple["DataFrame", "DataFrame"]:
        import pandas as pd

        if not self._sdk_inputs_path.is_file() or not self._sdk_output_path.is_file():
            inputs, outputs = self._collect_io_from_debug_info()
        else:
            with open(self._sdk_inputs_path, mode="r", encoding=DEFAULT_ENCODING) as f:
                inputs = pd.read_json(f, orient="records", lines=True)
            with open(self._sdk_output_path, mode="r", encoding=DEFAULT_ENCODING) as f:
                outputs = pd.read_json(f, orient="records", lines=True)
                # if all line runs are failed, no need to fill
                if len(outputs) > 0:
                    outputs = self._outputs_padding(outputs, inputs["line_number"].tolist())
                    outputs.fillna(value="(Failed)", inplace=True)  # replace nan with explicit prompt
                    outputs = outputs.set_index(LINE_NUMBER)
        return inputs, outputs

    def _collect_io_from_debug_info(self) -> Tuple["DataFrame", "DataFrame"]:
        import pandas as pd

        inputs, outputs = [], []
        for line_run_record_file in sorted(self._run_infos_folder.iterdir()):
            if line_run_record_file.suffix.lower() != ".jsonl":
                continue
            with open(line_run_record_file, mode="r", encoding=DEFAULT_ENCODING) as f:
                data = json.load(f)
                line_number: int = data[LINE_NUMBER]
                line_run_info: dict = data["run_info"]
                current_inputs = line_run_info.get("inputs")
                current_outputs = line_run_info.get("output")
                inputs.append(copy.deepcopy(current_inputs))
                if current_outputs is not None:
                    current_outputs[LINE_NUMBER] = line_number
                    outputs.append(copy.deepcopy(current_outputs))
        return pd.DataFrame(inputs), pd.DataFrame(outputs)
