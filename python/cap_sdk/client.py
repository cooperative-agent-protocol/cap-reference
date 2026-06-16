# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""gRPC client for connecting to the CAP runtime as a machine agent."""

from __future__ import annotations

import asyncio
import logging
import warnings
from pathlib import Path
from typing import AsyncIterator, Callable, Awaitable, Any

import grpc

from cap.v0.core import runtime_pb2, runtime_pb2_grpc
from cap.v0.core import machine_agent_pb2, common_pb2, entity_pb2, dialogue_pb2

from .frame import (
    make_header,
    wrap_capability_manifest,
    wrap_heartbeat,
    wrap_entity_state_update,
    wrap_agent_dialogue,
)
from .machine_model import MachineModelInterface
from .entity_generator import dict_to_entity_descriptor

logger = logging.getLogger(__name__)


class MachineAgentClient:
    """Connects to the CAP runtime as a machine agent.

    Sends CapabilityManifest on connect, then heartbeats at a fixed interval,
    and processes incoming CapFrames via a user-provided handler.

    Optional model integration:
      - Populates Heartbeat.entity_state_summary via model.generate_state_description()
      - Provides send_dialogue() / send_entity_state_update() convenience methods
    """

    def __init__(
        self,
        *,
        machine_id: str,
        site_agent_id: str,
        server_address: str = "localhost:50051",
        heartbeat_interval_sec: float = 5.0,
        manifest: machine_agent_pb2.CapabilityManifest,
        heartbeat_fn: Callable[[], machine_agent_pb2.Heartbeat],
        on_frame: Callable[[runtime_pb2.CapFrame], Awaitable[runtime_pb2.ConnectRequest | None]],
        model: MachineModelInterface | None = None,
        slm: MachineModelInterface | None = None,  # Deprecated alias for model
        machine_state_fn: Callable[[], dict[str, Any]] | None = None,
        # TLS/mTLS options (Ch09 §9.2.1)
        tls_cert_path: str | Path | None = None,
        tls_key_path: str | Path | None = None,
        tls_ca_path: str | Path | None = None,
    ):
        if slm is not None and model is None:
            warnings.warn(
                "'slm' parameter is deprecated, use 'model' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            model = slm

        self._machine_id = machine_id
        self._site_agent_id = site_agent_id
        self._server_address = server_address
        self._heartbeat_interval = heartbeat_interval_sec
        self._manifest = manifest
        self._heartbeat_fn = heartbeat_fn
        self._on_frame = on_frame
        self._model = model
        self._machine_state_fn = machine_state_fn
        self._outbox: asyncio.Queue[runtime_pb2.ConnectRequest] = asyncio.Queue()
        self._running = False
        self._cached_entity_summary: str = ""
        # TLS
        self._tls_cert_path = Path(tls_cert_path) if tls_cert_path else None
        self._tls_key_path = Path(tls_key_path) if tls_key_path else None
        self._tls_ca_path = Path(tls_ca_path) if tls_ca_path else None

    def _create_channel(self) -> grpc.aio.Channel:
        """Create a gRPC channel (insecure or mTLS)."""
        if self._tls_ca_path is not None:
            ca_cert = self._tls_ca_path.read_bytes()
            client_cert = self._tls_cert_path.read_bytes() if self._tls_cert_path else None
            client_key = self._tls_key_path.read_bytes() if self._tls_key_path else None
            credentials = grpc.ssl_channel_credentials(
                root_certificates=ca_cert,
                private_key=client_key,
                certificate_chain=client_cert,
            )
            logger.info("Connecting with %s to %s", "mTLS" if client_cert else "TLS", self._server_address)
            return grpc.aio.secure_channel(self._server_address, credentials)
        else:
            logger.info("Connecting insecure to %s", self._server_address)
            return grpc.aio.insecure_channel(self._server_address)

    async def run(self) -> None:
        """Connect and run the bidirectional stream until stopped."""
        self._running = True
        async with self._create_channel() as channel:
            stub = runtime_pb2_grpc.CapRuntimeServiceStub(channel)

            # Auto-generate Entity Descriptor descriptor if model is available and manifest lacks one
            if self._model and not self._manifest.HasField("entity_descriptor"):
                try:
                    machine_info = self._build_machine_info()
                    entity_dict = await self._model.generate_entity_descriptor(machine_info)
                    entity_proto = dict_to_entity_descriptor(entity_dict, owner_agent_id=self._machine_id)
                    self._manifest.entity_descriptor.CopyFrom(entity_proto)
                    logger.info("Entity Descriptor auto-generated: %s (%s)", entity_proto.canonical_name, entity_proto.entity_id)
                except Exception as e:
                    logger.warning("Entity Descriptor auto-generation failed: %s", e)

            # Send manifest first
            header = make_header(
                sender_id=self._machine_id,
                receiver_id=self._site_agent_id,
            )
            await self._outbox.put(
                wrap_capability_manifest(header, self._manifest)
            )

            # Run initial state validation if model available
            if self._model and self._machine_state_fn:
                try:
                    state = self._machine_state_fn()
                    validation = await self._model.validate_state(
                        {"entity_id": self._machine_id}, state
                    )
                    if not validation.get("valid", True):
                        logger.warning("Entity Descriptor state validation: %s", validation.get("anomalies", []))
                except Exception as e:
                    logger.debug("Initial validation skipped: %s", e)

            # Start heartbeat task
            hb_task = asyncio.create_task(self._heartbeat_loop())

            try:
                stream = stub.Connect(self._request_iter())
                async for response in stream:
                    frame = response.frame
                    logger.debug("Received frame: %s", frame.header.message_id)
                    reply = await self._on_frame(frame)
                    if reply is not None:
                        await self._outbox.put(reply)
            finally:
                self._running = False
                hb_task.cancel()

    async def send(self, request: runtime_pb2.ConnectRequest) -> None:
        """Enqueue a message to send."""
        await self._outbox.put(request)

    async def send_dialogue(self, dialogue: dialogue_pb2.AgentDialogue) -> None:
        """Send an AgentDialogue message to the site agent."""
        header = make_header(
            sender_id=self._machine_id,
            receiver_id=self._site_agent_id,
        )
        await self._outbox.put(wrap_agent_dialogue(header, dialogue))

    async def send_entity_state_update(self, update: entity_pb2.EntityStateUpdate) -> None:
        """Send an EntityStateUpdate message to the site agent."""
        header = make_header(
            sender_id=self._machine_id,
            receiver_id=self._site_agent_id,
        )
        await self._outbox.put(wrap_entity_state_update(header, update))

    def _build_machine_info(self) -> dict[str, Any]:
        """Extract machine info from manifest for Entity Descriptor generation."""
        m = self._manifest
        return {
            "machine_id": m.machine_id,
            "machine_type": common_pb2.MachineType.Name(m.machine_type),
            "hal_profile": m.hal_profile,
            "software_version": m.software_version,
            "capabilities": [
                {
                    "skill": c.skill,
                    "limits": [{"key": lim.key, "value": lim.value} for lim in c.limits],
                }
                for c in m.capabilities
            ],
            "metadata": [{"key": kv.key, "value": kv.value} for kv in m.metadata],
        }

    def stop(self) -> None:
        """Signal the client to stop."""
        self._running = False

    async def _request_iter(self) -> AsyncIterator[runtime_pb2.ConnectRequest]:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._outbox.get(), timeout=1.0)
                yield msg
            except asyncio.TimeoutError:
                continue

    async def _heartbeat_loop(self) -> None:
        hb_count = 0
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)
            if not self._running:
                break

            hb = self._heartbeat_fn()

            # Refresh model state description every 3rd heartbeat (to manage latency)
            if self._model and self._machine_state_fn and hb_count % 3 == 0:
                try:
                    state = self._machine_state_fn()
                    self._cached_entity_summary = await self._model.generate_state_description(state)
                except Exception as e:
                    logger.warning("Model state description failed: %s", e)

            if self._cached_entity_summary:
                hb.entity_state_summary = self._cached_entity_summary

            header = make_header(
                sender_id=self._machine_id,
                receiver_id=self._site_agent_id,
            )
            await self._outbox.put(wrap_heartbeat(header, hb))
            logger.debug("Sent heartbeat")
            hb_count += 1
