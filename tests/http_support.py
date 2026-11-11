"""Local-only HTTP fixtures shared by reference and contract tests."""

from contextlib import contextmanager
import http.client
import json
from threading import Thread

from qualia import Percept
from qualia.server import Server


@contextmanager
def running_server(**options):
    with Server(0, **options) as server:
        thread = Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("Reference server did not stop")


def url(server):
    return f"http://127.0.0.1:{server.server_port}"


def request(server, method, path, payload=None, *, headers=None):
    body = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload).encode()
        if payload is not None
        else None
    )
    headers = dict(headers or {})
    if body is not None:
        headers.setdefault("Content-Type", "application/json")
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        return (
            response.status,
            dict(response.getheaders()),
            json.loads(raw) if raw else None,
        )
    finally:
        connection.close()


def initial():
    return {
        "protocol": "qtp/1.0",
        "step": 0,
        "percept": Percept(width=1, height=1, rgb=b"\x0c\x10\x18").to_dict(),
        "action": None,
        "consequence": None,
    }
