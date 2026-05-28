# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""gRPC transport adapter for CAP.

Wraps the existing gRPC bidirectional streaming into the TransportAdapter
interface.  This is the primary (reference) transport for CAP.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

import grpc

from cap.v0.core import runtime_pb2, runtime_pb2_grpc
from .base import TransportAdapter, TransportConfig

logger = logging.getLogger(__name__)


@dataclass
class GrpcTransportConfig(TransportConfig):
    """Configuration specific to the gRPC transport."""

    port: int = 50051
    max_message_size: int = 4 * 1024 * 1024  # 4 MB
    keepalive_time_ms: int = 30_000  # 30 seconds
    keepalive_timeout_ms: int = 10_000  # 10 seconds
    supported_versions: list[str] = field(default_factory=lambda: ["v0.1"])


class GrpcTransportAdapter(TransportAdapter):
    """gRPC bidirectional streaming transport adapter.

    Client-side adapter: connects to a gRPC CapRuntimeService and provides
    a unified send/receive interface over the bidirectional stream.
    """

    def __init__(self, config: GrpcTransportConfig | None = None) -> None:
        self._config = config or GrpcTransportConfig()
        self._channel: grpc.aio.Channel | None = None
        self._stream = None
        self._outbox: asyncio.Queue[runtime_pb2.CapFrame] = asyncio.Queue()
        self._connected = False
        self._negotiated_version: str | None = None

    async def connect(self) -> None:
        """Establish gRPC channel and start bidirectional stream."""
        address = f"{self._config.host}:{self._config.port}"

        options = [
            ("grpc.max_send_message_length", self._config.max_message_size),
            ("grpc.max_receive_message_length", self._config.max_message_size),
            ("grpc.keepalive_time_ms", self._config.keepalive_time_ms),
            ("grpc.keepalive_timeout_ms", self._config.keepalive_timeout_ms),
        ]

        if self._config.use_tls:
            if self._config.tls_ca_path:
                with open(self._config.tls_ca_path, "rb") as f:
                    ca_cert = f.read()
            else:
                ca_cert = None

            if self._config.tls_cert_path and self._config.tls_key_path:
                with open(self._config.tls_cert_path, "rb") as f:
                    client_cert = f.read()
                with open(self._config.tls_key_path, "rb") as f:
                    client_key = f.read()
                credentials = grpc.ssl_channel_credentials(
                    root_certificates=ca_cert,
                    private_key=client_key,
                    certificate_chain=client_cert,
                )
            else:
                credentials = grpc.ssl_channel_credentials(root_certificates=ca_cert)

            self._channel = grpc.aio.secure_channel(address, credentials, options=options)
        else:
            self._channel = grpc.aio.insecure_channel(address, options=options)

        stub = runtime_pb2_grpc.CapRuntimeServiceStub(self._channel)
        self._stream = stub.Connect(self._request_iter())
        self._connected = True
        logger.info("gRPC transport connected to %s (TLS=%s)", address, self._config.use_tls)

    async def disconnect(self) -> None:
        """Close the gRPC channel."""
        self._connected = False
        if self._channel:
            await self._channel.close()
            self._channel = None
        self._stream = None
        logger.info("gRPC transport disconnected")

    async def send(self, frame: runtime_pb2.CapFrame) -> None:
        """Enqueue a CapFrame to be sent on the gRPC stream."""
        if not self._connected:
            raise ConnectionError("gRPC transport is not connected")
        await self._outbox.put(frame)

    async def receive(self) -> AsyncIterator[runtime_pb2.CapFrame]:
        """Yield incoming CapFrames from the gRPC stream."""
        if self._stream is None:
            raise ConnectionError("gRPC transport is not connected")

        first = True
        async for response in self._stream:
            if first and response.negotiated_version:
                self._negotiated_version = response.negotiated_version
                logger.info("Negotiated protocol version: %s", self._negotiated_version)
                first = False
            yield response.frame

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def negotiated_version(self) -> str | None:
        """Protocol version negotiated with the site agent."""
        return self._negotiated_version

    async def _request_iter(self) -> AsyncIterator[runtime_pb2.ConnectRequest]:
        """Yield ConnectRequests from the outbox queue."""
        first = True
        while self._connected:
            try:
                frame = await asyncio.wait_for(self._outbox.get(), timeout=1.0)
                request = runtime_pb2.ConnectRequest(frame=frame)
                if first:
                    request.supported_versions.extend(self._config.supported_versions)
                    first = False
                yield request
            except asyncio.TimeoutError:
                continue
