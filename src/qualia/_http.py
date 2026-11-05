"""Native HTTP deadlines, including slow headers and trickling bodies."""

from __future__ import annotations

import http.client
import socket
from threading import Event, Lock, Thread
from time import monotonic
import urllib.error
import urllib.request


class HTTPFailure(Exception):
    def __init__(self, message, *, status=None, timed_out=False):
        super().__init__(message)
        self.status = status
        self.timed_out = timed_out


def read_response(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    """Return one response, closing its socket when the total deadline expires."""
    exchange = _Exchange(request, timeout)
    started = monotonic()
    Thread(target=exchange.run, daemon=True).start()
    if not exchange.done.wait(max(0, timeout - (monotonic() - started))):
        exchange.abort()
        raise HTTPFailure(
            f"Request timed out after {timeout}s",
            status=exchange.status,
            timed_out=True,
        )
    if exchange.error is not None:
        error = exchange.error
        if not isinstance(
            error, (urllib.error.URLError, http.client.HTTPException, OSError)
        ):
            raise error
        raise HTTPFailure(
            str(error),
            status=exchange.status,
            timed_out=isinstance(error, TimeoutError)
            or isinstance(getattr(error, "reason", None), TimeoutError),
        ) from error
    return exchange.status, exchange.body


class _Exchange:
    def __init__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        self.done = Event()
        self.lock = Lock()
        self.aborted = False
        self.connection = None
        self.socket = None
        self.status = None
        self.body = b""
        self.error = None

    def track(self, connection):
        with self.lock:
            if self.aborted:
                raise TimeoutError("Request deadline expired")
            self.connection = connection

    def connected(self, connection):
        with self.lock:
            self.socket = connection.sock
            aborted = self.aborted
        if aborted:
            self.abort()
            raise TimeoutError("Request deadline expired")

    def abort(self):
        with self.lock:
            self.aborted = True
            sock = self.socket or getattr(self.connection, "sock", None)
        if sock is not None:
            # shutdown interrupts a reader in another thread; close alone may
            # leave the socket alive through HTTPResponse's buffered file.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def run(self):
        try:
            opener = urllib.request.build_opener(
                _HTTPHandler(self), _HTTPSHandler(self)
            )
            with opener.open(self.request, timeout=self.timeout) as response:
                self.status = response.status
                self.body = response.read()
        except urllib.error.HTTPError as exc:
            self.status = exc.code
            self.error = exc
            exc.close()
        except Exception as exc:
            self.error = exc
        finally:
            self.done.set()


def _connection(kind, exchange):
    class Connection(kind):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            exchange.track(self)

        def connect(self):
            super().connect()
            # DNS resolution cannot be interrupted portably. If it finishes
            # after expiry, close the connection before sending HTTP bytes.
            exchange.connected(self)

    return Connection


class _HTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, exchange):
        super().__init__()
        self.connection = _connection(http.client.HTTPConnection, exchange)

    def http_open(self, request):
        return self.do_open(self.connection, request)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, exchange):
        super().__init__()
        self.connection = _connection(http.client.HTTPSConnection, exchange)

    def https_open(self, request):
        return self.do_open(self.connection, request, context=self._context)
