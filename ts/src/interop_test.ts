// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 CAP Authors

/**
 * CAP Cross-Language Interop Test — TypeScript side.
 *
 * This script reads a protobuf-serialized CapFrame from stdin,
 * deserializes it, validates the contents, creates a response
 * CapFrame (WorkOrderAck), and writes it to stdout.
 *
 * Used by cap-conformance/tests/test_interop_ts.py to verify
 * that Python and TypeScript protobuf implementations produce
 * compatible wire formats.
 *
 * Usage:
 *   echo <binary> | node dist/interop_test.js
 *
 * Exit codes:
 *   0: Success (response written to stdout)
 *   1: Deserialization or validation error (details on stderr)
 */

import { create, toBinary, fromBinary } from "@bufbuild/protobuf";
import { CapFrameSchema } from "../../cap-spec/gen/ts/cap/v0/runtime_pb.js";
import { MessageHeaderSchema } from "../../cap-spec/gen/ts/cap/v0/common_pb.js";
import {
  WorkOrderAckSchema,
  WorkOrderAck_Decision,
} from "../../cap-spec/gen/ts/cap/v0/machine_agent_pb.js";

async function readStdin(): Promise<Buffer> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks);
}

async function main() {
  try {
    // 1. Read binary from stdin
    const inputBytes = await readStdin();
    if (inputBytes.length === 0) {
      console.error("ERROR: No input received on stdin");
      process.exit(1);
    }
    console.error(`[TS] Received ${inputBytes.length} bytes`);

    // 2. Deserialize as CapFrame
    const frame = fromBinary(CapFrameSchema, inputBytes);
    console.error(`[TS] Deserialized CapFrame successfully`);

    // 3. Validate: expect a CapabilityManifest
    if (frame.body.case !== "capabilityManifest") {
      console.error(
        `ERROR: Expected capabilityManifest, got ${frame.body.case}`
      );
      process.exit(1);
    }

    const manifest = frame.body.value;
    console.error(`[TS] Machine ID: ${manifest.machineId}`);
    console.error(`[TS] Machine Type: ${manifest.machineType}`);
    console.error(`[TS] Skills: ${manifest.capabilities.map((c) => c.skill).join(", ")}`);
    console.error(`[TS] Mode: ${manifest.currentMode}`);
    console.error(`[TS] HAL Profile: ${manifest.halProfile}`);
    console.error(`[TS] Software Version: ${manifest.softwareVersion}`);

    // Validate required fields
    if (!manifest.machineId) {
      console.error("ERROR: machineId is empty");
      process.exit(1);
    }
    if (manifest.capabilities.length === 0) {
      console.error("ERROR: capabilities is empty");
      process.exit(1);
    }

    // 4. Create response CapFrame with WorkOrderAck
    const responseHeader = create(MessageHeaderSchema, {
      messageId: "ts-interop-response-001",
      senderId: manifest.machineId,
      receiverId: frame.header?.senderId ?? "site-agent-01",
    });

    const ack = create(WorkOrderAckSchema, {
      taskId: "interop-test-task",
      decision: WorkOrderAck_Decision.ACCEPTED,
      reason: "Interop test: TS successfully deserialized Python manifest",
    });

    const responseFrame = create(CapFrameSchema, {
      header: responseHeader,
      body: {
        case: "workOrderAck",
        value: ack,
      },
    });

    // 5. Serialize and write to stdout
    const outputBytes = toBinary(CapFrameSchema, responseFrame);
    process.stdout.write(Buffer.from(outputBytes));
    console.error(`[TS] Wrote ${outputBytes.length} bytes response`);
    console.error("[TS] PASS");
  } catch (err) {
    console.error(`ERROR: ${err}`);
    process.exit(1);
  }
}

main();
