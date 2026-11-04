/** Numeric conventions shared by both client implementations. */
export class ProtocolError extends Error {}

export function integer(value, name, minimum = 0) {
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new ProtocolError(`${name} must be a safe integer >= ${minimum}`);
  }
  return value;
}

export function number(value, name, minimum = -Infinity) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum) {
    throw new ProtocolError(`${name} must be a finite number >= ${minimum}`);
  }
  return value;
}

export function boolean(value, name) {
  if (typeof value !== "boolean")
    throw new ProtocolError(`${name} must be a boolean`);
  return value;
}

export function fields(payload, required, optional = []) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ProtocolError("Expected a QTP object");
  }
  const allowed = [...required, ...optional];
  if (
    required.some((key) => !Object.hasOwn(payload, key)) ||
    Object.keys(payload).some((key) => !allowed.includes(key))
  ) {
    throw new ProtocolError("Invalid QTP fields");
  }
  return payload;
}

export function roundEven(value) {
  const lower = Math.floor(value);
  const fraction = value - lower;
  return fraction < 0.5 || (fraction === 0.5 && lower % 2 === 0)
    ? lower
    : lower + 1;
}

export const round6 = (value) => roundEven(value * 1_000_000) / 1_000_000;
export const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
export const clampU8 = (value) => clamp(roundEven(value), 0, 255);
