# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared type definitions for the Agent Runtime system.

Enums replace hardcoded strings. BaseModel subclasses replace untyped dicts.
All agent code should import types from here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enums — replace hardcoded string literals
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Event types from reactive layer to cognitive layer."""

    MILESTONE = "milestone"
    ISSUE = "issue"
    INCOMING_MESSAGE = "incoming_message"
    STATE_CHANGE = "state_change"
    NEW_INSTRUCTION = "new_instruction"
    SAFETY_VIOLATION = "safety_violation"
    STUCK = "stuck"


class ReportType(str, Enum):
    """Report types sent from Machine Agent to Site Agent."""

    MILESTONE = "milestone"
    ISSUE = "issue"
    STATUS = "status"
    COMPLETION = "completion"
    REQUEST = "request"


class DecisionScope(str, Enum):
    """Scope for Machine Agent decisions requiring approval."""

    MICRO = "micro"
    TASK = "task"
    CROSS_TASK = "cross_task"


class DialogueIntent(str, Enum):
    """Intent types for AgentDialogue messages (maps to CAP proto)."""

    SITUATION_REPORT = "situation_report"
    LOCAL_DECISION = "local_decision"
    PLAN_PROPOSAL = "plan_proposal"
    ACKNOWLEDGEMENT = "acknowledgement"
    INSTRUCTION = "instruction"
    QUERY = "query"


class TaskState(str, Enum):
    """Task execution state (maps to CAP proto TaskState)."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Machine state models — replace dict[str, Any]
# ---------------------------------------------------------------------------


class MachinePosition(BaseModel):
    """Machine position in world coordinates."""

    x: float = 0.0
    y: float = 0.0
    yaw_deg: float = 0.0


class MachineStateBase(BaseModel):
    """Base machine state shared by all machine types."""

    machine_id: str = ""
    position: MachinePosition = MachinePosition()
    mode: str = "unknown"
    fuel_percent: float = 100.0
    active_task_id: str = ""


class ExcavatorStateModel(MachineStateBase):
    """Excavator-specific state."""

    bucket_load_m3: float = 0.0
    cycles_completed: int = 0
    total_volume_moved_m3: float = 0.0
    current_phase: str = "idle"


class DumpTruckStateModel(MachineStateBase):
    """Dump truck-specific state."""

    payload_m3: float = 0.0
    route_progress: str = "0/0"
    total_hauled_m3: float = 0.0
    current_phase: str = "idle"


# ---------------------------------------------------------------------------
# Think response model — replace dict[str, Any] from model.think()
# ---------------------------------------------------------------------------


class ToolCallModel(BaseModel):
    """A tool call requested by the LLM."""

    tool_name: str
    arguments: dict[str, Any] = {}


class ThinkResponse(BaseModel):
    """Response from MachineModelInterface.think()."""

    text: str = ""
    tool_calls: list[ToolCallModel] = []
    done: bool = False


# ---------------------------------------------------------------------------
# Sensor enums
# ---------------------------------------------------------------------------


class GnssFixQuality(str, Enum):
    """GNSS fix quality levels."""

    RTK_FIXED = "rtk_fixed"
    RTK_FLOAT = "rtk_float"
    DGPS = "dgps"
    AUTONOMOUS = "autonomous"
    NO_FIX = "no_fix"


class VisibilityCondition(str, Enum):
    """Atmospheric visibility conditions affecting camera/LiDAR."""

    CLEAR = "clear"
    DUST = "dust"
    RAIN = "rain"
    FOG = "fog"
    NIGHT = "night"


class SurfaceCondition(str, Enum):
    """Ground surface condition."""

    DRY = "dry"
    WET = "wet"
    MUDDY = "muddy"
    ROCKY = "rocky"
    FROZEN = "frozen"


class MachineMode(str, Enum):
    """Machine operating mode."""

    MANUAL = "manual"
    TELEOP = "teleop"
    SUPERVISED_AUTONOMY = "supervised_autonomy"
    FULL_AUTONOMY = "full_autonomy"
    SAFE_STOP = "safe_stop"


class ObstacleClass(str, Enum):
    """Classification of detected obstacles."""

    PERSON = "person"
    VEHICLE = "vehicle"
    ROCK = "rock"
    STRUCTURE = "structure"
    UNKNOWN = "unknown"


class SensorSource(str, Enum):
    """Which sensor(s) detected an object."""

    LIDAR_CAMERA = "lidar+camera"
    LIDAR_ONLY = "lidar_only"
    RADAR = "radar"
    CAMERA_ONLY = "camera_only"
    V2V = "v2v"


# ---------------------------------------------------------------------------
# Sensor data models — replace untyped dicts from HAL
# ---------------------------------------------------------------------------


class Position2D(BaseModel):
    """2D world position."""

    x: float = 0.0
    y: float = 0.0


class DetectedObstacle(BaseModel):
    """A single obstacle detected by fused sensors (LiDAR + radar + camera)."""

    obstacle_id: str = ""
    position: Position2D = Position2D()
    distance_m: float = 0.0
    size_m: tuple[float, float] = (1.0, 1.0)  # width, height
    classification: ObstacleClass = ObstacleClass.UNKNOWN
    confidence: float = 0.5
    velocity_mps: float = 0.0  # radar Doppler (0 = stationary)
    source: SensorSource = SensorSource.LIDAR_CAMERA


class ZoneInfo(BaseModel):
    """Zone detected via geofence / site map."""

    zone_id: str = ""
    zone_type: str = ""
    distance_m: float = 0.0
    direction_deg: float = 0.0  # relative to machine heading


class MachineSighting(BaseModel):
    """Another machine detected via V2V or perception sensors."""

    machine_id: str = ""
    machine_type: str = ""
    position: Position2D = Position2D()
    heading_deg: float = 0.0
    speed_mps: float = 0.0
    current_task: str = ""  # summary only (not detailed)
    last_update_sec_ago: float = 0.0  # information freshness
    payload_m3: float | None = None  # truck payload (None if not a truck)
    payload_capacity_m3: float | None = None  # truck max capacity


class TerrainCell(BaseModel):
    """A single terrain grid cell from LiDAR terrain scan."""

    row: int = 0
    col: int = 0
    volume_m3: float = 0.0
    zone_type: str = ""
    has_obstacle: bool = False
    design_volume_m3: float = 0.0  # target from BIM/CIM
    surface_condition: SurfaceCondition = SurfaceCondition.DRY


# ---------------------------------------------------------------------------
# Physical profile — static machine dimensions
# ---------------------------------------------------------------------------


class PhysicalProfile(BaseModel):
    """Static physical dimensions of the machine.

    Populated once at startup from MachineSpec. Enables spatial
    reasoning about clearance, passing distances, and work envelope.
    """

    length_m: float = 0.0
    width_m: float = 0.0
    height_m: float = 0.0
    weight_kg: float = 0.0
    min_turning_radius_m: float = 0.0
    track_width_m: float = 0.0
    safety_radius_m: float = 0.0  # max(length, width) / 2 + margin


# ---------------------------------------------------------------------------
# HAL sensor response models
# ---------------------------------------------------------------------------


class SelfState(BaseModel):
    """Self-state from GNSS + IMU + stroke sensors + hydraulics (fused).

    This is what the machine knows about itself — like proprioception.
    """

    # Position & pose (GNSS+RTK + IMU)
    position: Position2D = Position2D()
    heading_deg: float = 0.0
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    speed_mps: float = 0.0

    # Machine state
    mode: MachineMode = MachineMode.SUPERVISED_AUTONOMY
    fuel_percent: float = 100.0
    engine_rpm: float = 0.0
    healthy: bool = True

    # Joint angles (excavator only, from stroke sensors → forward kinematics)
    joint_angles: dict[str, float] = {}  # {"boom": 45.0, "arm": -30.0, "bucket": 15.0}

    # Hydraulic pressure (pressure transducers per circuit)
    hydraulic_pressure_bar: dict[str, float] = {}  # {"boom": 250.0, "arm": 180.0}

    # Payload estimate (from hydraulic pressure + kinematics)
    payload_kg: float = 0.0
    payload_volume_m3: float = 0.0

    # Task progress
    active_task_id: str = ""
    cycles_completed: int = 0
    total_volume_moved_m3: float = 0.0

    # Sensor quality metadata
    gnss_fix_quality: GnssFixQuality = GnssFixQuality.RTK_FIXED
    sensor_timestamp: float = 0.0

    # Physical dimensions (static, populated from MachineSpec at startup)
    physical_profile: PhysicalProfile | None = None


class PerceptionState(BaseModel):
    """Environment perception from LiDAR + radar + camera fusion.

    This is what the machine sees around it — like eyes and ears.
    """

    obstacles: list[DetectedObstacle] = []
    nearby_zones: list[ZoneInfo] = []
    visibility: VisibilityCondition = VisibilityCondition.CLEAR
    lidar_range_m: float = 50.0
    radar_range_m: float = 100.0
    camera_effective_range_m: float = 30.0


class TerrainState(BaseModel):
    """Terrain from LiDAR terrain scan vs design surface (BIM/CIM).

    Only cells within scan radius are visible.
    """

    visible_cells: list[TerrainCell] = []
    scan_radius_m: float = 20.0
    cut_remaining_m3: float = 0.0
    fill_remaining_m3: float = 0.0


class FleetInfo(BaseModel):
    """Other machines' info received via V2V communication."""

    other_machines: list[MachineSighting] = []
    communication_quality: str = "good"  # "good" / "degraded" / "lost"


# ---------------------------------------------------------------------------
# Normalized Observation — unified snapshot for Machine Agent
# ---------------------------------------------------------------------------


class Localization(BaseModel):
    """Fused localization from GNSS + IMU + odometry."""

    position_m: list[float] = [0.0, 0.0, 0.0]
    yaw_deg: float = 0.0
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    velocity_mps: float = 0.0
    quality: float = 1.0


class WorkDeviceState(BaseModel):
    """Excavator arm / dump truck bed state from joint sensors + FK."""

    swing_deg: float = 0.0
    boom_deg: float = 0.0
    arm_deg: float = 0.0
    bucket_deg: float = 0.0
    bucket_tip_xyz: list[float] = [0.0, 0.0, 0.0]
    bucket_tip_speed_mps: float = 0.0  # velocity of bucket tip
    bucket_load_m3: float = 0.0


class PerceptionSummary(BaseModel):
    """Derived spatial awareness from V2V + LiDAR.

    V2V fields: nearest_machine_m, truck_ready (from CAP fleet info)
    LiDAR fields: nearest_obstacle_m, detected_obstacles, terrain (from local sensor)
    Task affordances: load_point_visible, dump_area_free
    Integrated: obstacle_in_swing_zone, swing_zone_clear (combines both sources)
    """

    # CAP/V2V由来
    nearest_machine_m: float | None = None
    truck_ready: bool = False

    # LiDAR由来 (ローカルセンサ)
    nearest_obstacle_m: float | None = None
    detected_obstacles: list[dict] = []
    terrain_height_at_front_m: float | None = None

    # Task affordances (V2V + LiDAR統合)
    load_point_visible: bool = False
    dump_area_free: bool = True

    # 統合判定
    obstacle_in_swing_zone: bool = False
    swing_zone_clear: bool = True


class MachineHealth(BaseModel):
    """Machine health from CAN / ECU / safety I/O."""

    fuel_pct: float = 100.0
    engine_rpm: float = 0.0
    hydraulic_temp_c: float = 0.0
    mode: str = "supervised_autonomy"
    estop: bool = False


class TaskContext(BaseModel):
    """Current task assignment context."""

    active_task_id: str = ""
    reservation_ids: list[str] = []


class NormalizedObservation(BaseModel):
    """Unified observation snapshot — the single source of truth for agents.

    Produced by ObservationWorker at 10-20Hz. Consumed by:
    - Reactive layer at 10-20Hz (fast path)
    - Cognitive layer at 1-2Hz (slow path, LLM-readable summary)
    """

    machine_id: str = ""
    timestamp: float = 0.0
    localization: Localization = Localization()
    work_device: WorkDeviceState = WorkDeviceState()
    perception_summary: PerceptionSummary = PerceptionSummary()
    machine_health: MachineHealth = MachineHealth()
    task_context: TaskContext = TaskContext()


class CameraIntrinsics(BaseModel):
    """Per-direction camera intrinsics.

    Pinhole + Brown-Conrady distortion model — the canonical OpenCV
    formulation used downstream for pixel ↔ camera-frame ray mapping.
    Together with ``CameraExtrinsics`` (camera pose relative to the
    machine frame) this completes the calibration so consumers can
    do full pixel → world mapping for BEV ground-truth alignment.

    Fields:
        fx, fy: Focal length in pixels (camera matrix diagonal).
            For an ideal pinhole at horizontal FoV ``θ`` and image
            width ``W``: ``fx = (W / 2) / tan(θ / 2)``. ``fy`` is
            usually equal but can differ for non-square pixels.
        cx, cy: Principal point (image-frame coordinates of the
            optical axis intersection). For ideal alignment:
            ``cx = W / 2, cy = H / 2``. Real cameras shift by 1-5 px
            due to lens manufacturing tolerance.
        image_width, image_height: Pixel dimensions of frames the
            intrinsics describe. Pin so consumers can validate
            against actual blob bytes (mismatch = wrong calibration).
        distortion: Brown-Conrady coefficients ``[k1, k2, p1, p2, k3]``
            (radial + tangential). Empty / shorter list = no
            distortion (ideal pinhole assumption — typical for
            simulator cameras and well-calibrated real lenses).

    The dataclass + HAL method exist as ABC-level contracts. HAL
    subclasses MAY return ``None`` from ``get_camera_intrinsics``
    until their calibration pipeline materializes; callers then fall
    back to ``infer_pinhole_intrinsics`` based on ``fov_deg`` from
    extrinsics, which is sufficient for simulator cameras (no real
    distortion).
    """

    fx: float = 0.0
    fy: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    image_width: int = 0
    image_height: int = 0
    distortion: list[float] = []


class CameraExtrinsics(BaseModel):
    """Per-direction camera extrinsic placement.

    Wire format for ``HAL.get_camera_extrinsics(direction)``. Mirror
    of ``CameraIntrinsics`` at the same HAL layer; together they
    complete the calibration pipeline so downstream consumers can do
    full pixel ↔ world-frame mapping through one stable contract.

    Implementations typically maintain their own canonical calibration
    table (e.g. a shared JSON file) and expose per-machine entries
    via the bridge endpoint
    ``GET /camera/{machine_id}/extrinsics?direction=...``. This wire
    format keeps **degrees** (matching ROS launch / URDF convention)
    so external consumers do not have to know the implementation's
    internal radians/degrees conversion choice.

    Coordinate convention (ROS):
      * forward_m: machine forward (+x)
      * lateral_m: machine left (+y)
      * height_m:  up (+z)
      * yaw_deg:   heading offset, CCW positive (front=0°, left=+90°)
      * pitch_deg: positive = nose down
      * roll_deg:  positive = right wing down (typically 0 for
                   construction equipment cameras)

    Fields:
        forward_m, lateral_m, height_m: camera optical-center offset
            from ``base_link`` origin in the machine body frame.
        yaw_deg, pitch_deg, roll_deg: rotation from machine forward
            to camera optical axis (Tait-Bryan ZYX, intrinsic).
        parent_link: URDF link this camera is rigidly attached to.
            Empty string ≡ ``"base_link"``. Used for articulated
            mounts (e.g. excavator bucket camera follows ``arm_link``
            so its world-frame pose updates with boom motion).
        fov_deg: horizontal field of view in degrees (e.g. Unity
            ``Camera.fieldOfView``). The intrinsics fallback uses
            this with ``infer_pinhole_intrinsics`` when a full
            ``CameraIntrinsics`` is unavailable.
        image_width, image_height: pixel dimensions of frames this
            placement describes. Pin so consumers can validate
            against actual blob bytes (mismatch = wrong calibration
            pair).

    The BaseModel + HAL method exist as ABC-level contracts. HAL
    subclasses MAY return ``None`` until their bridge endpoint
    materializes; callers that get ``None`` are expected to use the
    implementation's own calibration fallback path.
    """

    forward_m: float = 0.0
    lateral_m: float = 0.0
    height_m: float = 0.0
    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    parent_link: str = ""
    fov_deg: float = 60.0
    image_width: int = 0
    image_height: int = 0


class OperatorInput(BaseModel):
    """One operator teleop input snapshot.

    Captures one moment of operator command stream input from a
    teleoperated machine. Consumed by operator-shadow capture
    pipelines (Echo / RuleBased / future Real policies) to compare
    real human action against CAP autonomous prediction.

    The dataclass + HAL method exist as ABC-level contracts. HAL
    subclasses MAY return ``None`` from ``get_operator_input`` (no
    teleop) until their capture pipeline materializes, so the
    contract is forward-compatible.

    Fields:
        timestamp_iso: When this input was captured (UTC ISO-8601).
            Empty when synthetic / not yet timestamped.
        machine_id: Which machine the operator was driving.
        input_kind: Stable categorical tag for this input type:
            * ``"joystick"`` — continuous control (throttle / steering
              / boom-lift / etc. as floats in raw_command)
            * ``"discrete"`` — categorical command (e.g. start_dump,
              stop, return_home; details in raw_command)
            * ``"emergency_stop"`` — operator pressed E-stop
            * ``"mode_switch"`` — operator changed mode (manual ↔
              auto ↔ supervised)
            * Custom strings allowed for plant-specific extensions
        raw_command: Free-form dict carrying the actual command
            payload. Structure is determined by ``input_kind`` —
            consumers (operator-shadow comparator, training
            extractors) interpret it according to that tag.
        emergency_stop: Canonical E-stop flag (True iff this snapshot
            represents an active emergency stop). Promoted out of
            ``raw_command`` because it gates safety-critical paths
            and must never be missed by ``input_kind`` typo.
        metadata: Arbitrary extra context (operator session id /
            input device serial / approval status). Forward-compatible
            extension point — prefer adding typed fields when a
            metadata key recurs across consumers.
    """

    timestamp_iso: str = ""
    machine_id: str = ""
    input_kind: str = ""
    raw_command: dict[str, object] = {}
    emergency_stop: bool = False
    metadata: dict[str, object] = {}
