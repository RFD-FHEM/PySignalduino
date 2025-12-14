"""
Encapsulates all serial commands for the SIGNALDuino firmware.
"""

from typing import Any, Callable, Optional, Pattern, Awaitable
import re

class SignalduinoCommands:
    """
    Provides methods to construct and send commands to the SIGNALDuino.
    
    This class abstracts the raw serial commands documented in AI_AGENT_COMMANDS.md.
    """

    def __init__(self, send_command_func: Callable[[str, bool, float, Optional[Pattern[str]]], Awaitable[Any]]):
        """
        Initialize with an asynchronous function to send commands.
        
        Args:
            send_command_func: An awaitable callable that accepts (payload, expect_response, timeout, response_pattern)
                               and returns the response (if expected).
        """
        self._send = send_command_func

    # --- System Commands ---

    async def get_version(self, timeout: float = 2.0) -> str:
        """Query firmware version (V)."""
        pattern = re.compile(r"V\s.*SIGNAL(?:duino|ESP|STM).*(?:\s\d\d:\d\d:\d\d)", re.IGNORECASE)
        return await self._send("V", expect_response=True, timeout=timeout, response_pattern=pattern)

    async def get_help(self) -> str:
        """Show help (?)."""
        # This is for internal use/legacy. The MQTT 'cmds' command uses a specific pattern.
        return await self._send("?", expect_response=True, timeout=2.0, response_pattern=None)

    async def get_cmds(self) -> str:
        """Show help/commands (?). Used for MQTT 'cmds' command."""
        pattern = re.compile(r".*")
        return await self._send("?", expect_response=True, timeout=2.0, response_pattern=pattern)
    
    async def get_free_ram(self) -> str:
        """Query free RAM (R)."""
        # Response is typically a number (bytes)
        pattern = re.compile(r"^[0-9]+")
        return await self._send("R", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def get_uptime(self) -> str:
        """Query uptime in seconds (t)."""
        # Response is a number (seconds)
        pattern = re.compile(r"^[0-9]+")
        return await self._send("t", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def ping(self) -> str:
        """Ping device (P)."""
        return await self._send("P", expect_response=True, timeout=2.0, response_pattern=re.compile(r"^OK$"))

    async def get_cc1101_status(self) -> str:
        """Query CC1101 status (s)."""
        return await self._send("s", expect_response=True, timeout=2.0, response_pattern=None)

    async def disable_receiver(self) -> None:
        """Disable reception (XQ)."""
        await self._send("XQ", expect_response=False, timeout=0, response_pattern=None)

    async def enable_receiver(self) -> None:
        """Enable reception (XE)."""
        await self._send("XE", expect_response=False, timeout=0, response_pattern=None)

    async def factory_reset(self) -> str:
        """Factory reset CC1101 and load EEPROM defaults (e)."""
        return await self._send("e", expect_response=True, timeout=5.0, response_pattern=None)

    # --- Configuration Commands ---

    async def get_config(self) -> str:
        """Read configuration (CG)."""
        # Response format: MS=1;MU=1;...
        pattern = re.compile(r"^M[S|N]=.*")
        return await self._send("CG", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def set_decoder_state(self, decoder: str, enabled: bool) -> None:
        """
        Configure decoder (C<CMD><FLAG>).
        
        Args:
            decoder: One of 'MS', 'MU', 'MC', 'Mred', 'AFC', 'WMBus', 'WMBus_T'
                     Internal mapping: S=MS, U=MU, C=MC, R=Mred, A=AFC, W=WMBus, T=WMBus_T
            enabled: True to enable, False to disable
        """
        decoder_map = {
            "MS": "S",
            "MU": "U",
            "MC": "C",
            "Mred": "R",
            "AFC": "A",
            "WMBus": "W",
            "WMBus_T": "T"
        }
        if decoder not in decoder_map:
            raise ValueError(f"Unknown decoder: {decoder}")
        
        cmd_char = decoder_map[decoder]
        flag_char = "E" if enabled else "D"
        command = f"C{cmd_char}{flag_char}"
        await self._send(command, expect_response=False, timeout=0, response_pattern=None)

    async def set_manchester_min_bit_length(self, length: int) -> str:
        """Set MC Min Bit Length (CSmcmbl=<val>)."""
        return await self._send(f"CSmcmbl={length}", expect_response=True, timeout=2.0, response_pattern=None)

    async def set_message_type_enabled(self, message_type: str, enabled: bool) -> None:
        """
        Enable/disable reception for message types (C<FLAG><TYPE>).

        Args:
            message_type: One of 'MS', 'MU', 'MC' (or other 2-letter codes, e.g. 'MN').
                          The second character is used as the type char in the command.
            enabled: True to enable (E), False to disable (D).
        """
        if not message_type or len(message_type) != 2:
             raise ValueError(f"Invalid message_type: {message_type}. Must be a 2-character string (e.g., 'MS').")

        # The command structure seems to be C<E/D><S/U/C/N>, where <S/U/C/N> is the second char of message_type
        cmd_char = message_type # 'S', 'U', 'C', 'N', etc.
        flag_char = "E" if enabled else "D"
        command = f"C{flag_char}{cmd_char}"
        await self._send(command, expect_response=False, timeout=0, response_pattern=None)

    async def get_ccconf(self) -> str:
        """Query CC1101 configuration (C0DnF)."""
        # Response format: C0Dnn=[A-F0-9a-f]+ (e.g., C0D11=0F)
        pattern = re.compile(r"C0Dn11=[A-F0-9a-f]+")
        return await self._send("C0DnF", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def get_ccpatable(self) -> str:
        """Query CC1101 PA Table (C3E)."""
        # Response format: C3E = ...
        pattern = re.compile(r"^C3E\s=\s.*")
        return await self._send("C3E", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def read_cc1101_register(self, register: int) -> str:
        """Read CC1101 register (C<reg>). Register is int, sent as 2-digit hex."""
        reg_hex = f"{register:02X}"
        # Response format: Cnn = vv or ccreg 00: ...
        pattern = re.compile(r"^(?:C[A-Fa-f0-9]{2}\s=\s[0-9A-Fa-f]+$|ccreg 00:)")
        return await self._send(f"C{reg_hex}", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def write_register(self, register: int, value: int) -> str:
        """Write to EEPROM/CC1101 register (W<reg><val>)."""
        reg_hex = f"{register:02X}"
        val_hex = f"{value:02X}"
        return await self._send(f"W{reg_hex}{val_hex}", expect_response=True, timeout=2.0, response_pattern=None)

    async def init_wmbus(self) -> str:
        """Initialize WMBus mode (WS34)."""
        return await self._send("WS34", expect_response=True, timeout=2.0, response_pattern=None)

    async def read_eeprom(self, address: int) -> str:
        """Read EEPROM byte (r<addr>)."""
        addr_hex = f"{address:02X}"
        # Response format: EEPROM <addr> = <val>
        pattern = re.compile(r"EEPROM.*", re.IGNORECASE)
        return await self._send(f"r{addr_hex}", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def read_eeprom_block(self, address: int) -> str:
        """Read EEPROM block (r<addr>n)."""
        addr_hex = f"{address:02X}"
        # Response format: EEPROM <addr> : <val> ...
        pattern = re.compile(r"EEPROM.*", re.IGNORECASE)
        return await self._send(f"r{addr_hex}n", expect_response=True, timeout=2.0, response_pattern=pattern)

    async def set_patable(self, value: str | int) -> str:
        """Write PA Table (x<val>)."""
        if isinstance(value, int):
            val_hex = f"{value:02X}"
        else:
            # Assume it's an already formatted hex string (e.g. 'C0')
            val_hex = value
        return await self._send(f"x{val_hex}", expect_response=True, timeout=2.0, response_pattern=None)

    async def set_bwidth(self, value: int) -> str:
        """Set CC1101 Bandwidth (C10<val>)."""
        val_str = str(value)
        return await self._send(f"C10{val_str}", expect_response=True, timeout=2.0, response_pattern=None)

    async def set_rampl(self, value: int) -> str:
        """Set CC1101 PA_TABLE/ramp length (W1D<val>)."""
        val_str = str(value)
        return await self._send(f"W1D{val_str}", expect_response=True, timeout=2.0, response_pattern=None)

    async def set_sens(self, value: int) -> str:
        """Set CC1101 sensitivity/MCSM0 (W1F<val>)."""
        val_str = str(value)
        return await self._send(f"W1F{val_str}", expect_response=True, timeout=2.0, response_pattern=None)

    # --- Send Commands ---
    # These typically don't expect a response, or the response is just an echo/OK which might be hard to sync with async rx
    
    async def send_combined(self, params: str) -> None:
        """Send Combined (SC...). params should be the full string after SC, e.g. ';R=4...'"""
        await self._send(f"SC{params}", expect_response=False, timeout=0, response_pattern=None)

    async def send_manchester(self, params: str) -> None:
        """Send Manchester (SM...). params should be the full string after SM."""
        await self._send(f"SM{params}", expect_response=False, timeout=0, response_pattern=None)

    async def send_raw(self, params: str) -> None:
        """Send Raw (SR...). params should be the full string after SR."""
        await self._send(f"SR{params}", expect_response=False, timeout=0, response_pattern=None)
    
    async def send_raw_message(self, message: str) -> str:
        """Send the raw message/command directly as payload. Expects a response."""
        # The 'rawmsg' MQTT command sends the content of the payload directly as a command.
        # It is assumed that it will get a response which is why we expect one.
        # No specific pattern can be given here, rely on the default response matchers.
        return await self._send(message, expect_response=True, timeout=2.0, response_pattern=None)

    async def send_xfsk(self, params: str) -> None:
        """Send xFSK (SN...). params should be the full string after SN."""
        await self._send(f"SN{params}", expect_response=False, timeout=0, response_pattern=None)

    async def send_message(self, message: str) -> None:
        """
        Sends a pre-encoded message (P..., S..., e.g. from an FHEM set command).
        This command is sent without any additional prefix.
        """
        await self._send(message, expect_response=False, timeout=0, response_pattern=None)
