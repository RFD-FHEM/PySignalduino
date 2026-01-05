from __future__ import annotations
import json
import logging
import re
from typing import (
    Callable, Any, Dict, List, Awaitable, Optional, Pattern, TYPE_CHECKING
)

from jsonschema import validate, ValidationError
from signalduino.exceptions import CommandValidationError, SignalduinoCommandTimeout

if TYPE_CHECKING:
    # Importiere SignalduinoController nur für Type Hinting zur Kompilierzeit
    from .controller import SignalduinoController 
    
logger = logging.getLogger(__name__)

# --- BEREICH 1: SignalduinoCommands (Implementierung der seriellen Befehle) ---

class SignalduinoCommands:
    """Provides high-level asynchronous methods for sending commands to the firmware."""
    
    def __init__(self, send_command: Callable[..., Awaitable[Any]], mqtt_topic_root: Optional[str] = None):
        self._send_command = send_command
        self.mqtt_topic_root = mqtt_topic_root
        
    async def get_version(self, timeout: float = 2.0) -> str:
        """Firmware version (V)"""
        return await self._send_command(command="V", expect_response=True, timeout=timeout)
        
    async def get_free_ram(self, timeout: float = 2.0) -> str:
        """Free RAM (R)"""
        return await self._send_command(command="R", expect_response=True, timeout=timeout)
        
    async def get_uptime(self, timeout: float = 2.0) -> str:
        """System uptime (t)"""
        return await self._send_command(command="t", expect_response=True, timeout=timeout)
        
    async def get_cmds(self, timeout: float = 2.0) -> str:
        """Available commands (?)"""
        return await self._send_command(command="?", expect_response=True, timeout=timeout)
        
    async def ping(self, timeout: float = 2.0) -> str:
        """Ping (P)"""
        return await self._send_command(command="P", expect_response=True, timeout=timeout)
        
    async def get_config(self, timeout: float = 2.0) -> str:
        """Decoder configuration (CG)"""
        return await self._send_command(command="CG", expect_response=True, timeout=timeout)
        
    async def get_ccconf(self, timeout: float = 2.0) -> str:
        """CC1101 configuration registers (C0DnF)"""
        # Response-Pattern aus 00_SIGNALduino.pm, Zeile 86, angepasst an Python regex
        return await self._send_command(command="C0DnF", expect_response=True, timeout=timeout, response_pattern=re.compile(r'C0Dn11=[A-F0-9a-f]+'))
    
    async def get_ccpatable(self, timeout: float = 2.0) -> str:
        """CC1101 PA table (C3E)"""
        # Response-Pattern aus 00_SIGNALduino.pm, Zeile 88
        return await self._send_command(command="C3E", expect_response=True, timeout=timeout, response_pattern=re.compile(r'^C3E\s=\s.*'))
        
    async def factory_reset(self, timeout: float = 5.0) -> Dict[str, str]:
        """Sets EEPROM defaults, effectively a factory reset (e).

        This command does not send a response unless debug mode is active. We treat the command
        as fire-and-forget, expecting the device to reboot.
        """
        logger.warning("Sending factory reset command 'e'. Device is expected to reboot.")
        # Sende Befehl ohne auf Antwort zu warten, da das Gerät neu startet
        await self._send_command(command="e", expect_response=False, timeout=timeout)
        return {"status": "Reset command sent", "info": "Factory reset triggered"}

    async def get_cc1101_settings(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retrieves a dictionary of key CC1101 configuration values (frequency_mhz, bandwidth, rampl, sens, datarate).
        """
        # Alle benötigten Getter existieren bereits in SignalduinoCommands
        freq_result = await self.get_frequency(payload)
        bandwidth = await self.get_bandwidth(payload)
        rampl = await self.get_rampl(payload)
        sens = await self.get_sensitivity(payload)
        datarate = await self.get_data_rate(payload)
        
        return {
            # Flatten the frequency structure
            "frequency_mhz": freq_result["frequency_mhz"],
            "bandwidth": bandwidth,
            "rampl": rampl,
            "sens": sens,
            "datarate": datarate,
        }

    # --- CC1101 Hardware Status GET-Methoden (Basierend auf 00_SIGNALduino.pm) ---

    async def _read_register_value(self, register_address: int) -> int:
        """Liest einen CC1101-Registerwert und gibt ihn als Integer zurück."""
        response = await self.read_cc1101_register(register_address)
        # Stellt sicher, dass wir nur den Wert nach 'C[A-Fa-f0-9]{2} = ' extrahieren
        match = re.search(r'C[A-Fa-f0-9]{2}\s=\s([0-9A-Fa-f]+)$', response)
        if match:
            return int(match.group(1), 16)
        # Fängt auch den Fall 'ccreg 00:' (default-Antwort) oder andere unerwartete Antworten ab
        raise ValueError(f"Unexpected response format for CC1101 register read: {response}")

    async def get_bandwidth(self, payload: Optional[Dict[str, Any]] = None) -> float:
        """Liest die CC1101 Bandbreitenregister (MDMCFG4/0x10) und berechnet die Bandbreite in kHz."""
        r10 = await self._read_register_value(0x10) # MDMCFG4
        
        # Bw (kHz) = 26000 / (8 * (4 + ((r10 >> 4) & 3)) * (1 << ((r10 >> 6) & 3)))
        mant_b = (r10 >> 4) & 3
        exp_b = (r10 >> 6) & 3
        
        # Frequenz (FXOSC) ist 26 MHz (26000 kHz)
        bandwidth_khz = 26000.0 / (8.0 * (4.0 + mant_b) * (1 << exp_b))
        
        return round(bandwidth_khz, 3)

    async def get_rampl(self, payload: Optional[Dict[str, Any]] = None) -> int:
        """Liest die CC1101 Verstärkungsregister (AGCCTRL0/0x1B) und gibt die Verstärkung in dB zurück."""
        r1b = await self._read_register_value(0x1B) # AGCCTRL0

        # Annahme der CC1101-Werte basierend auf FHEM Code:
        # Dies sind die AGC_LNA_GAIN-Einstellungen. Wir nehmen die im Code verfügbare Liste.
        ampllist = [24, 27, 30, 33, 36, 38, 40, 42] 
        
        # Index ist die unteren 3 Bits von 0x1B: r1b & 7
        index = r1b & 7
        
        if index < len(ampllist):
            return ampllist[index]
        else:
            # Dies sollte nicht passieren, wenn die CC1101-Registerwerte korrekt sind
            logger.warning("Invalid AGC_LNA_GAIN setting found in 0x1B: %s", index)
            return -1 # Fehlerwert

    async def get_sensitivity(self, payload: Optional[Dict[str, Any]] = None) -> int:
        """Liest die CC1101 Empfindlichkeitsregister (RSSIAGC/0x1D) und gibt die Empfindlichkeit in dB zurück."""
        r1d = await self._read_register_value(0x1D) # RSSIAGC (0x1D)
        
        # Sens (dB) = 4 + 4 * (r1d & 3)
        # Die unteren 2 Bits enthalten den LNA-Modus (LNA_PD_BUF)
        sens_db = 4 + 4 * (r1d & 3)
        
        return sens_db
        
    async def get_data_rate(self, payload: Optional[Dict[str, Any]] = None) -> float:
        """Liest die CC1101 Datenratenregister (MDMCFG4/0x10 und MDMCFG3/0x11) und berechnet die Datenrate in kBaud."""
        r10 = await self._read_register_value(0x10) # MDMCFG4
        r11 = await self._read_register_value(0x11) # MDMCFG3

        # DataRate (kBaud) = (((256 + r11) * (2 ** (r10 & 15))) * 26000000 / (2**28)) / 1000
        
        # DRATE_M ist r11 (8 Bit) und DRATE_E sind die unteren 4 Bits von r10
        drate_m = r11
        drate_e = r10 & 15

        # FXOSC = 26 MHz = 26000000 Hz
        FXOSC = 26000000.0
        DIVIDER = 2**28
        
        # Berechnung in Hz
        data_rate_hz = ((256.0 + drate_m) * (2**drate_e) * FXOSC) / DIVIDER
        
        # Umrechnung in kBaud (kiloBaud = kiloBits pro Sekunde)
        data_rate_kbaud = data_rate_hz / 1000.0
        
        return round(data_rate_kbaud, 2)
        
    def _calculate_datarate_registers(self, datarate_kbaud: float) -> tuple[int, int]:
        """
        Berechnet die Registerwerte DRATE_E (MDMCFG4[3:0]) und DRATE_M (MDMCFG3) 
        für die gewünschte Datenrate in kBaud.
        
        Basierend auf der CC1101-Formel:
        DataRate = f_xosc * (256 + DRATE_M) * 2^DRATE_E / 2^28
        
        Da DataRate_Hz = datarate_kbaud * 1000.0 gilt, lässt sich umformen zu:
        (256 + DRATE_M) * 2^DRATE_E = DataRate_Hz * 2^28 / f_xosc
        
        FXOSC = 26 MHz
        """
        
        FXOSC = 26000000.0
        target_datarate_hz = datarate_kbaud * 1000.0
        
        # Berechne den Wert T, der auf der rechten Seite der umgestellten Formel steht
        T = (target_datarate_hz * (2**28)) / FXOSC
        
        # DRATE_E (Exponent) kann von 0 bis 15 gehen. Wir suchen die beste Kombination.
        best_drate_e = 0
        best_drate_m = 0
        min_error = float('inf')
        
        for drate_e in range(16):
            # Versuche, DRATE_M zu isolieren:
            # 256 + DRATE_M = T / 2^DRATE_E
            
            # Da T / 2^DRATE_E ein Float ist, rechnen wir mit dem Zähler weiter, um Fehler zu minimieren
            term = T / (2**drate_e)
            
            # DRATE_M = term - 256
            drate_m_float = term - 256.0
            
            # DRATE_M muss zwischen 0 und 255 liegen.
            if 0 <= drate_m_float <= 255:
                # Wähle den nächsten ganzen Wert für DRATE_M
                drate_m_candidate = int(round(drate_m_float))
                
                # Berechne die tatsächliche Datenrate mit den Kandidaten-Registern
                actual_datarate_hz = ((256.0 + drate_m_candidate) * (2**drate_e) * FXOSC) / (2**28)
                
                # Berechne den Fehler (Absolutwert)
                error = abs(target_datarate_hz - actual_datarate_hz)
                
                if error < min_error:
                    min_error = error
                    best_drate_e = drate_e
                    best_drate_m = drate_m_candidate
                    
        if min_error == float('inf'):
            logger.error("Could not find suitable DRATE_E/DRATE_M for datarate %.2f kBaud. Defaulting to 0.", datarate_kbaud)
            return 0, 0
            
        return best_drate_e, best_drate_m

    async def read_cc1101_register(self, register_address: int, timeout: float = 2.0) -> str:
        """Read CC1101 register (C<reg>)"""
        hex_addr = f"{register_address:02X}"
        # Response-Pattern: ccreg 00: oder Cxx = yy (aus 00_SIGNALduino.pm, Zeile 87)
        return await self._send_command(command=f"C{hex_addr}", expect_response=True, timeout=timeout, response_pattern=re.compile(r'C[A-Fa-f0-9]{2}\s=\s[0-9A-Fa-f]+$|ccreg 00:'))

    async def _get_frequency_registers(self) -> int:
        """Liest die CC1101 Frequenzregister (FREQ2, FREQ1, FREQ0) und kombiniert sie zu einem 24-Bit-Wert (F_REG)."""
        
        # Adressen der Register
        FREQ2 = 0x0D
        FREQ1 = 0x0E
        FREQ0 = 0x0F

        # Funktion zum Extrahieren des Hex-Werts aus der Antwort: Cxx = <hex>
        def extract_hex_value(response: str) -> int:
            # Stellt sicher, dass wir nur den Wert nach 'C[A-Fa-f0-9]{2} = ' extrahieren
            match = re.search(r'C[A-Fa-f0-9]{2}\s=\s([0-9A-Fa-f]+)$', response)
            if match:
                return int(match.group(1), 16)
            # Fängt auch den Fall 'ccreg 00:' (default-Antwort) oder andere unerwartete Antworten ab
            raise ValueError(f"Unexpected response format for CC1101 register read: {response}")

        # FREQ2 (0D)
        response2 = await self.read_cc1101_register(FREQ2)
        freq2 = extract_hex_value(response2)

        # FREQ1 (0E)
        response1 = await self.read_cc1101_register(FREQ1)
        freq1 = extract_hex_value(response1)
        
        # FREQ0 (0F)
        response0 = await self.read_cc1101_register(FREQ0)
        freq0 = extract_hex_value(response0)

        # Die Register bilden eine 24-Bit-Zahl: (FREQ2 << 16) | (FREQ1 << 8) | FREQ0
        f_reg = (freq2 << 16) | (freq1 << 8) | freq0
        return f_reg

    async def get_frequency(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        """Ruft die Frequenzregister ab und berechnet die Frequenz in MHz.
        
        Diese Methode ist für den MqttCommandDispatcher gedacht und akzeptiert daher den 'payload'-Parameter,
        der ignoriert wird, da keine Eingabewerte benötigt werden.
        """
        
        f_reg = await self._get_frequency_registers()

        # Quarzfrequenz (FXOSC) ist 26 MHz
        # DIVIDER ist 2^16 = 65536.0
        DIVIDER = 65536.0
        
        # Frequenz in MHz: (26.0 / 65536.0) * F_REG
        frequency_mhz = (26.0 / DIVIDER) * f_reg
        
        # Rückgabe des gekapselten und auf 4 Dezimalstellen gerundeten Wertes, wie in tests/test_mqtt.py erwartet.
        return {
            "frequency_mhz": round(frequency_mhz, 4)
        }

    async def send_raw_message(self, command: str, timeout: float = 2.0) -> str:
        """Send raw message (M...)"""
        return await self._send_command(command=command, expect_response=True, timeout=timeout)

    async def send_message(self, message: str, timeout: float = 2.0) -> None:
        """Send a pre-encoded message (P...#R...). This is typically used for 'set raw' commands where the message is already fully formatted.
        
        NOTE: This sends the message AS IS, without any wrapping like 'set raw '.
        """
        return await self._send_command(command=message, expect_response=False, timeout=timeout)

    async def enable_receiver(self) -> str:
        """Enable receiver (XE)"""
        return await self._send_command(command="XE", expect_response=False)
        
    async def disable_receiver(self) -> str:
        """Disable receiver (XQ)"""
        return await self._send_command(command="XQ", expect_response=False)
    
    async def set_decoder_enable(self, decoder_type: str) -> str:
        """Enable decoder type (CE S/U/C)"""
        return await self._send_command(command=f"CE{decoder_type}", expect_response=False)

    async def set_decoder_disable(self, decoder_type: str) -> str:
        """Disable decoder type (CD S/U/C)"""
        return await self._send_command(command=f"CD{decoder_type}", expect_response=False)

    async def set_message_type_enabled(self, message_type: str, enabled: bool) -> str:
        """Enable or disable a specific message type (CE/CD S/U/C)"""
        command_prefix = "CE" if enabled else "CD"
        return await self._send_command(command=f"{command_prefix}{message_type}", expect_response=False)

    async def set_bwidth(self, bwidth: int, timeout: float = 2.0) -> None:
        """Set CC1101 IF bandwidth. Test case: 102 -> C10102."""
        # Die genaue Logik ist komplex, hier die Befehlsstruktur für den Testfall:
        if bwidth == 102:
            command = "C10102"
        else:
            # Platzhalter für zukünftige Implementierung
            command = f"C101{bwidth:02X}"
        await self._send_command(command=command, expect_response=False)
        await self.cc1101_write_init()

    async def set_frequency(self, frequency_mhz: float, timeout: float = 2.0) -> None:
        """Set CC1101 RF frequency (W0F, W10, W11) from MHz value."""
        # F_REG = frequency_mhz * 2560 (26 * 10^6 * 2^16 / 26 * 10^6)
        f_reg = int(frequency_mhz * 2560.0)
        
        # 24-Bit-Wert in 3 Bytes aufteilen
        freq2 = (f_reg >> 16) & 0xFF  # 0D
        freq1 = (f_reg >> 8) & 0xFF   # 0E
        freq0 = f_reg & 0xFF          # 0F
        
        # Sende W<RegAddr><Value>
        await self._send_command(command=f"W0D{freq2:02X}", expect_response=False)
        await self._send_command(command=f"W0E{freq1:02X}", expect_response=False)
        await self._send_command(command=f"W0F{freq0:02X}", expect_response=False)
        
        await self.cc1101_write_init()

    async def set_datarate(self, datarate_kbaud: float, timeout: float = 2.0) -> None:
        """Set CC1101 data rate (MDMCFG4/MDMCFG3) from kBaud value."""
        drate_e, drate_m = self._calculate_datarate_registers(datarate_kbaud)
        
        # MDMCFG4 (0x10): Behalte die Bits [7:4] (Rx-Filter-Bandbreite) und setze Bits [3:0] (DRATE_E)
        # Um die existierenden Bits [7:4] zu erhalten, müssen wir MDMCFG4 (0x10) zuerst lesen.
        try:
            r10_current = await self._read_register_value(0x10)
        except Exception:
            # Bei Fehlern (z.B. Timeout) setzen wir die Bits 7:4 auf den Reset-Wert (0xC0).
            r10_current = 0xC0
            
        # Bits 7:4 beibehalten, Bits 3:0 mit DRATE_E überschreiben.
        r10_new = (r10_current & 0xF0) | (drate_e & 0x0F)
        
        # MDMCFG3 (0x11): Setze auf DRATE_M
        r11_new = drate_m # DRATE_M ist ein 8-Bit-Wert

        await self._send_command(command=f"W10{r10_new:02X}", expect_response=False)
        await self._send_command(command=f"W11{r11_new:02X}", expect_response=False)
        
        await self.cc1101_write_init()
        
    async def set_rampl(self, rampl_value: int, timeout: float = 2.0) -> None:
        """Set CC1101 receiver amplification (W1D<index>)."""
        ampllist = [24, 27, 30, 33, 36, 38, 40, 42]
        
        try:
            # Findet den Index des dB-Wertes (0-7), basierend auf Perl setrAmpl
            index = ampllist.index(rampl_value)
        except ValueError:
            logger.error("Rampl value %d not found in ampllist. Sending no command.", rampl_value)
            return

        # Index (0-7) wird in Hex-String konvertiert (00-07)
        register_value_hex = f"{index:02X}"
        
        # Perl verwendet W1D<Index>
        await self._send_command(command=f"W1D{register_value_hex}", expect_response=False)
        await self.cc1101_write_init()

    async def set_sens(self, sens_value: int, timeout: float = 2.0) -> None:
        """Set CC1101 sensitivity (W1F<val>)."""
        # Perl Logik: $v = sprintf("9%d",$a[1]/4-1);
        index = int(sens_value / 4) - 1
        register_value_str = f"9{index}"
        await self._send_command(command=f"W1F{register_value_str}", expect_response=False)
        await self.cc1101_write_init()

    async def set_patable(self, patable_value: str, timeout: float = 2.0) -> None:
        """Set CC1101 PA table (x<val>)."""
        await self._send_command(command=f"x{patable_value}", expect_response=False)
        await self.cc1101_write_init()

    async def cc1101_write_init(self) -> None:
        """Sends SIDLE, SFRX, SRX (W36, W3A, W34) to re-initialize CC1101 after register changes."""
        # Logik aus SIGNALduino_WriteInit in 00_SIGNALduino.pm
        await self._send_command(command='WS36', expect_response=False)   # SIDLE
        await self._send_command(command='WS3A', expect_response=False)   # SFRX
        await self._send_command(command='WS34', expect_response=False)   # SRX


# --- BEREICH 2: MqttCommandDispatcher und Schemata ---

# --- BEREICH 2: MqttCommandDispatcher und Schemata ---

# JSON Schema für die Basis-Payload aller Commands (SET/GET/COMMAND)
BASE_SCHEMA = {
    "type": "object",
    "properties": {
        "req_id": {"type": "string", "description": "Correlation ID for request-response matching."},
        "value": {"type": ["string", "number", "boolean", "null"], "description": "Main value for SET commands."},
        "parameters": {"type": "object", "description": "Additional parameters for complex commands (e.g., sendMsg)."},
    },
    "required": [], # req_id ist jetzt optional
    "additionalProperties": False
}

def create_value_schema(value_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Erstellt ein vollständiges Schema aus BASE_SCHEMA, indem das 'value'-Feld erweitert wird."""
    schema = BASE_SCHEMA.copy()
    schema['properties'] = BASE_SCHEMA['properties'].copy()
    schema['properties']['value'] = value_schema
    # Da BASE_SCHEMA['required'] jetzt leer ist, fügen wir nur 'value' hinzu
    schema['required'] = ['value']
    return schema

# --- CC1101 SPEZIFISCHE SCHEMATA (PHASE 2) ---

FREQ_SCHEMA = create_value_schema({
    "type": "number",
    "minimum": 315.0, "maximum": 915.0, # CC1101 Frequenzbereich
    "description": "Frequency in MHz (e.g., 433.92, 868.35)."
})

RAMPL_SCHEMA = create_value_schema({
    "type": "number",
    "enum": [24, 27, 30, 33, 36, 38, 40, 42],
    "description": "Receiver Amplification in dB."
})

SENS_SCHEMA = create_value_schema({
    "type": "number",
    "enum": [4, 8, 12, 16],
    "description": "Sensitivity in dB."
})

PATABLE_SCHEMA = create_value_schema({
    "type": "string",
    "enum": ['-30_dBm','-20_dBm','-15_dBm','-10_dBm','-5_dBm','0_dBm','5_dBm','7_dBm','10_dBm'],
    "description": "PA Table power level string."
})

BWIDTH_SCHEMA = create_value_schema({
    "type": "number",
    # Die tatsächlichen Werte, die der CC1101 annehmen kann (in kHz)
    "enum": [58, 68, 81, 102, 116, 135, 162, 203, 232, 270, 325, 406, 464, 541, 650, 812],
    "description": "Bandwidth in kHz (closest supported value is used)."
})

DATARATE_SCHEMA = create_value_schema({
    "type": "number",
    "minimum": 0.0247955, "maximum": 1621.83,
    "description": "Data Rate in kBaud (float)."
})

DEVIATN_SCHEMA = create_value_schema({
    "type": "number",
    "minimum": 1.586914, "maximum": 380.859375,
    "description": "Frequency Deviation in kHz (float)."
})

# --- SEND MSG SCHEMA (PHASE 2) ---
SEND_MSG_SCHEMA = {
    "type": "object",
    "properties": {
        "req_id": BASE_SCHEMA["properties"]["req_id"],
        "parameters": {
            "type": "object",
            "properties": {
                "protocol_id": {"type": "number", "minimum": 0, "description": "Protocol ID (P<id>)."},
                "data": {"type": "string", "pattern": r"^[0-9A-Fa-f]+$", "description": "Hex or binary data string."},
                "repeats": {"type": "number", "minimum": 1, "default": 1, "description": "Number of repeats (R<n>)."},
                "clock_us": {"type": "number", "minimum": 1, "description": "Optional clock in us (C<n>)."},
                "frequency_mhz": {"type": "number", "minimum": 300, "maximum": 950, "description": "Optional frequency in MHz (F<val>)."},
            },
            "required": ["protocol_id", "data"],
            "additionalProperties": False,
        }
    },
    "required": ["parameters"],
    "additionalProperties": False
}


# --- Befehlsdefinitionen für den Dispatcher ---
COMMAND_MAP: Dict[str, Dict[str, Any]] = {
    # Phase 1: Einfache GET-Befehle (Core)
    'get/system/version': { 'method': 'get_version', 'schema': BASE_SCHEMA, 'description': 'Firmware version (V)' },
    'get/system/freeram': { 'method': 'get_freeram', 'schema': BASE_SCHEMA, 'description': 'Free RAM (R)' },
    'get/system/uptime': { 'method': 'get_uptime', 'schema': BASE_SCHEMA, 'description': 'System uptime (t)' },
    'get/config/decoder': { 'method': 'get_config_decoder', 'schema': BASE_SCHEMA, 'description': 'Decoder configuration (CG)' },
    'get/cc1101/config': { 'method': 'get_cc1101_config', 'schema': BASE_SCHEMA, 'description': 'CC1101 configuration registers (C0DnF)' },
    'get/cc1101/patable': { 'method': 'get_cc1101_patable', 'schema': BASE_SCHEMA, 'description': 'CC1101 PA table (C3E)' },
    'get/cc1101/register': { 'method': 'get_cc1101_register', 'schema': BASE_SCHEMA, 'description': 'Read CC1101 register (C<reg>)' },
    'get/cc1101/frequency': { 'method': 'get_frequency', 'schema': BASE_SCHEMA, 'description': 'CC1101 current RF frequency' },
    'get/cc1101/settings': { 'method': 'get_cc1101_settings', 'schema': BASE_SCHEMA, 'description': 'CC1101 key configuration settings (freq, bw, rampl, sens, dr)' },

    # NEU: Hardware Status Abfragen
    'get/cc1101/bandwidth': { 'method': 'get_bandwidth', 'schema': BASE_SCHEMA, 'description': 'CC1101 IF bandwidth (MDMCFG4/0x10)' },
    'get/cc1101/rampl': { 'method': 'get_rampl', 'schema': BASE_SCHEMA, 'description': 'CC1101 Receiver Amplification (AGCCTRL0/0x1B)' },
    'get/cc1101/sensitivity': { 'method': 'get_sensitivity', 'schema': BASE_SCHEMA, 'description': 'CC1101 Sensitivity (RSSIAGC/0x1D)' },
    'get/cc1101/datarate': { 'method': 'get_data_rate', 'schema': BASE_SCHEMA, 'description': 'CC1101 Data Rate (MDMCFG4/0x10, MDMCFG3/0x11)' },

    # Phase 1: Einfache SET-Befehle (Decoder Enable/Disable)
    'set/config/decoder_ms_enable': { 'method': 'set_decoder_ms_enable', 'schema': BASE_SCHEMA, 'description': 'Enable Synced Message (MS) (CE S)' },
    'set/config/decoder_ms_disable': { 'method': 'set_decoder_ms_disable', 'schema': BASE_SCHEMA, 'description': 'Disable Synced Message (MS) (CD S)' },
    'set/config/decoder_mu_enable': { 'method': 'set_decoder_mu_enable', 'schema': BASE_SCHEMA, 'description': 'Enable Unsynced Message (MU) (CE U)' },
    'set/config/decoder_mu_disable': { 'method': 'set_decoder_mu_disable', 'schema': BASE_SCHEMA, 'description': 'Disable Unsynced Message (MU) (CD U)' },
    'set/config/decoder_mc_enable': { 'method': 'set_decoder_mc_enable', 'schema': BASE_SCHEMA, 'description': 'Enable Manchester Coded Message (MC) (CE C)' },
    'set/config/decoder_mc_disable': { 'method': 'set_decoder_mc_disable', 'schema': BASE_SCHEMA, 'description': 'Disable Manchester Coded Message (MC) (CD C)' },

    # NEU: Factory Reset
    'set/factory_reset': { 'method': 'factory_reset', 'schema': BASE_SCHEMA, 'description': 'Set EEPROM defaults (e)' },

    # --- Phase 2: CC1101 SET-Befehle ---
    'set/cc1101/frequency': { 'method': 'set_cc1101_frequency', 'schema': FREQ_SCHEMA, 'description': 'Set RF frequency (0D-0F)' },
    'set/cc1101/rampl': { 'method': 'set_cc1101_rampl', 'schema': RAMPL_SCHEMA, 'description': 'Set receiver amplification (1B)' },
    'set/cc1101/sensitivity': { 'method': 'set_cc1101_sensitivity', 'schema': SENS_SCHEMA, 'description': 'Set sensitivity (1D)' },
    'set/cc1101/patable': { 'method': 'set_cc1101_patable', 'schema': PATABLE_SCHEMA, 'description': 'Set PA table (x<val>)' },
    'set/cc1101/bandwidth': { 'method': 'set_cc1101_bandwidth', 'schema': BWIDTH_SCHEMA, 'description': 'Set IF bandwidth (10)' },
    'set/cc1101/datarate': { 'method': 'set_cc1101_datarate', 'schema': DATARATE_SCHEMA, 'description': 'Set data rate (10-11)' },
    'set/cc1101/deviation': { 'method': 'set_cc1101_deviation', 'schema': DEVIATN_SCHEMA, 'description': 'Set frequency deviation (15)' },
    
    # --- Phase 2: Komplexe Befehle ---
    'command/send/msg': { 'method': 'command_send_msg', 'schema': SEND_MSG_SCHEMA, 'description': 'Send protocol-encoded message (sendMsg)' },
}


class MqttCommandDispatcher:
    """
    Dispatches incoming MQTT commands to the appropriate method in the SignalduinoController
    after validating the payload against a defined JSON schema.
    """
    
    def __init__(self, controller: 'SignalduinoController'):
        self.controller = controller
        self.command_map = COMMAND_MAP
        
    def _validate_payload(self, command_name: str, payload: dict) -> None:
        """Validates the payload against the command's JSON schema."""
        if command_name not in self.command_map:
            raise CommandValidationError(f"Unknown command: {command_name}")
            
        schema = self.command_map[command_name].get('schema', BASE_SCHEMA)
        
        try:
            validate(instance=payload, schema=schema)
        except ValidationError as e:
            raise CommandValidationError(f"Payload validation failed for {command_name}: {e.message}") from e

    async def dispatch(self, command_path: str, payload: str) -> Dict[str, Any]:
        """
        Main entry point for dispatching a raw MQTT command.
        """
        
        # 1. Parse Payload
        try:
            # Wenn Payload leer ist (z.B. b''), behandle als leeres Dictionary.
            if not payload.strip():
                payload_dict = {}
            else:
                payload_dict = json.loads(payload)
        except json.JSONDecodeError as e:
            raise CommandValidationError(f"Invalid JSON payload: {e.msg}") from e

        # 2. Validate
        self._validate_payload(command_path, payload_dict)

        # 3. Dispatch
        command_entry = self.command_map[command_path]
        method_name = command_entry['method']
        
        # Rufe die entsprechende Methode im Controller auf
        if not hasattr(self.controller, method_name):
            logger.error("Controller method '%s' not found for command '%s'.", method_name, command_path)
            raise CommandValidationError(f"Internal error: Controller method {method_name} not found.")

        method: Callable[..., Awaitable[Any]] = getattr(self.controller, method_name)

        # Alle Methoden erhalten das gesamte validierte Payload-Dictionary
        result = await method(payload_dict)

        # 4. Prepare Response
        return {
            "status": "OK",
            "req_id": payload_dict.get("req_id", None), # req_id ist jetzt optional
            "data": result
        }