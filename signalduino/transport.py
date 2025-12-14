from __future__ import annotations

import logging
import socket
from socket import gaierror
from typing import Optional, Any
import asyncio # NEU: Für asynchrone I/O und Kontextmanager

from .exceptions import SignalduinoConnectionError

logger = logging.getLogger(__name__)


class BaseTransport:
    """Minimal asynchronous interface shared by all transports."""

    async def __aenter__(self) -> "BaseTransport":  # pragma: no cover
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # pragma: no cover
        await self.close()

    async def open(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def write_line(self, data: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def readline(self) -> Optional[str]:  # pragma: no cover - interface
        # Wir entfernen das Timeout-Argument, da wir dies mit asyncio.wait_for im Controller handhaben
        raise NotImplementedError
    
    def closed(self) -> bool:  # pragma: no cover - interface
        """Returns True if the transport is closed, False otherwise."""
        raise NotImplementedError

    # is_open wird entfernt, da es in async-Umgebungen schwer zu implementieren ist
    # und die Transportfehler (SignalduinoConnectionError) zur Beendigung führen.


class SerialTransport(BaseTransport):
    """Placeholder for asynchronous serial transport."""

    def __init__(self, port: str, baudrate: int = 115200, read_timeout: float = 0.5):
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self._serial: Any = None # Placeholder für asynchrones Serial-Objekt

    async def open(self) -> None:
        # Hier wäre die Logik für `async_serial.to_serial_port()` oder ähnliches
        raise NotImplementedError("Asynchronous serial transport is not implemented yet.")

    async def close(self) -> None:
        # Hier wäre die Logik für das Schließen des asynchronen Ports
        pass

    async def write_line(self, data: str) -> None:
        # Platzhalter: Müsste zu `await self._writer.write(payload)` werden
        await asyncio.sleep(0) # Nicht-blockierende Wartezeit
        raise NotImplementedError("Asynchronous serial transport is not implemented yet.")

    async def readline(self) -> Optional[str]:
        # Platzhalter: Müsste zu `await self._reader.readline()` werden
        # Simuliere das Warten auf eine Zeile (blockiert effektiv)
        await asyncio.Future() # Hängt die Coroutine auf
        raise NotImplementedError("Asynchronous serial transport is not implemented yet.")

    def closed(self) -> bool:
        return self._serial is None

        
class TCPTransport(BaseTransport):
    """Asynchronous TCP transport using asyncio streams."""

    def __init__(self, host: str, port: int, read_timeout: float = 10.0):
        self.host = host
        self.port = port
        self.read_timeout = read_timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def open(self) -> None:
        try:
            # Das `read_timeout` wird im Controller mit `asyncio.wait_for` gehandhabt
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
            logger.info("TCPTransport connected to %s:%s", self.host, self.port)
        except (OSError, gaierror) as exc:
            raise SignalduinoConnectionError(str(exc)) from exc

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None
            logger.info("TCPTransport closed.")

    def closed(self) -> bool:
        return self._writer is None

    async def write_line(self, data: str) -> None:
        if not self._writer:
            raise SignalduinoConnectionError("TCPTransport is not open")
        payload = (data + "\n").encode("latin-1", errors="ignore")
        self._writer.write(payload)
        await self._writer.drain()

    async def readline(self) -> Optional[str]:
        if not self._reader:
            raise SignalduinoConnectionError("TCPTransport is not open")
        try:
            # readline liest bis zum Trennzeichen oder EOF
            raw = await self._reader.readline()
            if not raw:
                # Verbindung geschlossen (EOF erreicht)
                raise SignalduinoConnectionError("Remote closed connection")
            # Wir verwenden strip(), um das Zeilenende zu entfernen, da der Controller dies erwartet
            return raw.decode("latin-1", errors="ignore").strip()
        except ConnectionResetError as exc:
             raise SignalduinoConnectionError("Connection reset by peer") from exc
        except Exception as exc:
            # Re-raise andere Exceptions als Verbindungsfehler
            if 'socket is closed' in str(exc) or 'cannot reuse' in str(exc):
                raise SignalduinoConnectionError(str(exc)) from exc
            raise

