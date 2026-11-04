/**
 * TypeScript definitions for the Qualia Transmission Protocol (QTP v1).
 */

export const VERSION = "0.3.0";
export const QTP_VERSION = "qtp/1.0";
export const DEFAULT_WIDTH = 64;
export const DEFAULT_HEIGHT = 48;
export const DEFAULT_URL = "http://127.0.0.1:8001";
export const MOTOR_ACTIONS: readonly ["left", "right", "forward"];

export type Action = "left" | "right" | "forward" | "still";
export type Phase = "sample" | "neutral" | "choice" | "visible";
export type Pattern = "solid" | "circle" | "stripes";
export type Mode = "auto" | "remote" | "local";
export type RGBTuple = readonly [number, number, number];

export interface PerceptWire {
  width: number;
  height: number;
  rgb: string;
  step: number;
  phase: Phase;
  cue: string | null;
}

export interface ConsequenceWire {
  accepted: boolean;
  blocked: boolean;
  success: boolean;
  reward: number;
  progress: number;
  range: number;
}

export interface IntentionWire {
  action: Action;
  step: number;
  active: Record<string, number>;
  candidates: Record<string, number>;
  scores: Record<string, number>;
  fallback: boolean;
}

export interface StepRequest {
  protocol: "qtp/1.0";
  step: number;
  percept: PerceptWire;
  consequence: ConsequenceWire | null;
  action: Action | null;
}

export type StepResponse = IntentionWire | { intention: IntentionWire };

export interface PerceptInit {
  width?: number;
  height?: number;
  rgb?: Uint8Array;
  step?: number;
  phase?: Phase;
  cue?: string | null;
}

export declare class Percept {
  readonly width: number;
  readonly height: number;
  readonly rgb: Uint8Array;
  readonly step: number;
  readonly phase: Phase;
  readonly cue: string | null;

  constructor(init?: PerceptInit);
  static fromDict(payload: PerceptWire | Record<string, unknown>): Percept;
  toDict(): PerceptWire;
  pixel(x: number, y: number): RGBTuple;
}

export interface ConsequenceInit {
  accepted?: boolean;
  blocked?: boolean;
  completed?: boolean;
  success?: boolean;
  reward?: number;
  progress?: number;
  range?: number;
}

export declare class Consequence {
  readonly accepted: boolean;
  readonly blocked: boolean;
  readonly completed: boolean;
  readonly reward: number;
  readonly progress: number;
  readonly range: number;

  constructor(init?: ConsequenceInit);
  get success(): boolean;
  static fromDict(
    payload: Partial<ConsequenceWire> | Record<string, unknown>,
  ): Consequence;
  toDict(): ConsequenceWire;
}

export interface IntentionInit {
  action?: Action;
  step?: number;
  active?: Record<string, number>;
  candidates?: Record<string, number>;
  scores?: Record<string, number>;
  fallback?: boolean;
}

export declare class Intention {
  readonly action: Action;
  readonly step: number;
  readonly active: Record<string, number>;
  readonly candidates: Record<string, number>;
  readonly scores: Record<string, number>;
  readonly fallback: boolean;

  constructor(init?: IntentionInit);
  /** Normalized lateral balance in [-1.0, +1.0] between "left" and "right". */
  get bias(): number;
  static fromDict(
    payload: Partial<IntentionWire> | Record<string, unknown>,
  ): Intention;
  toDict(): IntentionWire;
}

export declare class ProtocolError extends Error {}

export declare class TransportError extends Error {
  readonly status: number | null;
  readonly timedOut: boolean;
  constructor(
    message: string,
    options?: { status?: number; timedOut?: boolean },
  );
}

export interface PatchFlow {
  x: number;
  y: number;
  red: number;
  green: number;
  blue: number;
  power: number;
  contrast: number;
  delta: number;
  rise: number;
  fall: number;
  dx: number;
  dy: number;
  drift: number;
}

export declare function extractPatches(
  percept: Percept,
  previous?: readonly PatchFlow[] | null,
  options?: { gridWidth?: number; gridHeight?: number },
): PatchFlow[];
export declare function centerOfMassX(
  percept: Percept,
  ambient?: RGBTuple,
): number;

export interface RetinaOptions {
  width?: number;
  height?: number;
  ambient?: RGBTuple;
  shiftColumns?: number;
  decay?: number;
  maxDistance?: number;
  units?: "normalized" | "physical";
}

export interface ObserveOptions {
  distance: number;
  color?: RGBTuple;
  turn?: Action | number;
  ambient?: RGBTuple;
  pattern?: Pattern;
  phase?: Phase;
  cue?: string | null;
  step?: number;
}

export declare class Retina {
  readonly width: number;
  readonly height: number;
  readonly ambient: RGBTuple;
  readonly shiftColumns: number;
  readonly decay: number;
  readonly maxDistance: number;
  readonly units: "normalized" | "physical";

  constructor(options?: RetinaOptions);
  get step(): number;
  reset(ambient?: RGBTuple): void;
  blank(options?: { phase?: Phase; step?: number }): Percept;
  observe(
    options: ObserveOptions | number,
    color?: RGBTuple,
    turn?: Action | number,
  ): Percept;
}

export declare class LocalEngine {
  readonly candidatesPerPool: number;
  readonly seed: number;
  constructor(options?: { candidatesPerPool?: number; seed?: number });
  get stepCount(): number;
  get streak(): number;
  reset(): void;
  status(): Record<string, unknown>;
  observe(
    percept: Percept,
    consequence: Consequence | null,
    options: { action: Action; step?: number },
  ): void;
  step(
    percept: Percept,
    consequence?: Consequence | null,
    options?: { step?: number; fallback?: boolean },
  ): Intention;
}

export interface ClientOptions {
  url?: string;
  mode?: Mode;
  stepPath?: string;
  statusPath?: string;
  timeout?: number;
  seed?: number;
}

export declare class Client {
  readonly url: string;
  readonly mode: Mode;
  readonly stepPath: string;
  readonly statusPath: string;
  readonly timeout: number;
  readonly retina: Retina;
  readonly local: LocalEngine;

  constructor(url?: string, mode?: Mode, options?: ClientOptions);
  get stepCount(): number;
  get lastAction(): Action | null;
  reset(): void;
  step(
    percept: Percept | PerceptWire,
    consequence?: Consequence | ConsequenceWire | null,
  ): Promise<Intention>;
  status(): Promise<Record<string, unknown>>;
}

export declare function connect(
  url?: string,
  mode?: Mode,
  options?: ClientOptions,
): Client;

export declare function schema(): Record<string, unknown>;

/** The portable HTTP contract, with canonical message schemas bundled. */
export declare function openapi(): Record<string, unknown>;
