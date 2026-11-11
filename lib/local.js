/** The same deterministic demonstration policy as the Python client. */
import { ACTIONS, Intention, QTP_VERSION } from "./protocol.js";
import { extractPatches } from "./retina.js";
import { ProtocolError, clamp, integer, round6, roundEven } from "./numbers.js";

export class LocalEngine {
  constructor(options = {}) {
    this.seed = integer(options.seed ?? 20261104, "seed");
    this.candidatesPerPool = integer(
      options.candidatesPerPool ?? 366,
      "candidatesPerPool",
      1,
    );
    this.reset();
  }
  get stepCount() {
    return this._step;
  }
  get streak() {
    return this._streak;
  }
  reset() {
    this._step = 0;
    this._streak = 0;
    this._lastAction = "still";
    this._previousPatches = null;
    this._decisions = { left: 0, right: 0, forward: 0 };
  }
  status() {
    return {
      protocol: QTP_VERSION,
      engine: "local",
      ready: true,
      steps: this._step,
      streak: this._streak,
      last_action: this._lastAction,
      decisions: { ...this._decisions },
    };
  }
  observe(percept, consequence = null, options = {}) {
    if (!ACTIONS.includes(options.action))
      throw new ProtocolError("Invalid observed action");
    const step =
      options.step === undefined ? this._step : integer(options.step, "step");
    this._receive(percept, consequence);
    this._record(options.action, step);
  }
  step(percept, consequence = null, options = {}) {
    const step =
      options.step === undefined ? this._step : integer(options.step, "step");
    const patches = this._receive(percept, consequence);
    const scores = {
      left: clamp(
        0.28 + 0.72 * poolDrive(patches.filter((p) => p.x < 5)),
        0,
        1,
      ),
      right: clamp(
        0.28 + 0.72 * poolDrive(patches.filter((p) => p.x >= 11)),
        0,
        1,
      ),
      forward: clamp(
        0.3 + 0.7 * poolDrive(patches.filter((p) => p.x >= 5 && p.x < 11)),
        0,
        1,
      ),
    };
    if (consequence?.completed && Object.hasOwn(scores, this._lastAction)) {
      scores[this._lastAction] = clamp(scores[this._lastAction] + 0.15, 0, 1);
    }
    let action;
    if (this._streak > 0) {
      action = this._recoveryTurn(step, scores);
      scores.forward = round6(scores.forward * 0.35);
      scores[action] = clamp(Math.max(scores[action], 0.68), 0, 1);
    } else {
      action = ["forward", "left", "right"].reduce(
        (best, candidate) =>
          scores[candidate] > scores[best] ? candidate : best,
        "forward",
      );
    }
    const candidates = {
      left: this.candidatesPerPool,
      right: this.candidatesPerPool,
      forward: this.candidatesPerPool,
    };
    const active = Object.fromEntries(
      Object.entries(scores).map(([key, value]) => [
        key,
        Math.min(
          this.candidatesPerPool,
          Math.max(1, roundEven(value * this.candidatesPerPool)),
        ),
      ]),
    );
    const rounded = Object.fromEntries(
      Object.entries(scores).map(([key, value]) => [key, round6(value)]),
    );
    this._record(action, step);
    return new Intention({
      action,
      step,
      active,
      candidates,
      scores: rounded,
      fallback: options.fallback ?? true,
    });
  }
  _receive(percept, consequence) {
    if (consequence) {
      if (
        consequence.blocked &&
        ["forward", "still"].includes(this._lastAction)
      )
        this._streak += 1;
      else this._streak = 0;
    }
    const patches = extractPatches(percept, this._previousPatches);
    this._previousPatches = patches;
    return patches;
  }
  _record(action, step) {
    this._lastAction = action;
    this._step = step + 1;
    if (Object.hasOwn(this._decisions, action)) this._decisions[action] += 1;
  }
  _recoveryTurn(step, scores) {
    const diff = scores.right - scores.left;
    if (Math.abs(diff) > 0.04) return diff > 0 ? "right" : "left";
    let word = 2166136261;
    for (const char of `${this.seed}:${this._streak}:${step}`)
      word = Math.imul(word ^ char.charCodeAt(0), 16777619) >>> 0;
    return word % 2 === 0 ? "left" : "right";
  }
}

function poolDrive(patches) {
  if (!patches.length) return 0;
  let total = 0;
  for (const p of patches)
    total +=
      0.55 * p.power +
      0.2 * p.contrast +
      0.15 * p.rise +
      0.1 * Math.max(Math.abs(p.delta), p.drift * 0.5);
  return round6(total / patches.length);
}
