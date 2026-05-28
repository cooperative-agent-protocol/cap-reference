# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Hardware abstraction interfaces for joint control and mobility.

Defines abstract base classes that decouple machine controllers from
specific hardware implementations. This enables the same controller code
to work with:
  - Gazebo simulation (joint / mobility adapters)
  - ros2_control (for real hardware via Gazebo or direct)
  - Vendor-specific fieldbus integrations (e.g. CAN bus / EtherCAT)
  - Nav2 (production navigation stack)

Layer [C] in the 3-layer architecture:
  [A] Site Agent — strategic planning (LLM)
  [B] Machine Agent — situation assessment (LLM, advisory only)
  [C] Safety Supervisor + HAL — deterministic control (this module)

Usage (illustrative — concrete subclasses live in implementation
repos):

    # In simulation
    joint_if = MyGzJointInterface(node, "/excavator_01", joint_names)

    # On real hardware (ros2_control)
    joint_if = MyRos2ControlJointInterface(node, "/excavator_01", joint_names)

    # Controller code is identical for both:
    joint_if.set_position("boom_joint", 0.5)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ---------------------------------------------------------------------------
# Joint Command Interface
# ---------------------------------------------------------------------------


class JointCommandInterface(ABC):
    """Abstract interface for controlling machine joints (boom, arm, bucket, etc.).

    Implementations:
      - GzJointInterface: publishes Float64 to Gazebo Ignition joint position controllers
      - Ros2ControlJointInterface: publishes JointTrajectory to ros2_control
      - CanBusJointInterface: sends CAN frames to hydraulic valves (future)
    """

    @abstractmethod
    def set_position(self, joint_name: str, position_rad: float) -> None:
        """Command a joint to move to a target position.

        Args:
            joint_name: URDF joint name (e.g., "boom_joint", "bucket_joint")
            position_rad: Target position in radians.
        """

    @abstractmethod
    def get_position(self, joint_name: str) -> float:
        """Read current joint position.

        Returns:
            Current position in radians. Returns 0.0 if not yet available.
        """

    @abstractmethod
    def get_joint_names(self) -> list[str]:
        """Return list of controllable joint names."""

    def set_positions(self, positions: dict[str, float]) -> None:
        """Command multiple joints at once (convenience method).

        Default implementation calls set_position for each joint.
        Subclasses may override for atomic multi-joint commands.
        """
        for joint_name, position_rad in positions.items():
            self.set_position(joint_name, position_rad)

    def get_positions(self) -> dict[str, float]:
        """Read all joint positions (convenience method)."""
        return {name: self.get_position(name) for name in self.get_joint_names()}


# ---------------------------------------------------------------------------
# Mobility Interface
# ---------------------------------------------------------------------------


class MobilityInterface(ABC):
    """Abstract interface for machine mobility (chassis movement).

    Implementations:
      - GzMobilityInterface: proportional controller → cmd_vel Twist → Gazebo DiffDrive/Ackermann
      - Nav2MobilityInterface: NavigateToPose action → Nav2 → cmd_vel (with path planning)
      - CanBusMobilityInterface: CAN frames to drive motors (future)
    """

    @abstractmethod
    def set_velocity(self, linear_x: float, angular_z: float) -> None:
        """Set chassis velocity directly (teleop mode).

        Args:
            linear_x: Forward velocity in m/s.
            angular_z: Rotational velocity in rad/s.
        """

    @abstractmethod
    def navigate_to(self, x: float, y: float, yaw: float | None = None) -> None:
        """Command the machine to navigate to a target position.

        The implementation handles path planning and execution.
        Call has_arrived() to check completion.

        Args:
            x: Target X position in world frame (meters).
            y: Target Y position in world frame (meters).
            yaw: Target heading in radians (None = don't care).
        """

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop all motion and cancel navigation."""

    @abstractmethod
    def get_odometry(self) -> tuple[float, float, float, float]:
        """Read current odometry.

        Returns:
            (x, y, yaw_rad, speed_mps) in world frame.
        """

    @abstractmethod
    def has_arrived(self) -> bool:
        """Check if the last navigate_to() command has completed.

        Returns True if no navigation is active or if the target was reached.
        """

    @property
    def position(self) -> tuple[float, float]:
        """Current (x, y) position (convenience)."""
        x, y, _, _ = self.get_odometry()
        return (x, y)

    @property
    def yaw_rad(self) -> float:
        """Current heading in radians (convenience)."""
        _, _, yaw, _ = self.get_odometry()
        return yaw

    @property
    def speed_mps(self) -> float:
        """Current speed in m/s (convenience)."""
        _, _, _, speed = self.get_odometry()
        return speed
