/** Deterministic overlap scenario shared by unit and cross-language tests. */
import { fileURLToPath } from "node:url";
import { connect, Percept } from "../../lib/index.js";

export async function overlapScenario() {
  const client = connect(undefined, "auto");
  let entered, release;
  const started = new Promise((resolve) => {
    entered = resolve;
  });
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    calls++;
    if (calls === 1) {
      entered();
      await gate;
    }
    throw new TypeError("offline");
  };
  try {
    const first = client.step(new Percept());
    await started;
    let overlap = "accepted",
      reset = "accepted";
    try {
      try {
        await client.step(new Percept());
      } catch (error) {
        overlap = error.constructor.name;
      }
      try {
        client.reset();
      } catch (error) {
        reset = error.constructor.name;
      }
    } finally {
      release();
    }
    const intentions = [await first, await client.step(new Percept())];
    return {
      overlap,
      reset,
      calls,
      steps: intentions.map((value) => value.step),
      count: client.stepCount,
      localCount: client.local.stepCount,
      decisions: client.local.status().decisions,
    };
  } finally {
    release();
    globalThis.fetch = original;
  }
}
if (process.argv[1] === fileURLToPath(import.meta.url))
  console.log(JSON.stringify(await overlapScenario()));
