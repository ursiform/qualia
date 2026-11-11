/** Cross-language runner: input comes only from the Python test process. */
import {
  Consequence,
  DEFAULT_URL,
  LocalEngine,
  Percept,
  Retina,
  Intention,
  extractPatches,
  schema,
  openapi,
} from "../../lib/index.js";
let input = "";
for await (const part of process.stdin) input += part;
const cases = JSON.parse(input);
const result = {
  schema: schema(),
  url: DEFAULT_URL,
  openapi: openapi(),
  engines: [],
  retinas: [],
  wires: [],
};
for (const scenario of cases.engines) {
  const engine = new LocalEngine({
    seed: scenario.seed,
    candidatesPerPool: scenario.candidates,
  });
  let prior = null;
  const rows = [];
  for (const row of scenario.rows) {
    const frame = Percept.fromDict(row.frame);
    const outcome = row.outcome ? Consequence.fromDict(row.outcome) : null;
    const patches = extractPatches(frame, prior);
    prior = patches;
    let intention = null;
    if (row.action) engine.observe(frame, outcome, { action: row.action });
    else intention = engine.step(frame, outcome).toDict();
    rows.push({ intention, status: engine.status(), patches });
  }
  result.engines.push(rows);
}
for (const scenario of cases.retinas) {
  const retina = new Retina(scenario.options);
  const rows = [];
  for (const row of scenario.rows) {
    if (row.reset) retina.reset();
    else
      rows.push(
        (row.blank
          ? retina.blank(row.blank)
          : retina.observe(row.observe)
        ).toDict(),
      );
  }
  result.retinas.push(rows);
}
for (const row of cases.wires ?? []) {
  try {
    const Type = {
      percept: Percept,
      consequence: Consequence,
      intention: Intention,
    }[row.kind];
    const value = Type.fromDict(row.value);
    result.wires.push({
      value: value.toDict(),
      ...(row.kind === "intention" ? { bias: value.bias } : {}),
    });
  } catch {
    result.wires.push({ error: true });
  }
}
console.log(JSON.stringify(result));
