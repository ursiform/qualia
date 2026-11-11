/** Egocentric sensory encoding and bounded patch matching. */
import { Percept, DEFAULT_WIDTH, DEFAULT_HEIGHT } from "./protocol.js";
import {
  ProtocolError,
  clamp,
  clampU8,
  integer,
  number,
  round6,
  roundEven,
} from "./numbers.js";

export class Retina {
  constructor(options = {}) {
    this.width = integer(options.width ?? DEFAULT_WIDTH, "width", 1);
    this.height = integer(options.height ?? DEFAULT_HEIGHT, "height", 1);
    const amb = options.ambient ?? [12, 16, 24];
    this.ambient = [clampU8(amb[0]), clampU8(amb[1]), clampU8(amb[2])];
    this.shiftColumns = integer(options.shiftColumns ?? 4, "shiftColumns", 1);
    this.decay = number(options.decay ?? 0.9, "decay", 0);
    if (this.decay > 1) throw new ProtocolError("decay must be <= 1");
    this.maxDistance = number(options.maxDistance ?? 100, "maxDistance", 0);
    this.units = options.units ?? "normalized";
    if (
      this.maxDistance === 0 ||
      !["normalized", "physical"].includes(this.units)
    )
      throw new ProtocolError(
        "Choose positive maxDistance and explicit distance units",
      );
    this._step = 0;
    this._buffer = this._blankBuffer(this.ambient);
  }

  get step() {
    return this._step;
  }

  reset(ambient) {
    if (ambient) {
      this.ambient = [
        clampU8(ambient[0]),
        clampU8(ambient[1]),
        clampU8(ambient[2]),
      ];
    }
    this._step = 0;
    this._buffer = this._blankBuffer(this.ambient);
  }

  observe(optionsOrDistance, color = [220, 220, 255], turn = "still") {
    const opts =
      typeof optionsOrDistance === "number"
        ? { distance: optionsOrDistance, color, turn }
        : optionsOrDistance;
    const bg = opts.ambient
      ? [
          clampU8(opts.ambient[0]),
          clampU8(opts.ambient[1]),
          clampU8(opts.ambient[2]),
        ]
      : this.ambient;
    const fg = opts.color
      ? [clampU8(opts.color[0]), clampU8(opts.color[1]), clampU8(opts.color[2])]
      : [220, 220, 255];

    const dx = this._turnShift(opts.turn ?? "still");
    this._shiftAndDecay(dx, bg);

    const normDist = this._normalizeDistance(opts.distance);
    const proximity = 1.0 - normDist;
    const pattern = opts.pattern ?? "solid";
    this._paintFovea(proximity, fg, bg, pattern);

    const frameStep =
      opts.step === undefined ? this._step : integer(opts.step, "step");
    this._step = frameStep + 1;
    return new Percept({
      width: this.width,
      height: this.height,
      rgb: new Uint8Array(this._buffer),
      step: frameStep,
      phase: opts.phase ?? "visible",
      cue: opts.cue ?? null,
    });
  }

  blank(options = {}) {
    const frameStep =
      options.step === undefined ? this._step : integer(options.step, "step");
    const frame = new Percept({
      width: this.width,
      height: this.height,
      rgb: this._blankBuffer(this.ambient),
      step: frameStep,
      phase: options.phase ?? "neutral",
    });
    this._buffer = new Uint8Array(frame.rgb);
    this._step = frameStep + 1;
    return frame;
  }

  _normalizeDistance(distance) {
    number(distance, "distance", 0);
    return Math.min(
      1,
      distance / (this.units === "physical" ? this.maxDistance : 1),
    );
  }

  _turnShift(turn) {
    if (typeof turn === "number") {
      number(turn, "turn");
      if (Math.abs(turn) < 1e-6) {
        return 0;
      }
      const scaled = roundEven(-turn * this.shiftColumns);
      return scaled === 0
        ? turn < 0
          ? this.shiftColumns
          : -this.shiftColumns
        : clamp(
            scaled,
            Math.floor(-this.width / 2),
            Math.floor(this.width / 2),
          );
    }
    const label = String(turn).trim().toLowerCase();
    if (label === "left") {
      return this.shiftColumns;
    }
    if (label === "right") {
      return -this.shiftColumns;
    }
    return 0;
  }

  _shiftAndDecay(dx, ambient) {
    const w = this.width;
    const h = this.height;
    const next = this._blankBuffer(ambient);
    const [ar, ag, ab] = ambient;

    for (let y = 0; y < h; y += 1) {
      const rowOffset = y * w * 3;
      for (let x = 0; x < w; x += 1) {
        const srcX = x - dx;
        if (srcX >= 0 && srcX < w) {
          const srcIdx = rowOffset + srcX * 3;
          const dstIdx = rowOffset + x * 3;
          next[dstIdx] = clampU8(ar + (this._buffer[srcIdx] - ar) * this.decay);
          next[dstIdx + 1] = clampU8(
            ag + (this._buffer[srcIdx + 1] - ag) * this.decay,
          );
          next[dstIdx + 2] = clampU8(
            ab + (this._buffer[srcIdx + 2] - ab) * this.decay,
          );
        }
      }
    }
    this._buffer = next;
  }

  _paintFovea(proximity, color, ambient, pattern) {
    const w = this.width;
    const h = this.height;
    const cx = Math.floor(w / 2);
    const cy = Math.floor(h / 2);
    const halfW = Math.max(2, Math.floor(w / 16));
    const x0 = Math.max(0, cx - halfW);
    const x1 = Math.min(w, cx + halfW);

    const minH = Math.max(4, Math.floor(h / 12));
    const maxH = Math.max(minH + 2, h - 4);
    const barH = roundEven(minH + proximity * (maxH - minH));
    const halfH = Math.max(2, Math.floor(barH / 2));
    const y0 = Math.max(0, cy - halfH);
    const y1 = Math.min(h, cy + halfH);

    const gain = 0.25 + 0.75 * proximity;
    const [ar, ag, ab] = ambient;
    const [cr, cg, cb] = color;
    const rx = Math.max(1.0, (x1 - x0) / 2.0);
    const ry = Math.max(1.0, (y1 - y0) / 2.0);
    const mx = (x0 + x1 - 1) / 2.0;
    const my = (y0 + y1 - 1) / 2.0;

    for (let y = y0; y < y1; y += 1) {
      for (let x = x0; x < x1; x += 1) {
        const nx = (x - mx) / rx;
        const ny = (y - my) / ry;
        let shade = gain;
        if (pattern === "circle") {
          const d2 = nx * nx + ny * ny;
          if (d2 > 1.05) {
            continue;
          }
          shade = gain * (0.75 + 0.25 * Math.cos(Math.sqrt(d2) * Math.PI));
        } else if (pattern === "stripes") {
          shade = gain * (Math.floor((x + y) / 2) % 2 === 0 ? 1.0 : 0.35);
        } else {
          shade =
            gain *
            Math.max(0.4, 1.0 - 0.18 * (Math.abs(nx) + 0.5 * Math.abs(ny)));
        }
        const idx = (y * w + x) * 3;
        this._buffer[idx] = clampU8(ar + (cr - ar) * shade);
        this._buffer[idx + 1] = clampU8(ag + (cg - ag) * shade);
        this._buffer[idx + 2] = clampU8(ab + (cb - ab) * shade);
      }
    }
  }

  _blankBuffer(ambient) {
    const out = new Uint8Array(this.width * this.height * 3);
    for (let i = 0; i < out.length; i += 3) {
      out[i] = ambient[0];
      out[i + 1] = ambient[1];
      out[i + 2] = ambient[2];
    }
    return out;
  }
}

export function extractPatches(percept, previous = null, options = {}) {
  const gw = integer(options.gridWidth ?? 16, "gridWidth", 1);
  const gh = integer(options.gridHeight ?? 16, "gridHeight", 1);
  const base = [];
  for (let py = 0; py < gh; py += 1) {
    const y0 = Math.floor((py * percept.height) / gh);
    const y1 = Math.max(y0, Math.floor(((py + 1) * percept.height) / gh) - 1);
    for (let px = 0; px < gw; px += 1) {
      const x0 = Math.floor((px * percept.width) / gw);
      const x1 = Math.max(x0, Math.floor(((px + 1) * percept.width) / gw) - 1);
      base.push({
        x: px,
        y: py,
        ...patchStats(percept, x0, x1, y0, y1),
        delta: 0,
        rise: 0,
        fall: 0,
        dx: 0,
        dy: 0,
        drift: 0,
      });
    }
  }
  if (!previous?.length) return base;
  const index = new Map(previous.map((p) => [`${p.x}:${p.y}`, p]));
  return base.map((patch) => {
    const prior = index.get(`${patch.x}:${patch.y}`);
    const delta = prior ? round6(patch.power - prior.power) : 0;
    const candidates = [];
    for (const dy of [-1, 0, 1]) {
      for (const dx of [-1, 0, 1]) {
        const p = index.get(`${patch.x + dx}:${patch.y + dy}`);
        if (p && p.x >= 0 && p.x < gw && p.y >= 0 && p.y < gh)
          candidates.push(p);
      }
    }
    let best = null;
    let bestDistance = Infinity;
    let bestDisplacement = Infinity;
    for (const candidate of candidates) {
      const distance = ["red", "green", "blue", "power", "contrast"].reduce(
        (sum, key) => sum + Math.abs(patch[key] - candidate[key]),
        0,
      );
      const displacement =
        Math.abs(patch.x - candidate.x) + Math.abs(patch.y - candidate.y);
      if (
        distance < bestDistance ||
        (distance === bestDistance && displacement < bestDisplacement)
      ) {
        best = candidate;
        bestDistance = distance;
        bestDisplacement = displacement;
      }
    }
    const dx = best ? patch.x - best.x : 0;
    const dy = best ? patch.y - best.y : 0;
    return {
      ...patch,
      delta,
      rise: round6(clamp(delta, 0, 1)),
      fall: round6(clamp(-delta, 0, 1)),
      dx,
      dy,
      drift: round6((Math.abs(dx) + Math.abs(dy)) / 2),
    };
  });
}

function patchStats(percept, x0, x1, y0, y1) {
  let r = 0,
    g = 0,
    b = 0;
  const lumas = [];
  for (let y = y0; y <= y1; y += 1) {
    for (let x = x0; x <= x1; x += 1) {
      const offset = (y * percept.width + x) * 3;
      const red = percept.rgb[offset],
        green = percept.rgb[offset + 1],
        blue = percept.rgb[offset + 2];
      r += red;
      g += green;
      b += blue;
      lumas.push((0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255);
    }
  }
  const count = lumas.length;
  const red = r / count / 255,
    green = g / count / 255,
    blue = b / count / 255;
  const power = Math.sqrt((red * red + green * green + blue * blue) / 3);
  const mean = lumas.reduce((sum, value) => sum + value, 0) / count;
  const contrast = Math.sqrt(
    lumas.reduce((sum, value) => sum + (value - mean) ** 2, 0) / count,
  );
  return {
    red: round6(red),
    green: round6(green),
    blue: round6(blue),
    power: round6(power),
    contrast: round6(contrast),
  };
}

export function centerOfMassX(percept, ambient = [12, 16, 24]) {
  const base =
    (0.2126 * ambient[0] + 0.7152 * ambient[1] + 0.0722 * ambient[2]) / 255;
  let weighted = 0,
    total = 0;
  for (let y = 0; y < percept.height; y += 1) {
    for (let x = 0; x < percept.width; x += 1) {
      const [r, g, b] = percept.pixel(x, y);
      const excess = Math.max(
        0,
        (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 - base,
      );
      weighted += x * excess;
      total += excess;
    }
  }
  return total <= 1e-9 ? (percept.width - 1) / 2 : weighted / total;
}
