# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""gRPC server implementing the CAP runtime (site agent side)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Callable, Awaitable

import grpc

from cap.v0.core import runtime_pb2, runtime_pb2_grpc
from cap.v0.core import machine_agent_pb2, error_pb2, common_pb2

from .frame import make_header
from .security.rbac import RBACEnforcer, Role

logger = logging.getLogger(__name__)

# Default timeout for heartbeat (seconds)
DEFAULT_HEARTBEAT_TIMEOUT = 15.0


class ConnectedMachine:
    """Tracks state of a connected machine agent."""

    def __init__(self, machine_id: str, heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT):
        self.machine_id = machine_id
        self.manifest: machine_agent_pb2.CapabilityManifest | None = None
        self.last_heartbeat: float = time.monotonic()
        self.outbox: asyncio.Queue[runtime_pb2.ConnectResponse] = asyncio.Queue()
        self.heartbeat_timeout = heartbeat_timeout
        self.timed_out_flagged = False  # set once the reaper has reported this machine

    @property
    def is_alive(self) -> bool:
        return (time.monotonic() - self.last_heartbeat) < self.heartbeat_timeout


class CapRuntimeServicer(runtime_pb2_grpc.CapRuntimeServiceServicer):
    """Site-agent-side implementation of the CAP runtime service.

    For each connected machine, maintains state and dispatches frames
    to a user-provided handler.

    When `enforce_rbac=True`, validates each incoming CapFrame against the
    Role × Message authorization matrix (Ch09 §9.3.2). When mTLS is active,
    also verifies that the client certificate CN matches the machine_id in
    CapabilityManifest (Ch09 §9.2.1).
    """

    def __init__(
        self,
        on_frame: Callable[[str, runtime_pb2.CapFrame], Awaitable[runtime_pb2.ConnectResponse | None]],
        *,
        enforce_rbac: bool = False,
        site_agent_id: str = "site-agent-01",
        enforce_manifest_first: bool = True,
        heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
        reaper_interval: float = 5.0,
        on_machine_timeout: Callable[[str], Awaitable[None]] | None = None,
    ):
        self._on_frame = on_frame
        self._machines: dict[str, ConnectedMachine] = {}
        self._enforce_rbac = enforce_rbac
        self._rbac = RBACEnforcer() if enforce_rbac else None
        self._site_agent_id = site_agent_id
        self._enforce_manifest_first = enforce_manifest_first
        self._heartbeat_timeout = heartbeat_timeout
        self._reaper_interval = reaper_interval
        self._on_machine_timeout = on_machine_timeout
        self._reaper_task: asyncio.Task | None = None

    @property
    def machines(self) -> dict[str, ConnectedMachine]:
        return self._machines

    def _extract_client_cn(self, context: grpc.aio.ServicerContext) -> str | None:
        """Extract CN from client certificate (mTLS). Returns None if not available."""
        try:
            auth_context = context.auth_context()
            if auth_context and "x509_common_name" in auth_context:
                cn_list = auth_context["x509_common_name"]
                if cn_list:
                    return cn_list[0].decode("utf-8") if isinstance(cn_list[0], bytes) else cn_list[0]
        except Exception:
            pass
        return None

    def _make_error_response(
        self, error_code: int, message: str, related_id: str = "",
        severity: int = common_pb2.FAULT_SEVERITY_ERROR,
    ) -> runtime_pb2.ConnectResponse:
        """Build a ConnectResponse containing a CapError."""
        header = make_header(sender_id=self._site_agent_id, receiver_id="")
        if related_id:
            header.correlation_id = related_id
        frame = runtime_pb2.CapFrame(
            header=header,
            cap_error=error_pb2.CapError(
                error_code=error_code,
                domain=error_pb2.ERROR_DOMAIN_APPLICATION,
                message=message,
                related_message_id=related_id,
                severity=severity,
                retryable=False,
            ),
        )
        return runtime_pb2.ConnectResponse(frame=frame)

    async def Connect(
        self,
        request_iterator,
        context: grpc.aio.ServicerContext,
    ):
        machine_id: str | None = None
        client_cn = self._extract_client_cn(context)

        try:
            async for request in request_iterator:
                frame = request.frame
                sender = frame.header.sender_id

                # Register on first message
                if machine_id is None:
                    machine_id = sender
                    self._machines[machine_id] = ConnectedMachine(machine_id, self._heartbeat_timeout)
                    logger.info("Machine connected: %s", machine_id)

                machine = self._machines[machine_id]

                # Manifest-first enforcement (Ch10 §10.2.1): the first frame in a
                # CAP stream MUST be a CapabilityManifest. Reject any earlier frame
                # with CapError(2006, UNEXPECTED_MESSAGE) and close the stream.
                if (
                    self._enforce_manifest_first
                    and machine.manifest is None
                    and not frame.HasField("capability_manifest")
                ):
                    logger.warning(
                        "Machine %s sent %s before CapabilityManifest",
                        machine_id, frame.WhichOneof("body"),
                    )
                    yield self._make_error_response(
                        2006,
                        "first message in a CAP stream must be CapabilityManifest",
                        frame.header.message_id,
                        severity=common_pb2.FAULT_SEVERITY_CRITICAL,
                    )
                    return  # close stream per Ch10 §10.2.1

                # Track manifest + mTLS CN validation (Ch09 §9.2.1)
                if frame.HasField("capability_manifest"):
                    machine.manifest = frame.capability_manifest
                    manifest_mid = machine.manifest.machine_id

                    if client_cn is not None and manifest_mid != client_cn:
                        logger.warning(
                            "mTLS CN mismatch: cert CN=%s, manifest machine_id=%s",
                            client_cn, manifest_mid,
                        )
                        yield self._make_error_response(
                            3006,
                            f"machine_id '{manifest_mid}' does not match certificate CN '{client_cn}'",
                            frame.header.message_id,
                        )
                        return  # Close stream per Ch09 §9.2.1

                    logger.info(
                        "Received manifest from %s: type=%s, skills=%s",
                        machine_id,
                        machine.manifest.machine_type,
                        [c.skill for c in machine.manifest.capabilities],
                    )

                # RBAC enforcement (Ch09 §9.3.2)
                if self._rbac is not None:
                    role = self._rbac.role_for_machine_id(machine_id)
                    decision = self._rbac.check(role, frame)
                    if not decision.allowed:
                        logger.warning("RBAC denied: %s", decision.reason)
                        yield self._make_error_response(
                            3006,
                            decision.reason,
                            frame.header.message_id,
                        )
                        continue  # Stream stays open per Ch08 §8.1.1

                # Track heartbeat
                if frame.HasField("heartbeat"):
                    machine.last_heartbeat = time.monotonic()

                # Dispatch to handler
                response = await self._on_frame(machine_id, frame)
                if response is not None:
                    yield response

                # Drain outbox (for messages queued by site agent logic)
                while not machine.outbox.empty():
                    yield machine.outbox.get_nowait()

        finally:
            if machine_id and machine_id in self._machines:
                del self._machines[machine_id]
                logger.info("Machine disconnected: %s", machine_id)

    async def send_to_machine(
        self, machine_id: str, response: runtime_pb2.ConnectResponse
    ) -> None:
        """Queue a message to send to a specific machine."""
        machine = self._machines.get(machine_id)
        if machine is None:
            raise ValueError(f"Machine {machine_id} not connected")
        await machine.outbox.put(response)

    def start_reaper(self) -> None:
        """Start the background heartbeat-timeout reaper.

        Every ``reaper_interval`` seconds the reaper detects machines whose last
        heartbeat is older than ``heartbeat_timeout`` (Ch10 §10.2.1: detect
        heartbeat timeout and mark the machine disconnected) and reports each one
        exactly once via the ``on_machine_timeout`` callback. It does not delete
        the registry entry -- the Connect coroutine owns the stream lifecycle --
        it surfaces the timeout so the Site Agent can react (e.g., release the
        timed-out machine's reservations). Idempotent; safe to call once at
        startup.
        """
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reaper_loop())

    async def stop_reaper(self) -> None:
        """Stop the background reaper, if running."""
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reaper_interval)
            for machine in list(self._machines.values()):
                if not machine.is_alive and not machine.timed_out_flagged:
                    machine.timed_out_flagged = True
                    logger.warning("Heartbeat timeout: machine %s", machine.machine_id)
                    if self._on_machine_timeout is not None:
                        await self._on_machine_timeout(machine.machine_id)
                elif machine.is_alive and machine.timed_out_flagged:
                    machine.timed_out_flagged = False  # re-armed after a fresh heartbeat


async def serve(servicer: CapRuntimeServicer, port: int = 50051) -> grpc.aio.Server:
    """Start the gRPC server (insecure — for development/testing only)."""
    server = grpc.aio.server()
    runtime_pb2_grpc.add_CapRuntimeServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    logger.info("CAP runtime server started on port %d (insecure)", port)
    return server


async def serve_secure(
    servicer: CapRuntimeServicer,
    *,
    port: int = 50051,
    server_cert_path: str | Path,
    server_key_path: str | Path,
    ca_cert_path: str | Path,
    require_client_cert: bool = True,
) -> grpc.aio.Server:
    """Start the gRPC server with TLS/mTLS (Ch09 §9.2.1, §9.4.1).

    Args:
        servicer: The CapRuntimeServicer.
        port: Port to listen on.
        server_cert_path: Path to the server certificate PEM.
        server_key_path: Path to the server private key PEM.
        ca_cert_path: Path to the CA certificate PEM (for client cert validation).
        require_client_cert: If True, require client certificates (mTLS).
                            If False, only server TLS is enforced.

    Returns:
        The started gRPC server.
    """
    server_cert = Path(server_cert_path).read_bytes()
    server_key = Path(server_key_path).read_bytes()
    ca_cert = Path(ca_cert_path).read_bytes()

    server_credentials = grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca_cert,
        require_client_auth=require_client_cert,
    )

    server = grpc.aio.server()
    runtime_pb2_grpc.add_CapRuntimeServiceServicer_to_server(servicer, server)
    server.add_secure_port(f"[::]:{port}", server_credentials)
    await server.start()

    mode = "mTLS" if require_client_cert else "TLS"
    logger.info("CAP runtime server started on port %d (%s)", port, mode)
    return server
