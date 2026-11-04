# Qualia Transmission Protocol (QTP v1)

The **Qualia Transmission Protocol (`qtp/1.0`)** is a lightweight HTTP/JSON wire contract that decouples embodied sensorimotor peripherals (such as browser-hosted Web Bluetooth robots, cameras, or simulated environments) from a local decision engine.

Rather than coupling hardware drivers to a specific runtime implementation, QTP defines only the **sensorimotor membrane**:

1. **`Percept`**: A 2D RGB sensory observation arriving from the body.
2. **`Consequence`**: The physical outcome of the body's preceding action (`accepted`, `blocked`, `success`, `reward`, `progress`, `range`).
3. **`Intention`**: The discrete motor decision (`"left"`, `"right"`, `"forward"`, or `"still"`) and candidate pool readouts (`active`, `candidates`, `scores`) returned to the body.

Machine-readable wire definitions are available in [`src/qualia/qtp.v1.schema.json`](src/qualia/qtp.v1.schema.json) or at runtime via `qualia.schema()`. The HTTP contract is specified by [`src/qualia/openapi.json`](src/qualia/openapi.json). `qualia.openapi()` and JavaScript `openapi()` return the same self-contained OpenAPI 3.1 document, with the canonical wire schemas bundled.

---

## 1. Transport & Endpoints

A QTP v1 service accepts UTF-8 JSON over HTTP with `Content-Type: application/json`.
The reference server and clients default to `http://127.0.0.1:8001`; the local
JupyterLite site uses port 8000. Ports are configurable and do not determine QTP
conformance.

| Method | Path            | Purpose                                                                                  |
| :----- | :-------------- | :--------------------------------------------------------------------------------------- |
| `POST` | `/api/qtp/step` | Deliver one `Percept` (and optional preceding `Consequence`) and receive an `Intention`. |
| `GET`  | `/api/status`   | Inspect runtime readiness and aggregate step telemetry.                                  |

Browser-hosted peripherals need an explicitly allowed origin on the QTP
adapter, including its OPTIONS preflight. For example, an adapter configured to
trust `https://notebook.link` can return:

```http
Access-Control-Allow-Origin: https://notebook.link
Vary: Origin
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type, Accept
Access-Control-Allow-Private-Network: true
```

The server must validate the origin against its configuration. Scope access to
the intended QTP routes; do not relax unrelated management APIs. Browser local
network permissions may also be required; these headers alone are not a
connection guarantee.

`GET /api/status` must advertise `"protocol": "qtp/1.0"` and a boolean `"ready"`.
A generic service's readiness response does not establish QTP compatibility.

Clients default to strict remote operation. Explicit `auto` mode permits local
fallback for network failures only. HTTP errors, invalid QTP responses, and
timeouts raise errors without advancing the client's counters. Browser deadlines
cover both headers and body and abort the request. Aborting does not roll back a
server operation: after an ambiguous failure, reconcile server state before
continuing. There are no automatic step retries.

---

## 2. Core Wire Structures

### 2.1 `Percept` (Sensory Frame)

A `Percept` represents one 2D retinal observation. By default, QTP uses a compact `64×48` RGB canvas (`9,216` bytes raw; `12,288` ASCII characters when Base64-encoded).

```json
{
  "width": 64,
  "height": 48,
  "rgb": "DAwYDAwY...",
  "step": 12,
  "phase": "visible",
  "cue": null
}
```

- `width` (`integer`, default `64`): Horizontal pixel resolution.
- `height` (`integer`, default `48`): Vertical pixel resolution.
- `rgb` (`string`, Base64): Standard Base64 encoding of row-major `uint8` RGB triplets (`width * height * 3` bytes).
- `step` (`integer`, `>= 0`): Zero-based monotonic frame index within the current episode.
- `phase` (`"sample" | "neutral" | "choice" | "visible"`): Task or curriculum phase tag.
- `cue` (`string | null`): Optional external annotation. It never selects a rendered pattern or supplies a hidden sensory answer.

### 2.2 `Consequence` (Embodied Action Outcome)

A `Consequence` reports what physically happened when the peripheral executed the previous step's `Intention`. It carries embodied transition feasibility rather than internal teacher labels.

```json
{
  "accepted": true,
  "blocked": false,
  "success": false,
  "reward": 0.0,
  "progress": 0.08,
  "range": 0.42
}
```

- `accepted` (`boolean`): `true` when the commanded physical transition completed; `false` when obstructed or rejected.
- `blocked` (`boolean`): `true` when forward motion was physically obstructed. Consecutive blocked forward transitions increment a turn-recovery streak.
- `success` (`boolean`): `true` when the peripheral contacted or satisfied its target condition (exposed on the Python `Consequence` object as `.completed` and `.success`).
- `reward` (`number`): External scalar reward measurement (`0.0` when unused).
- `progress` (`number`): Signed change in target proximity over the step (positive when closing distance).
- `range` (`number`, `>= 0.0`): Current normalized or physical distance to the target.

### 2.3 `Intention` (Motor Decision & Pool Readout)

An `Intention` is returned by the QTP runtime after integrating the incoming `Percept` and `Consequence`.

```json
{
  "action": "forward",
  "step": 12,
  "active": {
    "left": 242,
    "right": 248,
    "forward": 261
  },
  "candidates": {
    "left": 366,
    "right": 366,
    "forward": 366
  },
  "scores": {
    "left": 0.661202,
    "right": 0.677596,
    "forward": 0.713115
  },
  "fallback": false
}
```

- `action` (`"left" | "right" | "forward" | "still"`): Discrete motor command for the peripheral to execute.
- `step` (`integer`, `>= 0`): Step index corresponding to the decision.
- `active` (`object` mapping action name to `integer`): Number of active motor units supporting each candidate action.
- `candidates` (`object` mapping action name to `integer`): Total motor pool capacity for each candidate action.
- `scores` (`object` mapping action name to `number`): Normalized readout score per candidate action.
- `fallback` (`boolean`): `false` when served by a remote QTP runtime; `true` when generated by the local reflex fallback driver.

---

## 3. Step Exchange (`POST /api/qtp/step`)

### Request Body (`StepRequest`)

```json
{
  "protocol": "qtp/1.0",
  "step": 12,
  "percept": {
    "width": 64,
    "height": 48,
    "rgb": "DAwYDAwY...",
    "step": 12,
    "phase": "visible",
    "cue": null
  },
  "consequence": {
    "accepted": true,
    "blocked": false,
    "success": false,
    "reward": 0.0,
    "progress": 0.08,
    "range": 0.42
  },
  "action": "forward"
}
```

On step `0`, `"consequence"` and `"action"` are null or absent. On step `t > 0`,
`"action"` must match the intention returned at step `t - 1`. `"consequence"`
reports that action's physical result, or is null or absent when unavailable.
A body that could not execute the intention reports rejection or obstruction
rather than silently substituting a different action.

Only a successful step advances the session. A stale, duplicate, or skipped step,
or a mismatched preceding action, returns HTTP 409 without changing session
state. A malformed message returns 400. A repeated step is rejected; it is not
an idempotent replay. The nested percept step is the source frame index and may
differ from the decision step.

The reference server runs one session per process. Restart it for a fresh
episode; a client reset alone cannot reset it. Session identification and reset
operations are outside QTP v1's minimum contract.

### Response Body (`StepResponse`)

The server responds with HTTP `200 OK` and either a complete top-level
`Intention` JSON object or an envelope `{"intention": { ... }}`. Every intention
field is required. The response step must equal the request step, and a remote
response must set `fallback` to `false`. A missing action is an error, not a
request to stand still.

Counts are nonnegative integers, active counts cannot exceed corresponding
candidate counts, and each readout includes `left`, `right`, and `forward`.
Numbers must be finite; integer fields stay within JavaScript's safe integer
range. Invalid types are rejected rather than coerced. The schema validates
request and response shapes; step correspondence and count relationships are
additional semantic checks.

The standalone fallback is one deterministic demonstration policy in both
languages: 16-by-16 patch features and temporal flow feed the same regional
scores. Ambiguous stationary patch matches prefer zero displacement, and seeded
recovery ties use FNV-1a over `seed:streak:step`. Decimal quantization and pixel
rounding use ties to even. Local activity counts are synthetic. While remote,
the client records the action actually returned, so later physical consequences
are attributed to that action if an explicitly allowed fallback occurs.

---

## 4. Egocentric Sensor-to-Retina Projection

Many mobile robots carry a 1D range and color sensor rather than a 2D camera. To project 1D readings and ego-motion into a QTP `Percept` with synthetic frame-to-frame motion cues:

1. **Lateral ego-turn shift (`drift`):**
   - When the body turns `"left"` (counterclockwise), previously observed columns shift **rightward** (`+x`) across the retinal sheet before the new central foveal reading is painted.
   - When the body turns `"right"` (clockwise), previously observed columns shift **leftward** (`-x`) across the retinal sheet.
2. **Forward approach looming (`rise` / `power`):**
   - The central foveal band renders a vertical object whose height and luminance scale inversely with `distance`.
   - As the body drives `"forward"` toward a surface and `distance` decreases, the central projection expands vertically and brightens, producing radial expansion and positive patch luminance rise across consecutive frames.

The projection buffer is stateful peripheral memory, not evidence of memory
acquired by a remote decision system. Declare its dimensions, distance units,
decay, and shift settings with experiment inputs. `Retina.blank()` clears that
memory and emits ambient pixels without restarting the episode; a neutral
phase tag alone does not clear it. Patterns are explicit rendering inputs;
`cue`, `phase`, world reward, and success annotations must remain separable from
sensory evidence and generic physical consequence.

## 5. Reference Service And Conformance

Run `python -m qualia.server --port 8001 --seed 17` to serve the real deterministic
reflex policy on IPv4 loopback. Its readiness identifies `policy: "reflex"` and
reports the current step and preceding intention. Pool readouts remain synthetic;
a response's `fallback: false` means it arrived from the remote HTTP service,
not that it came from a different kind of decision engine.

The reference server loads its routes and operation names from OpenAPI and uses
the shared wire validators before changing local state. It serves the bundled
contract at `/openapi.json`. Browser access requires an explicit `--origin`
allowlist, including OPTIONS preflight. Its 2 MiB body cap and five-second socket
timeout bound individual requests. It rejects unsupported media types with 415,
missing lengths with 411, oversized requests with 413, disallowed origins with
403, and unsupported resource methods with 405. Errors are JSON objects with
`error` and `detail`; sequence errors also report the expected `step`.

OpenAPI validation establishes message and HTTP shape conformance. It does not
by itself establish correct session transitions, RGB length, canonical base64,
or active-count relationships. The regression suite checks these semantic
requirements separately and runs both clients through real loopback HTTP.
Another QTP service may use any decision policy consistent with this contract;
matching the reference reflex scores or choices is not a conformance requirement.
