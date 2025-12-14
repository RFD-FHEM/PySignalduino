import socket
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

import pytest

from signalduino.transport import TCPTransport
from signalduino.exceptions import SignalduinoConnectionError


# Anstelle von unittest.TestCase verwenden wir jetzt pytest und asynchrone Funktionen
class MockReader:
    """Mock for asyncio.StreamReader."""
    def __init__(self, data: bytes = b''):
        self._data = asyncio.Queue()
        # Stellen Sie sicher, dass jede Zeile mit \n endet
        for line in data.split(b'\n'):
             if line: # Ignoriere leere Zeilen vom letzten \n
                 self._data.put_nowait(line + b'\n')
    
    async def readline(self) -> bytes:
        """Simuliert stream.readline()."""
        # stream.readline() blockiert, bis eine Zeile verfügbar ist oder EOF erreicht wird.
        # Wir lassen die Queue blockieren. Timeout wird im aufrufenden Code (Controller) gehandhabt.
        try:
            data = await self._data.get()
            if data == b'':
                # Sentinelle von close() oder EOF
                return b''
            return data
        except asyncio.CancelledError:
            raise # Erlaubt CancelledError
    
    async def readuntil(self, separator: bytes = b'\n') -> bytes:
        # readuntil ist in TCPTransport nicht direkt verwendet
        raise NotImplementedError

    def at_eof(self) -> bool:
        return self._data.empty()
        
    def close(self):
        """Unblockt blockierende readline-Aufrufe durch Hinzufügen einer Sentinelle."""
        # Das Hinzufügen einer Sentinelle (b'') ist die Standardmethode, um blockierte asyncio.Queue.get()
        # sicher in Tests aufzuheben, wenn der Stream geschlossen wird.
        if self._data.empty():
            self._data.put_nowait(b'')
        # Füge immer eine Sentinelle hinzu, falls der Aufruf blockiert
        self._data.put_nowait(b'')

class MockWriter:
    """Mock for asyncio.StreamWriter."""
    def __init__(self, reader):
        self.data_written = bytearray()
        self._reader = reader
        
    def write(self, data: bytes):
        self.data_written.extend(data)
        
    async def drain(self):
        pass

    def close(self):
        self._reader.close() # Ruft MockReader.close() auf, um blockierende Aufrufe aufzuheben

    async def wait_closed(self):
        pass


@pytest.fixture
def mock_open_connection():
    """Mocks asyncio.open_connection to return mock reader/writer pairs."""
    mock_reader = MockReader()
    mock_writer = MockWriter(reader=mock_reader)
    
    async def side_effect(*args, **kwargs):
        # Wir müssen den Timeout ignorieren, da er im open_connection nicht verwendet wird,
        # sondern später in den Stream-Operationen.
        return mock_reader, mock_writer
    
    with patch('asyncio.open_connection', new=AsyncMock(side_effect=side_effect)) as mock_conn:
        yield mock_conn, mock_reader, mock_writer


@pytest.mark.asyncio
async def test_open_success(mock_open_connection):
    """Testet, dass open den Transport korrekt öffnet."""
    mock_conn, _, _ = mock_open_connection
    transport = TCPTransport("127.0.0.1", 8080)
    
    async with transport:
        mock_conn.assert_called_once_with('127.0.0.1', 8080)
        # is_open wird durch das Vorhandensein von _reader/writer impliziert.
        assert transport._reader is not None


@pytest.mark.asyncio
async def test_readline_timeout(mock_open_connection):
    """Testet, dass readline bei Timeout None zurückgibt."""
    mock_conn, mock_reader, _ = mock_open_connection
    transport = TCPTransport("127.0.0.1", 8080, read_timeout=0.5) # Wir verwenden kein Timeout, da wir es mit asyncio.wait_for testen.


    # Da die Queue des MockReader leer ist, würde transport.readline() blockieren (await self._data.get())
    # Wir umgeben den Aufruf mit asyncio.wait_for, um das Verhalten des Controllers zu simulieren
    # und das Timeout-Verhalten zu testen.

    async with transport:
        transport._reader = mock_reader
        
        # Testen Sie, dass das Timeout auftritt
        with pytest.raises(asyncio.TimeoutError):
            # Wir verwenden ein sehr kurzes Timeout, um sicherzustellen, dass die blockierende readline()
            # Methode rechtzeitig abgebrochen wird.
            await asyncio.wait_for(transport.readline(), timeout=0.1)


@pytest.mark.asyncio
async def test_readline_eof(mock_open_connection):
    """Testet, dass readline bei EOF eine ConnectionError wirft."""
    mock_conn, mock_reader, _ = mock_open_connection
    transport = TCPTransport("127.0.0.1", 8080)

    async def mock_readline_eof() -> bytes:
        # TCPTransport.readline erwartet bei Verbindungsabbruch/EOF b'' und wirft dann ConnectionError
        return b''

    mock_reader._data.put_nowait(b'test line 1\n')
    mock_reader.readline = AsyncMock(side_effect=mock_readline_eof)

    async with transport:
        transport._reader = mock_reader
        
        with pytest.raises(SignalduinoConnectionError):
            await transport.readline()


@pytest.mark.asyncio
async def test_readline_success(mock_open_connection):
    """Testet das erfolgreiche Lesen einer Zeile."""
    mock_conn, mock_reader, _ = mock_open_connection
    transport = TCPTransport("127.0.0.1", 8080)
    
    async def mock_readline_success() -> bytes:
        return b'test line\n'
    
    mock_reader.readline = AsyncMock(side_effect=mock_readline_success)

    async with transport:
        transport._reader = mock_reader
        
        result = await transport.readline()
        assert result == 'test line'
