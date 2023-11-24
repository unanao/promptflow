# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import copy
import logging
import os.path
import sys
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Union

from promptflow._sdk._constants import (
    LOGGER_NAME,
    MAX_RUN_LIST_RESULTS,
    MAX_SHOW_DETAILS_RESULTS,
    FlowRunProperties,
    ListViewType,
    RunStatus,
)
from promptflow._sdk._errors import InvalidRunStatusError, RunExistsError, RunNotFoundError, RunOperationParameterError
from promptflow._sdk._orm import RunInfo as ORMRun
from promptflow._sdk._utils import incremental_print, print_red_error, safe_parse_object_list
from promptflow._sdk._visualize_functions import dump_html, generate_html_string
from promptflow._sdk.entities import Run
from promptflow._sdk.operations._local_storage_operations import LocalStorageOperations
from promptflow._telemetry.activity import ActivityType, monitor_operation
from promptflow._telemetry.telemetry import TelemetryMixin
from promptflow.contracts._run_management import RunMetadata, RunVisualization
from promptflow.exceptions import UserErrorException

RUNNING_STATUSES = RunStatus.get_running_statuses()

logger = logging.getLogger(LOGGER_NAME)


class RunOperations(TelemetryMixin):
    """RunOperations."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @monitor_operation(activity_name="pf.runs.list", activity_type=ActivityType.PUBLICAPI)
    def list(
        self,
        max_results: Optional[int] = MAX_RUN_LIST_RESULTS,
        *,
        list_view_type: ListViewType = ListViewType.ACTIVE_ONLY,
    ) -> List[Run]:
        """List runs.

        :param max_results: Max number of results to return. Default: MAX_RUN_LIST_RESULTS.
        :type max_results: Optional[int]
        :param list_view_type: View type for including/excluding (for example) archived runs. Default: ACTIVE_ONLY.
        :type include_archived: Optional[ListViewType]
        :return: List of run objects.
        :rtype: List[~promptflow.entities.Run]
        """
        orm_runs = ORMRun.list(max_results=max_results, list_view_type=list_view_type)
        return safe_parse_object_list(
            obj_list=orm_runs,
            parser=Run._from_orm_object,
            message_generator=lambda x: f"Error parsing run {x.name!r}, skipped.",
        )

    @monitor_operation(activity_name="pf.runs.get", activity_type=ActivityType.PUBLICAPI)
    def get(self, name: str) -> Run:
        """Get a run entity.

        :param name: Name of the run.
        :type name: str
        :return: run object retrieved from the database.
        :rtype: ~promptflow.entities.Run
        """
        name = Run._validate_and_return_run_name(name)
        try:
            return Run._from_orm_object(ORMRun.get(name))
        except RunNotFoundError as e:
            raise e

    @monitor_operation(activity_name="pf.runs.create_or_update", activity_type=ActivityType.PUBLICAPI)
    def create_or_update(self, run: Run, **kwargs) -> Run:
        """Create or update a run.

        :param run: Run object to create or update.
        :type run: ~promptflow.entities.Run
        :return: Run object created or updated.
        :rtype: ~promptflow.entities.Run
        """
        # TODO: change to async
        stream = kwargs.pop("stream", False)
        try:
            from promptflow._sdk._submitter import RunSubmitter

            created_run = RunSubmitter(run_operations=self).submit(run=run, **kwargs)
            if stream:
                self.stream(created_run)
            return created_run
        except RunExistsError:
            raise RunExistsError(f"Run {run.name!r} already exists.")

    def _print_run_summary(self, run: Run) -> None:
        print("======= Run Summary =======\n")
        duration = str(run._end_time - run._created_on)
        print(
            f'Run name: "{run.name}"\n'
            f'Run status: "{run.status}"\n'
            f'Start time: "{run._created_on}"\n'
            f'Duration: "{duration}"\n'
            f'Output path: "{run._output_path}"\n'
        )

    @monitor_operation(activity_name="pf.runs.stream", activity_type=ActivityType.PUBLICAPI)
    def stream(self, name: Union[str, Run], raise_on_error: bool = True) -> Run:
        """Stream run logs to the console.

        :param name: Name of the run, or run object.
        :type name: Union[str, ~promptflow.sdk.entities.Run]
        :param raise_on_error: Raises an exception if a run fails or canceled.
        :type raise_on_error: bool
        :return: Run object.
        :rtype: ~promptflow.entities.Run
        """
        name = Run._validate_and_return_run_name(name)
        run = self.get(name=name)
        local_storage = LocalStorageOperations(run=run)

        file_handler = sys.stdout
        try:
            printed = 0
            run = self.get(run.name)
            while run.status in RUNNING_STATUSES or run.status == RunStatus.FINALIZING:
                file_handler.flush()
                available_logs = local_storage.logger.get_logs()
                printed = incremental_print(available_logs, printed, file_handler)
                time.sleep(10)
                run = self.get(run.name)
            # ensure all logs are printed
            file_handler.flush()
            available_logs = local_storage.logger.get_logs()
            incremental_print(available_logs, printed, file_handler)
            self._print_run_summary(run)
        except KeyboardInterrupt:
            error_message = "The output streaming for the run was interrupted, but the run is still executing."
            print(error_message)

        if run.status == RunStatus.FAILED or run.status == RunStatus.CANCELED:
            if run.status == RunStatus.FAILED:
                error_message = local_storage.load_exception().get("message", "Run fails with unknown error.")
            else:
                error_message = "Run is canceled."
            if raise_on_error:
                raise InvalidRunStatusError(error_message)
            else:
                print_red_error(error_message)

        return run

    @monitor_operation(activity_name="pf.runs.archive", activity_type=ActivityType.PUBLICAPI)
    def archive(self, name: Union[str, Run]) -> Run:
        """Archive a run.

        :param name: Name of the run.
        :type name: str
        :return: archived run object.
        :rtype: ~promptflow._sdk.entities._run.Run
        """
        name = Run._validate_and_return_run_name(name)
        ORMRun.get(name).archive()
        return self.get(name)

    @monitor_operation(activity_name="pf.runs.restore", activity_type=ActivityType.PUBLICAPI)
    def restore(self, name: Union[str, Run]) -> Run:
        """Restore a run.

        :param name: Name of the run.
        :type name: str
        :return: restored run object.
        :rtype: ~promptflow._sdk.entities._run.Run
        """
        name = Run._validate_and_return_run_name(name)
        ORMRun.get(name).restore()
        return self.get(name)

    @monitor_operation(activity_name="pf.runs.update", activity_type=ActivityType.PUBLICAPI)
    def update(
        self,
        name: Union[str, Run],
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Run:
        """Update run status.

        :param name: run name
        :param display_name: display name to update
        :param description: description to update
        :param tags: tags to update
        :param kwargs: other fields to update, fields not supported will be directly dropped.
        :return: updated run object
        :rtype: ~promptflow._sdk.entities._run.Run
        """
        name = Run._validate_and_return_run_name(name)
        # the kwargs is to support update run status scenario but keep it private
        ORMRun.get(name).update(display_name=display_name, description=description, tags=tags, **kwargs)
        return self.get(name)

    @monitor_operation(activity_name="pf.runs.get_details", activity_type=ActivityType.PUBLICAPI)
    def get_details(
        self, name: Union[str, Run], max_results: int = MAX_SHOW_DETAILS_RESULTS, all_results: bool = False
    ) -> "DataFrame":
        """Get the details from the run.

        .. note::

            If `all_results` is set to True, `max_results` will be overwritten to sys.maxsize.

        :param name: The run name or run object
        :type name: Union[str, ~promptflow.sdk.entities.Run]
        :param max_results: The max number of runs to return, defaults to 100
        :type max_results: int
        :param all_results: Whether to return all results, defaults to False
        :type all_results: bool
        :raises RunOperationParameterError: If `max_results` is not a positive integer.
        :return: The details data frame.
        :rtype: pandas.DataFrame
        """
        from pandas import DataFrame

        # if all_results is True, set max_results to sys.maxsize
        if all_results:
            max_results = sys.maxsize

        if not isinstance(max_results, int) or max_results < 1:
            raise RunOperationParameterError(f"'max_results' must be a positive integer, got {max_results!r}")

        name = Run._validate_and_return_run_name(name)
        run = self.get(name=name)
        local_storage = LocalStorageOperations(run=run)
        inputs, outputs = local_storage.load_inputs_and_outputs()
        inputs = inputs.to_dict("list")
        outputs = outputs.to_dict("list")
        data = {}
        columns = []
        for k in inputs:
            new_k = f"inputs.{k}"
            data[new_k] = copy.deepcopy(inputs[k])
            columns.append(new_k)
        for k in outputs:
            new_k = f"outputs.{k}"
            data[new_k] = copy.deepcopy(outputs[k])
            columns.append(new_k)
        df = DataFrame(data).head(max_results).reindex(columns=columns)
        return df

    @monitor_operation(activity_name="pf.runs.get_metrics", activity_type=ActivityType.PUBLICAPI)
    def get_metrics(self, name: Union[str, Run]) -> Dict[str, Any]:
        """Get run metrics.

        :param name: name of the run.
        :type name: str
        :return: Run metrics.
        :rtype: Dict[str, Any]
        """
        name = Run._validate_and_return_run_name(name)
        run = self.get(name=name)
        run._check_run_status_is_completed()
        local_storage = LocalStorageOperations(run=run)
        return local_storage.load_metrics()

    def _visualize(self, runs: List[Run], html_path: Optional[str] = None) -> None:
        details, metadatas = [], []
        for run in runs:
            # check run status first
            # if run status is not compeleted, there might be unexpected error during parse data
            # so we directly raise error if there is any incomplete run
            run._check_run_status_is_completed()

            local_storage = LocalStorageOperations(run)
            detail = local_storage.load_detail()
            metadata = RunMetadata(
                name=run.name,
                display_name=run.display_name,
                create_time=run.created_on,
                flow_path=run.properties[FlowRunProperties.FLOW_PATH],
                output_path=run.properties[FlowRunProperties.OUTPUT_PATH],
                tags=run.tags,
                lineage=run.run,
                metrics=self.get_metrics(name=run.name),
                dag=local_storage.load_dag_as_string(),
                flow_tools_json=local_storage.load_flow_tools_json(),
            )
            details.append(copy.deepcopy(detail))
            metadatas.append(asdict(metadata))
        data_for_visualize = RunVisualization(detail=details, metadata=metadatas)
        html_string = generate_html_string(asdict(data_for_visualize))
        # if html_path is specified, not open it in webbrowser(as it comes from VSC)
        dump_html(html_string, html_path=html_path, open_html=html_path is None)

    @monitor_operation(activity_name="pf.runs.visualize", activity_type=ActivityType.PUBLICAPI)
    def visualize(self, runs: Union[str, Run, List[str], List[Run]], **kwargs) -> None:
        """Visualize run(s).

        :param runs: List of run objects, or names of the runs.
        :type runs: Union[str, ~promptflow.sdk.entities.Run, List[str], List[~promptflow.sdk.entities.Run]]
        """
        if not isinstance(runs, list):
            runs = [runs]

        validated_runs = []
        for run in runs:
            run_name = Run._validate_and_return_run_name(run)
            validated_runs.append(self.get(name=run_name))

        html_path = kwargs.pop("html_path", None)
        try:
            self._visualize(validated_runs, html_path=html_path)
        except InvalidRunStatusError as e:
            error_message = f"Cannot visualize non-completed run. {str(e)}"
            logger.error(error_message)

    def _get_outputs(self, run: Union[str, Run]) -> List[Dict[str, Any]]:
        """Get the outputs of the run, load from local storage."""
        local_storage = self._get_local_storage(run)
        return local_storage.load_outputs()

    def _get_inputs(self, run: Union[str, Run]) -> List[Dict[str, Any]]:
        """Get the outputs of the run, load from local storage."""
        local_storage = self._get_local_storage(run)
        return local_storage.load_inputs()

    def _get_outputs_path(self, run: Union[str, Run]) -> str:
        """Get the outputs file path of the run."""
        local_storage = self._get_local_storage(run)
        return local_storage._outputs_path if local_storage.load_outputs() else None

    def _get_data_path(self, run: Union[str, Run]) -> str:
        """Get the outputs file path of the run."""
        local_storage = self._get_local_storage(run)
        # TODO: what if the data is deleted?
        if not local_storage._data_path or not os.path.exists(local_storage._data_path):
            raise UserErrorException(
                f"Data path {local_storage._data_path} for run {run.name} does not exist. "
                "Please make sure it exists and not deleted."
            )
        return local_storage._data_path

    def _get_local_storage(self, run: Union[str, Run]) -> LocalStorageOperations:
        """Get the local storage of the run."""
        if isinstance(run, str):
            run = self.get(name=run)
        return LocalStorageOperations(run)
