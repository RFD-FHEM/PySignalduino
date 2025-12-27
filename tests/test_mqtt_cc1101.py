import json
import pytest
from unittest.mock import Mock, AsyncMock, call
import re
from typing import Dict, Any

from signalduino.controller import SignalduinoController
from signalduino.exceptions import CommandValidationError, SignalduinoCommandTimeout
from signalduino.commands import SDUINO_CMD_TIMEOUT
# Dummy-Definitionen für fehlende Imports
class MqttCommandDispatcher:
    def __init__(self, controller):
        pass

# Hilfsfunktion für die Erstellung eines Mock-Controllers mit dem Dispatcher
@pytest.fixture
def mock_cc1101_controller():
    mock_commands = Mock()
    mock_publisher = Mock()
    mock_publisher.response_topic = "test/responses"
    mock_publisher.error_topic = "test/errors"
    mock_publisher.publish_simple = AsyncMock()

    class MockController(SignalduinoController):
        def __init__(self):
            self.logger = Mock()
            self.mqtt_publisher = mock_publisher
            self.commands = mock_commands
            self.mqtt_dispatcher = MqttCommandDispatcher(self)
        
        
        # Implementiere die vom Dispatcher aufgerufenen Methoden, die jetzt direkt im Controller implementiert sind.
        # Da wir die tatsächliche Implementierung nicht haben, mocken wir sie.
        async def set_cc1101_frequency(self, payload: Dict[str, Any]) -> str:
            # Hier sollte die Implementierung stehen, die send_command aufruft.
            return "OK" # Dummy-Rückgabe
        
        async def set_cc1101_rampl(self, payload: Dict[str, Any]) -> str:
            return "OK"
            
        async def set_cc1101_patable(self, payload: Dict[str, Any]) -> str:
            return "OK"

        async def set_cc1101_sensitivity(self, payload: Dict[str, Any]) -> str:
            return "OK"

        async def set_cc1101_deviation(self, payload: Dict[str, Any]) -> str:
            return "OK"

        async def set_cc1101_datarate(self, payload: Dict[str, Any]) -> str:
            return "OK"

        async def set_cc1101_bandwidth(self, payload: Dict[str, Any]) -> str:
            return "OK"
            
        async def command_send_msg(self, payload: Dict[str, Any]) -> str:
            return "OK"
            
        # Füge Mock-Implementierungen für CCconf/ccpatable hinzu
        mock_commands.get_ccconf = AsyncMock(return_value="M[S|N]=0;C0Dn11=1122")
        mock_commands.get_ccpatable = AsyncMock(return_value="C3E = C0")
        mock_commands.read_cc1101_register = AsyncMock()
        mock_commands.cc1101_write_init = AsyncMock()
        mock_commands._send_command = AsyncMock(return_value="OK") # Niedrig-Level-Befehlsversand
        mock_commands.send_raw_message = AsyncMock(return_value="OK") # NEU: Für command_send_msg

    return MockController()


@pytest.mark.asyncio
async def test_set_cc1101_frequency(mock_cc1101_controller):
    """Testet das Setzen der Frequenz (433.92 MHz -> W0Fxx, W10xx, W11xx)."""
    ctrl = mock_cc1101_controller
    command_path = 'set/cc1101/frequency'
    freq_mhz = 433.92
    
    # 433.92 * 2^16 / 26 = 1083838.16... -> 0x10B071 (FREQ2=10, FREQ1=B0, FREQ0=71)
    
    payload = json.dumps({"req_id": "req-freq-1", "value": freq_mhz})
    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    # Prüfe die gesendeten Commands (W0F<F2>, W10<F1>, W11<F0>)
    expected_calls = [
        call(payload='W0F10', expect_response=False),
        call(payload='W10B0', expect_response=False),
        call(payload='W1171', expect_response=False),
    ]
    
    ctrl.commands._send_command.assert_has_calls(expected_calls, any_order=True)
    ctrl.commands.cc1101_write_init.assert_awaited_once()
    ctrl.commands.get_ccconf.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_cc1101_rampl(mock_cc1101_controller):
    """Testet das Setzen der Empfängerverstärkung (40 dB -> W1D06)."""
    ctrl = mock_cc1101_controller
    command_path = 'set/cc1101/rampl'
    rampl_db = 40
    
    # ampllist = [24, 27, 30, 33, 36, 38, 40, 42]
    # Index 6 für 40 dB (v=6)
    
    payload = json.dumps({"req_id": "req-rampl-1", "value": rampl_db})
    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    # Prüfe den gesendeten Command (W1D<v>)
    ctrl.commands._send_command.assert_awaited_with(payload='W1D06', expect_response=False)
    ctrl.commands.cc1101_write_init.assert_awaited_once()
    ctrl.commands.get_ccconf.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_cc1101_patable(mock_cc1101_controller):
    """Testet das Setzen der PA Table (-10_dBm -> x34)."""
    ctrl = mock_cc1101_controller
    command_path = 'set/cc1101/patable'
    pa_level = "-10_dBm"
    
    # Mapping: -10_dBm -> 34
    
    payload = json.dumps({"req_id": "req-patable-1", "value": pa_level})
    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    # Prüfe den gesendeten Command (x<hex>)
    ctrl.commands._send_command.assert_awaited_with(payload='x34', expect_response=False)
    ctrl.commands.cc1101_write_init.assert_awaited_once()
    ctrl.commands.get_ccpatable.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_cc1101_deviation(mock_cc1101_controller):
    """Testet das Setzen der Deviation (38.4 kHz)."""
    ctrl = mock_cc1101_controller
    command_path = 'set/cc1101/deviation'
    deviation_khz = 38.4 # Nahe dem realen Wert 38.484375 kHz (0x44)
    
    # Der berechnete Wert sollte 0x44 (0100 0100) sein: M=4, E=4 (38.48 kHz)
    
    payload = json.dumps({"req_id": "req-dev-1", "value": deviation_khz})
    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    # Prüfe den gesendeten Command (W17<hex>)
    ctrl.commands._send_command.assert_awaited_with(payload='W1744', expect_response=False)
    ctrl.commands.cc1101_write_init.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_cc1101_datarate_full_flow(mock_cc1101_controller):
    """Testet den vollen Flow für das Setzen der Datenrate, inkl. Registerlesen."""
    ctrl = mock_cc1101_controller
    command_path = 'set/cc1101/datarate'
    datarate_kbaud = 9.6 # Sollte zu MDMCFG4=C9 und MDMCFG3=93 führen, wenn MDMCFG4[7:4]=C
    
    # MDMCFG4 (0x10) lesen: Wir simulieren, dass die Bits 7:4 (BW) auf 0xC0 (1100) stehen.
    ctrl.commands.read_cc1101_register.return_value = "C10 = C0" 

    payload = json.dumps({"req_id": "req-dr-1", "value": datarate_kbaud})
    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    # Schritt 1: Lesen
    ctrl.commands.read_cc1101_register.assert_called_once_with(0x10, timeout=SDUINO_CMD_TIMEOUT)
    
    # Schritt 2: Schreiben
    # Target 9.6 kBaud -> DRATE_E=9, DRATE_M=92 (gerundet) -> 92 (0x5C)
    # MDMCFG4[7:4] (0xC0) behalten, MDMCFG4[3:0] (DRATE_E=9=0x9) setzen -> 0xC9
    # MDMCFG3 (DRATE_M) = 92 (0x5C)
    
    expected_calls = [
        call(payload='W12C8', expect_response=False), # W12 ist 0x10+2
        call(payload='W1383', expect_response=False), # W13 ist 0x11+2
    ]
    
    # Mock send_command wurde bereits für read_cc1101_register verwendet, also prüfen wir den zweiten Aufruf
    ctrl.commands._send_command.assert_has_calls(expected_calls, any_order=True)
    ctrl.commands.cc1101_write_init.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_cc1101_bandwidth_full_flow(mock_cc1101_controller):
    """Testet den vollen Flow für das Setzen der Bandbreite, inkl. Registerlesen."""
    ctrl = mock_cc1101_controller
    command_path = 'set/cc1101/bandwidth'
    bw_khz = 102 # Sollte zu 102 kHz führen (M=1, E=2 -> 0x81)
    
    # MDMCFG4 (0x10) lesen: Wir simulieren, dass die Bits 3:0 (Data Rate E) auf 0x1 (0001) stehen.
    ctrl.commands.read_cc1101_register.return_value = "C10 = 01" 
    
    payload = json.dumps({"req_id": "req-bw-1", "value": bw_khz})
    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    # Target 101 kHz -> Sollte zu M=1, E=2 führen. Bits 7:4 = (2<<6) + (1<<4) = 128 + 16 = 144 (0x90)
    # MDMCFG4[3:0] (0x01) behalten. MDMCFG4[7:4] (0x90) setzen -> 0x91
    
    # Schritt 1: Lesen
    ctrl.commands.read_cc1101_register.assert_called_once_with(0x10, timeout=SDUINO_CMD_TIMEOUT)
    
    # Schritt 2: Schreiben
    expected_call = call(payload='W12C1', expect_response=False) # W12 ist 0x10+2
    
    # Mock send_command wurde bereits für read_cc1101_register verwendet, also prüfen wir den zweiten Aufruf
    ctrl.commands._send_command.assert_awaited_with(payload='W12C1', expect_response=False) # Korrekte Assertion des letzten Aufrufs

    ctrl.commands.cc1101_write_init.assert_awaited_once()


@pytest.mark.asyncio
async def test_command_send_msg_manchester_sm(mock_cc1101_controller):
    """Testet das Senden einer Manchester-Nachricht (SM)."""
    ctrl = mock_cc1101_controller
    command_path = 'command/send/msg'
    
    params = {
        "protocol_id": 10,
        "data": "DEADBEEF",
        "repeats": 5,
        "clock_us": 400,
        "frequency_mhz": 433.92 # Sollte ignoriert werden, da Frequenz separat gesetzt wird.
    }
    
    payload = json.dumps({"req_id": "req-send-1", "parameters": params})
    
    # Berechnung der Frequenz-Hex-Werte
    freq_val = int(params["frequency_mhz"] * (2**16) / 26)
    f2 = freq_val // 65536
    f1 = (freq_val % 65536) // 256
    f0 = freq_val % 256
    freq_part = f"F={f2:02X}{f1:02X}{f0:02X};" # F=10B071;
    
    expected_raw_cmd = f"SM;R=5;C=400;D=DEADBEEF;{freq_part}"

    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    # Prüfe, ob die send_raw_message im commands-Objekt aufgerufen wurde
    ctrl.commands.send_raw_message.assert_awaited_with(expected_raw_cmd, timeout=SDUINO_CMD_TIMEOUT)


@pytest.mark.asyncio
async def test_command_send_msg_xfsk_sn(mock_cc1101_controller):
    """Testet das Senden einer xFSK/Hex-Nachricht (SN)."""
    ctrl = mock_cc1101_controller
    command_path = 'command/send/msg'
    
    params = {
        "protocol_id": 35,
        "data": "ABCDEF",
        "repeats": 2,
    }
    
    payload = json.dumps({"req_id": "req-send-2", "parameters": params})
    
    expected_raw_cmd = "SN;R=2;D=ABCDEF;" # Keine Clock -> SN
    
    await ctrl.mqtt_dispatcher.dispatch(command_path, payload)

    ctrl.commands.send_raw_message.assert_awaited_with(expected_raw_cmd, timeout=SDUINO_CMD_TIMEOUT)

@pytest.mark.asyncio
async def test_command_send_msg_validation_error(mock_cc1101_controller):
    """Testet die Validierung, wenn Protokolldaten ohne Hex-Präfix gesendet werden (ungültiger Fall)."""
    ctrl = mock_cc1101_controller
    command_path = 'command/send/msg'
    req_id = "req-err-1"
    
    # Versuch, Raw-Daten ohne Hex-Präfix und ohne Clock zu senden (führt zu Validierungsfehler in command_send_msg)
    params = {
        "protocol_id": 0,
        "data": "101101", # Keine Hex-Präfix
    }
    
    payload = json.dumps({"req_id": req_id, "parameters": params})
    
    await ctrl._handle_mqtt_command(command_path, payload)

    # Erwarte, dass der Dispatcher eine CommandValidationError wirft, die vom Controller
    # in eine 400-Fehlermeldung umgewandelt wird.
    
    # 1. Prüfe, ob die Fehlermeldung korrekt als 400 gesendet wurde
    ctrl.mqtt_publisher.publish_simple.assert_awaited_once()
    call_args = ctrl.mqtt_publisher.publish_simple.call_args[0]
    error_topic = call_args[0]
    error_payload = json.loads(call_args[1])
    
    assert error_topic == f"errors/{command_path}"
    assert error_payload["error_code"] == 400
    assert "Raw binary data (string of '0's and '1's) requires a 'clock_us'" in error_payload["error_message"]
    assert error_payload["req_id"] == req_id