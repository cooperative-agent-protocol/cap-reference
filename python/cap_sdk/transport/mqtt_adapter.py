# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""MQTT transport adapter for CAP.

Maps CapFrame messages to MQTT topics following the CAP MQTT transport profile:
  - Upstream (machine → site):  cap/v0/{site_id}/machines/{machine_id}/up
  - Downstream (site → machine): cap/v0/{site_id}/machines/{machine_id}/down
  - Broadcast events:            cap/v0/{site_id}/events
  - Site-wide control:           cap/v0/{site_id}/control

Requires the ``aiomqtt`` package (``pip install aiomqtt``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

from cap.v0.core import runtime_pb2, events_pb2, common_pb2

from .base import TransportAdapter, TransportConfig

logger = logging.getLogger(__name__)

# QoS mapping per message type (see ch04-communication-model.md §4.4.3)
_QOS_MAP: dict[str, int] = {
    "heartbeat": 0,
    "progress_event": 0,
    "alo_state_update": 0,
    # Everything else defaults to QoS 1
}


def _qos_for_frame(frame: runtime_pb2.CapFrame) -> int:
    """Return the MQTT QoS level for a given CapFrame body type."""
    body_field = frame.WhichOneof("body")
    return _QOS_MAP.get(body_field, 1)


@dataclass
class MqttTransportConfig(TransportConfig):
    """Configuration specific to the MQTT transport."""

    port: int = 1883
    site_id: str = "default"
    machine_id: str = ""
    role: str = "machine_agent"  # "machine_agent" | "site_agent" | "observer"
    username: str | None = None
    password: str | None = None
    keepalive: int = 60  # MQTT keepalive in seconds
    topic_prefix: str = "cap/v0"
    # Last Will and Testament
    lwt_enabled: bool = True

    @property
    def upstream_topic(self) -> str:
        """Topic for machine → site messages."""
        return f"{self.topic_prefix}/{self.site_id}/machines/{self.machine_id}/up"

    @property
    def downstream_topic(self) -> str:
        """Topic for site → machine messages."""
        return f"{self.topic_prefix}/{self.site_id}/machines/{self.machine_id}/down"

    @property
    def events_topic(self) -> str:
        """Broadcast events topic."""
        return f"{self.topic_prefix}/{self.site_id}/events"

    @property
    def control_topic(self) -> str:
        """Site-wide control topic."""
        return f"{self.topic_prefix}/{self.site_id}/control"

    @property
    def subscribe_topic_machine(self) -> str:
        """Topic pattern for machine to subscribe to."""
        return self.downstream_topic

    @property
    def subscribe_topic_site(self) -> str:
        """Topic pattern for site agent to subscribe to (wildcard)."""
        return f"{self.topic_prefix}/{self.site_id}/machines/+/up"


def _build_lwt_payload(machine_id: str) -> bytes:
    """Build the Last Will and Testament payload — a CapFrame with FaultEvent."""
    fault = events_pb2.FaultEvent(
        machine_id=machine_id,
        severity=common_pb2.FAULT_SEVERITY_ERROR,
        fault_code="UNEXPECTED_DISCONNECT",
        summary=f"Machine agent {machine_id} disconnected unexpectedly",
    )
    frame = runtime_pb2.CapFrame()
    frame.fault_event.CopyFrom(fault)
    return frame.SerializeToString()


class MqttTransportAdapter(TransportAdapter):
    """MQTT transport adapter for CAP.

    Supports both machine_agent role (publishes to upstream, subscribes to
    downstream) and site_agent role (publishes to downstream, subscribes
    to upstream wildcard).
    """

    def __init__(self, config: MqttTransportConfig) -> None:
        self._config = config
        self._client = None
        self._connected = False
        self._incoming: asyncio.Queue[runtime_pb2.CapFrame] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None
        self._seen_message_ids: set[str] = set()
        self._max_seen_ids: int = 10_000

    async def connect(self) -> None:
        """Connect to the MQTT broker and subscribe to relevant topics."""
        try:
            import aiomqtt
        except ImportError:
            raise ImportError(
                "aiomqtt is required for MQTT transport. "
                "Install it with: pip install aiomqtt"
            )

        # Build MQTT client kwargs
        kwargs: dict = {
            "hostname": self._config.host,
            "port": self._config.port,
            "keepalive": self._config.keepalive,
        }

        if self._config.username:
            kwargs["username"] = self._config.username
        if self._config.password:
            kwargs["password"] = self._config.password

        # TLS configuration
        if self._config.use_tls:
            import ssl

            tls_context = ssl.create_default_context()
            if self._config.tls_ca_path:
                tls_context.load_verify_locations(self._config.tls_ca_path)
            if self._config.tls_cert_path and self._config.tls_key_path:
                tls_context.load_cert_chain(
                    self._config.tls_cert_path,
                    self._config.tls_key_path,
                )
            kwargs["tls_context"] = tls_context

        # Last Will and Testament
        if self._config.lwt_enabled and self._config.role == "machine_agent":
            kwargs["will"] = aiomqtt.Will(
                topic=self._config.upstream_topic,
                payload=_build_lwt_payload(self._config.machine_id),
                qos=1,
                retain=False,
            )

        self._mqtt_client_cm = aiomqtt.Client(**kwargs)
        self._client = await self._mqtt_client_cm.__aenter__()
        self._connected = True

        # Subscribe based on role
        if self._config.role == "machine_agent":
            await self._client.subscribe(self._config.subscribe_topic_machine, qos=1)
            await self._client.subscribe(self._config.events_topic, qos=1)
            await self._client.subscribe(self._config.control_topic, qos=1)
            logger.info(
                "MQTT machine agent subscribed: %s, %s, %s",
                self._config.subscribe_topic_machine,
                self._config.events_topic,
                self._config.control_topic,
            )
        elif self._config.role == "site_agent":
            await self._client.subscribe(self._config.subscribe_topic_site, qos=1)
            logger.info(
                "MQTT site agent subscribed: %s",
                self._config.subscribe_topic_site,
            )
        elif self._config.role == "observer":
            await self._client.subscribe(self._config.events_topic, qos=0)
            logger.info("MQTT observer subscribed: %s", self._config.events_topic)

        # Start background message receiver
        self._recv_task = asyncio.create_task(self._message_loop())

        logger.info(
            "MQTT transport connected to %s:%d (site=%s, role=%s)",
            self._config.host,
            self._config.port,
            self._config.site_id,
            self._config.role,
        )

    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        self._connected = False
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._client:
            await self._mqtt_client_cm.__aexit__(None, None, None)
            self._client = None
        logger.info("MQTT transport disconnected")

    async def send(self, frame: runtime_pb2.CapFrame) -> None:
        """Publish a CapFrame to the appropriate MQTT topic."""
        if not self._connected or not self._client:
            raise ConnectionError("MQTT transport is not connected")

        topic = self._resolve_publish_topic(frame)
        qos = _qos_for_frame(frame)
        payload = frame.SerializeToString()

        await self._client.publish(topic, payload, qos=qos)
        logger.debug(
            "MQTT published to %s (qos=%d, %d bytes)",
            topic, qos, len(payload),
        )

    async def receive(self) -> AsyncIterator[runtime_pb2.CapFrame]:
        """Yield incoming CapFrames from MQTT subscriptions."""
        while self._connected:
            try:
                frame = await asyncio.wait_for(self._incoming.get(), timeout=1.0)
                yield frame
            except asyncio.TimeoutError:
                continue

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _resolve_publish_topic(self, frame: runtime_pb2.CapFrame) -> str:
        """Determine the MQTT topic to publish a CapFrame to."""
        body_field = frame.WhichOneof("body")

        if self._config.role == "machine_agent":
            # Machine agents publish to their upstream topic
            return self._config.upstream_topic

        elif self._config.role == "site_agent":
            # Site agent publishes to the specific machine's downstream topic
            # Extract machine_id from frame header
            receiver_id = frame.header.receiver_id
            if receiver_id:
                return (
                    f"{self._config.topic_prefix}/{self._config.site_id}"
                    f"/machines/{receiver_id}/down"
                )
            # Broadcast events go to the events topic
            if body_field in ("safety_event", "audit_event"):
                return self._config.events_topic
            # Fallback to events topic
            return self._config.events_topic

        return self._config.events_topic

    async def _message_loop(self) -> None:
        """Background task that reads MQTT messages and queues CapFrames."""
        try:
            async for message in self._client.messages:
                try:
                    frame = runtime_pb2.CapFrame()
                    frame.ParseFromString(message.payload)

                    # Deduplication using message_id
                    msg_id = frame.header.message_id
                    if msg_id and msg_id in self._seen_message_ids:
                        logger.debug("Duplicate message_id %s, discarding", msg_id)
                        continue

                    if msg_id:
                        self._seen_message_ids.add(msg_id)
                        # Prevent unbounded memory growth
                        if len(self._seen_message_ids) > self._max_seen_ids:
                            # Remove oldest ~half
                            to_remove = list(self._seen_message_ids)[
                                : self._max_seen_ids // 2
                            ]
                            for rid in to_remove:
                                self._seen_message_ids.discard(rid)

                    await self._incoming.put(frame)
                    logger.debug(
                        "MQTT received from %s (%d bytes)",
                        message.topic, len(message.payload),
                    )
                except Exception as e:
                    logger.warning("Failed to parse MQTT message: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("MQTT message loop error: %s", e)
            self._connected = False
