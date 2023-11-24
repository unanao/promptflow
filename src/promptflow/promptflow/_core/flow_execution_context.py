# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import functools
import inspect
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from logging import WARNING
from typing import Callable

from promptflow._core._errors import ToolExecutionError, UnexpectedError
from promptflow._core.cache_manager import AbstractCacheManager, CacheInfo, CacheResult
from promptflow._core.operation_context import OperationContext
from promptflow._utils.logger_utils import flow_logger, logger
from promptflow._utils.thread_utils import RepeatLogTimer
from promptflow._utils.utils import generate_elapsed_time_messages
from promptflow.contracts.flow import Node
from promptflow.contracts.run_info import RunInfo
from promptflow.exceptions import PromptflowException

from .run_tracker import RunTracker
from .thread_local_singleton import ThreadLocalSingleton
from .tracer import Tracer


class FlowExecutionContext(ThreadLocalSingleton):
    """The context for a flow execution."""

    CONTEXT_VAR_NAME = "Flow"
    context_var = ContextVar(CONTEXT_VAR_NAME, default=None)

    def __init__(
        self,
        name,
        run_tracker: RunTracker,
        cache_manager: AbstractCacheManager,
        run_id=None,
        flow_id=None,
        line_number=None,
        variant_id=None,
    ):
        self._name = name
        self._run_tracker = run_tracker
        self._cache_manager = cache_manager
        self._run_id = run_id or str(uuid.uuid4())
        self._flow_id = flow_id or self._run_id
        self._line_number = line_number
        self._variant_id = variant_id

    def copy(self):
        return FlowExecutionContext(
            name=self._name,
            run_tracker=self._run_tracker,
            cache_manager=self._cache_manager,
            run_id=self._run_id,
            flow_id=self._flow_id,
            line_number=self._line_number,
            variant_id=self._variant_id,
        )

    def _update_operation_context(self):
        flow_context_info = {"flow-id": self._flow_id, "root-run-id": self._run_id}
        OperationContext.get_instance().update(flow_context_info)

    def invoke_tool(self, node: Node, f: Callable, kwargs):
        run_info = self._prepare_node_run(node, f, kwargs)
        node_run_id = run_info.run_id

        traces = []
        try:
            hit_cache = False
            # Get result from cache. If hit cache, no need to execute f.
            cache_info: CacheInfo = self._cache_manager.calculate_cache_info(self._flow_id, f, [], kwargs)
            if node.enable_cache and cache_info:
                cache_result: CacheResult = self._cache_manager.get_cache_result(cache_info)
                if cache_result and cache_result.hit_cache:
                    # Assign cached_flow_run_id and cached_run_id.
                    run_info.cached_flow_run_id = cache_result.cached_flow_run_id
                    run_info.cached_run_id = cache_result.cached_run_id
                    result = cache_result.result
                    hit_cache = True

            if not hit_cache:
                Tracer.start_tracing(node_run_id, node.name)
                result = self._invoke_tool_with_timer(node, f, kwargs)
                traces = Tracer.end_tracing(node_run_id)

            self._run_tracker.end_run(node_run_id, result=result, traces=traces)
            # Record result in cache so that future run might reuse its result.
            if not hit_cache and node.enable_cache:
                self._persist_cache(cache_info, run_info)

            flow_logger.info(f"Node {node.name} completes.")
            return result
        except Exception as e:
            logger.exception(f"Node {node.name} in line {self._line_number} failed. Exception: {e}.")
            if not traces:
                traces = Tracer.end_tracing(node_run_id)
            self._run_tracker.end_run(node_run_id, ex=e, traces=traces)
            raise
        finally:
            self._run_tracker.persist_node_run(run_info)

    def _prepare_node_run(self, node: Node, f, kwargs={}):
        # Ensure this thread has a valid operation context
        self._update_operation_context()
        node_run_id = self._generate_node_run_id(node)
        flow_logger.info(f"Executing node {node.name}. node run id: {node_run_id}")
        parent_run_id = f"{self._run_id}_{self._line_number}" if self._line_number is not None else self._run_id
        run_info: RunInfo = self._run_tracker.start_node_run(
            node=node.name,
            flow_run_id=self._run_id,
            parent_run_id=parent_run_id,
            run_id=node_run_id,
            index=self._line_number,
        )
        run_info.index = self._line_number
        run_info.variant_id = self._variant_id
        self._run_tracker.set_inputs(node_run_id, {key: value for key, value in kwargs.items() if key != "self"})
        return run_info

    async def invoke_tool_async(self, node: Node, f: Callable, kwargs):
        if not inspect.iscoroutinefunction(f):
            raise UnexpectedError(
                message_format="Tool '{function}' in node '{node}' is not a coroutine function.",
                function=f,
                node=node.name,
            )
        run_info = self._prepare_node_run(node, f, kwargs=kwargs)
        node_run_id = run_info.run_id

        traces = []
        try:
            Tracer.start_tracing(node_run_id, node.name)
            result = await self._invoke_tool_async_inner(node, f, kwargs)
            traces = Tracer.end_tracing(node_run_id)
            self._run_tracker.end_run(node_run_id, result=result, traces=traces)
            flow_logger.info(f"Node {node.name} completes.")
            return result
        except Exception as e:
            logger.exception(f"Node {node.name} in line {self._line_number} failed. Exception: {e}.")
            traces = Tracer.end_tracing(node_run_id)
            self._run_tracker.end_run(node_run_id, ex=e, traces=traces)
            raise
        finally:
            self._run_tracker.persist_node_run(run_info)

    async def _invoke_tool_async_inner(self, node: Node, f: Callable, kwargs):
        module = f.func.__module__ if isinstance(f, functools.partial) else f.__module__
        try:
            return await f(**kwargs)
        except PromptflowException as e:
            # All the exceptions from built-in tools are PromptflowException.
            # For these cases, raise the exception directly.
            if module is not None:
                e.module = module
            raise e
        except Exception as e:
            # Otherwise, we assume the error comes from user's tool.
            # For these cases, raise ToolExecutionError, which is classified as UserError
            # and shows stack trace in the error message to make it easy for user to troubleshoot.
            raise ToolExecutionError(node_name=node.name, module=module) from e

    def _invoke_tool_with_timer(self, node: Node, f: Callable, kwargs):
        module = f.func.__module__ if isinstance(f, functools.partial) else f.__module__
        node_name = node.name
        try:
            logging_name = node_name
            if self._line_number is not None:
                logging_name = f"{node_name} in line {self._line_number}"
            interval_seconds = 60
            start_time = time.perf_counter()
            thread_id = threading.current_thread().ident
            with RepeatLogTimer(
                interval_seconds=interval_seconds,
                logger=logger,
                level=WARNING,
                log_message_function=generate_elapsed_time_messages,
                args=(logging_name, start_time, interval_seconds, thread_id),
            ):
                return f(**kwargs)
        except PromptflowException as e:
            # All the exceptions from built-in tools are PromptflowException.
            # For these cases, raise the exception directly.
            if module is not None:
                e.module = module
            raise e
        except Exception as e:
            # Otherwise, we assume the error comes from user's tool.
            # For these cases, raise ToolExecutionError, which is classified as UserError
            # and shows stack trace in the error message to make it easy for user to troubleshoot.
            raise ToolExecutionError(node_name=node_name, module=module) from e

    def bypass_node(self, node: Node):
        """Update teh bypassed node run info."""
        node_run_id = self._generate_node_run_id(node)
        flow_logger.info(f"Bypassing node {node.name}. node run id: {node_run_id}")
        parent_run_id = f"{self._run_id}_{self._line_number}" if self._line_number is not None else self._run_id
        run_info = self._run_tracker.bypass_node_run(
            node=node.name,
            flow_run_id=self._run_id,
            parent_run_id=parent_run_id,
            run_id=node_run_id,
            index=self._line_number,
            variant_id=self._variant_id,
        )
        self._run_tracker.persist_node_run(run_info)

    def _persist_cache(self, cache_info: CacheInfo, run_info: RunInfo):
        """Record result in cache storage if hash_id is valid."""
        if cache_info and cache_info.hash_id is not None and len(cache_info.hash_id) > 0:
            try:
                self._cache_manager.persist_result(run_info, cache_info, self._flow_id)
            except Exception as ex:
                # Not a critical path, swallow the exception.
                logging.warning(f"Failed to persist cache result. run_id: {run_info.run_id}. Exception: {ex}")

    def _generate_node_run_id(self, node: Node) -> str:
        if node.aggregation:
            # For reduce node, the id should be constructed by the flow run info run id
            return f"{self._run_id}_{node.name}_reduce"
        if self._line_number is None:
            return f"{self._run_id}_{node.name}_{uuid.uuid4()}"
        return f"{self._run_id}_{node.name}_{self._line_number}"
