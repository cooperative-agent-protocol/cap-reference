// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors
//
// Hardware Abstraction Layer (HAL) — pure virtual interfaces that decouple
// Machine Agent logic from specific hardware / simulator backends. Mirrors
// the Python reference (cap_sdk/hal.py) at the abstract-contract level.
//
// Header-only ABCs at v0.1; concrete implementations (Gazebo / ros2_control
// / vendor fieldbus) live in downstream integration repos.

#pragma once

#include <optional>
#include <string>
#include <tuple>
#include <vector>

namespace cap::sdk {

/// Joint command interface — controlling machine joints (boom, arm, bucket).
class JointCommandInterface {
 public:
  virtual ~JointCommandInterface() = default;

  /// Command a joint to a target position (radians).
  virtual void set_position(const std::string& joint_name,
                            double position_rad) = 0;

  /// Read current joint position (radians); 0.0 if unavailable.
  virtual double get_position(const std::string& joint_name) = 0;

  /// List controllable joint names.
  virtual std::vector<std::string> get_joint_names() = 0;
};

/// Mobility interface — chassis movement.
class MobilityInterface {
 public:
  virtual ~MobilityInterface() = default;

  /// Set chassis velocity directly (teleop): linear m/s, angular rad/s.
  virtual void set_velocity(double linear_x, double angular_z) = 0;

  /// Navigate to a world-frame target (meters; yaw optional, radians).
  virtual void navigate_to(double x, double y,
                           std::optional<double> yaw = std::nullopt) = 0;

  /// Immediately stop all motion and cancel navigation.
  virtual void stop() = 0;

  /// Read odometry: (x, y, yaw_rad, speed_mps) in world frame.
  virtual std::tuple<double, double, double, double> get_odometry() = 0;

  /// True if no navigation is active or the last target was reached.
  virtual bool has_arrived() = 0;
};

/// Top-level HAL — bundles joint + mobility control plus identity.
class HardwareAbstractionLayer {
 public:
  virtual ~HardwareAbstractionLayer() = default;

  virtual const std::string& machine_id() const = 0;
  virtual JointCommandInterface& joints() = 0;
  virtual MobilityInterface& mobility() = 0;

  /// Optional camera frame as PNG bytes for a VLM verifier. Default: none.
  /// Implementations MUST NOT throw — return std::nullopt when no frame.
  virtual std::optional<std::vector<unsigned char>> get_camera_frame(
      const std::string& /*direction*/ = "front") {
    return std::nullopt;
  }
};

}  // namespace cap::sdk
