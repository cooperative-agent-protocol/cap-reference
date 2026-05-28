/**
 * CAP Cross-Language Interop Test — JavaScript/Node.js side.
 *
 * Reads a protobuf-serialized CapFrame from stdin (Python side),
 * deserializes it with @bufbuild/protobuf, validates fields,
 * creates a WorkOrderAck response, and writes it to stdout.
 *
 * This proves Python and TypeScript protobuf implementations
 * produce compatible wire formats.
 *
 * Usage:  echo <binary> | node interop_test.mjs
 * Exit:   0=success, 1=error
 */

import { create, toBinary, fromBinary } from "@bufbuild/protobuf";
import { CapFrameSchema } from "../../cap-spec/gen/ts/cap/v0/runtime_pb.js";
import { MessageHeaderSchema } from "../../cap-spec/gen/ts/cap/v0/common_pb.js";
import {
  WorkOrderAckSchema,
  WorkOrderAck_Decision,
} from "../../cap-spec/gen/ts/cap/v0/machine_agent_pb.js";

function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on("data", (chunk) => chunks.push(chunk));
    process.stdin.on("end", () => resolve(Buffer.concat(chunks)));
    process.stdin.on("error", reject);
  });
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
    const frame = fromBinary(CapFrameSchema, new Uint8Array(inputBytes));
    console.error("[TS] Deserialized CapFrame successfully");

    // 3. Validate header
    if (!frame.header) {
      console.error("ERROR: CapFrame has no header");
      process.exit(1);
    }
    console.error(`[TS] Header message_id: ${frame.header.messageId}`);
    console.error(`[TS] Header sender_id: ${frame.header.senderId}`);

    // 4. Validate body — expect CapabilityManifest
    if (frame.body.case !== "capabilityManifest") {
      console.error(`ERROR: Expected capabilityManifest, got '${frame.body.case}'`);
      process.exit(1);
    }

    const manifest = frame.body.value;
    console.error(`[TS] Machine ID: ${manifest.machineId}`);
    console.error(`[TS] Machine Type: ${manifest.machineType}`);
    console.error(`[TS] Skills: ${manifest.capabilities.map((c) => c.skill).join(", ")}`);
    console.error(`[TS] Mode: ${manifest.currentMode}`);
    console.error(`[TS] HAL Profile: ${manifest.halProfile}`);
    console.error(`[TS] Software Version: ${manifest.softwareVersion}`);

    if (!manifest.machineId) {
      console.error("ERROR: machineId is empty");
      process.exit(1);
    }
    if (manifest.capabilities.length === 0) {
      console.error("ERROR: capabilities is empty");
      process.exit(1);
    }

    // 5. Create response CapFrame with WorkOrderAck
    const responseFrame = create(CapFrameSchema, {
      header: create(MessageHeaderSchema, {
        messageId: "ts-interop-response-001",
        senderId: manifest.machineId,
        receiverId: frame.header.senderId || "site-agent-01",
      }),
      body: {
        case: "workOrderAck",
        value: create(WorkOrderAckSchema, {
          taskId: "interop-test-task",
          decision: WorkOrderAck_Decision.ACCEPTED,
          reason: "TS deserialized Python manifest OK",
        }),
      },
    });

    // 6. Serialize and write to stdout
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
