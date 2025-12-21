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
    
    def __init__(self, send_command: Callable[..., Awaitable[Any]]):
        self._send_command = send_command
        
    async def get_version(self, timeout: float = 2.0) -> str:
        """Firmware version (V)"""
        return await self._send_command(payload="V", expect_response=True, timeout=timeout)
        
    async def get_free_ram(self, timeout: float = 2.0) -> str:
        """Free RAM (R)"""
        return await self._send_command(payload="R", expect_response=True, timeout=timeout)
        
    async def get_uptime(self, timeout: float = 2.0) -> str:
        """System uptime (t)"""
        return await self._send_command(payload="t", expect_response=True, timeout=timeout)
        
    async def get_cmds(self, timeout: float = 2.0) -> str:
        """Available commands (?)"""
        return await self._send_command(payload="?", expect_response=True, timeout=timeout)
        
    async def ping(self, timeout: float = 2.0) -> str:
        """Ping (P)"""
        return await self._send_command(payload="P", expect_response=True, timeout=timeout)
        
    async def get_config(self, timeout: float = 2.0) -> str:
        """Decoder configuration (CG)"""
        return await self._send_command(payload="CG", expect_response=True, timeout=timeout)
        
    async def get_ccconf(self, timeout: float = 2.0) -> str:
        """CC1101 configuration registers (C0DnF)"""
        # Response-Pattern aus 00_SIGNALduino.pm, Zeile 86, angepasst an Python regex
        return await self._send_command(payload="C0DnF", expect_response=True, timeout=timeout, response_pattern=re.compile(r'C0Dn11=[A-F0-9a-f]+'))
    
    async def get_ccpatable(self, timeout: float = 2.0) -> str:
        """CC1101 PA table (C3E)"""
        # Response-Pattern aus 00_SIGNALduino.pm, Zeile 88
        return await self._send_command(payload="C3E", expect_response=True, timeout=timeout, response_pattern=re.compile(r'^C3E\s=\s.*'))
        
    async def read_cc1101_register(self, register_address: int, timeout: float = 2.0) -> str:
        """Read CC1101 register (C<reg>)"""
        hex_addr = f"{register_address:02X}"
        # Response-Pattern: ccreg 00: oder Cxx = yy (aus 00_SIGNALduino.pm, Zeile 87)
        return await self._send_command(payload=f"C{hex_addr}", expect_response=True, timeout=timeout, response_pattern=re.compile(r'C[A-Fa-f0-9]{2}\s=\s[0-9A-Fa-f]+$|ccreg 00:'))

    async def send_raw_message(self, raw_message: str, timeout: float = 2.0) -> str:
        """Send raw message (M...)"""
        return await self._send_command(payload=raw_message, expect_response=True, timeout=timeout)

    async def enable_receiver(self) -> str:
        """Enable receiver (XE)"""
        return await self._send_command(payload="XE", expect_response=False)
        
    async def disable_receiver(self) -> str:
        """Disable receiver (XQ)"""
        return await self._send_command(payload="XQ", expect_response=False)
    
    async def set_decoder_enable(self, decoder_type: str) -> str:
        """Enable decoder type (CE S/U/C)"""
        return await self._send_command(payload=f"CE{decoder_type}", expect_response=False)

    async def set_decoder_disable(self, decoder_type: str) -> str:
        """Disable decoder type (CD S/U/C)"""
        return await self._send_command(payload=f"CD{decoder_type}", expect_response=False)

    async def cc1101_write_init(self) -> None:
        """Sends SIDLE, SFRX, SRX (W36, W3A, W34) to re-initialize CC1101 after register changes."""
        # Logik aus SIGNALduino_WriteInit in 00_SIGNALduino.pm
        await self._send_command(payload='WS36', expect_response=False)   # SIDLE
        await self._send_command(payload='WS3A', expect_response=False)   # SFRX
        await self._send_command(payload='WS34', expect_response=False)   # SRX


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
    "required": ["req_id"],
    "additionalProperties": False
}

def create_value_schema(value_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Erstellt ein vollständiges Schema aus BASE_SCHEMA, indem das 'value'-Feld erweitert wird."""
    schema = BASE_SCHEMA.copy()
    schema['properties'] = BASE_SCHEMA['properties'].copy()
    schema['properties']['value'] = value_schema
    schema['required'].append('value')
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
    "required": ["req_id", "parameters"],
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

    # Phase 1: Einfache SET-Befehle (Decoder Enable/Disable)
    'set/config/decoder_ms_enable': { 'method': 'set_decoder_ms_enable', 'schema': BASE_SCHEMA, 'description': 'Enable Synced Message (MS) (CE S)' },
    'set/config/decoder_ms_disable': { 'method': 'set_decoder_ms_disable', 'schema': BASE_SCHEMA, 'description': 'Disable Synced Message (MS) (CD S)' },
    'set/config/decoder_mu_enable': { 'method': 'set_decoder_mu_enable', 'schema': BASE_SCHEMA, 'description': 'Enable Unsynced Message (MU) (CE U)' },
    'set/config/decoder_mu_disable': { 'method': 'set_decoder_mu_disable', 'schema': BASE_SCHEMA, 'description': 'Disable Unsynced Message (MU) (CD U)' },
    'set/config/decoder_mc_enable': { 'method': 'set_decoder_mc_enable', 'schema': BASE_SCHEMA, 'description': 'Enable Manchester Coded Message (MC) (CE C)' },
    'set/config/decoder_mc_disable': { 'method': 'set_decoder_mc_disable', 'schema': BASE_SCHEMA, 'description': 'Disable Manchester Coded Message (MC) (CD C)' },

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
            "req_id": payload_dict["req_id"],
            "data": result
        }
