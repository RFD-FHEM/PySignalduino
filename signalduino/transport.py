"""Transport abstractions for serial and TCP Signalduino connections."""

from __future__ import annotations

import logging
import socket
from typing import Optional

from .exceptions import SignalduinoConnectionError

logger = logging.getLogger(__name__)


class BaseTransport:
    """Minimal interface shared by all transports."""

    def open(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def write_line(self, data: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def readline(self, timeout: Optional[float] = None) -> Optional[str]:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def is_open(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class SerialTransport(BaseTransport):
    """Serial transport backed by pyserial."""

    def __init__(self, port: str, baudrate: int = 115200, read_timeout: float = 0.5):
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self._serial = None

    def open(self) -> None:
        try:
            import serial  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - import guard
            raise SignalduinoConnectionError("pyserial is required for SerialTransport") from exc

        try:
            self._serial = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.read_timeout,
                write_timeout=1,
            )
        except serial.SerialException as exc:  # type: ignore[attr-defined]
            raise SignalduinoConnectionError(str(exc)) from exc

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    @property
    def is_open(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def write_line(self, data: str) -> None:
        if not self._serial or not self._serial.is_open:
            raise SignalduinoConnectionError("serial port is not open")
        payload = (data + "\n").encode("latin-1", errors="ignore")
        self._serial.write(payload)

    def readline(self, timeout: Optional[float] = None) -> Optional[str]:
        if not self._serial or not self._serial.is_open:
            raise SignalduinoConnectionError("serial port is not open")
        if timeout is not None:
            self._serial.timeout = timeout
        raw = self._serial.readline()
        return raw.decode("latin-1", errors="ignore") if raw else None


class TCPTransport(BaseTransport):
    """TCP transport talking to firmware via sockets."""

    def __init__(self, host: str, port: int, read_timeout: float = 0.5):
        self.host = host
        self.port = port
        self.read_timeout = read_timeout
        self._sock: Optional[socket.socket] = None
        self._buffer = bytearray()

    def open(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=5)
        sock.settimeout(self.read_timeout)
        self._sock = sock

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None
        self._buffer.clear()

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def write_line(self, data: str) -> None:
        if not self._sock:
            raise SignalduinoConnectionError("socket is not open")
        payload = (data + "\n").encode("latin-1", errors="ignore")
        self._sock.sendall(payload)

    def readline(self, timeout: Optional[float] = None) -> Optional[str]:
        if not self._sock:
            raise SignalduinoConnectionError("socket is not open")
        if timeout is not None:
            self._sock.settimeout(timeout)

        while True:
            if b"\n" in self._buffer:
                line, _, self._buffer = self._buffer.partition(b"\n")
                return line.decode("latin-1", errors="ignore")

            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                return None

            if chunk:
                logger.debug("TCP RECV CHUNK: %r", chunk)

            if not chunk:
                raise SignalduinoConnectionError("Remote closed connection")
            self._buffer.extend(chunk)
