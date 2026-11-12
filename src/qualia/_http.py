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


class _Exchange:
    def __init__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        self.wake = Event()
        self.lock = Lock()
        self.aborted = False
        self.connection = None
        self.socket = None
        self.status = None
        self.body = b""
        self.error = None

    def read(self) -> tuple[int, bytes]:
        """Wait for one response, interruption, or total request deadline."""
        with self.lock:
            if self.aborted:
                raise HTTPFailure("Request cancelled", status=self.status)
        started = monotonic()
        Thread(target=self.run, daemon=True).start()
        if not self.wake.wait(max(0, self.timeout - (monotonic() - started))):
            status = self.abort()
            raise HTTPFailure(
                f"Request timed out after {self.timeout}s",
                status=status,
                timed_out=True,
            )
        with self.lock:
            if self.aborted:
                raise HTTPFailure("Request cancelled", status=self.status)
            error, status, body = self.error, self.status, self.body
        if error is not None:
            if not isinstance(
                error, (urllib.error.URLError, http.client.HTTPException, OSError)
            ):
                raise error
            raise HTTPFailure(
                str(error),
                status=status,
                timed_out=isinstance(error, TimeoutError)
                or isinstance(getattr(error, "reason", None), TimeoutError),
            ) from error
        return status, body

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
            status = self.status
        if sock is not None:
            # shutdown interrupts a reader in another thread; close alone may
            # leave the socket alive through HTTPResponse's buffered file.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self.wake.set()
        return status

    def run(self):
        try:
            opener = urllib.request.build_opener(
                _HTTPHandler(self), _HTTPSHandler(self)
            )
            with opener.open(self.request, timeout=self.timeout) as response:
                with self.lock:
                    if self.aborted:
                        return
                    self.status = response.status
                body = response.read()
                with self.lock:
                    if self.aborted:
                        return
                    self.body = body
        except urllib.error.HTTPError as exc:
            with self.lock:
                if not self.aborted:
                    self.status = exc.code
                    self.error = exc
            exc.close()
        except Exception as exc:
            with self.lock:
                if not self.aborted:
                    self.error = exc
        finally:
            self.wake.set()


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
