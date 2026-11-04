import assert from "node:assert/strict";
import test from "node:test";
import {
  Consequence,
  Intention,
  Percept,
  QTP_VERSION,
  Retina,
  VERSION,
  connect,
} from "../../lib/index.js";

test("Percept and Consequence roundtrip over QTP wire format", () => {
  const retina = new Retina();
  const frame = retina.observe(0.35, [240, 180, 60], "still");
  assert.equal(frame.width, 64);
  assert.equal(frame.height, 48);
  assert.equal(frame.rgb.length, 64 * 48 * 3);

  const wire = frame.toDict();
  assert.equal(typeof wire.rgb, "string");
  const restored = Percept.fromDict(wire);
  assert.deepEqual(restored.pixel(32, 24), frame.pixel(32, 24));

  const outcome = new Consequence({
    accepted: false,
    blocked: true,
    completed: true,
    progress: 0.12,
    range: 0.08,
  });
  assert.equal(outcome.success, true);
  assert.equal(outcome.toDict().success, true);
});

test("Client local reflex loop and Intention bias", async () => {
  assert.equal(VERSION, "0.3.0");
  assert.equal(QTP_VERSION, "qtp/1.0");

  const client = connect("http://127.0.0.1:8001", "local");
  const f0 = client.retina.observe(0.4, [220, 220, 255], "still");
  const i0 = await client.step(f0);
  assert.equal(i0.action, "forward");
  assert.equal(i0.fallback, true);

  const f1 = client.retina.observe(0.1, [220, 220, 255], "forward");
  const blocked = new Consequence({
    accepted: false,
    blocked: true,
    range: 0.1,
  });
  const i1 = await client.step(f1, blocked);
  assert.ok(i1.action === "left" || i1.action === "right");

  const biased = new Intention({
    action: "right",
    step: 2,
    scores: { left: 0.25, right: 0.75, forward: 0.5 },
  });
  assert.equal(biased.bias, 0.5);
});
