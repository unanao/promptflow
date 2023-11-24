# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
import logging
import platform

from opencensus.ext.azure.log_exporter import AzureEventHandler

from promptflow._cli._user_agent import USER_AGENT
from promptflow._sdk._configuration import Configuration

# promptflow-sdk in east us
INSTRUMENTATION_KEY = "8b52b368-4c91-4226-b7f7-be52822f0509"
# promptflow-sdk-eu in west europe
EU_INSTRUMENTATION_KEY = "6e81b826-60de-411c-964a-e7af287f6d3c"


# cspell:ignore overriden
def get_appinsights_log_handler():
    """
    Enable the OpenCensus logging handler for specified logger and instrumentation key to send info to AppInsights.
    """
    from promptflow._sdk._utils import setup_user_agent_to_operation_context
    from promptflow._telemetry.telemetry import is_telemetry_enabled

    try:

        config = Configuration.get_instance()
        instrumentation_key = INSTRUMENTATION_KEY
        user_agent = setup_user_agent_to_operation_context(USER_AGENT)
        custom_properties = {
            "python_version": platform.python_version(),
            "user_agent": user_agent,
            "installation_id": config.get_or_set_installation_id(),
        }

        handler = PromptFlowSDKLogHandler(
            connection_string=f"InstrumentationKey={instrumentation_key}",
            custom_properties=custom_properties,
            enable_telemetry=is_telemetry_enabled(),
        )
        return handler
    except Exception:  # pylint: disable=broad-except
        # ignore any exceptions, telemetry collection errors shouldn't block an operation
        return logging.NullHandler()


# cspell:ignore AzureMLSDKLogHandler
class PromptFlowSDKLogHandler(AzureEventHandler):
    """Customized AzureLogHandler for PromptFlow SDK"""

    def __init__(self, custom_properties, enable_telemetry, **kwargs):
        super().__init__(**kwargs)

        self._is_telemetry_enabled = enable_telemetry
        self._custom_dimensions = custom_properties

    def _check_stats_collection(self):
        # skip checking stats collection since it's time-consuming
        # according to doc: https://learn.microsoft.com/en-us/azure/azure-monitor/app/statsbeat
        # it doesn't affect customers' overall monitoring volume
        return False

    def emit(self, record):
        # skip logging if telemetry is disabled
        if not self._is_telemetry_enabled:
            return

        try:
            self._queue.put(record, block=False)

            # log the record immediately if it is an error
            if record.exc_info and not all(item is None for item in record.exc_info):
                self._queue.flush()
        except Exception:  # pylint: disable=broad-except
            # ignore any exceptions, telemetry collection errors shouldn't block an operation
            return

    def log_record_to_envelope(self, record):
        from promptflow._utils.utils import is_in_ci_pipeline

        # skip logging if telemetry is disabled

        if not self._is_telemetry_enabled:
            return
        custom_dimensions = {
            "level": record.levelname,
            # add to distinguish if the log is from ci pipeline
            "from_ci": is_in_ci_pipeline(),
        }
        custom_dimensions.update(self._custom_dimensions)
        if hasattr(record, "custom_dimensions") and isinstance(record.custom_dimensions, dict):
            record.custom_dimensions.update(custom_dimensions)
        else:
            record.custom_dimensions = custom_dimensions

        return super().log_record_to_envelope(record=record)
