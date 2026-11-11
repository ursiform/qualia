import {
  Client,
  Consequence,
  LocalEngine,
  Percept,
  ProtocolError,
  Retina,
  TransportError,
  connect,
  extractPatches,
  schema,
  openapi,
  type StepResponse,
} from "../lib/index.js";

const retina = new Retina({ units: "physical", maxDistance: 100 });
const frame: Percept = retina.observe({
  distance: 30,
  pattern: "circle",
  cue: "target",
});
const neutral: Percept = retina.blank({ phase: "neutral" });
const outcome = new Consequence({ accepted: true, range: 0.3 });
const local = new LocalEngine({ seed: 17, candidatesPerPool: 19 });
local.observe(frame, outcome, { action: "left" });
const wire: StepResponse = { intention: local.step(neutral).toDict() };
const client: Client = connect(undefined, "remote", { timeout: 2, seed: 17 });
void client.step(frame, outcome);
void extractPatches(frame);
void schema();
void openapi();
void wire;
void new ProtocolError("invalid message");
void new TransportError("timeout", { timedOut: true });
