/** One bounded HTTP exchange, with no automatic mutation retries. */
import { ProtocolError, number } from "./numbers.js";

export class TransportError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.status = options.status ?? null;
    this.timedOut = options.timedOut ?? false;
  }
}

export function timeoutValue(timeout) {
  number(timeout, "timeout", 0);
  if (timeout === 0) throw new RangeError("timeout must be positive");
  return timeout;
}

export async function requestJSON(
  url,
  { method = "GET", payload, timeout = 2 } = {},
) {
  timeoutValue(timeout);
  const controller = new AbortController();
  let status = null;
  let timer;
  const deadline = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      reject(
        new TransportError(`QTP request timed out after ${timeout}s`, {
          status,
          timedOut: true,
        }),
      );
      controller.abort();
    }, timeout * 1000);
  });
  async function exchange() {
    const headers = { Accept: "application/json" };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (error) {
      throw new TransportError(`QTP transport error: ${error}`);
    }
    status = response.status;
    if (!response.ok)
      throw new TransportError(`HTTP ${response.status} from ${url}`, {
        status: response.status,
      });
    let data;
    try {
      data = JSON.parse(await response.text());
    } catch (error) {
      if (error instanceof SyntaxError)
        throw new ProtocolError("Expected a JSON object response");
      throw new TransportError(`QTP response read failed: ${error}`, {
        status,
      });
    }
    if (!data || typeof data !== "object" || Array.isArray(data))
      throw new ProtocolError("Expected a JSON object response");
    return data;
  }
  try {
    return await Promise.race([exchange(), deadline]);
  } finally {
    clearTimeout(timer);
  }
}
