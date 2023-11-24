# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

from promptflow._utils.exception_utils import ExceptionPresenter, infer_error_code_from_class
from promptflow.exceptions import (
    ErrorTarget,
    PromptflowException,
    SystemErrorException,
    UserErrorException,
    ValidationException,
)


class InvalidCustomLLMTool(ValidationException):
    """Exception raised when package tool definition is wrong."""

    pass


class ValueTypeUnresolved(ValidationException):
    pass


class ToolValidationError(ValidationException):
    def __init__(
        self,
        target: ErrorTarget = ErrorTarget.EXECUTOR,
        **kwargs,
    ):
        super().__init__(
            target=target,
            **kwargs,
        )


class InvalidRequest(ValidationException):
    def __init__(
        self,
        target: ErrorTarget = ErrorTarget.EXECUTOR,
        **kwargs,
    ):
        super().__init__(
            target=target,
            **kwargs,
        )


class ConnectionNotFound(InvalidRequest):
    pass


class InvalidBulkTestRequest(ValidationException):
    def __init__(
        self,
        target: ErrorTarget = ErrorTarget.EXECUTOR,
        **kwargs,
    ):
        super().__init__(
            target=target,
            **kwargs,
        )


class InvalidFlowRequest(ValidationException):
    def __init__(
        self,
        target: ErrorTarget = ErrorTarget.EXECUTOR,
        **kwargs,
    ):
        super().__init__(
            target=target,
            **kwargs,
        )


class InvalidSource(ValidationException):
    pass


class NodeInputValidationError(InvalidFlowRequest):
    pass


class DuplicateNodeName(InvalidFlowRequest):
    pass


class EmptyOutputReference(InvalidFlowRequest):
    pass


class OutputReferenceNotFound(InvalidFlowRequest):
    pass


class InputReferenceNotFound(InvalidFlowRequest):
    pass


class InputNotFound(InvalidFlowRequest):
    pass


class InvalidAggregationInput(SystemErrorException):
    pass


class InputNotFoundFromAncestorNodeOutput(SystemErrorException):
    pass


class NoNodeExecutedError(SystemErrorException):
    pass


class InputTypeError(InvalidFlowRequest):
    pass


class InputParseError(InvalidFlowRequest):
    pass


class InvalidConnectionType(InvalidFlowRequest):
    pass


class NodeReferenceNotFound(InvalidFlowRequest):
    pass


class NodeCircularDependency(InvalidFlowRequest):
    pass


class InvalidNodeReference(InvalidFlowRequest):
    pass


class NodeReferenceError(UserErrorException):
    """Exception raised when node reference not found or unsupported"""

    pass


class UnsupportedReference(NodeReferenceError):
    pass


class InvalidReferenceProperty(NodeReferenceError):
    pass


class OutputReferenceNotExist(NodeReferenceError):
    pass


class NodeOutputNotFound(UserErrorException):
    pass


class SingleNodeValidationError(UserErrorException):
    pass


class LineExecutionTimeoutError(UserErrorException):
    """Exception raised when single line execution timeout"""

    def __init__(self, line_number, timeout):
        super().__init__(
            message=f"Line {line_number} execution timeout for exceeding {timeout} seconds", target=ErrorTarget.EXECUTOR
        )


class EmptyLLMApiMapping(UserErrorException):
    """Exception raised when connection_type_to_api_mapping is empty and llm node provider can't be inferred"""

    def __init__(self):
        super().__init__(
            message="LLM api mapping is empty, please ensure 'promptflow-tools' package has been installed.",
            target=ErrorTarget.EXECUTOR,
        )


class ResolveToolError(PromptflowException):
    """Exception raised when tool load failed.

    It is used to append the name of the failed node to the error message to improve the user experience.
    It simply wraps the error thrown by the Resolve Tool phase.
    It has the same additional_info and error_codes as inner error.
    """

    def __init__(self, *, node_name: str, target: ErrorTarget = ErrorTarget.EXECUTOR, module: str = None):
        self._node_name = node_name
        super().__init__(target=target, module=module)

    @property
    def message_format(self):
        if self.inner_exception:
            return "Tool load failed in '{node_name}': {error_type_and_message}"
        else:
            return "Tool load failed in '{node_name}'."

    @property
    def message_parameters(self):
        error_type_and_message = None
        if self.inner_exception:
            error_type_and_message = f"({self.inner_exception.__class__.__name__}) {self.inner_exception}"

        return {
            "node_name": self._node_name,
            "error_type_and_message": error_type_and_message,
        }

    @property
    def additional_info(self):
        """Get additional info from innererror when the innererror is PromptflowException"""
        if isinstance(self.inner_exception, PromptflowException):
            return self.inner_exception.additional_info
        return None

    @property
    def error_codes(self):
        """The hierarchy of the error codes.

        We follow the "Microsoft REST API Guidelines" to define error codes in a hierarchy style.
        See the below link for details:
        https://github.com/microsoft/api-guidelines/blob/vNext/Guidelines.md#7102-error-condition-responses

        Due to ResolveToolError has no classification of its own.
        Its error_codes respect the inner_error.
        """
        if self.inner_exception:
            return ExceptionPresenter.create(self.inner_exception).error_codes
        return [infer_error_code_from_class(SystemErrorException), self.__class__.__name__]
