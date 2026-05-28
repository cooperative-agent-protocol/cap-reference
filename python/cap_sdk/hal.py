# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Hardware Abstraction Layer (HAL) — interface between Machine Agent and physical machine.

Machine Agent tools call HAL methods to control the machine. HAL implementations
vary by environment:
  - SimulatorHAL: HTTP → simulator server (development)
  - RosHAL: ROS2 topics (future, real machines with ROS)
  - CanBusHAL: CAN bus / J1939 (future, real machines with CAN)
  - OemHAL: OEM SDK (future, Komatsu/Cat specific)

Sensor architecture:
  Physical sensors → Sensor fusion → HAL → Agent tools → Cognitive Layer

  HAL provides fused, processed sensor data via category-specific methods:
    get_self_state()  — GNSS + IMU + stroke sensors + hydraulics
    get_perception()  — LiDAR + radar + camera fusion
    get_terrain()     — LiDAR terrain scan vs design surface
    get_fleet_info()  — V2V communication data

Design principle: Machine Agent is the control subject, not Site Agent.
Site Agent sends NL instructions via WorkOrder; Machine Agent decides
when/how to send HAL commands.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel

from .agent_types import (
    CameraExtrinsics,
    CameraIntrinsics,
    DetectedObstacle,
    FleetInfo,
    MachineSighting,
    OperatorInput,
    PerceptionState,
    PhysicalProfile,
    Position2D,
    SelfState,
    TerrainCell,
    TerrainState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HAL Commands — typed enum instead of magic strings
# ---------------------------------------------------------------------------


class HALCommand(str, Enum):
    """All HAL commands. Prevents typos and enables autocomplete."""

    # Excavator commands
    EXC_DRIVE_TO = "exc_drive_to"
    EXC_MOVE_TO = "exc_move_to"
    EXC_START_DIG = "exc_start_dig"
    EXC_SWING_TO_LOAD = "exc_swing_to_load"
    EXC_LOAD_TRUCK = "exc_load_truck"
    EXC_STABILIZE_ARM = "exc_stabilize_arm"

    # Truck commands
    TRUCK_DRIVE_TO = "truck_drive_to"
    TRUCK_WAIT_FOR_LOAD = "truck_wait_for_load"
    TRUCK_HAUL_TO_DUMP = "truck_haul_to_dump"
    TRUCK_START_DUMP = "truck_start_dump"
    TRUCK_RETURN_TO_LOAD = "truck_return_to_load"

    # Generic commands
    START_MOVE = "start_move"
    TURN_IN_PLACE = "turn_in_place"
    CREEP = "creep"
    UPDATE_WAYPOINTS = "update_waypoints"
    STOP = "stop"


# ---------------------------------------------------------------------------
# Command parameter models — typed instead of dict[str, Any]
# ---------------------------------------------------------------------------


class ExcMoveToParams(BaseModel):
    target_row: int
    target_col: int
    waypoints: list[tuple[float, float]] = []
    motion_types: list[int] = []  # MotionType per segment (len == len(waypoints)-1)
    headings: list[float] = []    # body yaw per waypoint (len == len(waypoints))


class ExcDriveToParams(BaseModel):
    target_x: float
    target_y: float
    waypoints: list[tuple[float, float]] = []
    motion_types: list[int] = []
    headings: list[float] = []


class TruckDriveToParams(BaseModel):
    target_x: float
    target_y: float
    waypoints: list[tuple[float, float]] = []
    motion_types: list[int] = []
    headings: list[float] = []


class StartMoveParams(BaseModel):
    machine_id: str
    direction: str = "forward"  # "forward" or "backward"
    distance_m: float = 10.0


class TurnInPlaceParams(BaseModel):
    machine_id: str
    angle_deg: float  # positive = counter-clockwise, negative = clockwise


class CreepParams(BaseModel):
    machine_id: str
    linear_mps: float = 0.0  # positive = forward, negative = reverse
    angular_radps: float = 0.0  # positive = counter-clockwise
    duration_sec: float = 2.0  # capped at 5s by bridge


class UpdateWaypointsParams(BaseModel):
    """Hot-swap the active path without changing the navigation goal.

    ``motion_types`` is optional and lists the motion primitive for
    each edge between consecutive waypoints (so
    ``len(motion_types) == len(waypoints) - 1`` when present). When
    supplied, the bridge derives ``cusp_indices`` (FWD↔REV
    transitions) and forwards them to the MPC controller for the
    horizon clip. When omitted, the bridge treats the path as a
    single-direction continuation and clears any stale cusp hints
    from a prior populated call. Forward-only local replanners emit
    ``[0]*N`` (all FWD_STRAIGHT) — the bridge then sees an empty
    cusp list and falls back to the legacy no-clip code path. The
    schema is forward-compatible with future multi-direction local
    replanners.
    """

    machine_id: str
    waypoints: list[tuple[float, float]]
    motion_types: list[int] | None = None


class StopParams(BaseModel):
    machine_id: str


class EmptyParams(BaseModel):
    """For commands that take no parameters."""


# ---------------------------------------------------------------------------
# HAL Result
# ---------------------------------------------------------------------------


@dataclass
class HALResult:
    """Result of a HAL command."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# HAL Interface
# ---------------------------------------------------------------------------


class MachineHAL(ABC):
    """Abstract hardware abstraction layer for machine control.

    Each machine agent holds a HAL instance. Tools call HAL methods
    to read sensors and send control commands.

    Sensor methods return fused, processed data (not raw sensor readings).
    Cognitive Layer receives text summaries; Reactive Layer uses structured data.

    Site Agent can also call emergency_stop() as a safety override.
    """

    # ── Sensor reads (fused data) ────────────────────────────

    @abstractmethod
    async def get_self_state(self) -> SelfState:
        """Self-state: GNSS + IMU + stroke sensors + hydraulics (fused).

        Like proprioception — what the machine knows about itself.
        """
        ...

    @abstractmethod
    async def get_perception(self) -> PerceptionState:
        """Environment perception: LiDAR + radar + camera (fused).

        Like eyes and ears — what the machine sees around it.
        Only returns objects within sensor range.
        """
        ...

    async def get_terrain(self) -> TerrainState:
        """Terrain: LiDAR terrain scan vs design surface (BIM/CIM).

        Only cells within scan radius are visible.
        Default: empty terrain (override in implementations with terrain sensing).
        """
        return TerrainState()

    async def get_fleet_info(self) -> FleetInfo:
        """Fleet: other machines' info via V2V communication.

        Default: empty fleet (override in implementations with V2V).
        """
        return FleetInfo()

    async def get_perception_summary(self) -> dict[str, Any]:
        """Derived perception: nearest machine, swing zone, truck readiness.

        Default: empty dict (override in implementations with perception).
        """
        return {}

    async def get_terrain_height_cells(self) -> list[dict]:
        """LiDAR-derived terrain height cells for spatial reasoning.

        Default: empty list (override in implementations with LiDAR).
        """
        return []

    async def get_camera_frame(self, direction: str = "front") -> bytes | None:
        """Latest camera frame as PNG bytes for the VLM verifier.

        Returns ``None`` when no camera is configured or no frame
        has arrived yet for the requested direction. Implementations
        should never raise — verifiers treat ``None`` as "skip VLM
        call" so the cognitive cycle keeps running on HAL-only
        effects evaluation.

        Args:
            direction: One of ``"front"`` (default), ``"bucket"``
                (excavator), ``"bed"`` / ``"rear"`` (dump_truck), or
                any direction the bridge exposes via
                ``GET /camera/{id}/list``.

        The returned bytes must be a complete PNG (image/png is
        directly consumable by typical VLM endpoints).
        """
        return None

    async def list_camera_directions(self) -> list[str]:
        """Discover camera directions exposed by this machine's bridge.

        Used by VLM verifiers to resolve manifest-declared
        ``required_camera_directions`` to the bridge's actually-
        streaming subset. Default returns ``["front"]`` (single-camera
        behaviour).
        """
        return ["front"]

    async def get_camera_intrinsics(
        self, direction: str = "front",
    ) -> CameraIntrinsics | None:
        """Read camera intrinsic calibration for ``direction``.

        Returns the per-direction pinhole + Brown-Conrady calibration
        for the camera identified by ``direction``, or ``None`` when:

          * No calibration data is available for this direction
          * The bridge endpoint isn't yet wired
          * The HAL implementation doesn't surface intrinsics

        The default ``return None`` impl in this ABC keeps every
        existing HAL subclass forward-compatible. A HAL that wants
        to publish intrinsics MAY override and serve them via a
        simulator-bridge endpoint such as
        ``GET /camera/{id}/intrinsics?direction=...``. Until the
        endpoint exists, downstream consumers typically fall back to
        ``infer_pinhole_intrinsics`` based on ``fov_deg`` (sufficient
        for simulator cameras with zero distortion).

        Implementations MUST NOT raise — callers treat ``None`` as
        "use the FoV-derived fallback" and continue.

        Args:
            direction: Camera direction string (e.g. ``"front"`` /
                ``"bucket"`` / ``"bed"`` / ``"rear"`` / ``"left"`` /
                ``"right"`` or any direction the bridge exposes).
        """
        return None

    async def get_camera_extrinsics(
        self, direction: str = "front",
    ) -> CameraExtrinsics | None:
        """Read camera extrinsic placement for ``direction``.

        Returns the per-direction camera placement (transform from
        machine ``base_link`` to camera optical center) for
        ``direction``, or ``None`` when:

          * No calibration data is available for this direction
          * The bridge endpoint isn't yet wired
          * The HAL implementation doesn't surface extrinsics

        The default ``return None`` impl makes every existing HAL
        subclass forward-compatible. A HAL that wants to publish
        camera extrinsics over the wire MAY expose them via a
        simulator-bridge endpoint (e.g.
        ``GET /camera/{id}/extrinsics?direction=...``) and override
        this method.

        Implementations MUST NOT raise — callers treat ``None`` as
        "use the implementation's own fallback" and continue.

        Together with ``get_camera_intrinsics``, this method
        completes the calibration contract pair so downstream
        consumers can do full pixel ↔ world-frame mapping through
        one stable HAL surface.

        Args:
            direction: Camera direction string (``"front"`` /
                ``"bucket"`` / ``"bed"`` / ``"rear"`` / ``"left"`` /
                ``"right"`` or any direction the bridge exposes).
        """
        return None

    async def get_operator_input(self) -> OperatorInput | None:
        """Read the latest operator teleop input.

        Returns the most recent ``OperatorInput`` from a teleoperated
        machine's command stream, or ``None`` when:

          * No teleop input source is configured (default for fully
            autonomous deployments)
          * The bridge endpoint is unreachable / no operator connected
          * The most recent input is older than the implementation's
            staleness threshold (decided per-impl)

        The default ``return None`` impl makes every existing HAL
        subclass forward-compatible — operator-shadow functionality
        activates only when a concrete subclass returns a real
        ``OperatorInput`` instance via its bridge endpoint.

        Implementations MUST NOT raise — operator-shadow capture
        treats ``None`` as "no operator connected" and proceeds with
        a synthetic operator policy.
        """
        return None

    # ── Legacy read (backward compatibility) ──────────────────

    async def read_state(self) -> dict[str, Any]:
        """Read full state as untyped dict. Deprecated: use typed sensor methods.

        Default: delegates to get_self_state().
        """
        state = await self.get_self_state()
        return state.model_dump()

    # ── Actuator commands ────────────────────────────────────

    @abstractmethod
    async def send_command(
        self,
        command: HALCommand | str,
        params: BaseModel | dict[str, Any] | None = None,
    ) -> HALResult:
        """Send a control command to the machine.

        Args:
            command: HALCommand enum (preferred) or string (legacy).
            params: BaseModel (preferred) or dict (legacy).

        Returns:
            HALResult with success/failure and response data.
        """
        ...

    # ── Emergency stop (Site Agent safety override) ──────────

    @abstractmethod
    async def emergency_stop(self) -> HALResult:
        """Emergency stop. Can be called by Site Agent as safety override."""
        ...


# ---------------------------------------------------------------------------
# Simulator HAL
# ---------------------------------------------------------------------------


class SimulatorHAL(MachineHAL):
    """HAL implementation for the CAP simulator.

    Sends HTTP commands to the simulator server.
    Reads sensor data via GET /sensor/{machine_id} (per-machine view).
    Falls back to GET /state for legacy compatibility.

    Each machine agent gets its own SimulatorHAL instance with its machine_id.
    """

    def __init__(
        self,
        sim_url: str,
        machine_id: str,
        physical_profile: PhysicalProfile | None = None,
    ) -> None:
        self._sim_url = sim_url.rstrip("/")
        self._machine_id = machine_id
        self._physical_profile = physical_profile
        self._http: Any = None  # Lazy init to avoid import at module level

    async def _get_http(self) -> Any:
        """Lazy-initialize httpx client."""
        if self._http is None:
            import httpx  # noqa: PLC0415

            self._http = httpx.AsyncClient(base_url=self._sim_url, timeout=5.0)
        return self._http

    async def _fetch_sensor_view(self) -> dict[str, Any]:
        """Fetch per-machine sensor view. Falls back to full state."""
        http = await self._get_http()
        try:
            resp = await http.get(f"/sensor/{self._machine_id}")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            logger.debug("[HAL %s] /sensor endpoint not available, using /state", self._machine_id)

        # Fallback to full state (legacy simulator without /sensor endpoint)
        try:
            resp = await http.get("/state")
            return self._extract_from_full_state(resp.json())
        except Exception as e:
            logger.error("[HAL %s] Failed to read state: %s", self._machine_id, e)
            return {}

    def _extract_from_full_state(self, full_state: dict[str, Any]) -> dict[str, Any]:
        """Extract per-machine data from full state (legacy fallback)."""
        # Try per-machine lookup first (machines dict keyed by machine_id)
        machines = full_state.get("machines", {})
        machine_data = machines.get(self._machine_id, {})

        # Fallback to legacy single-machine fields
        if not machine_data:
            for key in ("excavator", "truck"):
                candidate = full_state.get(key, {})
                if candidate.get("machine_id") == self._machine_id:
                    machine_data = candidate
                    break

        return {
            "self_state": machine_data,
            "perception": {"obstacles": [], "visibility": "clear"},
            "terrain": {"visible_cells": []},
            "fleet": {"other_machines": []},
        }

    # ── Sensor reads ─────────────────────────────────────────

    async def get_self_state(self) -> SelfState:
        """Read self-state from simulator."""
        view = await self._fetch_sensor_view()
        raw = view.get("self_state", {})
        state = _parse_self_state(raw, self._machine_id)
        if self._physical_profile:
            state.physical_profile = self._physical_profile
        return state

    async def get_perception(self) -> PerceptionState:
        """Read environment perception from simulator."""
        view = await self._fetch_sensor_view()
        raw = view.get("perception", {})
        return _parse_perception(raw)

    async def get_perception_summary(self) -> dict[str, Any]:
        """Read derived perception summary (nearest machine, swing zone, etc.)."""
        view = await self._fetch_sensor_view()
        return view.get("perception_summary", {})

    async def get_terrain(self) -> TerrainState:
        """Read terrain from simulator."""
        view = await self._fetch_sensor_view()
        raw = view.get("terrain", {})
        return _parse_terrain(raw)

    async def get_terrain_height_cells(self) -> list[dict]:
        """Read LiDAR-derived terrain height cells for TerrainGrid construction."""
        view = await self._fetch_sensor_view()
        terrain = view.get("terrain", {})
        return terrain.get("terrain_height_cells", [])

    async def get_fleet_info(self) -> FleetInfo:
        """Read fleet info from simulator."""
        view = await self._fetch_sensor_view()
        raw = view.get("fleet", {})
        return _parse_fleet(raw)

    async def get_camera_frame(self, direction: str = "front") -> bytes | None:
        """Fetch the latest camera frame as PNG bytes via HTTP.

        URL routing:
          * ``direction="front"`` → ``GET /camera/{machine_id}``
            (backward-compat alias; bridges may also expose the same
            content at ``/camera/{id}/front``)
          * other directions → ``GET /camera/{machine_id}/{direction}``

        Status code mapping:
          * 200 + image/png body → return bytes
          * 503 — sensor not yet streaming / no frame cached → None
          * 500 — encode failed / unsupported encoding → None

        Network / HTTP errors are silently coerced to None so a flaky
        bridge connection never breaks the verifier call site.
        """
        try:
            http = await self._get_http()
            url = (
                f"/camera/{self._machine_id}"
                if direction == "front"
                else f"/camera/{self._machine_id}/{direction}"
            )
            resp = await http.get(url)
            if resp.status_code == 200:
                return resp.content
            return None
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] get_camera_frame(%s) failed: %s",
                self._machine_id, direction, e,
            )
            return None

    async def list_camera_directions(self) -> list[str]:
        """Fetch ``GET /camera/{id}/list`` to discover bridge cameras.

        Returns the ``directions`` list from the bridge response. On
        any error (bridge unreachable, malformed response, missing
        endpoint on older bridges) returns ``["front"]`` as a safe
        fallback so VLM verifiers always have at least the
        single-camera path.
        """
        try:
            http = await self._get_http()
            resp = await http.get(f"/camera/{self._machine_id}/list")
            if resp.status_code == 200:
                data = resp.json()
                directions = data.get("directions") if isinstance(data, dict) else None
                if isinstance(directions, list) and directions:
                    return [str(d) for d in directions if isinstance(d, str)]
            return ["front"]
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] list_camera_directions failed: %s",
                self._machine_id, e,
            )
            return ["front"]

    async def get_camera_intrinsics(
        self, direction: str = "front",
    ) -> CameraIntrinsics | None:
        """Fetch camera intrinsics via the simulator bridge HTTP.

        Polls ``GET /camera/{machine_id}/intrinsics?direction=...`` on
        the simulator bridge. A Unity-based bridge typically derives
        intrinsics from ``Camera.projectionMatrix`` (Unity provides
        the canonical OpenCV-compatible matrix). When the endpoint
        is not implemented yet (404 / connection-refused) this method
        returns ``None`` — downstream consumers use
        ``infer_pinhole_intrinsics`` as fallback.

        Response shape (when the endpoint exists):
            ``{
                "fx": float, "fy": float,
                "cx": float, "cy": float,
                "image_width": int, "image_height": int,
                "distortion": [k1, k2, p1, p2, k3]
            }``

        Defensive everywhere: HTTP errors / malformed JSON / missing
        fields → ``None``. Same contract as ``get_operator_input``.
        """
        try:
            http = await self._get_http()
            resp = await http.get(
                f"/camera/{self._machine_id}/intrinsics",
                params={"direction": direction},
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] get_camera_intrinsics HTTP failed: %s",
                self._machine_id, e,
            )
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] get_camera_intrinsics JSON decode failed: %s",
                self._machine_id, e,
            )
            return None
        if not isinstance(data, dict):
            return None
        try:
            distortion_raw = data.get("distortion", [])
            distortion = (
                [float(x) for x in distortion_raw]
                if isinstance(distortion_raw, list) else []
            )
            return CameraIntrinsics(
                fx=float(data.get("fx", 0.0)),
                fy=float(data.get("fy", 0.0)),
                cx=float(data.get("cx", 0.0)),
                cy=float(data.get("cy", 0.0)),
                image_width=int(data.get("image_width", 0)),
                image_height=int(data.get("image_height", 0)),
                distortion=distortion,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] CameraIntrinsics construction failed: %s",
                self._machine_id, e,
            )
            return None

    async def get_camera_extrinsics(
        self, direction: str = "front",
    ) -> CameraExtrinsics | None:
        """Fetch camera extrinsics via the simulator bridge HTTP endpoint.

        Polls ``GET /camera/{machine_id}/extrinsics?direction=...`` on
        the bridge. When the endpoint is not implemented yet (404 /
        connection-refused) this method returns ``None`` — callers
        treat ``None`` as "use the implementation's own fallback".

        Response shape (when the endpoint exists):
            ``{
                "forward_m": float, "lateral_m": float, "height_m": float,
                "yaw_deg": float, "pitch_deg": float, "roll_deg": float,
                "parent_link": str, "fov_deg": float,
                "image_width": int, "image_height": int
            }``

        Defensive everywhere: HTTP errors / malformed JSON / missing
        fields → ``None``. Same contract as ``get_camera_intrinsics``.
        """
        try:
            http = await self._get_http()
            resp = await http.get(
                f"/camera/{self._machine_id}/extrinsics",
                params={"direction": direction},
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] get_camera_extrinsics HTTP failed: %s",
                self._machine_id, e,
            )
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] get_camera_extrinsics JSON decode failed: %s",
                self._machine_id, e,
            )
            return None
        if not isinstance(data, dict):
            return None
        try:
            return CameraExtrinsics(
                forward_m=float(data.get("forward_m", 0.0)),
                lateral_m=float(data.get("lateral_m", 0.0)),
                height_m=float(data.get("height_m", 0.0)),
                yaw_deg=float(data.get("yaw_deg", 0.0)),
                pitch_deg=float(data.get("pitch_deg", 0.0)),
                roll_deg=float(data.get("roll_deg", 0.0)),
                parent_link=str(data.get("parent_link", "")),
                fov_deg=float(data.get("fov_deg", 60.0)),
                image_width=int(data.get("image_width", 0)),
                image_height=int(data.get("image_height", 0)),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] CameraExtrinsics construction failed: %s",
                self._machine_id, e,
            )
            return None

    async def get_operator_input(self) -> OperatorInput | None:
        """Fetch the latest operator input via the bridge HTTP endpoint.

        Polls ``GET /operator-input/{machine_id}`` on the simulator
        bridge. When the bridge endpoint is not implemented yet
        (404 / connection-refused) this method returns ``None`` —
        forward-compatible with deployments that have NOT yet wired
        teleop.

        Response shape (when the endpoint exists):
            ``{
                "timestamp_iso": str,
                "machine_id": str,
                "input_kind": str,
                "raw_command": dict,
                "emergency_stop": bool,
                "metadata": dict
            }``

        Defensive everywhere: HTTP errors / malformed JSON / missing
        fields → ``None``. Operator-shadow capture treats ``None``
        as "no operator" and continues with a synthetic policy.
        """
        try:
            http = await self._get_http()
            resp = await http.get(f"/operator-input/{self._machine_id}")
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] get_operator_input HTTP failed: %s",
                self._machine_id, e,
            )
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] get_operator_input JSON decode failed: %s",
                self._machine_id, e,
            )
            return None
        if not isinstance(data, dict):
            return None
        try:
            return OperatorInput(
                timestamp_iso=str(data.get("timestamp_iso", "")),
                machine_id=str(data.get("machine_id", self._machine_id)),
                input_kind=str(data.get("input_kind", "")),
                raw_command=(
                    data.get("raw_command") if isinstance(
                        data.get("raw_command"), dict,
                    ) else {}
                ),
                emergency_stop=bool(data.get("emergency_stop", False)),
                metadata=(
                    data.get("metadata") if isinstance(
                        data.get("metadata"), dict,
                    ) else {}
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "[HAL %s] OperatorInput construction failed: %s",
                self._machine_id, e,
            )
            return None

    async def read_state(self) -> dict[str, Any]:
        """Legacy: read full state."""
        http = await self._get_http()
        try:
            resp = await http.get("/state")
            return resp.json()
        except Exception as e:
            logger.error("[HAL %s] read_state failed: %s", self._machine_id, e)
            return {}

    # ── Actuator commands ────────────────────────────────────

    async def send_command(
        self,
        command: HALCommand | str,
        params: BaseModel | dict[str, Any] | None = None,
    ) -> HALResult:
        """Send command to simulator via POST /command."""
        http = await self._get_http()
        cmd_str = command.value if isinstance(command, HALCommand) else command
        params_dict = params.model_dump() if isinstance(params, BaseModel) else (params or {})
        payload = {
            "action": cmd_str,
            "params": {"machine_id": self._machine_id, **params_dict},
        }
        try:
            resp = await http.post("/command", json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("status") != "error":
                logger.debug("[HAL %s] %s → OK", self._machine_id, command)
                return HALResult(success=True, data=data)
            logger.warning("[HAL %s] %s → Error: %s", self._machine_id, command, data)
            return HALResult(success=False, data=data, error=data.get("message", "Unknown error"))
        except Exception as e:
            logger.error("[HAL %s] %s failed: %s", self._machine_id, command, e)
            return HALResult(success=False, error=str(e))

    async def emergency_stop(self) -> HALResult:
        """Send emergency stop command."""
        logger.warning("[HAL %s] EMERGENCY STOP", self._machine_id)
        return await self.send_command("stop", {"machine_id": self._machine_id})

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None


# ---------------------------------------------------------------------------
# Parsers: raw dict → typed sensor models
# ---------------------------------------------------------------------------


def _parse_self_state(raw: dict[str, Any], machine_id: str) -> SelfState:
    """Parse raw state dict into SelfState model."""
    pos = raw.get("position", {})
    return SelfState(
        position=Position2D(x=pos.get("x", 0.0), y=pos.get("y", 0.0)),
        heading_deg=pos.get("yaw", raw.get("heading_deg", 0.0)),
        roll_deg=raw.get("roll_deg", 0.0),
        pitch_deg=raw.get("pitch_deg", 0.0),
        speed_mps=raw.get("speed_mps", 0.0),
        mode=raw.get("mode", "supervised_autonomy"),
        fuel_percent=raw.get("fuel_percent", 100.0),
        engine_rpm=raw.get("engine_rpm", 0.0),
        healthy=raw.get("healthy", True),
        joint_angles=raw.get("joint_angles", {}),
        hydraulic_pressure_bar=raw.get("hydraulic_pressure_bar", {}),
        payload_kg=raw.get("payload_kg", 0.0),
        payload_volume_m3=raw.get(
            "payload_volume_m3",
            raw.get("bucket_load_m3", raw.get("payload_m3", 0.0)),
        ),
        active_task_id=raw.get("active_task_id", ""),
        cycles_completed=raw.get("cycles_completed", 0),
        total_volume_moved_m3=raw.get(
            "total_volume_moved_m3",
            raw.get("total_hauled_m3", 0.0),
        ),
        gnss_fix_quality=raw.get("gnss_fix_quality", "rtk_fixed"),
        sensor_timestamp=raw.get("sensor_timestamp", 0.0),
    )


def _parse_perception(raw: dict[str, Any]) -> PerceptionState:
    """Parse raw perception dict into PerceptionState model."""
    obstacles = []
    for obs in raw.get("obstacles", []):
        obstacles.append(DetectedObstacle(
            obstacle_id=obs.get("obstacle_id", ""),
            position=Position2D(
                x=obs.get("position", {}).get("x", 0.0),
                y=obs.get("position", {}).get("y", 0.0),
            ),
            distance_m=obs.get("distance_m", 0.0),
            classification=obs.get("classification", "unknown"),
            confidence=obs.get("confidence", 0.5),
            velocity_mps=obs.get("velocity_mps", 0.0),
            source=obs.get("source", "lidar+camera"),
        ))
    return PerceptionState(
        obstacles=obstacles,
        visibility=raw.get("visibility", "clear"),
        lidar_range_m=raw.get("lidar_range_m", 50.0),
        radar_range_m=raw.get("radar_range_m", 100.0),
        camera_effective_range_m=raw.get("camera_effective_range_m", 30.0),
    )


def _parse_terrain(raw: dict[str, Any]) -> TerrainState:
    """Parse raw terrain dict into TerrainState model."""
    cells = []
    for cell in raw.get("visible_cells", []):
        cells.append(TerrainCell(
            row=cell.get("row", 0),
            col=cell.get("col", 0),
            volume_m3=cell.get("volume_m3", 0.0),
            zone_type=cell.get("zone_type", ""),
            has_obstacle=cell.get("has_obstacle", False),
            design_volume_m3=cell.get("design_volume_m3", 0.0),
            surface_condition=cell.get("surface_condition", "dry"),
        ))
    return TerrainState(
        visible_cells=cells,
        scan_radius_m=raw.get("scan_radius_m", 20.0),
        cut_remaining_m3=raw.get("cut_remaining_m3", 0.0),
        fill_remaining_m3=raw.get("fill_remaining_m3", 0.0),
    )


def _parse_fleet(raw: dict[str, Any]) -> FleetInfo:
    """Parse raw fleet dict into FleetInfo model."""
    machines = []
    for m in raw.get("other_machines", []):
        machines.append(MachineSighting(
            machine_id=m.get("machine_id", ""),
            machine_type=m.get("machine_type", ""),
            position=Position2D(
                x=m.get("position", {}).get("x", 0.0),
                y=m.get("position", {}).get("y", 0.0),
            ),
            heading_deg=m.get("heading_deg", 0.0),
            speed_mps=m.get("speed_mps", 0.0),
            current_task=m.get("current_task", ""),
            last_update_sec_ago=m.get("last_update_sec_ago", 0.0),
            payload_m3=m.get("payload_m3"),
            payload_capacity_m3=m.get("payload_capacity_m3"),
        ))
    return FleetInfo(
        other_machines=machines,
        communication_quality=raw.get("communication_quality", "good"),
    )


# ── Pinhole intrinsics derivation ────────────────────────────────────


def infer_pinhole_intrinsics(
    *,
    fov_deg: float,
    image_width: int,
    image_height: int,
) -> CameraIntrinsics | None:
    """Derive ideal pinhole intrinsics from horizontal FoV + image size.

    Fallback for deployments that haven't yet wired
    ``hal.get_camera_intrinsics``. Uses the standard pinhole model:

      * ``fx = fy = (W / 2) / tan(fov_h / 2)``
      * ``cx = W / 2``, ``cy = H / 2``
      * ``distortion = []`` (zero distortion — typical simulator default)

    Returns ``None`` when:

      * ``fov_deg`` is not in (0, 180) — non-physical
      * ``image_width`` or ``image_height`` ≤ 0
      * Any input is non-finite (NaN / Inf)

    A shared per-direction ``fov_deg`` table (e.g. from the bridge's
    canonical calibration file) is the typical caller's input source.
    With a 640×480 frame default, this yields fx/fy in [320, 720] for
    typical wide-angle (60°-95°) construction-camera FoVs.

    Downstream consumers use this as the v1 calibration when
    ``get_camera_intrinsics`` returns ``None`` — accurate enough for
    simulator cameras (which are ideal pinholes by construction).
    """
    import math as _math

    if not isinstance(fov_deg, (int, float)):
        return None
    if not _math.isfinite(fov_deg):
        return None
    if fov_deg <= 0.0 or fov_deg >= 180.0:
        return None
    if image_width <= 0 or image_height <= 0:
        return None
    fov_rad = _math.radians(float(fov_deg))
    focal = (image_width / 2.0) / _math.tan(fov_rad / 2.0)
    return CameraIntrinsics(
        fx=focal,
        fy=focal,
        cx=image_width / 2.0,
        cy=image_height / 2.0,
        image_width=image_width,
        image_height=image_height,
        distortion=[],
    )
