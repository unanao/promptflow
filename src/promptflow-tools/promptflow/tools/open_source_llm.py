import functools
import json
import os
import re
import sys
import time
import urllib.request

from abc import abstractmethod
from enum import Enum
from typing import Any, Dict, List, Tuple, Mapping, Optional
from urllib.request import HTTPError

from promptflow import ToolProvider, tool
from promptflow.connections import CustomConnection
from promptflow.contracts.types import PromptTemplate
from promptflow.tools.common import render_jinja_template, parse_chat
from promptflow.tools.exception import (
    OpenSourceLLMOnlineEndpointError,
    OpenSourceLLMUserError,
    OpenSourceLLMKeyValidationError
)

VALID_LLAMA_ROLES = {"system", "user", "assistant"}
REQUIRED_CONFIG_KEYS = ["endpoint_url", "model_family"]
REQUIRED_SECRET_KEYS = ["endpoint_api_key"]
DEFAULT_ENDPOINT_NAME = "-- please enter an endpoint name --"
ENDPOINT_REQUIRED_ENV_VARS = ["AZUREML_ARM_SUBSCRIPTION", "AZUREML_ARM_RESOURCEGROUP", "AZUREML_ARM_WORKSPACE_NAME"]


def handle_oneline_endpoint_error(max_retries: int = 3,
                                  initial_delay: float = 1,
                                  exponential_base: float = 2):
    def deco_retry(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except HTTPError as e:
                    if i == max_retries - 1:
                        error_message = f"Exception hit calling Oneline Endpoint: {type(e).__name__}: {str(e)}"
                        print(error_message, file=sys.stderr)
                        raise OpenSourceLLMOnlineEndpointError(message=error_message)

                    delay *= exponential_base
                    time.sleep(delay)
        return wrapper
    return deco_retry


def format_generic_response_payload(output: bytes, response_key: str) -> str:
    response_json = json.loads(output)
    try:
        if response_key is None:
            return response_json[0]
        else:
            return response_json[0][response_key]
    except KeyError as e:
        if response_key is None:
            message = f"""Expected the response to fit the following schema:
`[
    <text>
]`
Instead, received {response_json} and access failed at key `{e}`.
"""
        else:
            message = f"""Expected the response to fit the following schema:
`[
    {{
        "{response_key}": <text>
    }}
]`
Instead, received {response_json} and access failed at key `{e}`.
"""
        raise OpenSourceLLMUserError(message=message)


def get_model_type(deployment_model: str) -> str:
    m = re.match(r'azureml://registries/[^/]+/models/([^/]+)/versions/', deployment_model)
    if m is None:
        raise ValueError(f"Unexpected model format: {deployment_model}")
    model = m[1].lower()
    if model.startswith(ModelFamily.LLAMA.lower()):
        return ModelFamily.LLAMA
    elif model.startswith(ModelFamily.FALCON.lower()):
        return ModelFamily.FALCON
    elif model.startswith(ModelFamily.DOLLY.lower()):
        return ModelFamily.DOLLY
    elif model.startswith("gpt2"):
        return ModelFamily.GPT2
    else:
        raise ValueError(f"Unexpected model type: {model} derived from deployed model: {deployment_model}")


def get_deployment_from_endpoint(endpoint_name: str, deployment_name: str = None) -> Tuple[str, str, str]:
    from azure.identity import DefaultAzureCredential
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)

    try:
        from azure.ai.ml import MLClient
        ml_client = MLClient(
            credential=credential,
            subscription_id=os.getenv("AZUREML_ARM_SUBSCRIPTION"),
            resource_group_name=os.getenv("AZUREML_ARM_RESOURCEGROUP"),
            workspace_name=os.getenv("AZUREML_ARM_WORKSPACE_NAME"))
    except Exception as e:
        message = "Unable to connect to AzureML. Please ensure the following environment variables are set: "
        message += ",".join(ENDPOINT_REQUIRED_ENV_VARS)
        message += "\nException: " + str(e)
        raise OpenSourceLLMOnlineEndpointError(message=message)

    found = False
    for ep in ml_client.online_endpoints.list():
        if ep.name == endpoint_name:
            endpoint_uri = ep.scoring_uri
            endpoint_key = ml_client.online_endpoints.get_keys(ep.name).primary_key
            found = True
            break

    if not found:
        raise ValueError(f"Endpoint {endpoint_name} not found.")

    found = False
    if deployment_name is None:
        deployment_name = sorted(ep.traffic, key=lambda item: item[1])[0]
        found = True

    for d in ml_client.online_deployments.list(ep.name):
        if d.name == deployment_name:
            model = get_model_type(d.model)
            found = True
            break

    if not found:
        raise ValueError(f"Deployment {deployment_name} not found.")

    return (endpoint_uri, endpoint_key, model)


def get_deployment_from_connection(connection: CustomConnection) -> Tuple[str, str, str]:
    conn_dict = dict(connection)
    for key in REQUIRED_CONFIG_KEYS:
        if key not in conn_dict:
            accepted_keys = ",".join([key for key in REQUIRED_CONFIG_KEYS])
            raise OpenSourceLLMKeyValidationError(
                message=f"""Required key `{key}` not found in given custom connection.
Required keys are: {accepted_keys}."""
            )
    for key in REQUIRED_SECRET_KEYS:
        if key not in conn_dict:
            accepted_keys = ",".join([key for key in REQUIRED_SECRET_KEYS])
            raise OpenSourceLLMKeyValidationError(
                message=f"""Required secret key `{key}` not found in given custom connection.
Required keys are: {accepted_keys}."""
            )
    try:
        model_family = ModelFamily[connection.configs['model_family']]
    except KeyError:
        accepted_models = ",".join([model.name for model in ModelFamily])
        raise OpenSourceLLMKeyValidationError(
            message=f"""Given model_family '{connection.configs['model_family']}' not recognized.
Supported models are: {accepted_models}."""
        )
    return (connection.configs['endpoint_url'],
            connection.secrets['endpoint_api_key'],
            model_family)


class ModelFamily(str, Enum):
    LLAMA = "LLaMa"
    DOLLY = "Dolly"
    GPT2 = "GPT-2"
    FALCON = "Falcon"


class API(str, Enum):
    CHAT = "chat"
    COMPLETION = "completion"


class ContentFormatterBase:
    """Transform request and response of AzureML endpoint to match with
    required schema.
    """

    content_type: Optional[str] = "application/json"
    """The MIME type of the input data passed to the endpoint"""

    accepts: Optional[str] = "application/json"
    """The MIME type of the response data returned from the endpoint"""

    @staticmethod
    def escape_special_characters(prompt: str) -> str:
        """Escapes any special characters in `prompt`"""
        return re.sub(
            r'\\([\\\"a-zA-Z])',
            r'\\\1',
            prompt)

    @abstractmethod
    def format_request_payload(self, prompt: str, model_kwargs: Dict) -> str:
        """Formats the request body according to the input schema of
        the model. Returns bytes or seekable file like object in the
        format specified in the content_type request header.
        """

    @abstractmethod
    def format_response_payload(self, output: bytes) -> str:
        """Formats the response body according to the output
        schema of the model. Returns the data type that is
        received from the response.
        """


class GPT2ContentFormatter(ContentFormatterBase):
    """Content handler for LLMs from the OSS catalog."""

    def format_request_payload(self, prompt: str, model_kwargs: Dict) -> str:
        input_str = json.dumps(
            {
                "inputs": {"input_string": [ContentFormatterBase.escape_special_characters(prompt)]},
                "parameters": model_kwargs,
            }
        )
        return input_str

    def format_response_payload(self, output: bytes) -> str:
        return format_generic_response_payload(output, response_key="0")


class HFContentFormatter(ContentFormatterBase):
    """Content handler for LLMs from the HuggingFace catalog."""

    def format_request_payload(self, prompt: str, model_kwargs: Dict) -> str:
        input_str = json.dumps(
            {
                "inputs": [ContentFormatterBase.escape_special_characters(prompt)],
                "parameters": model_kwargs,
            }
        )
        return input_str

    def format_response_payload(self, output: bytes) -> str:
        return format_generic_response_payload(output, response_key="generated_text")


class DollyContentFormatter(ContentFormatterBase):
    """Content handler for the Dolly-v2-12b model"""

    def format_request_payload(self, prompt: str, model_kwargs: Dict) -> str:
        input_str = json.dumps(
            {
                "input_data": {"input_string": [ContentFormatterBase.escape_special_characters(prompt)]},
                "parameters": model_kwargs,
            }
        )
        return input_str

    def format_response_payload(self, output: bytes) -> str:
        return format_generic_response_payload(output, response_key=None)


class LlamaContentFormatter(ContentFormatterBase):
    """Content formatter for LLaMa"""

    def __init__(self, api: API, chat_history: Optional[str] = ""):
        super().__init__()
        self.api = api
        self.chat_history = chat_history

    def format_request_payload(self, prompt: str, model_kwargs: Dict) -> str:
        """Formats the request according the the chosen api"""
        if "do_sample" not in model_kwargs:
            model_kwargs["do_sample"] = True

        if self.api == API.CHAT:
            prompt_value = parse_chat(self.chat_history, valid_roles=["assistant", "user", "system"])
        else:
            prompt_value = [ContentFormatterBase.escape_special_characters(prompt)]

        return json.dumps(
            {
                "input_data":
                {
                    "input_string": prompt_value,
                    "parameters": model_kwargs
                }
            }
        )

    def format_response_payload(self, output: bytes) -> str:
        """Formats response"""
        response_json = json.loads(output)

        if self.api == API.CHAT and "output" in response_json:
            return response_json["output"]
        elif self.api == API.COMPLETION and len(response_json) > 0 and "0" in response_json[0]:
            return response_json[0]["0"]
        else:
            error_message = f"Unexpected response format. Response: {response_json}"
            print(error_message, file=sys.stderr)
            raise OpenSourceLLMOnlineEndpointError(message=error_message)


class ContentFormatterFactory:
    """Factory class for supported models"""

    def get_content_formatter(
        model_family: ModelFamily, api: API, chat_history: Optional[List[Dict]] = []
    ) -> ContentFormatterBase:
        if model_family == ModelFamily.LLAMA:
            return LlamaContentFormatter(chat_history=chat_history, api=api)
        elif model_family == ModelFamily.DOLLY:
            return DollyContentFormatter()
        elif model_family == ModelFamily.GPT2:
            return GPT2ContentFormatter()
        elif model_family == ModelFamily.FALCON:
            return HFContentFormatter()


class AzureMLOnlineEndpoint:
    """Azure ML Online Endpoint models."""

    endpoint_url: str = ""
    """URL of pre-existing Endpoint. Should be passed to constructor or specified as
        env var `AZUREML_ENDPOINT_URL`."""

    endpoint_api_key: str = ""
    """Authentication Key for Endpoint. Should be passed to constructor or specified as
        env var `AZUREML_ENDPOINT_API_KEY`."""

    content_formatter: Any = None
    """The content formatter that provides an input and output
    transform function to handle formats between the LLM and
    the endpoint"""

    model_kwargs: Optional[Dict] = None
    """Key word arguments to pass to the model."""

    def __init__(
        self,
        endpoint_url: str,
        endpoint_api_key: str,
        content_formatter: ContentFormatterBase,
        model_family: ModelFamily,
        deployment_name: Optional[str] = None,
        model_kwargs: Optional[Dict] = None,
    ):
        self.endpoint_url = endpoint_url
        self.endpoint_api_key = endpoint_api_key
        self.deployment_name = deployment_name
        self.content_formatter = content_formatter
        self.model_kwargs = model_kwargs
        self.model_family = model_family

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """Get the identifying parameters."""
        _model_kwargs = self.model_kwargs or {}
        return {
            **{"model_kwargs": _model_kwargs},
        }

    @property
    def _llm_type(self) -> str:
        """Return type of llm."""
        return "azureml_endpoint"

    def _call_endpoint(self, body: bytes) -> bytes:
        """call."""

        headers = {
            "Content-Type": "application/json",
            "Authorization": ("Bearer " + self.endpoint_api_key),
            "x-ms-user-agent": "PromptFlow/OpenSourceLLM/" + self.model_family}

        # If this is not set it'll use the default deployment on the endpoint.
        if self.deployment_name is not None:
            headers["azureml-model-deployment"] = self.deployment_name

        req = urllib.request.Request(self.endpoint_url, body, headers)
        response = urllib.request.urlopen(req, timeout=50)
        result = response.read()
        return result

    def __call__(
        self,
        prompt: str
    ) -> str:
        """Call out to an AzureML Managed Online endpoint.
        Args:
            prompt: The prompt to pass into the model.
        Returns:
            The string generated by the model.
        Example:
            .. code-block:: python
                response = azureml_model("Tell me a joke.")
        """
        _model_kwargs = self.model_kwargs or {}

        body = self.content_formatter.format_request_payload(prompt, _model_kwargs)
        endpoint_request = str.encode(body)
        endpoint_response = self._call_endpoint(endpoint_request)
        response = self.content_formatter.format_response_payload(endpoint_response)

        return response


class OpenSourceLLM(ToolProvider):

    def __init__(self,
                 connection: CustomConnection = None,
                 endpoint_name: str = None):
        super().__init__()

        self.endpoint_key = None
        self.endpoint_name = endpoint_name

        if endpoint_name is None or endpoint_name == DEFAULT_ENDPOINT_NAME:
            (self.endpoint_uri,
             self.endpoint_key,
             self.model_family) = get_deployment_from_connection(connection)

    @tool
    @handle_oneline_endpoint_error()
    def call(
        self,
        prompt: PromptTemplate,
        api: API,
        deployment_name: str = None,
        temperature: float = 1.0,
        max_new_tokens: int = 500,
        top_p: float = 1.0,
        model_kwargs: Optional[Dict] = {},
        **kwargs
    ) -> str:
        self.deployment_name = deployment_name

        if self.endpoint_key is None and self.endpoint_name is not None:
            (self.endpoint_uri,
             self.endpoint_key,
             self.model_family) = get_deployment_from_endpoint(self.endpoint_name, self.deployment_name)

        prompt = render_jinja_template(prompt, trim_blocks=True, keep_trailing_newline=True, **kwargs)

        model_kwargs["top_p"] = top_p
        model_kwargs["temperature"] = temperature
        model_kwargs["max_new_tokens"] = max_new_tokens

        content_formatter = ContentFormatterFactory.get_content_formatter(
            model_family=self.model_family,
            api=api,
            chat_history=prompt
        )

        llm = AzureMLOnlineEndpoint(
            endpoint_url=self.endpoint_uri,
            endpoint_api_key=self.endpoint_key,
            model_family=self.model_family,
            content_formatter=content_formatter,
            deployment_name=self.deployment_name,
            model_kwargs=model_kwargs
        )

        return llm(prompt)
