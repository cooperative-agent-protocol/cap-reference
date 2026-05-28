// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors
//
// Construction Domain Pack — skill / zone name constants for C++ consumers.
// Zero runtime code; pure compile-time string constants matching
// cap.v0.domains.construction.skills / .zones. Header-only.
//
// Wire identifiers are the string values below (e.g.
// "construction.excavate_batch"), carried on SkillManifest.name.

#pragma once

#include <string_view>

namespace cap::sdk::construction {

// ─── Skill name constants ────────────────────────────────────────────
struct Skills {
  static constexpr std::string_view ExcavateBatch =
      "construction.excavate_batch";
  static constexpr std::string_view HaulRoute = "construction.haul_route";
  static constexpr std::string_view Dump = "construction.dump";
};

// ─── Zone type constants ─────────────────────────────────────────────
struct ZoneTypes {
  static constexpr std::string_view Excavation = "excavation";
  static constexpr std::string_view Dump = "dump";
  static constexpr std::string_view HaulRoad = "haul_road";
  static constexpr std::string_view Terrain = "terrain";
  static constexpr std::string_view Staging = "staging";
};

// ─── Effect metric keys ──────────────────────────────────────────────
struct EffectKeys {
  static constexpr std::string_view VolumeExcavatedM3 = "volume_excavated_m3";
  static constexpr std::string_view BucketFillAvg = "bucket_fill_avg";
  static constexpr std::string_view VolumeDumpedM3 = "volume_dumped_m3";
  static constexpr std::string_view PayloadDeltaM3 = "payload_delta_m3";
};

}  // namespace cap::sdk::construction
