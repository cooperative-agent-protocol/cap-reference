// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors

#include "cap_sdk_core/validator.h"

#include <gtest/gtest.h>

#include "cap_sdk_construction/skills_registry.h"

namespace {

using namespace cap::sdk;
namespace pb = cap::v0::core;

TEST(Validator, ManifestRequiresMachineId) {
  pb::CapabilityManifest m;
  m.set_machine_type(pb::MACHINE_TYPE_EXCAVATOR);
  EXPECT_FALSE(validate_manifest(m).valid);

  m.set_machine_id("zx120-01");
  EXPECT_TRUE(validate_manifest(m).valid);
}

TEST(Validator, ManifestRejectsUnspecifiedType) {
  pb::CapabilityManifest m;
  m.set_machine_id("zx120-01");
  m.set_machine_type(pb::MACHINE_TYPE_UNSPECIFIED);
  EXPECT_FALSE(validate_manifest(m).valid);
}

TEST(Validator, HeartbeatFuelRange) {
  pb::Heartbeat h;
  h.set_machine_id("zx120-01");
  h.set_fuel_or_battery_percent(50.0);
  EXPECT_TRUE(validate_heartbeat(h).valid);

  h.set_fuel_or_battery_percent(150.0);
  EXPECT_FALSE(validate_heartbeat(h).valid);
}

TEST(Validator, WorkOrderRequiresSkill) {
  pb::WorkOrder wo;
  wo.set_task_id("t-1");
  EXPECT_FALSE(validate_work_order(wo).valid);

  wo.set_skill(std::string(construction::Skills::ExcavateBatch));
  EXPECT_TRUE(validate_work_order(wo).valid);
}

TEST(Validator, ProgressCompletionRatioRange) {
  pb::ProgressEvent ev;
  ev.set_task_id("t-1");
  ev.set_completion_ratio(0.5);
  EXPECT_TRUE(validate_progress_event(ev).valid);

  ev.set_completion_ratio(1.5);
  EXPECT_FALSE(validate_progress_event(ev).valid);
}

TEST(Validator, TerminalTaskStatesAbsorb) {
  EXPECT_TRUE(is_terminal_task_state(pb::TASK_STATE_SUCCEEDED));
  EXPECT_TRUE(is_terminal_task_state(pb::TASK_STATE_FAILED));
  EXPECT_TRUE(is_terminal_task_state(pb::TASK_STATE_CANCELLED));
  EXPECT_TRUE(is_terminal_task_state(pb::TASK_STATE_REJECTED));
  EXPECT_TRUE(is_terminal_task_state(pb::TASK_STATE_EXPIRED));
  EXPECT_FALSE(is_terminal_task_state(pb::TASK_STATE_RUNNING));

  EXPECT_FALSE(
      validate_task_transition(pb::TASK_STATE_SUCCEEDED, pb::TASK_STATE_RUNNING).valid);
  EXPECT_TRUE(
      validate_task_transition(pb::TASK_STATE_PENDING, pb::TASK_STATE_RUNNING).valid);
}

TEST(Construction, SkillConstants) {
  EXPECT_EQ(construction::Skills::ExcavateBatch, "construction.excavate_batch");
  EXPECT_EQ(construction::Skills::HaulRoute, "construction.haul_route");
  EXPECT_EQ(construction::ZoneTypes::Excavation, "excavation");
}

}  // namespace
