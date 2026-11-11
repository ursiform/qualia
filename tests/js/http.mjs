/** Exercise the real reference HTTP service with the public JavaScript client. */
import { connect, Consequence, Percept } from "../../lib/index.js";
let input = "";
for await (const part of process.stdin) input += part;
const client = connect(process.argv[2], "remote", { seed: 17 });
const result = [];
for (const row of JSON.parse(input)) {
  const intent = await client.step(
    Percept.fromDict(row.frame),
    row.outcome ? Consequence.fromDict(row.outcome) : null,
  );
  const status = await client.status();
  delete status.url;
  result.push({ intention: intent.toDict(), status });
}
console.log(JSON.stringify(result));
