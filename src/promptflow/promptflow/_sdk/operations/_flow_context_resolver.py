# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
from functools import lru_cache
from os import PathLike
from pathlib import Path
from typing import Dict

from promptflow._sdk._constants import NODES
from promptflow._sdk._utils import parse_variant
from promptflow._sdk.entities import FlowContext
from promptflow._sdk.entities._flow import Flow
from promptflow._utils.flow_utils import load_flow_dag
from promptflow.contracts.flow import Node
from promptflow.exceptions import UserErrorException

# Resolve flow context to invoker
# Resolve flow according to flow context
#   Resolve connection, variant, overwrite, store in-memory
# create invoker based on resolved flow
# cache invoker if flow context not changed (define hash function for flow context).


class FlowContextResolver:
    """Flow context resolver."""

    def __init__(self, flow_path: PathLike):
        from promptflow import PFClient

        self.flow_path, self.flow_dag = load_flow_dag(flow_path=Path(flow_path))
        self.working_dir = Path(self.flow_path).parent.resolve()
        self.node_name_2_node: Dict[str, Node] = {node["name"]: node for node in self.flow_dag[NODES]}
        self.client = PFClient()

    @classmethod
    @lru_cache
    def resolve(cls, flow: Flow) -> "FlowInvoker":
        """Resolve flow to flow invoker."""
        resolver = cls(flow_path=flow.path)
        resolver._resolve(flow_context=flow.context)
        return resolver._create_invoker(flow=flow, flow_context=flow.context)

    def _resolve(self, flow_context: FlowContext):
        """Resolve flow context."""
        # TODO(2813319): support node overrides
        # TODO: define priority of the contexts
        flow_context._resolve_connections()
        self._resolve_variant(flow_context=flow_context)._resolve_connections(
            flow_context=flow_context,
        )._resolve_overrides(flow_context=flow_context)

    def _resolve_variant(self, flow_context: FlowContext) -> "FlowContextResolver":
        """Resolve variant of the flow and store in-memory."""
        # TODO: put all varint string parser here
        if not flow_context.variant:
            return self
        else:
            tuning_node, variant = parse_variant(flow_context.variant)

        from promptflow._sdk._submitter import overwrite_variant

        overwrite_variant(
            flow_dag=self.flow_dag,
            tuning_node=tuning_node,
            variant=variant,
        )
        return self

    def _resolve_connections(self, flow_context: FlowContext) -> "FlowContextResolver":
        """Resolve connections of the flow and store in-memory."""
        from promptflow._sdk._submitter import overwrite_connections

        overwrite_connections(
            flow_dag=self.flow_dag,
            connections=flow_context.connections,
            working_dir=self.working_dir,
        )
        return self

    def _resolve_overrides(self, flow_context: FlowContext) -> "FlowContextResolver":
        """Resolve overrides of the flow and store in-memory."""
        from promptflow._sdk._submitter import overwrite_flow

        overwrite_flow(
            flow_dag=self.flow_dag,
            params_overrides=flow_context.overrides,
        )

        return self

    def _resolve_connection_objs(self, flow_context: FlowContext):
        # validate connection objs
        connections = {}
        for key, connection_obj in flow_context._connection_objs.items():
            scrubbed_secrets = connection_obj._get_scrubbed_secrets()
            if scrubbed_secrets:
                raise UserErrorException(
                    f"Connection {connection_obj} contains scrubbed secrets with key {scrubbed_secrets.keys()}, "
                    "please make sure connection has decrypted secrets to use in flow execution. "
                )
            connections[key] = connection_obj._to_execution_connection_dict()
        return connections

    def _create_invoker(self, flow: Flow, flow_context: FlowContext) -> "FlowInvoker":
        from promptflow._sdk._serving.flow_invoker import FlowInvoker

        connections = self._resolve_connection_objs(flow_context=flow_context)
        # use updated flow dag to create new flow object for invoker
        resolved_flow = Flow(code=self.working_dir, dag=self.flow_dag)
        invoker = FlowInvoker(
            flow=resolved_flow,
            connections=connections,
            streaming=flow_context.streaming,
        )
        return invoker
