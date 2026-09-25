"""Request-local urllib abort for complete-WAV TTS (including header wait).

No global connection, provider state or streaming protocol changes. The owner
keeps the socket valid when http.client releases it for Connection: close.
Before a socket exists, connect uses a five-second timeout; DNS resolution is
subject to the OS resolver. Once connected, header/body waits are cancellable.
"""
from contextlib import contextmanager
import http.client
import io
import select
import socket
import threading
import urllib.request
import urllib.error
from time import monotonic


class _ReadSocket:
    def __init__(self, sock, cancel_event, timeout):
        self.sock, self.cancel_event, self.timeout = sock, cancel_event, timeout

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def close(self):
        pass  # closed by the request owner after HTTPResponse is released

    def makefile(self, mode, *args, **kwargs):
        if mode != "rb":
            raise ValueError("Only binary HTTP reads are supported")
        # Installed only after sending the request. A timeout from recv is
        # handled below, never poisons socket.makefile's internal buffer.
        self.sock.settimeout(.05)
        return io.BufferedReader(_Read(self.sock, self.cancel_event, self.timeout))


class _Read(io.RawIOBase):
    def __init__(self, sock, cancel_event, timeout):
        self.sock, self.cancel_event, self.timeout = sock, cancel_event, timeout

    def readable(self):
        return True

    def readinto(self, buffer):
        deadline = monotonic() + self.timeout
        while not self.cancel_event.is_set():
            if monotonic() >= deadline:
                raise TimeoutError("TTS response timed out")
            pending = getattr(self.sock, "pending", lambda: 0)()
            if not pending and not select.select([self.sock], [], [], .02)[0]:
                continue
            try:
                data = self.sock.recv(len(buffer))
            except socket.timeout:
                continue
            buffer[:len(data)] = data
            return len(data)
        return 0


@contextmanager
def cancellable_response(request, timeout, cancel_event, http_open):
    stopped = threading.Event()
    lock = threading.Lock()
    sockets = []
    response = None

    def abort(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def attach(sock):
        with lock:
            sockets.append(sock)
            if cancel_event.is_set():
                abort(sock)

    def watch():
        while not stopped.wait(.02):
            if cancel_event.is_set():
                with lock:
                    for sock in sockets:
                        abort(sock)
                    current = response
                # Injected transports can expose close without a native socket.
                if current is not None and not sockets:
                    current.close()
                return

    class Connection(http.client.HTTPConnection):
        def connect(self):
            super().connect()
            attach(self.sock)
            self.sock.settimeout(timeout)
            self.sock = _ReadSocket(self.sock, cancel_event, timeout)

    class SecureConnection(http.client.HTTPSConnection):
        def connect(self):
            super().connect()
            attach(self.sock)
            self.sock.settimeout(timeout)
            self.sock = _ReadSocket(self.sock, cancel_event, timeout)

    class Handler(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(Connection, req)

    class SecureHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(SecureConnection, req, context=self._context)

    watcher = threading.Thread(target=watch, name="tts-http-cancel", daemon=True)
    watcher.start()
    try:
        if cancel_event.is_set():
            raise InterruptedError("TTS cancelled")
        # Preserve the provider's injectable transport for deterministic tests.
        if http_open is urllib.request.urlopen:
            opener = urllib.request.build_opener(Handler(), SecureHandler())
            result = opener.open(request, timeout=min(timeout, 5.0))
        else:
            result = http_open(request, timeout=timeout)
        with lock:
            response = result
            cancelled = cancel_event.is_set()
        if cancelled:
            raise InterruptedError("TTS cancelled")
        yield response
    except urllib.error.HTTPError as error:
        response = error
        raise
    finally:
        stopped.set()
        watcher.join()
        if response is not None:
            response.close()
        with lock:
            for sock in sockets:
                sock.close()
