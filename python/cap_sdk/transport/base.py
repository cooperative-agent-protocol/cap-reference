# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Abstract base class for CAP transport adapters.

A TransportAdapter handles the sending and receiving of CapFrame messages
over a specific transport protocol (gRPC, MQTT, WebSocket).  The adapter
is responsible for:
  - establishing and tearing down the transport connection
  - serialising/deserialising CapFrame messages
  - providing an async iterator for incoming frames
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import AsyncIterator

from cap.v0.core import runtime_pb2


@dataclass
class TransportConfig:
    """Base configuration for all transports."""

    host: str = "localhost"
    port: int = 50051
    use_tls: bool = False
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    tls_ca_path: str | None = None


class TransportAdapter(abc.ABC):
    """Abstract interface for CAP message transport.

    Implementations must support bidirectional CapFrame exchange.
    The adapter owns the connection lifecycle: connect → send/receive → disconnect.
    """

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish the transport connection.

        Raises:
            ConnectionError: if the connection cannot be established.
        """

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the transport connection."""

    @abc.abstractmethod
    async def send(self, frame: runtime_pb2.CapFrame) -> None:
        """Send a single CapFrame to the peer.

        Args:
            frame: The CapFrame to send.

        Raises:
            ConnectionError: if the transport is not connected.
        """

    @abc.abstractmethod
    def receive(self) -> AsyncIterator[runtime_pb2.CapFrame]:
        """Yield incoming CapFrames from the peer.

        Returns:
            An async iterator of CapFrame messages.

        Raises:
            ConnectionError: if the transport is disconnected mid-iteration.
        """

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Whether the transport is currently connected."""
