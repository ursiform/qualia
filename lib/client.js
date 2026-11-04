/** An explicit remote session, with opt-in local demonstration modes. */
import {
  Consequence,
  DEFAULT_URL,
  Intention,
  Percept,
  QTP_VERSION,
} from "./protocol.js";
import { Retina } from "./retina.js";
import { LocalEngine } from "./local.js";
import { ProtocolError, boolean } from "./numbers.js";
import { TransportError, requestJSON, timeoutValue } from "./transport.js";

export class Client {
  constructor(url = DEFAULT_URL, mode = "remote", options = {}) {
    this.url = String(options.url ?? url).replace(/\/+$/, "");
    this.mode = options.mode ?? mode;
    if (!["remote", "local", "auto"].includes(this.mode))
      throw new ProtocolError("Invalid mode");
    this.timeout = timeoutValue(options.timeout ?? 2);
    this.stepPath =
      "/" + String(options.stepPath ?? "/api/qtp/step").replace(/^\/+/, "");
    this.statusPath =
      "/" + String(options.statusPath ?? "/api/status").replace(/^\/+/, "");
    this.retina = new Retina();
    this.local = new LocalEngine({ seed: options.seed ?? 20261104 });
    this._step = 0;
    this._lastAction = null;
  }
  get stepCount() {
    return this._step;
  }
  get lastAction() {
    return this._lastAction;
  }
  reset() {
    this._step = 0;
    this._lastAction = null;
    this.retina.reset();
    this.local.reset();
  }
  async step(perceptInput, consequenceInput = null) {
    const percept =
      perceptInput instanceof Percept
        ? perceptInput
        : Percept.fromDict(perceptInput);
    const consequence =
      consequenceInput == null
        ? null
        : consequenceInput instanceof Consequence
          ? consequenceInput
          : Consequence.fromDict(consequenceInput);
    const step = this._step;
    let intention;
    if (this.mode === "local")
      intention = this.local.step(percept, consequence, {
        step,
        fallback: true,
      });
    else {
      try {
        const response = await requestJSON(`${this.url}${this.stepPath}`, {
          method: "POST",
          timeout: this.timeout,
          payload: {
            protocol: QTP_VERSION,
            step,
            percept: percept.toDict(),
            consequence: consequence?.toDict() ?? null,
            action: this._lastAction,
          },
        });
        let inner = response;
        if (Object.hasOwn(response, "intention")) {
          if (Object.keys(response).length !== 1)
            throw new ProtocolError("Invalid intention envelope");
          inner = response.intention;
        }
        intention = Intention.fromDict(inner);
        if (intention.step !== step)
          throw new ProtocolError(`Expected response step ${step}`);
        if (intention.fallback)
          throw new ProtocolError(
            "A remote response cannot claim local fallback",
          );
        this.local.observe(percept, consequence, {
          action: intention.action,
          step,
        });
      } catch (error) {
        if (!this._canFallback(error)) throw error;
        intention = this.local.step(percept, consequence, {
          step,
          fallback: true,
        });
      }
    }
    this._lastAction = intention.action;
    this._step = step + 1;
    return intention;
  }
  async status() {
    if (this.mode === "local") return this.local.status();
    try {
      const status = await requestJSON(`${this.url}${this.statusPath}`, {
        timeout: this.timeout,
      });
      if (status.protocol !== QTP_VERSION)
        throw new ProtocolError("Status does not advertise qtp/1.0");
      boolean(status.ready, "ready");
      return {
        ...status,
        protocol: QTP_VERSION,
        engine: "remote",
        url: this.url,
      };
    } catch (error) {
      if (!this._canFallback(error)) throw error;
      return { ...this.local.status(), fallback: true };
    }
  }
  _canFallback(error) {
    return (
      this.mode === "auto" &&
      error instanceof TransportError &&
      error.status === null &&
      !error.timedOut
    );
  }
}

export function connect(url = DEFAULT_URL, mode = "remote", options = {}) {
  return new Client(url, mode, options);
}
