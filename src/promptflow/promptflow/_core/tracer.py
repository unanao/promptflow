# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import inspect
import json
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import datetime
from typing import Optional

from promptflow._core.generator_proxy import GeneratorProxy, generate_from_proxy
from promptflow._utils.dataclass_serializer import serialize
from promptflow._utils.multimedia_utils import default_json_encoder
from promptflow.contracts.tool import ConnectionType
from promptflow.contracts.trace import Trace, TraceType

from .thread_local_singleton import ThreadLocalSingleton


class Tracer(ThreadLocalSingleton):
    CONTEXT_VAR_NAME = "Tracer"
    context_var = ContextVar(CONTEXT_VAR_NAME, default=None)

    def __init__(self, run_id, node_name: Optional[str] = None):
        self._run_id = run_id
        self._node_name = node_name
        self._traces = []
        self._trace_stack = []

    @classmethod
    def start_tracing(cls, run_id, node_name: Optional[str] = None):
        current_run_id = cls.current_run_id()
        if current_run_id is not None:
            msg = f"Try to start tracing for run {run_id} but {current_run_id} is already active."
            logging.warning(msg)
            return
        tracer = cls(run_id, node_name)
        tracer._activate_in_context()

    @classmethod
    def current_run_id(cls):
        tracer = cls.active_instance()
        if not tracer:
            return None
        return tracer._run_id

    @classmethod
    def end_tracing(cls, run_id: Optional[str] = None, raise_ex=False):
        tracer = cls.active_instance()
        if not tracer:
            msg = "Try end tracing but no active tracer in current context."
            if raise_ex:
                raise Exception(msg)
            logging.warning(msg)
            return []
        if run_id is not None and tracer._run_id != run_id:
            msg = f"Try to end tracing for run {run_id} but {tracer._run_id} is active."
            logging.warning(msg)
            return []
        tracer._deactivate_in_context()
        return tracer.to_json()

    @classmethod
    def push_tool(cls, f, args=[], kwargs={}):
        obj = cls.active_instance()
        sig = inspect.signature(f).parameters
        all_kwargs = {**{k: v for k, v in zip(sig.keys(), args)}, **kwargs}
        all_kwargs = {
            k: ConnectionType.serialize_conn(v) if ConnectionType.is_connection_value(v) else v
            for k, v in all_kwargs.items()
        }
        # TODO: put parameters in self to inputs for builtin tools
        all_kwargs.pop("self", None)
        trace = Trace(
            name=f.__qualname__,
            type=TraceType.TOOL,
            start_time=datetime.utcnow().timestamp(),
            inputs=all_kwargs,
        )
        obj._push(trace)
        return trace

    @classmethod
    def push(cls, trace: Trace):
        obj = cls.active_instance()
        if not obj:
            logging.warning("Try to push trace but no active tracer in current context.")
            return
        obj._push(trace)

    @staticmethod
    def to_serializable(obj):
        if isinstance(obj, dict) and all(isinstance(k, str) for k in obj.keys()):
            return {k: Tracer.to_serializable(v) for k, v in obj.items()}
        if isinstance(obj, GeneratorProxy):
            return obj
        try:
            obj = serialize(obj)
            json.dumps(obj, default=default_json_encoder)
        except Exception:
            # We don't want to fail the whole function call because of a serialization error,
            # so we simply convert it to str if it cannot be serialized.
            obj = str(obj)
        return obj

    def _push(self, trace: Trace):
        if trace.inputs:
            trace.inputs = self.to_serializable(trace.inputs)
        if not trace.start_time:
            trace.start_time = datetime.utcnow().timestamp()
        if not self._trace_stack:
            # Set node name for root trace
            trace.node_name = self._node_name
            self._traces.append(trace)
        else:
            self._trace_stack[-1].children = self._trace_stack[-1].children or []
            self._trace_stack[-1].children.append(trace)
        self._trace_stack.append(trace)

    @classmethod
    def pop(cls, output=None, error: Optional[Exception] = None):
        obj = cls.active_instance()
        return obj._pop(output, error)

    def _pop(self, output=None, error: Optional[Exception] = None):
        last_trace = self._trace_stack[-1]
        if isinstance(output, Iterator):
            output = GeneratorProxy(output)
        if output is not None:
            last_trace.output = self.to_serializable(output)
        if error is not None:
            last_trace.error = self._format_error(error)
        self._trace_stack[-1].end_time = datetime.utcnow().timestamp()
        self._trace_stack.pop()

        if isinstance(output, GeneratorProxy):
            return generate_from_proxy(output)
        else:
            return output

    def to_json(self) -> list:
        return serialize(self._traces)

    @staticmethod
    def _format_error(error: Exception) -> dict:
        return {
            "message": str(error),
            "type": type(error).__qualname__,
        }
