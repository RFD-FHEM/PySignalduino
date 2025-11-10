"""
Manchester encoding/decoding and protocol-specific signal handlers.

This module contains a mixin class with Manchester-format signal processing
methods. Manchester encoding is used by various radio frequency protocols
for robust signal transmission.

The mcBit2* methods are output handlers that convert Manchester-encoded
bit data into protocol-specific message formats.
"""


class ManchesterMixin:
    """Mixin providing Manchester signal encoding/decoding methods.
    
    Manchester signals represent binary data where:
    - 0 is represented as "10" (high-to-low transition)
    - 1 is represented as "01" (low-to-high transition)
    
    Methods in this mixin handle protocol-specific variations of Manchester
    encoding and conversion to hex or other output formats.
    """

    def mcBit2Funkbus(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Funkbus (ID 119) Manchester signal with parity & checksum validation.
        
        Funkbus protocol uses Manchester-encoded signals with parity bits
        and CRC-like checksum validation. The demodulated signal must pass
        both parity and checksum verification.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (typically 119 for Funkbus)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success
                   (-1, error_message) on parity/checksum error
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        self._logging(f"lib/mcBitFunkbus, {name} Funkbus: raw={bit_data}", 5)
        
        # Convert Manchester: 1->lh, 0->hl, then decode to differential manchester
        converted = bit_data.replace('1', 'lh').replace('0', 'hl')
        s_bitmsg = self.mc2dmc(converted)
        
        # Protocol-specific bit arrangement
        protocol_id_int = int(protocol_id) if isinstance(protocol_id, str) else protocol_id
        
        if protocol_id_int == 119:
            # Funkbus specific: look for sync pattern '01100'
            pos = s_bitmsg.find('01100')
            if pos >= 0 and pos < 5:
                s_bitmsg = '001' + s_bitmsg[pos:]
                if len(s_bitmsg) < 48:
                    return (-1, 'wrong bits at begin')
            else:
                return (-1, 'wrong bits at begin')
        else:
            s_bitmsg = '0' + s_bitmsg
        
        # Calculate parity and checksum
        hex_data = ""
        xor_val = 0
        chk = 0
        parity = 0
        
        for i in range(6):  # 6 bytes
            byte_str = s_bitmsg[i*8:(i+1)*8]
            data = int(byte_str, 2)
            hex_data += f"{data:02X}"
            
            if i < 5:
                xor_val ^= data
            else:
                chk = data & 0x0F
                xor_val ^= data & 0xE0
                data &= 0xF0
            
            # Parity calculation
            temp = data
            while temp:
                parity ^= (temp & 1)
                temp >>= 1
        
        if parity == 1:
            return (-1, 'parity error')
        
        # Checksum validation
        xor_nibble = ((xor_val & 0xF0) >> 4) ^ (xor_val & 0x0F)
        result = 0
        if xor_nibble & 0x8:
            result ^= 0xC
        if xor_nibble & 0x4:
            result ^= 0x2
        if xor_nibble & 0x2:
            result ^= 0x8
        if xor_nibble & 0x1:
            result ^= 0x3
        
        if result != chk:
            return (-1, 'checksum error')
        
        self._logging(f"lib/mcBitFunkbus, {name} Funkbus: len={len(s_bitmsg)} parity={parity} result={result} chk={chk} hex={hex_data}", 4)
        
        return (1, hex_data)

    def mcBit2Sainlogic(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Sainlogic weather sensor Manchester signal.
        
        Sainlogic sensors transmit 128-bit Manchester-encoded messages.
        This handler synchronizes the bitstream if needed and extracts
        the message portion.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
            
        Raises:
            Returns error tuple if message is too short/long or sync pattern not found
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2Sainlogic, protocol {protocol_id}, length {mcbitnum}", 5)
        self._logging(f"{name}: lib/mcBit2Sainlogic, {bit_data}", 5)

        length_max = self.check_property(protocol_id, "length_max", 0)
        if mcbitnum > length_max:
            return (-1, ' message is to long')

        if mcbitnum < 128:
            start = bit_data.find('010100')
            self._logging(f"{name}: lib/mcBit2Sainlogic, protocol {protocol_id}, start found at pos {start}", 5)
            
            if start < 0 or start > 10:
                self._logging(f"{name}: lib/mcBit2Sainlogic, protocol {protocol_id}, start 010100 not found", 4)
                return (-1, f"{name}: lib/mcBit2Sainlogic, start 010100 not found")
            
            # Prepend '1' bits until we have 10+ bits before the sync pattern
            while start < 10:
                bit_data = '1' + bit_data
                start = bit_data.find('010100')
            
            # Trim to 128 bits
            bit_data = bit_data[:128]
            mcbitnum = len(bit_data)

        self._logging(f"{name}: lib/mcBit2Sainlogic, {bit_data}", 5)
        
        length_min = self.check_property(protocol_id, "length_min", 0)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        return (1, self.bin_str_2_hex_str(bit_data))

    def mcBit2AS(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode AS (ambient sound / weather sensor) Manchester signal.
        
        AS protocol uses a "1100" sync pattern (repeated high values).
        The message is extracted between two sync patterns.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
            
        Raises:
            Returns (-1, None) if valid AS message pattern not detected
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        # Look for AS sync pattern "1100" starting at position 16+
        start_pos = bit_data.find('1100', 16)
        
        if start_pos >= 0:
            # Valid AS detected!
            self._logging("lib/mcBit2AS, AS protocol detected", 5)
            
            # Find next sync pattern (message end)
            end_pos = bit_data.find('1100', start_pos + 16)
            if end_pos == -1:
                end_pos = len(bit_data)
            
            message_length = end_pos - start_pos
            
            length_min = self.check_property(protocol_id, "length_min", -1)
            if message_length < length_min:
                return (-1, ' message is to short')
            
            length_max = self.get_property(protocol_id, "length_max")
            if length_max is not None and message_length > length_max:
                return (-1, ' message is to long')
            
            msgbits = bit_data[start_pos:]
            ashex = self.bin_str_2_hex_str(msgbits)
            
            self._logging(f"{name}: AS, protocol converted to hex: ({ashex}) with length ({message_length}) bits", 5)
            
            return (1, ashex)
        
        return (-1, None)

    def mcBit2Hideki(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Hideki temperature/humidity sensor Manchester signal.
        
        Hideki sensors transmit variable-length Manchester messages.
        This handler extracts and converts the message to hex.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2Hideki, protocol {protocol_id}, length {mcbitnum}", 5)
        
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: Hideki converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)

    def mcBit2Maverick(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Maverick (BBQ thermometer) Manchester signal.
        
        Maverick sensors transmit Manchester-encoded temperature and
        identification data in a fixed-length message format.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2Maverick, protocol {protocol_id}, length {mcbitnum}", 5)
        
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: Maverick converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)

    def mcBit2OSV1(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Oregon Scientific V1 weather sensor Manchester signal.
        
        Oregon Scientific V1 sensors use Manchester encoding for weather
        station data transmission. This handler processes V1 protocol format.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2OSV1, protocol {protocol_id}, length {mcbitnum}", 5)
        
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: OSV1 converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)

    def mcBit2OSV2o3(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Oregon Scientific V2/V3 weather sensor Manchester signal.
        
        Oregon Scientific V2 and V3 sensors use enhanced Manchester encoding
        with parity/checksum validation for improved reliability.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2OSV2o3, protocol {protocol_id}, length {mcbitnum}", 5)
        
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: OSV2o3 converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)

    def mcBit2OSPIR(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Oregon Scientific PIR (motion) sensor Manchester signal.
        
        Oregon Scientific PIR sensors transmit motion detection data in
        Manchester-encoded format with specific protocol structure.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2OSPIR, protocol {protocol_id}, length {mcbitnum}", 5)
        
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: OSPIR converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)

    def mcBit2TFA(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode TFA (Dostmann) weather station Manchester signal.
        
        TFA weather stations transmit Manchester-encoded sensor data
        with temperature, humidity, and pressure information.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2TFA, protocol {protocol_id}, length {mcbitnum}", 5)
        
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: TFA converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)

    def mcBit2Grothe(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Grothe weather sensor Manchester signal.
        
        Grothe sensors transmit fixed 32-bit Manchester-encoded messages.
        This handler validates the message length and converts to hex.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring (must be 32 bits)
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
            
        Note:
            Grothe protocol requires exactly 32 bits. Messages with different
            lengths are rejected.
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2Grothe, bitdata: {bit_data} ({mcbitnum})", 5)
        
        # Grothe requires exactly 32 bits
        if mcbitnum != 32:
            self._logging(f"{name}: lib/mcBit2Grothe, ERROR - expected 32 bits, got {mcbitnum}", 3)
            return (-1, f"message must be 32 bits, got {mcbitnum}")
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: Grothe converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)

    def mcBit2SomfyRTS(self, name, bit_data, protocol_id, mcbitnum=None):
        """Decode Somfy RTS roller shutter/blind control Manchester signal.
        
        Somfy RTS devices transmit 56-bit or 57-bit Manchester-encoded messages.
        If 57 bits are received, the first bit is skipped (index 1-56).
        This handler validates the message length and converts to hex.
        
        Args:
            name: Device/message name for logging
            bit_data: Raw Manchester-encoded bitstring (56 or 57 bits)
            protocol_id: Protocol identifier (string or int)
            mcbitnum: Bit length (defaults to length of bit_data)
            
        Returns:
            Tuple: (1, hex_string) on success or (-1, error_message) on failure
            
        Note:
            If message is 57 bits, the first bit is discarded, keeping bits 1-56.
            Final message must be exactly 56 bits.
        """
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        self._logging(f"{name}: lib/mcBit2SomfyRTS, bitdata: {bit_data} ({mcbitnum})", 5)
        
        # Handle 57-bit message (discard first bit)
        if mcbitnum == 57:
            bit_data = bit_data[1:57]  # Keep bits from index 1 to 56
            self._logging(f"{name}: lib/mcBit2SomfyRTS, bitdata: {bit_data}, truncated to length: {len(bit_data)}", 5)
        
        # Validate final length must be 56 bits
        if len(bit_data) != 56:
            self._logging(f"{name}: lib/mcBit2SomfyRTS, ERROR - expected 56 bits, got {len(bit_data)}", 3)
            return (-1, f"message must be 56 bits, got {len(bit_data)}")
        
        hex_msg = self.bin_str_2_hex_str(bit_data)
        
        self._logging(f"{name}: SomfyRTS converted to hex: {hex_msg}", 5)
        
        return (1, hex_msg)
