import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { overlapScenario } from "./sessions.mjs";
import {
  Client,
  Consequence,
  Intention,
  Percept,
  ProtocolError,
  Retina,
  TransportError,
  connect,
  extractPatches,
  schema,
  openapi,
} from "../../lib/index.js";

const decision = (action = "left", step = 0) =>
  new Intention({ action, step }).toDict();
const response = (value) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
const ready = { protocol: "qtp/1.0", ready: true };

async function withFetch(fetcher, run) {
  const original = globalThis.fetch;
  globalThis.fetch = fetcher;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("overlapping steps and resets are rejected before capturing an index", async () => {
  const result = await overlapScenario();
  assert.equal(result.overlap, "ProtocolError");
  assert.equal(result.reset, "ProtocolError");
  assert.equal(result.calls, 2);
  assert.deepEqual(result.steps, [0, 1]);
  assert.equal(result.count, 2);
  assert.equal(result.localCount, 2);
  assert.equal(
    Object.values(result.decisions).reduce((a, b) => a + b, 0),
    2,
  );
});

test("step guard is released after input and response failures", async () => {
  const replies = [
    new Response("failure", { status: 503 }),
    response({}),
    response(decision()),
  ];
  let calls = 0;
  await withFetch(
    async () => {
      calls++;
      return replies.shift();
    },
    async () => {
      const client = connect();
      await assert.rejects(client.step({}), ProtocolError);
      assert.equal(calls, 0);
      await assert.rejects(client.step(new Percept()), TransportError);
      await assert.rejects(client.step(new Percept()), ProtocolError);
      assert.equal(client.stepCount, 0);
      assert.equal(client.local.stepCount, 0);
      assert.equal((await client.step(new Percept())).step, 0);
      assert.equal(calls, 3);
      client.reset();
      assert.equal(client.stepCount, 0);
    },
  );
});

test("strict UTF-8 decoding rejects malformed bytes without advancing state", async () => {
  const template = JSON.stringify({
    ...decision(),
    scores: { left: 0, right: 0, forward: 0, extra: 1 },
  });
  const [before, after] = template.split("extra");
  const encode = (value) => new TextEncoder().encode(value);
  for (const invalid of [
    [0x80],
    [0xc3, 0x28],
    [0xed, 0xa0, 0x80],
    [0xf0, 0x9f],
  ]) {
    const body = new Uint8Array([
      ...encode(before),
      ...invalid,
      ...encode(after),
    ]);
    await withFetch(
      async () => new Response(body),
      async () => {
        const client = connect();
        await assert.rejects(client.step(new Percept()), ProtocolError);
        assert.equal(client.stepCount, 0);
        assert.equal(client.local.stepCount, 0);
      },
    );
  }
  const wire = {
    ...decision(),
    scores: { left: 0, right: 0, forward: 0, "café-雪-�": 1 },
  };
  await withFetch(
    async () => response(wire),
    async () => {
      const intention = await connect().step(new Percept());
      assert.deepEqual(intention.toDict(), wire);
    },
  );
});

test("extreme and threshold score pairs produce the specified finite bias", () => {
  const cases = JSON.parse(
    readFileSync(new URL("../bias.json", import.meta.url), "utf8"),
  );
  for (const row of cases) {
    const intention = new Intention({
      scores: { left: row.left, right: row.right, forward: 0 },
      active: { left: 2, right: 8, forward: 0 },
      candidates: { left: 10, right: 10, forward: 10 },
    });
    assert.ok(Number.isFinite(intention.bias));
    assert.equal(intention.bias, row.bias);
  }
});

test("HTTP error responses abort unread bodies without waiting for the deadline", async () => {
  for (const status of [403, 404, 503]) {
    for (const operation of ["status", "step"]) {
      let signal;
      const methods = [];
      let reads = 0;
      await withFetch(
        async (url, options) => {
          signal = options.signal;
          methods.push(options.method ?? "GET");
          return {
            ok: false,
            status,
            arrayBuffer: () => {
              reads++;
              return new Promise(() => {});
            },
          };
        },
        async () => {
          const client = connect();
          await assert.rejects(
            operation === "status"
              ? client.status()
              : client.step(new Percept()),
            (error) =>
              error instanceof TransportError &&
              error.status === status &&
              !error.timedOut,
          );
          assert.equal(signal.aborted, true);
          assert.equal(reads, 0);
          assert.deepEqual(methods, [operation === "status" ? "GET" : "POST"]);
          assert.equal(client.stepCount, 0);
          assert.equal(client.local.stepCount, 0);
        },
      );
    }
  }
});

test("large finite numbers survive JSON wire serialization", () => {
  for (const value of [
    2 ** 33,
    2 ** 33 + 0.5,
    100000000000000.5,
    -100000000000000.5,
    2 ** 52,
    -(2 ** 52),
    1e303,
    1e308,
    -1e308,
    Number.MAX_VALUE,
  ]) {
    const consequence = new Consequence({
      reward: value,
      progress: value,
      range: Math.abs(value),
    });
    const wire = JSON.parse(JSON.stringify(consequence.toDict()));
    assert.equal(wire.reward, value);
    assert.equal(wire.progress, value);
    assert.equal(wire.range, Math.abs(value));
    const intention = new Intention({
      scores: { left: value, right: 0.3, forward: 0.2 },
    });
    assert.equal(
      JSON.parse(JSON.stringify(intention.toDict())).scores.left,
      value,
    );
  }
});

test("a failed POST never falls back even without response headers", async () => {
  for (const body of [false, true]) {
    const methods = [];
    await withFetch(
      async (url, options) => {
        methods.push(options.method ?? "GET");
        if (options.method !== "POST") return response(ready);
        if (!body) throw new TypeError("connection lost after remote commit");
        return {
          ok: true,
          status: 200,
          arrayBuffer: async () => {
            throw new TypeError("body reset");
          },
        };
      },
      async () => {
        const client = connect(undefined, "auto");
        await assert.rejects(
          client.step(new Percept()),
          (error) =>
            error instanceof TransportError &&
            error.status === (body ? 200 : null),
        );
        assert.deepEqual(methods, ["GET", "POST"]);
        assert.equal(client.stepCount, 0);
        assert.equal(client.local.stepCount, 0);
        assert.equal(client.lastAction, null);
      },
    );
  }
});

test("identical uniform and textured images have zero flow", () => {
  for (const rgb of [
    new Uint8Array(64 * 48 * 3).fill(80),
    Uint8Array.from({ length: 64 * 48 * 3 }, (_, i) => i % 256),
  ]) {
    const frame = new Percept({ rgb });
    const patches = extractPatches(frame, extractPatches(frame));
    assert.ok(
      patches.every(
        (p) => p.dx === 0 && p.dy === 0 && p.drift === 0 && p.delta === 0,
      ),
    );
  }
});

test("blank clears retained cues while annotations do not draw pixels", () => {
  const retina = new Retina();
  const plain = retina.observe(0.3);
  const tagged = new Retina().observe({
    distance: 0.3,
    cue: "circle",
    phase: "sample",
  });
  assert.deepEqual(tagged.rgb, plain.rgb);
  retina.observe({ distance: 0.1, pattern: "circle", cue: "circle" });
  const blank = retina.blank();
  assert.equal(blank.step, 2);
  assert.equal(blank.cue, null);
  assert.equal(blank.phase, "neutral");
  assert.deepEqual(
    blank.rgb,
    Uint8Array.from({ length: 64 * 48 * 3 }, (_, i) => [12, 16, 24][i % 3]),
  );
  assert.deepEqual(
    retina.observe({ distance: 1, color: [12, 16, 24] }).rgb,
    blank.rgb,
  );
});

test("default remote mode and explicit auto do not hide HTTP failures", async () => {
  assert.equal(connect().mode, "remote");
  await withFetch(
    async () => {
      throw new TypeError("offline");
    },
    async () => {
      await assert.rejects(connect().step(new Percept()), TransportError);
      assert.equal(
        (await connect(undefined, "auto").step(new Percept())).fallback,
        true,
      );
    },
  );
  for (const status of [403, 404, 500]) {
    await withFetch(
      async () => new Response("failure", { status }),
      async () => {
        const client = connect(undefined, "auto");
        await assert.rejects(
          client.step(new Percept()),
          (error) => error instanceof TransportError && error.status === status,
        );
        assert.equal(client.stepCount, 0);
        assert.equal(client.local.stepCount, 0);
      },
    );
  }
});

test("malformed responses never advance either engine", async () => {
  const invalid = [
    {},
    [],
    null,
    { ready: true },
    { result: decision() },
    { intention: null },
    { intention: decision(), extra: true },
  ];
  for (const change of [
    { action: "fly" },
    { action: null },
    { step: 999 },
    { step: -1 },
    { step: true },
    { step: 0.5 },
    { fallback: true },
    { fallback: "false" },
    { active: {} },
    { candidates: { left: -1, right: 0, forward: 0 } },
    { active: { left: 1, right: 0, forward: 0 } },
  ])
    invalid.push({ ...decision(), ...change });
  for (const value of invalid) {
    await withFetch(
      async (url, options) =>
        response(options.method === "POST" ? value : ready),
      async () => {
        const client = connect(undefined, "auto");
        await assert.rejects(client.step(new Percept()), ProtocolError);
        assert.equal(client.stepCount, 0);
        assert.equal(client.lastAction, null);
        assert.equal(client.local.stepCount, 0);
      },
    );
  }
  for (const body of ["", "not-json", '{"value":NaN}']) {
    await withFetch(
      async (url, options) =>
        options.method === "POST" ? new Response(body) : response(ready),
      async () => {
        await assert.rejects(
          connect(undefined, "auto").step(new Percept()),
          ProtocolError,
        );
      },
    );
  }
});

test("direct and enveloped responses retain real remote history", async () => {
  const replies = [decision(), { intention: decision("right", 1) }];
  await withFetch(
    async () => response(replies.shift()),
    async () => {
      const client = connect();
      assert.equal((await client.step(new Percept())).action, "left");
      assert.equal((await client.step(new Percept())).action, "right");
      assert.deepEqual(client.local.status().decisions, {
        left: 1,
        right: 1,
        forward: 0,
      });
    },
  );
});

test("fallback interprets blocking against the real remote action", async () => {
  for (const [action, streak] of [
    ["left", 0],
    ["forward", 1],
    ["still", 1],
  ]) {
    let online = true;
    await withFetch(
      async (url, options) => {
        if (!online) throw new TypeError("offline");
        return response(options.method === "POST" ? decision(action) : ready);
      },
      async () => {
        const client = connect(undefined, "auto");
        const frame = client.retina.observe(0.4);
        await client.step(frame);
        assert.equal(client.local.status().last_action, action);
        online = false;
        const next = await client.step(
          frame,
          new Consequence({ accepted: false, blocked: true }),
        );
        assert.equal(next.fallback, true);
        assert.equal(client.local.streak, streak);
        assert.equal(client.local.stepCount, 2);
      },
    );
  }
});

test("timeout covers headers and response body and aborts the request", async () => {
  for (const stallBody of [false, true]) {
    let signal;
    let calls = 0;
    await withFetch(
      async (url, options) => {
        calls += 1;
        signal = options.signal;
        if (stallBody)
          return {
            ok: true,
            status: 200,
            arrayBuffer: () => new Promise(() => {}),
          };
        return new Promise(() => {});
      },
      async () => {
        const client = connect(undefined, "auto", { timeout: 0.01 });
        await assert.rejects(
          client.step(new Percept()),
          (error) =>
            error instanceof TransportError &&
            error.timedOut &&
            error.status === (stallBody ? 200 : null),
        );
        assert.equal(signal.aborted, true);
        assert.equal(calls, 1);
        assert.equal(client.stepCount, 0);
        assert.equal(client.local.stepCount, 0);
      },
    );
  }
});

test("status requires QTP readiness and cannot override source identity", async () => {
  for (const value of [
    { ready: true },
    { protocol: "qtp/1.0", ready: "true" },
  ]) {
    await withFetch(
      async () => response(value),
      async () => {
        await assert.rejects(
          connect(undefined, "auto").status(),
          ProtocolError,
        );
      },
    );
  }
  await withFetch(
    async () => response({ protocol: "qtp/1.0", ready: true, engine: "local" }),
    async () => {
      assert.equal((await connect().status()).engine, "remote");
    },
  );
});

test("wire fields reject coercion and preserve extra pool scores", () => {
  for (const change of [
    { width: true },
    { height: 1.5 },
    { step: -1 },
    { phase: "unknown" },
    { rgb: "!" },
    { rgb: null },
  ]) {
    assert.throws(
      () => Percept.fromDict({ ...new Percept().toDict(), ...change }),
      ProtocolError,
    );
  }
  for (const change of [
    { accepted: "false" },
    { range: -1 },
    { reward: Infinity },
    { blocked: null },
  ]) {
    assert.throws(
      () => Consequence.fromDict({ ...new Consequence().toDict(), ...change }),
      ProtocolError,
    );
  }
  assert.throws(
    () =>
      Intention.fromDict({
        ...decision(),
        scores: { left: NaN, right: 0, forward: 0 },
      }),
    ProtocolError,
  );
  const value = {
    ...decision(),
    scores: { left: 0.1, right: 0.2, forward: 0.3, still: 0.4 },
  };
  assert.deepEqual(Intention.fromDict(value).toDict(), value);
  assert.throws(() => new Client(undefined, "invalid"), ProtocolError);
});

test("schema exposes full definitions and returns independent copies", () => {
  const first = schema();
  assert.ok(first.$defs.StepRequest);
  assert.ok(first.$defs.StepResponse);
  delete first.$defs;
  assert.ok(schema().$defs.Intention);
});

test("OpenAPI export bundles message definitions and returns independent copies", () => {
  const contract = openapi();
  assert.equal(contract.openapi, "3.1.0");
  assert.ok(contract.paths["/api/qtp/step"].post);
  assert.ok(contract.components.schemas.Percept);
  delete contract.components;
  assert.ok(openapi().components.schemas.StepRequest);
});
