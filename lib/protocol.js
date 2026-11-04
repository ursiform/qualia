/** QTP wire types; remote data is validated before becoming a decision. */
import {
  ProtocolError,
  boolean,
  fields,
  integer,
  number,
  clamp,
  round6,
} from "./numbers.js";
export { ProtocolError } from "./numbers.js";

export const VERSION = "0.3.0";
export const QTP_VERSION = "qtp/1.0";
export const DEFAULT_WIDTH = 64;
export const DEFAULT_HEIGHT = 48;
export const DEFAULT_URL = "http://127.0.0.1:8001";
export const MOTOR_ACTIONS = Object.freeze(["left", "right", "forward"]);
export const ACTIONS = Object.freeze([...MOTOR_ACTIONS, "still"]);
const PHASES = ["sample", "neutral", "choice", "visible"];

function bytesToBase64(bytes) {
  if (typeof Buffer !== "undefined")
    return Buffer.from(bytes).toString("base64");
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(encoded) {
  if (
    typeof encoded !== "string" ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
      encoded,
    )
  ) {
    throw new ProtocolError("Invalid base64 RGB buffer");
  }
  const bytes =
    typeof Buffer !== "undefined"
      ? new Uint8Array(Buffer.from(encoded, "base64"))
      : Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
  if (bytesToBase64(bytes) !== encoded)
    throw new ProtocolError("Noncanonical base64 RGB buffer");
  return bytes;
}

function pools(value, name, counts) {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    MOTOR_ACTIONS.some((key) => !Object.hasOwn(value, key))
  ) {
    throw new ProtocolError(
      `${name} must contain left, right, and forward pools`,
    );
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      counts ? integer(item, name) : number(item, name),
    ]),
  );
}

export class Percept {
  constructor(init = {}) {
    this.width = integer(init.width ?? DEFAULT_WIDTH, "width", 1);
    this.height = integer(init.height ?? DEFAULT_HEIGHT, "height", 1);
    const expected = this.width * this.height * 3;
    this.rgb =
      init.rgb === undefined
        ? new Uint8Array(expected)
        : new Uint8Array(init.rgb);
    if (this.rgb.length !== expected)
      throw new ProtocolError("RGB buffer does not match dimensions");
    this.step = integer(init.step ?? 0, "step");
    this.phase = init.phase ?? "visible";
    if (!PHASES.includes(this.phase)) throw new ProtocolError("Invalid phase");
    this.cue = init.cue ?? null;
    if (this.cue !== null && typeof this.cue !== "string")
      throw new ProtocolError("cue must be a string or null");
    Object.freeze(this);
  }

  static fromDict(payload) {
    fields(payload, ["width", "height", "rgb", "step", "phase"], ["cue"]);
    integer(payload.width, "width", 1);
    integer(payload.height, "height", 1);
    integer(payload.step, "step");
    if (!PHASES.includes(payload.phase))
      throw new ProtocolError("Invalid phase");
    return new Percept({ ...payload, rgb: base64ToBytes(payload.rgb) });
  }

  toDict() {
    return {
      width: this.width,
      height: this.height,
      rgb: bytesToBase64(this.rgb),
      step: this.step,
      phase: this.phase,
      cue: this.cue,
    };
  }

  pixel(x, y) {
    integer(x, "x");
    integer(y, "y");
    if (x >= this.width || y >= this.height)
      throw new RangeError("Pixel out of bounds");
    const offset = (y * this.width + x) * 3;
    return [this.rgb[offset], this.rgb[offset + 1], this.rgb[offset + 2]];
  }
}

export class Consequence {
  constructor(init = {}) {
    this.accepted = boolean(init.accepted ?? true, "accepted");
    this.blocked = boolean(init.blocked ?? false, "blocked");
    this.completed = boolean(
      init.completed ?? init.success ?? false,
      "completed",
    );
    this.reward = number(init.reward ?? 0, "reward");
    this.progress = number(init.progress ?? 0, "progress");
    this.range = number(init.range ?? 0, "range", 0);
    Object.freeze(this);
  }
  get success() {
    return this.completed;
  }
  static fromDict(payload) {
    fields(payload, [
      "accepted",
      "blocked",
      "success",
      "reward",
      "progress",
      "range",
    ]);
    for (const key of ["accepted", "blocked", "success"])
      boolean(payload[key], key);
    number(payload.reward, "reward");
    number(payload.progress, "progress");
    number(payload.range, "range", 0);
    return new Consequence({ ...payload, completed: payload.success });
  }
  toDict() {
    return {
      accepted: this.accepted,
      blocked: this.blocked,
      success: this.completed,
      reward: round6(this.reward),
      progress: round6(this.progress),
      range: round6(this.range),
    };
  }
}

export class Intention {
  constructor(init = {}) {
    this.action = init.action ?? "still";
    if (!ACTIONS.includes(this.action))
      throw new ProtocolError("Invalid action");
    this.step = integer(init.step ?? 0, "step");
    this.active = pools(
      init.active ?? { left: 0, right: 0, forward: 0 },
      "active",
      true,
    );
    this.candidates = pools(
      init.candidates ?? { left: 0, right: 0, forward: 0 },
      "candidates",
      true,
    );
    this.scores = pools(
      init.scores ?? { left: 0, right: 0, forward: 0 },
      "scores",
      false,
    );
    if (
      Object.entries(this.active).some(
        ([key, count]) =>
          count >
          (Object.hasOwn(this.candidates, key) ? this.candidates[key] : 0),
      )
    ) {
      throw new ProtocolError("active counts cannot exceed candidate counts");
    }
    this.fallback = boolean(init.fallback ?? false, "fallback");
    Object.freeze(this);
  }
  get bias() {
    const left = this.scores.left;
    const right = this.scores.right;
    const sum = Math.abs(left) + Math.abs(right);
    if (sum > 1e-9) return round6(clamp((right - left) / sum, -1, 1));
    const total = this.active.left + this.active.right;
    return total > 0
      ? round6(clamp((this.active.right - this.active.left) / total, -1, 1))
      : 0;
  }
  static fromDict(payload) {
    fields(payload, [
      "action",
      "step",
      "active",
      "candidates",
      "scores",
      "fallback",
    ]);
    if (!ACTIONS.includes(payload.action))
      throw new ProtocolError("Invalid action");
    integer(payload.step, "step");
    boolean(payload.fallback, "fallback");
    pools(payload.active, "active", true);
    pools(payload.candidates, "candidates", true);
    pools(payload.scores, "scores", false);
    return new Intention(payload);
  }
  toDict() {
    return {
      action: this.action,
      step: this.step,
      active: { ...this.active },
      candidates: { ...this.candidates },
      scores: Object.fromEntries(
        Object.entries(this.scores).map(([key, value]) => [key, round6(value)]),
      ),
      fallback: this.fallback,
    };
  }
}
