// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors

#include "cap_sdk_core/frame_builder.h"

#include <gtest/gtest.h>

namespace {

using namespace cap::sdk;
namespace pb = cap::v0::core;

TEST(FrameBuilder, MakeHeaderPopulatesIds) {
  auto h = make_header("zx120-01", "site-agent-01");
  EXPECT_EQ(h.sender_id(), "zx120-01");
  EXPECT_EQ(h.receiver_id(), "site-agent-01");
  EXPECT_FALSE(h.message_id().empty());
}

TEST(FrameBuilder, WrapManifestRoundTrip) {
  auto h = make_header("zx120-01", "site-agent-01");
  pb::CapabilityManifest m;
  m.set_machine_id("zx120-01");
  m.set_machine_type(pb::MACHINE_TYPE_EXCAVATOR);

  pb::ConnectRequest req = wrap_capability_manifest(h, m);
  ASSERT_TRUE(req.has_frame());
  EXPECT_TRUE(req.frame().has_capability_manifest());
  EXPECT_EQ(req.frame().capability_manifest().machine_id(), "zx120-01");
}

TEST(FrameBuilder, WrapHeartbeat) {
  auto h = make_header("zx120-01", "site-agent-01");
  pb::Heartbeat hb;
  hb.set_machine_id("zx120-01");
  hb.set_fuel_or_battery_percent(88.0);

  pb::ConnectRequest req = wrap_heartbeat(h, hb);
  ASSERT_TRUE(req.has_frame());
  EXPECT_TRUE(req.frame().has_heartbeat());
}

}  // namespace
