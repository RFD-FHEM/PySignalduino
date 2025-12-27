import asyncio
from asyncio import Queue
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout
from signalduino.transport import BaseTransport
from signalduino.types import DecodedMessage, RawFrame, SerialInterface
from signalduino.commands import Command, CommandType


@pytest.fixture
def mock_transport():
    """Fixture for a mocked async transport layer."""
    transport = AsyncMock(spec=SerialInterface)
    transport.is_connected = False
    
    # Define side effects that update state but let the Mock track the call
    async def aconnect_side_effect(*args, **kwargs):
        transport.is_connected = True
        return transport
    
    async def aclose_side_effect(*args, **kwargs):
        transport.is_connected = False

    transport.connect = AsyncMock(side_effect=aconnect_side_effect)
    transport.close.side_effect = aclose_side_effect
    
    # Configure closed() to return True initially (not applicable to SerialInterface)
        
    async def read_line_side_effect():
        await asyncio.sleep(0.01) # Give the reader task a chance to yield
        return None

    transport.read_line.side_effect = read_line_side_effect
    return transport




@pytest.mark.asyncio
async def test_connect_disconnect(mock_transport, mock_parser):
    """Test that connect() and disconnect() open/close transport and tasks."""
    controller = SignalduinoController(serial_interface=mock_transport, parser=mock_parser)

    async with controller:
        # Assertion auf .open ändern, da die Fixture dies als zu startende Methode definiert
        mock_transport.connect.assert_called_once()
        # Tasks werden in _main_tasks gespeichert. Ihre Überprüfung ist zu komplex.

    mock_transport.close.assert_called_once()
    # Der Test ist nur dann erfolgreich, wenn der async with Block fehlerfrei durchläuft.


@pytest.mark.asyncio
async def test_send_command_fire_and_forget(mock_transport, mock_parser):
    """Test sending a command without expecting a response."""
    controller = SignalduinoController(serial_interface=mock_transport, parser=mock_parser)
    async with controller:
        # The command is sent immediately to the transport layer.
        await controller.send_command(Command.VERSION())
        mock_transport.write_line.assert_called_once_with("V")


@pytest.mark.asyncio
async def test_send_command_with_response(mock_transport, mock_parser):
    """Test sending a command and waiting for a response."""
    # Verwende eine asyncio Queue zur Synchronisation
    response_q = Queue()

    async def write_line_side_effect(payload):
        # Beim Schreiben des Kommandos (z.B. "V") die Antwort in die Queue legen
        if payload == "V":
            await response_q.put("V 3.5.0-dev SIGNALduino - compiled at Mar 10 2017 22:54:50\n")

    async def read_line_side_effect():
        # Lese die nächste Antwort aus der Queue.
        # Der Controller nutzt asyncio.wait_for, daher können wir hier warten.
        # Um Deadlocks zu vermeiden, warten wir kurz auf die Queue.
        try:
            return await asyncio.wait_for(response_q.get(), timeout=0.1)
        except asyncio.TimeoutError:
            # Wenn nichts in der Queue ist, geben wir nichts zurück (simuliert Warten auf Daten)
            # Im echten Controller wird readline() vom Transport erst zurückkehren, wenn Daten da sind.
            # Wir simulieren das Warten durch asyncio.sleep, damit der Reader-Loop nicht spinnt.
            await asyncio.sleep(0.1)
            return None # Kein Ergebnis, Reader Loop macht weiter

    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.read_line.side_effect = read_line_side_effect

    controller = SignalduinoController(serial_interface=mock_transport, parser=mock_parser)
    async with controller:

        
        # get_version uses send_command, which uses controller.commands._send, which calls controller.send_command
        # This will block until the response is received
        response = await controller.send_command(Command(name="VERSION", raw_command="V", command_type=CommandType.GET, timeout=1.0))
        
        mock_transport.write_line.assert_called_once_with("V")
        assert response is not None
        assert "SIGNALduino" in response


@pytest.mark.asyncio
async def test_send_command_with_interleaved_message(mock_transport, mock_parser):
    """
    Test sending a command and receiving an irrelevant message before the
    expected command response. The irrelevant message must not be consumed
    as the response, and the correct response must still be received.
    """
    # Queue for all messages from the device
    response_q = Queue()

    # The irrelevant message (e.g., an asynchronous received signal)
    interleaved_message = "MU;P0=353;P1=-184;D=0123456789;CP=1;SP=0;R=248;\n"
    # The expected command response
    command_response = "V 3.5.0-dev SIGNALduino - compiled at Mar 10 2017 22:54:50\n"

    async def write_line_side_effect(payload):
        # When the controller writes "V", simulate the device responding with
        # an interleaved message *then* the command response.
        if payload == "V":
            # 1. Interleaved message
            await response_q.put(interleaved_message)
            # 2. Command response
            await response_q.put(command_response)

    async def read_line_side_effect():
        # Simulate blocking read that gets a value from the queue.
        try:
            return await asyncio.wait_for(response_q.get(), timeout=0.1)
        except asyncio.TimeoutError:
            await asyncio.sleep(0.1)
            return None

    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.read_line.side_effect = read_line_side_effect

    # Mock the parser to track if the interleaved message is passed to it
    mock_parser.parse_line = Mock(wraps=mock_parser.parse_line)

    controller = SignalduinoController(serial_interface=mock_transport, parser=mock_parser)
    async with controller:

        
        response = await controller.send_command(Command(name="VERSION", raw_command="V", command_type=CommandType.GET, timeout=2.0))
        mock_transport.write_line.assert_called_once_with("V")
        
        # 1. Verify that the correct command response was received by send_command
        assert response is not None
        assert "SIGNALduino" in response
        assert response.strip() == command_response.strip()

        # 2. Verify that the interleaved message was passed to the parser
        # The parser loop (_parser_loop) should attempt to parse the interleaved_message
        # because _handle_as_command_response should return False for it.
        # Wait briefly for parser task to process
        await asyncio.sleep(0.05)
        mock_parser.parse_line.assert_called_once_with(interleaved_message.strip())


@pytest.mark.asyncio
async def test_send_command_timeout(mock_transport, mock_parser):
    """Test that a command times out if no response is received."""
    # Verwende eine Liste zur Steuerung der Read/Write-Reihenfolge (leer für Timeout)
    response_list = []

    async def write_line_side_effect(payload):
        # Wir schreiben, simulieren aber keine Antwort (um das Timeout auszulösen)
        pass

    async def read_line_side_effect():
        # Lese die nächste Antwort aus der Liste, wenn verfügbar, ansonsten warte und gib None zurück
        if response_list:
            return response_list.pop(0)
        await asyncio.sleep(0.5) # Blockiere, um das Kommando-Timeout auszulösen (0.2s)
        return None
    
    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.read_line.side_effect = read_line_side_effect
    
    controller = SignalduinoController(serial_interface=mock_transport, parser=mock_parser)
    async with controller:

        
        with pytest.raises(SignalduinoCommandTimeout):
            await controller.send_command(Command(name="VERSION", raw_command="V", command_type=CommandType.GET, timeout=0.2))


@pytest.mark.asyncio
async def test_message_callback(mock_transport, mock_parser):
    """Test that the message callback is invoked for decoded messages."""
    callback_mock = Mock()
    decoded_msg = DecodedMessage(protocol_id="1", payload="test", raw=RawFrame(line=""))
    mock_parser.parse_line.return_value = [decoded_msg]

    async def mock_readline():
        # We only want to return the message once, then return None indefinitely
        if not hasattr(mock_readline, "called"):
            setattr(mock_readline, "called", True)
            return "MS;P0=1;D=...;\n"
        await asyncio.sleep(0.1)
        return None

    mock_transport.read_line.side_effect = mock_readline
    
    controller = SignalduinoController(
        serial_interface=mock_transport,
        parser=mock_parser,
        message_callback=callback_mock,
    )

    async with controller:

        
        # Warte auf das Parsen, wenn die Nachricht ankommt
        await asyncio.sleep(0.2)
        callback_mock.assert_called_once_with(decoded_msg)


@pytest.mark.asyncio
async def test_initialize_retry_logic(mock_transport, mock_parser):
    """Test the retry logic during initialization."""
    
    # Mock send_command to fail initially and then succeed
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        payload = kwargs.get("payload") or args[0] if args else None
        # print(f"DEBUG Mock Call {call_count}: {payload}")

        if payload == "XQ":
            return None
        if payload == "V":
            # XQ ist Aufruf 1. V fail ist Aufruf 2. V success ist Aufruf 3.
            if call_count < 3:  # Fail first V attempt (call_count 2)
                raise SignalduinoCommandTimeout("Timeout")
            return "V 3.5.0-dev SIGNALduino - compiled at Mar 10 2017 22:54:50\n"
        
        if payload == "XE":
            return None
        
        return None

    mocked_send_command = AsyncMock(side_effect=side_effect)

    # Use very short intervals for testing by patching the imported constants in the controller module
    import signalduino.controller
    
    original_wait_interval = signalduino.controller.SDUINO_RETRY_INTERVAL
    original_max_tries = signalduino.controller.SDUINO_INIT_MAXRETRY
    
    # Setze die Wartezeiten und Versuche für einen schnelleren Test
    signalduino.controller.SDUINO_RETRY_INTERVAL = 0.01
    signalduino.controller.SDUINO_INIT_MAXRETRY = 3 # Max 3 Versuche gesamt: XQ, V (fail), V (success)

    try:
        controller = SignalduinoController(serial_interface=mock_transport, parser=mock_parser)
        # Mocke die Methode, die tatsächlich von Commands.get_version aufgerufen wird
        # WICHTIG: controller.commands._send muss auch aktualisiert werden, da es bei __init__ gebunden wurde
        controller.send_command = mocked_send_command
        
        # Mocket _reset_device, um die rekursiven aexit-Aufrufe zu verhindern,
        # die während des Test-Cleanups einen RecursionError auslösen

        async with controller:

            # initialize startet Background Tasks und kehrt zurück
            await controller.initialize()
            await asyncio.sleep(0.2) # Gib dem Event-Loop Zeit, die Init-Tasks zu starten
            
            # Warte explizit auf den Abschluss der Initialisierung, wie in controller.run()
            
            # Wir müssen nicht mehr so lange warten, da das Event gesetzt wird
            # Wir geben den Tasks nur kurz Zeit, sich zu beenden
            await asyncio.sleep(1.0)

            # Verify calls:
            # 1. XQ
            # 2. V (fails)
            # 3. V (retry, succeeds)
            # 4. XE (enabled after success)
            
            # Note: Depending on timing and implementation details, call count might vary slighty
            # but we expect at least XQ, failed V, successful V, XE.
            
            calls = [c.kwargs.get('payload') or c.args for c in mocked_send_command.call_args_list]
            
            # Debugging helper
            # print(f"Calls: {calls}")

            assert ("XQ",) in calls # Payload wird als Tupel übergeben
            assert len([c for c in calls if c == ('V',)]) >= 2
            assert ("XE",) in calls

    finally:
        signalduino.controller.SDUINO_RETRY_INTERVAL = original_wait_interval
        signalduino.controller.SDUINO_INIT_MAXRETRY = original_max_tries


@pytest.mark.asyncio
async def test_stx_message_bypasses_command_response(mock_transport, mock_parser):
    """
    Test that messages starting with STX (\x02) are NOT treated as command responses,
    even if the command's regex (like .* for cmds) would match them.
    They should be passed directly to the parser.
    """
    # Liste für Antworten
    response_list = []

    # STX message (Sensor data)
    stx_message = "\x02SomeSensorData\x03\n"
    # Expected response for 'cmds' (?)
    cmd_response = "V X t R C S U P G r W x E Z\n"

    async def write_line_side_effect(payload):
        if payload == "?":
            # Simulate STX message followed by real response
            response_list.append(stx_message)
            response_list.append(cmd_response)

    async def read_line_side_effect():
        # Lese die nächste Antwort aus der Liste, wenn verfügbar, ansonsten warte und gib None zurück
        if response_list:
            return response_list.pop(0)
        await asyncio.sleep(0.1) # Kurze Pause, um den Reader-Loop zu entsperren
        return None

    mock_transport.write_line.side_effect = write_line_side_effect
    mock_transport.read_line.side_effect = read_line_side_effect
    
    # Mock parser to verify STX message is parsed
    mock_parser.parse_line = Mock(wraps=mock_parser.parse_line)
    
    controller = SignalduinoController(serial_interface=mock_transport, parser=mock_parser)
    async with controller:

        
        # get_cmds uses pattern r".*", which would normally match the STX message
        # if we didn't have the special handling in the controller.
        response = await controller.send_command(Command(name="GET_CMDS", raw_command="?", command_type=CommandType.GET))
        
        # Verify we got the correct response, not the STX message
        assert response is not None
        assert response.strip() == cmd_response.strip()
        
        # Give parser thread some time
        await asyncio.sleep(0.5)
        
        # Verify STX message was sent to parser
        mock_parser.parse_line.assert_any_call(stx_message.strip())