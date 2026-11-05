# qualia

**`qualia`** is the reference specification and client library (for **Python / Pyodide** and **TypeScript / JavaScript**) for the **Qualia Transmission Protocol (QTP v1)**—a lightweight HTTP/JSON wire protocol that connects embodied sensorimotor peripherals (such as Web Bluetooth robots in JupyterLite, cameras, or interactive widgets) to a local decision runtime.

## Why `qualia` Exists

Embodied peripherals often live where hardware access is easiest—for example, inside a browser notebook (`https://notebook.link` / JupyterLite) talking to a physical robot over Web Bluetooth—while the decision runtime lives in a local process on `http://127.0.0.1:8001`.

`qualia` defines the clean, dependency-free sensorimotor membrane between them:

- **`Percept`**: A `64×48` 2D RGB retinal frame (with built-in stdlib PNG rendering so frames display inline in Jupyter without `matplotlib` or `Pillow`).
- **`Retina`**: An egocentric projector that turns 1D range/color sensor readings and left/right/forward ego-motion into 2D `Percept` frames with synthetic lateral (`drift`) and looming (`rise`) cues.
- **`Consequence`**: The physical result of the preceding action (`accepted`, `blocked`, `completed`, `progress`, `range`).
- **`Intention`**: The discrete action decision (`"left"`, `"right"`, `"forward"`, or `"still"`), pool readouts (`active`, `candidates`, `scores`), and lateral `.bias` in `[-1.0, +1.0]`.
- **`Client` & `LocalEngine`**: Dual Pyodide (`pyfetch`) / CPython (`urllib`) client that talks to a live QTP server on `127.0.0.1:8001` and requires a remote service by default. Local demonstration and network fallback are explicit options.

The package includes a loopback reference server running the deterministic
`LocalEngine` demonstration policy. A separate adapter can connect the same
clients to another decision runtime. QTP readiness advertises
`protocol: "qtp/1.0"` and a boolean `ready` value.

`mode="auto"` checks `GET /api/status` before each step and permits local
fallback only if that check cannot reach the service. Once a step is sent,
every failure raises: even a connection loss before response headers can leave
the remote decision committed. HTTP errors (including 403 and 404), malformed
responses, and timeouts always raise.
Use `remote` for research sessions so a service failure cannot replace the
decision policy. Local pool counts and scores are synthetic demonstration
readouts, not measurements of a remote system. Neither client retries a failed
step automatically. Reconcile server state after an ambiguous failure before
continuing; a client reset does not undo a remote step.

Each client processes one step at a time. Await its result before starting the
next step. Overlapping steps and resets during a step raise `ProtocolError`;
Python uses the same guard for synchronous and asynchronous calls.

---

## Installation

`qualia` is a pure-Python universal wheel (`py3-none-any.whl`) with **zero runtime dependencies**.

In standard Python:

```sh
pip install qualia
```

In JupyterLite / Pyodide (`https://notebook.link`):

```python
%pip install qualia
```

In TypeScript / JavaScript (Node.js or browser bundlers):

```sh
npm install qualia
```

---

## Run The Reference Server

After installing the Python package, start a fresh demonstration session:

```sh
python -m qualia.server --port 8001 --seed 17
```

From a source checkout, `pixi run reference` starts the same service with its
default seed and allows the local JupyterLite origins `http://127.0.0.1:8000`
and `http://localhost:8000`. The server binds `127.0.0.1`, identifies its policy as `reflex`,
and serves:

- `GET /api/status`: readiness, policy identity, and session position.
- `POST /api/qtp/step`: a real decision from `LocalEngine`.
- `GET /openapi.json`: the self-contained OpenAPI 3.1 contract.

The client defaults to port 8001, matching the reference server. Lite uses port 8000. These are configurable defaults, not protocol requirements. This is one client session per
process; restart the server to begin a new episode. Resetting a client does not
reset the server. Invalid messages return 400, sequence conflicts return 409,
and neither advances the session. Requests are limited to 2 MiB.

For a browser notebook, explicitly allow its exact origin:

```sh
python -m qualia.server --port 8001 --seed 17 --origin https://notebook.link
```

Repeat `--origin` for another trusted notebook origin, such as
`http://127.0.0.1:8000`. Browser local-network permissions may also be required.
The reference server runs in desktop Python; the Python and JavaScript clients
can run in the notebook.

## Quickstart

```python
import qualia

# Require a QTP service; failures raise errors instead of changing the policy.
# For an offline demonstration, explicitly choose mode="local".
client = qualia.connect()
retina = qualia.Retina()

# 1. Synthesize a 64x48 2D retinal Percept from a 1D range/color sensor
frame = retina.observe(distance=0.45, color=(240, 180, 60), turn="still")

# In a Jupyter notebook cell, evaluating `frame` renders an upscaled
# 256x192 pixel-art PNG inline with zero external dependencies!
frame

# 2. Step the sensorimotor loop (use `await client.step(...)` in notebooks)
intent = client.step_sync(frame)
print(intent.action, intent.bias, intent.active)

# 3. Report the physical Consequence on the next step
next_frame = retina.observe(distance=0.30, color=(240, 180, 60), turn=intent.action)
outcome = qualia.Consequence(
    accepted=True,
    blocked=False,
    completed=False,
    progress=0.15,
    range=0.30,
)
next_intent = client.step_sync(next_frame, outcome)
```

## Sensory Encoding And Memory

`Retina` draws an engineering representation of range and color; it does not
reconstruct a camera image. Its shifted, decaying buffer retains earlier
observations, so that peripheral memory must be included in an experiment's
interpretation. `phase="neutral"` is only an annotation and does not erase it.
Use `retina.blank()` to clear the buffer and emit an ambient-only frame while
continuing the frame counter. `retina.reset()` starts a new episode.

Distance units are explicit: the default is normalized `[0, 1]`; physical
readings require `Retina(units="physical", max_distance=100.0)` (JavaScript:
`new Retina({units: "physical", maxDistance: 100})`). A `cue` is annotation only;
use `pattern="circle"` or `pattern="stripes"` to draw a synthetic pattern.
Annotations and external reward remain outside a decision runtime's sensory
and learning content unless an experiment explicitly declares otherwise.

---

## Web Bluetooth Robot Loop (`ipymovehub` / JupyterLite)

When driving a differential-drive robot such as a LEGO Boost Move Hub R2-D2 over Web Bluetooth in JupyterLite, `Retina` converts the chest-mounted distance/color sensor into 2D retinal frames, while `Intention.bias` (`[-1.0, +1.0]`) lets the dome head express the balance between competing left and right motor pools before the treads move:

```python
import asyncio
import qualia

client = qualia.connect()
retina = qualia.Retina(units="physical", max_distance=100.0)

last_action = "still"
consequence = None

for _ in range(30):
    dist_cm = hub.distance          # e.g. 0..100 cm from chest sensor
    rgb_color = hub.color_rgb       # e.g. (220, 220, 255)

    percept = retina.observe(
        distance=dist_cm,
        color=rgb_color,
        turn=last_action,
    )
    intent = await client.step(percept, consequence)

    # Orient the communicative dome head proportionally to lateral pool bias
    await hub.turn_head(int(intent.bias * 45))

    # Execute the chosen discrete tread action
    blocked = dist_cm < 12.0 and intent.action == "forward"
    if not blocked:
        await hub.move(intent.action)

    # Resample after execution: this outcome belongs to the action just issued.
    after_cm = hub.distance
    consequence = qualia.Consequence(
        accepted=not blocked,
        blocked=blocked,
        completed=after_cm <= 8.0,
        progress=(dist_cm - after_cm) / 100.0,
        range=after_cm / 100.0,
    )
    last_action = intent.action if not blocked else "still"
```

---

## Interactive JupyterLite Demo (In-Browser)

You can explore `qualia` directly in your browser without installing anything locally:

- **Interactive Walkthrough**: [Open Qualia in JupyterLite](https://ursiform.github.io/qualia/lab/index.html?path=qualia_walkthrough.ipynb)

### Building or Running JupyterLite Locally

Using **Pixi** (recommended), run these in separate terminals:

```sh
pixi run reference
```

```sh
pixi run lite
```

Open [the local walkthrough](http://127.0.0.1:8000/lab/index.html?path=qualia_walkthrough.ipynb)
and run it from the top. Lite serves the freshly built wheel on port 8000;
the notebook connects to the reference service on port 8001 in `remote` mode.
The reference task explicitly allows both `http://127.0.0.1:8000` and
`http://localhost:8000`; hostnames and ports are part of the browser origin.
A different Lite port or a hosted notebook needs its own `--origin` value.

The notebook continues one server session throughout. Restart `pixi run reference`
before running it again from the top. To run without a reference server, change
the notebook's explicit `MODE` setting to `"local"`. After rebuilding Lite,
reload the notebook and restart its kernel to load the rebuilt package.
An edited notebook saved in Lite's browser storage takes precedence over the
shipped file. If old cells remain, back up your edits and remove that browser
copy to restore the updated example, following
[JupyterLite's file instructions](https://jupyterlite.readthedocs.io/en/stable/quickstart/using.html#accessing-existing-files).

Or using standard tools:

```sh
# Install optional lite build dependencies:
pip install "qualia[lite]"

# Build the static JupyterLite distribution (with local qualia wheel indexed):
npm run build:lite
# or via the Python CLI:
jupyter lite build --config lite/jupyter_lite_config.json

# Serve the local distribution:
npm run serve:lite
# or via the Python CLI:
jupyter lite serve --config lite/jupyter_lite_config.json
```

---

## Protocol & Schema

- Full wire specification: [`PROTOCOL.md`](PROTOCOL.md)
- JSON Schema (`qtp/1.0`): [`src/qualia/qtp.v1.schema.json`](src/qualia/qtp.v1.schema.json), available through `qualia.schema()` or JavaScript `schema()`.
- OpenAPI 3.1: [`src/qualia/openapi.json`](src/qualia/openapi.json), available as a self-contained document through `qualia.openapi()`, JavaScript `openapi()`, or the running server's `/openapi.json`.

The authored OpenAPI file references the neighboring JSON Schema; retain both
files when using it directly. The bundled document requires no external schema
fetches. It describes routes, messages, and HTTP errors. Session ordering and
preceding-action checks also form part of QTP's behavioral contract. A different
service can implement QTP with its own decision policy; it need not reproduce
the demonstration's reflex choices.

## Development & Tests

```sh
pip install ".[test]"
pytest
# or with standard library unittest (optional schema validators are reported as skips):
PYTHONPATH=src python3 -m unittest discover -s tests -v
npm test
```

With Node available, the Python suite also compares both implementations over
identical trajectories: exact RGB bytes, patch flow, seeded decisions, remote
history, synthetic pool readouts, and the full JSON schema. `QUALIA_NODE` may
name a Node executable. CI requires this parity check. After editing the canonical
message schema or OpenAPI document, run `python3 tools/schema.py` to regenerate
the browser contracts. CI validates OpenAPI, checks real HTTP responses against
it, and compares both clients against fresh reference servers on temporary
loopback ports. These tests never connect to an existing decision service.

## License

BSD-3-Clause. Copyright (c) 2019-2026 Afshin T. Darian.
