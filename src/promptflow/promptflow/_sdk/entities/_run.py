# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import datetime
import json
import logging
import uuid
from os import PathLike
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dateutil import parser as date_parser

from promptflow._sdk._configuration import Configuration
from promptflow._sdk._constants import (
    BASE_PATH_CONTEXT_KEY,
    DEFAULT_VARIANT,
    FLOW_DIRECTORY_MACRO_IN_CONFIG,
    LOGGER_NAME,
    PARAMS_OVERRIDE_KEY,
    PROMPT_FLOW_DIR_NAME,
    RUN_MACRO,
    TIMESTAMP_MACRO,
    VARIANT_ID_MACRO,
    AzureRunTypes,
    FlowRunProperties,
    RestRunTypes,
    RunDataKeys,
    RunInfoSources,
    RunStatus,
    RunTypes,
)
from promptflow._sdk._errors import InvalidRunError, InvalidRunStatusError
from promptflow._sdk._orm import RunInfo as ORMRun
from promptflow._sdk._utils import _sanitize_python_variable_name, parse_variant
from promptflow._sdk.entities._yaml_translatable import YAMLTranslatableMixin
from promptflow._sdk.schemas._run import RunSchema
from promptflow._utils.flow_utils import get_flow_lineage_id
from promptflow.exceptions import UserErrorException

AZURE_RUN_TYPE_2_RUN_TYPE = {
    AzureRunTypes.BATCH: RunTypes.BATCH,
    AzureRunTypes.EVALUATION: RunTypes.EVALUATION,
    AzureRunTypes.PAIRWISE_EVALUATE: RunTypes.PAIRWISE_EVALUATE,
}

REST_RUN_TYPE_2_RUN_TYPE = {
    RestRunTypes.BATCH: RunTypes.BATCH,
    RestRunTypes.EVALUATION: RunTypes.EVALUATION,
    RestRunTypes.PAIRWISE_EVALUATE: RunTypes.PAIRWISE_EVALUATE,
}


class Run(YAMLTranslatableMixin):
    """Flow run entity.

    :param flow: Path of the flow directory.
    :type flow: Path
    :param name: Name of the run.
    :type name: Optional[str]
    :param data: Input data for the run. Local path or remote uri(starts with azureml: or public URL) are supported. Note: remote uri is only supported for cloud run. # noqa: E501
    :type data: Optional[str]
    :param variant: Variant of the run.
    :type variant: Optional[str]
    :param run: Parent run or run ID.
    :type run: Optional[Union[Run, str]]
    :param column_mapping: Column mapping for the run. Optional since it's not stored in the database.
    :type column_mapping: Optional[dict]
    :param display_name: Display name of the run.
    :type display_name: Optional[str]
    :param description: Description of the run.
    :type description: Optional[str]
    :param tags: Tags of the run.
    :type tags: Optional[List[Dict[str, str]]]
    :param created_on: Date and time the run was created.
    :type created_on: Optional[datetime.datetime]
    :param start_time: Date and time the run started.
    :type start_time: Optional[datetime.datetime]
    :param end_time: Date and time the run ended.
    :type end_time: Optional[datetime.datetime]
    :param status: Status of the run.
    :type status: Optional[str]
    :param environment_variables: Environment variables for the run.
    :type environment_variables: Optional[Dict[str, str]]
    :param connections: Connections for the run.
    :type connections: Optional[Dict[str, Dict]]
    :param properties: Properties of the run.
    :type properties: Optional[Dict[str, Any]]
    :param kwargs: Additional keyword arguments.
    :type kwargs: Optional[dict]
    """

    def __init__(
        self,
        flow: Path,
        name: Optional[str] = None,
        # input fields are optional since it's not stored in DB
        data: Optional[str] = None,
        variant: Optional[str] = None,
        run: Optional[Union["Run", str]] = None,
        column_mapping: Optional[dict] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[Dict[str, str]]] = None,
        *,
        created_on: Optional[datetime.datetime] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        status: Optional[str] = None,
        environment_variables: Optional[Dict[str, str]] = None,
        connections: Optional[Dict[str, Dict]] = None,
        properties: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        # TODO: remove when RUN CRUD don't depend on this
        self.type = RunTypes.BATCH
        self.data = data
        self.column_mapping = column_mapping
        self.display_name = display_name
        self.description = description
        self.tags = tags
        self.variant = variant
        self.run = run
        self._created_on = created_on or datetime.datetime.now()
        self._status = status or RunStatus.NOT_STARTED
        self.environment_variables = environment_variables or {}
        self.connections = connections or {}
        self._properties = properties or {}
        self._is_archived = kwargs.get("is_archived", False)
        self._run_source = kwargs.get("run_source", RunInfoSources.LOCAL)
        self._start_time = start_time
        self._end_time = end_time
        self._duration = kwargs.get("duration", None)
        self._portal_url = kwargs.get(RunDataKeys.PORTAL_URL, None)
        self._creation_context = kwargs.get("creation_context", None)
        # init here to make sure those fields initialized in all branches.
        self.flow = flow
        self._experiment_name = None
        self._lineage_id = None
        # default run name: flow directory name + timestamp
        self.name = name or self._generate_run_name()
        if self._run_source == RunInfoSources.LOCAL:
            self.flow = Path(flow).resolve().absolute()
            flow_dir = self._get_flow_dir()
            # sanitize flow_dir to avoid invalid experiment name
            self._experiment_name = _sanitize_python_variable_name(flow_dir.name)
            self._lineage_id = get_flow_lineage_id(flow_dir=flow_dir)
            self._output_path = Path(
                kwargs.get("output_path", self._generate_output_path(config=kwargs.get("config", None)))
            )
        elif self._run_source == RunInfoSources.INDEX_SERVICE:
            self._metrics = kwargs.get("metrics", {})
            self._experiment_name = kwargs.get("experiment_name", None)
        elif self._run_source == RunInfoSources.RUN_HISTORY:
            self._error = kwargs.get("error", None)
            self._data_portal_url = kwargs.get("data_portal_url", None)
            self._input_run_portal_url = kwargs.get("input_run_portal_url", None)
            self._output = kwargs.get("output", None)
            self._output_portal_url = kwargs.get("output_portal_url", None)
        self._runtime = kwargs.get("runtime", None)
        self._resources = kwargs.get("resources", None)

    @property
    def created_on(self) -> str:
        return self._created_on.isoformat()

    @property
    def status(self) -> str:
        return self._status

    @property
    def properties(self) -> Dict[str, str]:
        if self._run_source == RunInfoSources.LOCAL:
            # show posix path to avoid windows path escaping
            result = {
                FlowRunProperties.FLOW_PATH: Path(self.flow).as_posix(),
                FlowRunProperties.OUTPUT_PATH: self._output_path.as_posix(),
            }
            if self.run:
                run_name = self.run.name if isinstance(self.run, Run) else self.run
                result[FlowRunProperties.RUN] = run_name
            if self.variant:
                result[FlowRunProperties.NODE_VARIANT] = self.variant
            return {
                **result,
                **self._properties,
            }
        return self._properties

    @classmethod
    def _from_orm_object(cls, obj: ORMRun) -> "Run":
        properties_json = json.loads(str(obj.properties))
        return Run(
            name=str(obj.name),
            flow=Path(properties_json[FlowRunProperties.FLOW_PATH]),
            output_path=properties_json[FlowRunProperties.OUTPUT_PATH],
            run=properties_json.get(FlowRunProperties.RUN, None),
            variant=properties_json.get(FlowRunProperties.NODE_VARIANT, None),
            display_name=obj.display_name,
            description=str(obj.description) if obj.description else None,
            tags=json.loads(str(obj.tags)) if obj.tags else None,
            # keyword arguments
            created_on=datetime.datetime.fromisoformat(str(obj.created_on)),
            start_time=datetime.datetime.fromisoformat(str(obj.start_time)) if obj.start_time else None,
            end_time=datetime.datetime.fromisoformat(str(obj.end_time)) if obj.end_time else None,
            status=str(obj.status),
            data=Path(obj.data).resolve().absolute().as_posix() if obj.data else None,
            properties={FlowRunProperties.SYSTEM_METRICS: properties_json.get(FlowRunProperties.SYSTEM_METRICS, {})},
        )

    @classmethod
    def _from_index_service_entity(cls, run_entity: dict) -> "Run":
        """Convert run entity from index service to run object."""
        start_time = run_entity["properties"].get("startTime", None)
        end_time = run_entity["properties"].get("endTime", None)
        duration = run_entity["properties"].get("duration", None)
        return Run(
            name=run_entity["properties"]["runId"],
            flow=Path(f"azureml://flows/{run_entity['properties']['experimentName']}"),
            type=AZURE_RUN_TYPE_2_RUN_TYPE[run_entity["properties"]["runType"]],
            created_on=date_parser.parse(run_entity["properties"]["creationContext"]["createdTime"]),
            status=run_entity["annotations"]["status"],
            display_name=run_entity["annotations"]["displayName"],
            description=run_entity["annotations"]["description"],
            tags=run_entity["annotations"]["tags"],
            properties=run_entity["properties"]["userProperties"],
            is_archived=run_entity["annotations"]["archived"],
            run_source=RunInfoSources.INDEX_SERVICE,
            metrics=run_entity["annotations"]["metrics"],
            start_time=date_parser.parse(start_time) if start_time else None,
            end_time=date_parser.parse(end_time) if end_time else None,
            duration=duration,
            portal_url=run_entity[RunDataKeys.PORTAL_URL],
            creation_context=run_entity["properties"]["creationContext"],
            experiment_name=run_entity["properties"]["experimentName"],
        )

    @classmethod
    def _from_run_history_entity(cls, run_entity: dict) -> "Run":
        """Convert run entity from run history service to run object."""
        flow_name = run_entity["properties"].get("azureml.promptflow.flow_name", None)
        start_time = run_entity.get("startTimeUtc", None)
        end_time = run_entity.get("endTimeUtc", None)
        duration = run_entity.get("duration", None)
        return Run(
            name=run_entity["runId"],
            flow=Path(f"azureml://flows/{flow_name}"),
            type=AZURE_RUN_TYPE_2_RUN_TYPE[run_entity["runType"]],
            created_on=date_parser.parse(run_entity["createdUtc"]),
            start_time=date_parser.parse(start_time) if start_time else None,
            end_time=date_parser.parse(end_time) if end_time else None,
            duration=duration,
            status=run_entity["status"],
            display_name=run_entity["displayName"],
            description=run_entity["description"],
            tags=run_entity["tags"],
            properties=run_entity["properties"],
            is_archived=run_entity.get("archived", False),  # TODO: Get archived status, depends on run history team
            error=run_entity.get("error", None),
            run_source=RunInfoSources.RUN_HISTORY,
            portal_url=run_entity[RunDataKeys.PORTAL_URL],
            creation_context=run_entity["createdBy"],
            data=run_entity[RunDataKeys.DATA],
            data_portal_url=run_entity[RunDataKeys.DATA_PORTAL_URL],
            run=run_entity[RunDataKeys.RUN],
            input_run_portal_url=run_entity[RunDataKeys.INPUT_RUN_PORTAL_URL],
            output=run_entity[RunDataKeys.OUTPUT],
            output_portal_url=run_entity[RunDataKeys.OUTPUT_PORTAL_URL],
        )

    @classmethod
    def _from_mt_service_entity(cls, run_entity) -> "Run":
        """Convert run object from MT service to run object."""
        flow_run_id = run_entity.flow_run_resource_id.split("/")[-1]
        return cls(
            name=flow_run_id,
            flow=Path(f"azureml://flows/{run_entity.flow_name}"),
            display_name=run_entity.flow_run_display_name,
            description="",
            tags=[],
            created_on=date_parser.parse(run_entity.created_on),
            status="",
            run_source=RunInfoSources.MT_SERVICE,
        )

    def _to_orm_object(self) -> ORMRun:
        """Convert current run entity to ORM object."""
        display_name = self._format_display_name()
        return ORMRun(
            name=self.name,
            created_on=self.created_on,
            status=self.status,
            start_time=self._start_time.isoformat() if self._start_time else None,
            end_time=self._end_time.isoformat() if self._end_time else None,
            display_name=display_name,
            description=self.description,
            tags=json.dumps(self.tags) if self.tags else None,
            properties=json.dumps(self.properties),
            data=Path(self.data).resolve().absolute().as_posix() if self.data else None,
        )

    def _dump(self) -> None:
        """Dump current run entity to local DB."""
        self._to_orm_object().dump()

    def _to_dict(self):
        from promptflow._sdk.operations._local_storage_operations import LocalStorageOperations

        properties = self.properties
        result = {
            "name": self.name,
            "created_on": self.created_on,
            "status": self.status,
            "display_name": self.display_name,
            "description": self.description,
            "tags": self.tags,
            "properties": properties,
        }

        if self._run_source == RunInfoSources.LOCAL:
            result["flow_name"] = Path(str(self.flow)).resolve().name
            local_storage = LocalStorageOperations(run=self)
            result[RunDataKeys.DATA] = (
                local_storage._data_path.resolve().absolute().as_posix()
                if local_storage._data_path is not None
                else None
            )
            result[RunDataKeys.OUTPUT] = local_storage.outputs_folder.as_posix()
            if self.run:
                run_name = self.run.name if isinstance(self.run, Run) else self.run
                result[RunDataKeys.RUN] = properties.pop(FlowRunProperties.RUN, run_name)
            # add exception part if any
            exception_dict = local_storage.load_exception()
            if exception_dict:
                result["error"] = exception_dict
        elif self._run_source == RunInfoSources.INDEX_SERVICE:
            result["creation_context"] = self._creation_context
            result["flow_name"] = self._experiment_name
            result["is_archived"] = self._is_archived
            result["start_time"] = self._start_time.isoformat() if self._start_time else None
            result["end_time"] = self._end_time.isoformat() if self._end_time else None
            result["duration"] = self._duration
        elif self._run_source == RunInfoSources.RUN_HISTORY:
            result["creation_context"] = self._creation_context
            result["start_time"] = self._start_time.isoformat() if self._start_time else None
            result["end_time"] = self._end_time.isoformat() if self._end_time else None
            result["duration"] = self._duration
            result[RunDataKeys.PORTAL_URL] = self._portal_url
            result[RunDataKeys.DATA] = self.data
            result[RunDataKeys.DATA_PORTAL_URL] = self._data_portal_url
            result[RunDataKeys.OUTPUT] = self._output
            result[RunDataKeys.OUTPUT_PORTAL_URL] = self._output_portal_url
            if self.run:
                result[RunDataKeys.RUN] = self.run
                result[RunDataKeys.INPUT_RUN_PORTAL_URL] = self._input_run_portal_url
            if self._error:
                result["error"] = self._error
        return result

    @classmethod
    def _load(
        cls,
        data: Optional[Dict] = None,
        yaml_path: Optional[Union[PathLike, str]] = None,
        params_override: Optional[list] = None,
        **kwargs,
    ):
        data = data or {}
        params_override = params_override or []
        context = {
            BASE_PATH_CONTEXT_KEY: Path(yaml_path).parent if yaml_path else Path("./"),
            PARAMS_OVERRIDE_KEY: params_override,
        }
        run = cls._load_from_dict(
            data=data,
            context=context,
            additional_message="Failed to load flow run",
            **kwargs,
        )
        if yaml_path:
            run._source_path = yaml_path
        return run

    def _generate_run_name(self) -> str:
        """Generate a run name with flow_name_variant_timestamp format."""
        try:
            flow_name = self._get_flow_dir().name
            variant = self.variant
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            variant = parse_variant(variant)[1] if variant else DEFAULT_VARIANT
            run_name_prefix = f"{flow_name}_{variant}"
            # TODO(2562996): limit run name to avoid it become too long
            run_name = f"{run_name_prefix}_{timestamp}"
            return _sanitize_python_variable_name(run_name)
        except Exception:
            return str(uuid.uuid4())

    def _get_default_display_name(self) -> str:
        display_name = self.display_name
        if not display_name:
            display_name = self.name
        return display_name

    def _format_display_name(self) -> str:
        """
        Format display name. Replace macros in display name with actual values.
        The following macros are supported: ${variant_id}, ${run}, ${timestamp}

        For example,
            if the display name is "run-${variant_id}-${timestamp}"
            it will be formatted to "run-variant_1-20210901123456"
        """

        display_name = self._get_default_display_name()
        time_stamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
        if self.run:
            display_name = display_name.replace(RUN_MACRO, self._validate_and_return_run_name(self.run))
        display_name = display_name.replace(TIMESTAMP_MACRO, time_stamp)
        variant = self.variant
        variant = parse_variant(variant)[1] if variant else DEFAULT_VARIANT
        display_name = display_name.replace(VARIANT_ID_MACRO, variant)

        return display_name

    def _get_flow_dir(self) -> Path:
        flow = Path(self.flow)
        if flow.is_dir():
            return flow
        return flow.parent

    @classmethod
    def _get_schema_cls(self):
        return RunSchema

    def _to_rest_object(self):
        from azure.ai.ml._utils._storage_utils import AzureMLDatastorePathUri

        from promptflow.azure._restclient.flow.models import (
            BatchDataInput,
            RunDisplayNameGenerationType,
            SubmitBulkRunRequest,
        )

        if self.run is not None:
            if isinstance(self.run, Run):
                variant = self.run.name
            elif isinstance(self.run, str):
                variant = self.run
            else:
                raise UserErrorException(f"Invalid run type: {type(self.run)}")
        else:
            variant = None

        if not variant and not self.data:
            raise UserErrorException("Either run or data should be provided")

        # parse inputs mapping
        inputs_mapping = {}
        if self.column_mapping and not isinstance(self.column_mapping, dict):
            raise UserErrorException(f"column_mapping should be a dictionary, got {type(self.column_mapping)} instead.")
        if self.column_mapping:
            for k, v in self.column_mapping.items():
                if isinstance(v, (int, float, str, bool)):
                    inputs_mapping[k] = v
                else:
                    try:
                        val = json.dumps(v)
                    except Exception as e:
                        raise UserErrorException(
                            f"Invalid input mapping value: {v}, "
                            f"only primitive or json serializable value is supported, got {type(v)}",
                            error=e,
                        )
                    inputs_mapping[k] = val

        if str(self.flow).startswith("azureml://"):
            # upload via _check_and_upload_path
            # submit with params FlowDefinitionDataStoreName and FlowDefinitionBlobPath
            path_uri = AzureMLDatastorePathUri(str(self.flow))
            return SubmitBulkRunRequest(
                flow_definition_data_store_name=path_uri.datastore,
                flow_definition_blob_path=path_uri.path,
                run_id=self.name,
                # will use user provided display name since PFS will have special logic to update it.
                run_display_name=self._get_default_display_name(),
                description=self.description,
                tags=self.tags,
                node_variant=self.variant,
                variant_run_id=variant,
                batch_data_input=BatchDataInput(
                    data_uri=self.data,
                ),
                inputs_mapping=inputs_mapping,
                run_experiment_name=self._experiment_name,
                environment_variables=self.environment_variables,
                connections=self.connections,
                flow_lineage_id=self._lineage_id,
                run_display_name_generation_type=RunDisplayNameGenerationType.USER_PROVIDED_MACRO,
            )
        else:
            # upload via CodeOperations.create_or_update
            # submit with param FlowDefinitionDataUri
            return SubmitBulkRunRequest(
                flow_definition_data_uri=str(self.flow),
                run_id=self.name,
                run_display_name=self._get_default_display_name(),
                description=self.description,
                tags=self.tags,
                node_variant=self.variant,
                variant_run_id=variant,
                batch_data_input=BatchDataInput(
                    data_uri=self.data,
                ),
                inputs_mapping=inputs_mapping,
                run_experiment_name=self._experiment_name,
                environment_variables=self.environment_variables,
                connections=self.connections,
                flow_lineage_id=self._lineage_id,
                run_display_name_generation_type=RunDisplayNameGenerationType.USER_PROVIDED_MACRO,
            )

    def _check_run_status_is_completed(self) -> None:
        if self.status != RunStatus.COMPLETED:
            error_message = f"Run {self.name!r} is not completed, the status is {self.status!r}."
            if self.status != RunStatus.FAILED:
                error_message += " Please wait for its completion, or select other completed run(s)."
            raise InvalidRunStatusError(error_message)

    @staticmethod
    def _validate_and_return_run_name(run: Union[str, "Run"]) -> str:
        """Check if run name is valid."""
        if isinstance(run, Run):
            return run.name
        elif isinstance(run, str):
            return run
        raise InvalidRunError(f"Invalid run {run!r}, expected 'str' or 'Run' object but got {type(run)!r}.")

    def _generate_output_path(self, config: Optional[Configuration]) -> Path:
        config = config or Configuration.get_instance()
        path = config.get_run_output_path()
        if path is None:
            path = Path.home() / PROMPT_FLOW_DIR_NAME / ".runs"
        else:
            try:
                flow_posix_path = self.flow.resolve().as_posix()
                path = Path(path.replace(FLOW_DIRECTORY_MACRO_IN_CONFIG, self.flow.resolve().as_posix())).resolve()
                # in case user manually modifies ~/.promptflow/pf.yaml
                # fall back to default run output path
                if path.as_posix() == flow_posix_path:
                    raise Exception(f"{FLOW_DIRECTORY_MACRO_IN_CONFIG!r} is not a valid value.")
                path.mkdir(parents=True, exist_ok=True)
            except Exception:  # pylint: disable=broad-except
                path = Path.home() / PROMPT_FLOW_DIR_NAME / ".runs"
                warning_message = (
                    "Got unexpected error when parsing specified output path: "
                    f"{config.get_run_output_path()!r}; "
                    f"will use default output path: {path!r} instead."
                )
                logging.getLogger(LOGGER_NAME).warning(warning_message)
        return (path / str(self.name)).resolve()
