import pytest
import json
from unittest.mock import AsyncMock, call, patch
from signalduino.commands import SignalduinoCommands
from signalduino.exceptions import CommandValidationError, SignalduinoCommandTimeout


@pytest.fixture
def mock_commands(request):
    """Fixture für eine SignalduinoCommands Instanz mit gemocktem _send_command."""
    send_command_mock = AsyncMock()
    # Mocking read_cc1101_register/get_bandwidth for set_datarate dependency on 0x10
    
    # Der Mock muss die Antwort für das Lesen von Register 0x10 (MDMCFG4) für die datarate-Set-Logik liefern.
    # MDMCFG4[7:4] ist die Bandbreite, die beibehalten werden soll. Reset-Wert ist 0xC0.
    # Wir simulieren, dass der Wert 0xD0 (0xCC) zurückgegeben wird, was einer Bandbreite von 102 kHz entspricht
    # MDMCFG4=0xD0 -> 1101 0000. Bits 7:4 sind 1101.
    async def mock_read_register(register_address: int):
        if register_address == 0x10:
            return 0xD0 # Rückgabe des Integer-Wertes, da _read_register_value ein int erwartet
        raise ValueError(f"Unexpected register read for 0x{register_address:X}")

    commands = SignalduinoCommands(send_command_mock)
    
    # Patche die abhängige interne Methode, um den gelesenen Registerwert für MDMCFG4 zu simulieren
    commands._read_register_value = AsyncMock(side_effect=mock_read_register)
    
    return commands

@pytest.mark.asyncio
async def test_set_frequency(mock_commands):
    """Testet, dass set_frequency die korrekten drei W-Befehle sendet."""
    
    # 433.92 MHz: F_REG = 433.92 * 2560 = 1110835.2 -> 0x10F073 (gerundet: 1110835)
    freq_mhz = 433.92
    f_reg = 1110835 
    
    # Registerwerte für 0x10, 0xF0, 0x73
    freq2 = (f_reg >> 16) & 0xFF
    freq1 = (f_reg >> 8) & 0xFF
    freq0 = f_reg & 0xFF
    
    # Stelle sicher, dass cc1101_write_init gemockt ist
    mock_commands.cc1101_write_init = AsyncMock()
    
    await mock_commands.set_frequency(freq_mhz) # Korrektur: Nutze freq_mhz anstelle von frequency_mhz (die Variable existiert bereits)

    expected_calls = [
        call(command=f"W0D{freq2:02X}", expect_response=False),
        call(command=f"W0E{freq1:02X}", expect_response=False),
        call(command=f"W0F{freq0:02X}", expect_response=False),
    ]
    
    mock_commands._send_command.assert_has_calls(expected_calls, any_order=False)
    mock_commands.cc1101_write_init.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_datarate(mock_commands):
    """Testet, dass set_datarate die korrekten W-Befehle sendet."""
    
    # Gewünschte Datenrate: 9.6 kBaud (9600 Hz)
    datarate_kbaud = 9.6
    
    # Berechnung sollte ergeben: DRATE_E=9 (0x09), DRATE_M=52 (0x34)
    # T = (9600 * 2^28) / 26000000 = 104857.6
    # DRATE_E=9: 104857.6 / 2^9 = 204.8
    # DRATE_M = round(204.8 - 256) -> ungültig.
    
    # Wir nehmen eine Datenrate, die eine gültige DRATE_E/DRATE_M Kombination ergibt, 
    # z.B. 10 kBaud. Das ist etwa 0x09 für E und 0x33 für M.
    
    # Target: 10 kBaud
    # DRATE_E=10 (0x0A), DRATE_M=52 (0x34) ist eine exakte Kombination:
    # 26000000 * (256 + 52) * 2^10 / 2^28 = 12000 Hz = 12 kBaud (Falsch)
    
    # Real: 10 kBaud (10000 Hz) -> DRATE_E=9 (0x09), DRATE_M=156 (0x9C)
    # 26000000 * (256 + 156) * 2^9 / 2^28 = 10000.00 Hz (Exakt)
    
    drate_e = 9   # 0x09
    drate_m = 156 # 0x9C
    
    # Patche die interne Logik, um die erwarteten Registerwerte zu liefern, wenn die Berechnung korrekt ist
    with patch.object(mock_commands, '_calculate_datarate_registers', return_value=(drate_e, drate_m)) as mock_calc:
        
        # MDMCFG4 (0x10) wird intern gelesen und sollte 0xD0 zurückgeben (simuliert in Fixture)
        # Die oberen 4 Bits (0xD) werden beibehalten. Die unteren 4 Bits werden auf DRATE_E (0x9) gesetzt.
        # Erwarteter Wert für 0x10: 0xD9
        r10_expected = 0xD0 | drate_e
        r11_expected = drate_m
        
        mock_commands.cc1101_write_init = AsyncMock()
        mock_commands._read_register_value.return_value = "C10 = D0" # Simulate 0xD0 read
        
        await mock_commands.set_datarate(datarate_kbaud)
        
        # Prüfe, dass das Register 0x10 gelesen wurde (durch _read_register_value)
        mock_commands._read_register_value.assert_awaited_with(0x10)
        
        expected_calls = [
            call(command=f"W10{r10_expected:02X}", expect_response=False),
            call(command=f"W11{r11_expected:02X}", expect_response=False),
        ]
        
        mock_commands._send_command.assert_has_calls(expected_calls, any_order=False)
        mock_commands.cc1101_write_init.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_rampl(mock_commands):
    """Testet, dass set_rampl den korrekten W1D Befehl sendet."""
    
    # Rampl Wert, der den Index 42 repräsentieren soll (Index 7)
    rampl_value = 42
    expected_command = "W1D07" # W1D07
    
    mock_commands.cc1101_write_init = AsyncMock()
    
    await mock_commands.set_rampl(rampl_value)

    mock_commands._send_command.assert_awaited_with(command=expected_command, expect_response=False)
    mock_commands.cc1101_write_init.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_sensitivity(mock_commands):
    """Testet, dass set_sensitivity den korrekten W1F Befehl sendet."""
    
    # Sens Wert 16 (repräsentiert '93' im Befehl)
    sens_value = 16
    expected_command = "W1F93" # W1F93
    
    mock_commands.cc1101_write_init = AsyncMock()
    
    await mock_commands.set_sens(sens_value)

    mock_commands._send_command.assert_awaited_with(command=expected_command, expect_response=False)
    mock_commands.cc1101_write_init.assert_awaited_once()

    
@pytest.mark.asyncio
async def test_set_bwidth(mock_commands):
    """Testet, dass set_bwidth den korrekten C101 Befehl sendet (nicht der Spezialfall)."""
    
    # Bandbreite 203 kHz (0xCB)
    bwidth = 203
    expected_command = f"C101{bwidth:02X}" # C101CB
    
    mock_commands.cc1101_write_init = AsyncMock()
    
    await mock_commands.set_bwidth(bwidth)

    mock_commands._send_command.assert_awaited_with(command=expected_command, expect_response=False)
    mock_commands.cc1101_write_init.assert_awaited_once()
    
@pytest.mark.asyncio
async def test_set_bwidth_special_case(mock_commands):
    """Testet den Spezialfall für Bandbreite 102 kHz."""
    
    bwidth = 102
    expected_command = "C10102"
    
    mock_commands.cc1101_write_init = AsyncMock()
    
    await mock_commands.set_bwidth(bwidth)

    mock_commands._send_command.assert_awaited_with(command=expected_command, expect_response=False)
    mock_commands.cc1101_write_init.assert_awaited_once()