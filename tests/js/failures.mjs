/** Compare failure classification and client state over real HTTP. */
import { connect, Percept } from "../../lib/index.js";

const client = connect(process.argv[2], "auto", { timeout: 0.15 });
let result;
try {
  const intention = await client.step(new Percept());
  result = { action: intention.action, fallback: intention.fallback };
} catch (error) {
  result = {
    error: error.constructor.name,
    status: error.status ?? null,
    timedOut: error.timedOut ?? false,
  };
}
console.log(
  JSON.stringify({
    ...result,
    steps: client.stepCount,
    localSteps: client.local.stepCount,
    lastAction: client.lastAction,
  }),
);
