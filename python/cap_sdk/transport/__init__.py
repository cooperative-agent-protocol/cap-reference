# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""CAP transport adapters.

Provides an abstract TransportAdapter interface and concrete implementations
for gRPC, MQTT, and WebSocket transports.
"""

from .base import TransportAdapter, TransportConfig
from .grpc_adapter import GrpcTransportAdapter, GrpcTransportConfig
from .mqtt_adapter import MqttTransportAdapter, MqttTransportConfig

__all__ = [
    "TransportAdapter",
    "TransportConfig",
    "GrpcTransportAdapter",
    "GrpcTransportConfig",
    "MqttTransportAdapter",
    "MqttTransportConfig",
]
