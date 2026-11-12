# qualia

**`qualia`** is the reference specification and client library (for **Python / Pyodide** and **TypeScript / JavaScript**) for the **Qualia Transmission Protocol (QTP v1)**—a lightweight HTTP/JSON wire protocol that connects embodied sensorimotor peripherals (such as Web Bluetooth robots in JupyterLite, cameras, or interactive widgets) to a local decision runtime.

## Why `qualia` Exists

Embodied peripherals often live where hardware access is easiest—for example, inside a browser notebook (such as JupyterLite) talking to a physical robot over Web Bluetooth—while the decision runtime lives in a local process on `http://127.0.0.1:8001`.

`qualia` defines the clean, dependency-free sensorimotor membrane between them:

- **`Percept`**: A `64×48` 2D RGB retinal frame (with built-in stdlib PNG rendering in Python so frames display inline in Jupyter without `matplotlib` or `Pillow`).
- **`Retina`**: An egocentric projector that turns 1D range/color sensor readings and left/right/forward ego-motion into 2D `Percept` frames with synthetic lateral (`drift`) and looming (`rise`) cues.
- **`Consequence`**: The physical result of the preceding action (`accepted`, `blocked`, `completed`, `progress`, `range`).
- **`Intention`**: The discrete action decision (`"left"`, `"right"`, `"forward"`, or `"still"`), pool readouts (`active`, `candidates`, `scores`), and lateral `.bias` in `[-1.0, +1.0]`.
- **`Client` & `LocalEngine`**: Clients for Python (CPython `urllib` and Pyodide `pyfetch`) and TypeScript/JavaScript (`fetch`) that connect to a live QTP service on `http://127.0.0.1:8001` in strict `remote` mode by default, paired with a deterministic `LocalEngine` reflex policy when local execution or `auto` fallback is explicitly requested.

### Session & Transport Guarantees

The package includes a loopback reference server running the deterministic `LocalEngine` demonstration policy, while an external adapter can connect the same clients to another decision runtime (`GET /api/status` advertises `"protocol": "qtp/1.0"` and a boolean `"ready"` value).

- **Use `mode="remote"` (the default) for research sessions** so a service failure cannot silently replace the active decision policy.
- **Explicit fallback (`mode="auto"`)** checks `GET /api/status` before each step and falls back locally only if that check cannot reach the service. Once a step request is sent, every failure raises—connection losses (even before response headers), HTTP errors (including `403` and `404`), malformed responses, and timeouts—because the remote decision may already have committed.
- **No automatic step retries:** After an ambiguous failure, reconcile server state before continuing; resetting a client does not undo a remote step.
- **Synthetic local readouts:** Local `active`, `candidates`, and `scores` values are demonstration readouts produced by `LocalEngine`, not measurements of a remote decision system.
- **One step at a time:** Await each step before starting the next. Overlapping steps or calling `reset()` during an active step raise `ProtocolError` (Python shares this guard across synchronous and asynchronous calls).

---

## Installation

Both the pure-Python wheel (`py3-none-any.whl`) and the npm package have **zero runtime dependencies**.

In standard Python:

```sh
pip install qualia
```

In JupyterLite / Pyodide:

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

From a source checkout, `pixi run reference` starts the same service with its default seed and allows the local JupyterLite origins `http://127.0.0.1:8000` and `http://localhost:8000`. The server binds IPv4 loopback (`127.0.0.1`), identifies its policy as `reflex`, and exposes:

- `GET /api/status`: readiness, policy identity, and session position.
- `POST /api/qtp/step`: a decision from `LocalEngine`.
- `GET /openapi.json`: the self-contained OpenAPI 3.1 contract.

Clients default to port `8001` and local JupyterLite serves on port `8000`; both are configurable defaults rather than protocol requirements. The reference server holds one client session per process—restart the server process to begin a new episode, since resetting a client does not reset the server. Invalid messages return HTTP `400`, sequence conflicts return HTTP `409` (neither advances the session), and request bodies are limited to 2 MiB.

To connect from a browser notebook hosted on another origin, allow its exact origin explicitly (for example, the hosted JupyterLite demo):

```sh
python -m qualia.server --port 8001 --seed 17 --origin https://ursiform.github.io
```

Repeat `--origin` for each additional trusted origin, such as `http://127.0.0.1:8000`. Browser local-network access permissions may also be required. While the reference server runs in desktop Python, both the Python (Pyodide) and JavaScript clients can run inside the browser notebook.

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

`Retina` draws a synthetic representation of range and color; it does not reconstruct a camera image. Its shifted, decaying buffer retains earlier observations, so experiments must account for that peripheral memory. Passing `phase="neutral"` is an annotation only and does not erase the buffer; call `retina.blank()` to clear retained sensory traces and emit an ambient-only frame while continuing the frame counter, or `retina.reset()` to start a new episode.

Distance units are explicit: normalized `[0, 1]` is the default, while physical readings require `Retina(units="physical", max_distance=100.0)` (JavaScript: `new Retina({ units: "physical", maxDistance: 100 })`). A `cue` is annotation only; pass `pattern="circle"` or `pattern="stripes"` to render a synthetic pattern. Annotations and external reward remain separate from a decision runtime's sensory and learning content unless an experiment explicitly declares otherwise.

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

Using **Pixi** (recommended), run the reference service and JupyterLite server in separate terminals:

```sh
pixi run reference
```

```sh
pixi run lite
```

Open [the local walkthrough](http://127.0.0.1:8000/lab/index.html?path=qualia_walkthrough.ipynb) and run all cells from the top. JupyterLite serves the freshly built local wheel on port `8000`, and the notebook connects to the reference service on port `8001` in `remote` mode. The `pixi run reference` task explicitly allows `http://127.0.0.1:8000` and `http://localhost:8000` (both scheme, host, and port matter for browser origin checks); a different Lite port or hosted notebook needs its own `--origin` value.

The notebook runs one continuous server session from top to bottom, so restart `pixi run reference` before running it again from the top. To try the walkthrough without a reference server, set `MODE = "local"` in the first code cell. After rebuilding JupyterLite, reload the notebook and restart its kernel to pick up the rebuilt package. Note that a modified notebook stored in browser storage takes precedence over the shipped file—follow [JupyterLite's file instructions](https://jupyterlite.readthedocs.io/en/stable/quickstart/using.html#accessing-existing-files) (back up your edits and delete the browser copy) to restore an updated walkthrough.

Or using standard tools:

```sh
# Install build dependencies and optional Lite extras:
pip install build "qualia[lite]"

# Build the Qualia wheel into dist/ and assemble the static JupyterLite site:
python -m build --wheel
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
- JSON Schema (`qtp/1.0`): [`src/qualia/qtp.v1.schema.json`](src/qualia/qtp.v1.schema.json), available via `qualia.schema()` or JavaScript `schema()`.
- OpenAPI 3.1: [`src/qualia/openapi.json`](src/qualia/openapi.json), available as a self-contained document via `qualia.openapi()`, JavaScript `openapi()`, or the running server's `/openapi.json`.

The authored OpenAPI file references the neighboring JSON Schema, so keep both files together when reading it directly from disk. The bundled runtime documents inline all schema definitions and require no external fetches. OpenAPI covers routes, message shapes, and HTTP errors, while sequential ordering and preceding-action checks form part of QTP's behavioral contract. Other QTP services can implement any decision policy and need not reproduce the demonstration's reflex choices.

## Development & Tests

```sh
pip install ".[test]"
pytest
# or with standard library unittest (optional schema validators are reported as skips):
PYTHONPATH=src python3 -m unittest discover -s tests -v
npm test
npm run typecheck
```

When Node.js is available (via `QUALIA_NODE`, `PATH`, or `.pixi`), the Python suite runs cross-language parity checks across identical trajectories: exact RGB bytes, patch flow, seeded decisions, remote history, synthetic pool readouts, HTTP failure classification, and the full JSON Schema/OpenAPI contract. CI requires these parity checks, validates the OpenAPI specification, checks live HTTP responses against it, and runs both clients against ephemeral loopback reference servers without touching any existing service.

After editing [`src/qualia/qtp.v1.schema.json`](src/qualia/qtp.v1.schema.json) or [`src/qualia/openapi.json`](src/qualia/openapi.json), regenerate [`lib/schema.js`](lib/schema.js):

```sh
python3 tools/schema.py
# or: npm run generate:schema
```

## License

BSD-3-Clause. Copyright (c) 2019-2026 Afshin T. Darian.
