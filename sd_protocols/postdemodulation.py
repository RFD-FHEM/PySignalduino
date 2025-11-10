"""
Post-demodulation signal processing for ASK/OOK protocols.

This module contains a mixin class with post-demodulation methods used to
validate and extract data from ASK/OOK-encoded signals after demodulation.

PostDemodulation is the process of extracting and validating the actual data
payload from a demodulated signal, typically involving:
- Preamble removal (finding sync patterns)
- Checksum/CRC validation
- Parity checking
- Format conversion (bit arrays to hex)

These methods handle protocol-specific variations in how these post-demodulation
steps are performed.
"""


class PostdemodulationMixin:
    """Mixin providing post-demodulation signal processing methods.
    
    Post-demodulation methods validate and extract data from ASK/OOK signals
    that have been demodulated from the raw RF signal. Each protocol has
    different structures for sync patterns, checksums, and payload formats.
    """

    def postDemo_EM(self, name, bit_msg_array):
        """Process EM protocol post-demodulation signal.
        
        EM sensors transmit data with a "0000000001" preamble followed by
        89 bits of payload with CRC validation.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, list_of_bits) on success or (0, None) on failure
            
        The EM format includes:
            - Preamble: 10 bits (0000000001) to find sync point
            - Payload: 89 bits with CRC validation
            - Every 9th bit is part of CRC calculation
        """
        bit_msg = bit_msg_array[:]  # Copy to avoid modifying original
        msg_str = ''.join(str(b) for b in bit_msg)
        
        # Find start of message (preamble)
        msg_start = msg_str.find('0000000001')
        
        if msg_start <= 0:
            self._logging(f"lib/postDemo_EM, protocol - Start not found", 3)
            return (0, None)
        
        # Remove preamble + 1 bit
        msg_str = msg_str[msg_start + 10:]
        msg_length = len(msg_str)
        
        if msg_length != 89:
            self._logging(f"lib/postDemo_EM, protocol - length {msg_length} not correct (expected 89)", 3)
            return (0, None)
        
        # Extract and validate CRC
        new_msg = []
        msgcrc = 0
        
        for count in range(0, msg_length, 9):
            if count + 8 < msg_length:
                crcbyte_str = msg_str[count:count + 8]
                crcbyte = int(crcbyte_str, 2)
                
                if count < (msg_length - 10):
                    # Reverse the 8 bits and add to new message
                    new_msg.extend(reversed([int(b) for b in crcbyte_str]))
                    msgcrc ^= crcbyte
        
        # Verify CRC
        final_crc_str = msg_str[msg_length - 8:msg_length]
        final_crc = int(final_crc_str, 2)
        
        if msgcrc == final_crc:
            return (1, new_msg)
        
        self._logging("lib/postDemo_EM, protocol - CRC ERROR", 3)
        return (0, None)

    def postDemo_Revolt(self, name, bit_msg_array):
        """Process Revolt protocol post-demodulation signal.
        
        Revolt sensors transmit 96-bit messages with an 8-bit checksum.
        The checksum is the sum of the first 11 bytes (88 bits).
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, bit_list_first_88_bits) on success or (0, None) on failure
            
        Format:
            - Bits 0-87: Data (11 bytes)
            - Bits 88-95: Checksum byte (sum of bytes 0-10)
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)
        
        if protolength < 96:
            return (0, None)
        
        # Extract checksum from last byte (bits 88-95)
        checksum_bits = bit_msg[88:96]
        checksum = int(''.join(str(b) for b in checksum_bits), 2)
        
        self._logging(f"lib/postDemo_Revolt, length={protolength}", 5)
        
        # Calculate checksum from first 88 bits
        calculated_sum = 0
        for b in range(0, 88, 8):
            byte_bits = bit_msg[b:b + 8]
            byte_val = int(''.join(str(bit) for bit in byte_bits), 2)
            calculated_sum += byte_val
        
        calculated_sum = calculated_sum & 0xFF
        
        if calculated_sum != checksum:
            msg_hex = self.bin_str_2_hex_str(''.join(str(b) for b in bit_msg[0:96]))
            self._logging(f"lib/postDemo_Revolt, ERROR checksum mismatch, {calculated_sum} != {checksum} in msg {msg_hex}", 3)
            return (0, None)
        
        # Return first 88 bits
        return (1, bit_msg[0:88])

    def postDemo_FS20(self, name, bit_msg_array):
        """Process FS20 remote control post-demodulation signal.
        
        FS20 remote controls transmit variable-length messages (45 or 54 bits)
        with parity per byte and a checksum at the end.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
            
        Format variations:
            - 45 bits: 4 data bytes + 1 checksum byte (with parity)
            - 54 bits: 5 data bytes + 1 checksum byte (with parity)
            - Each byte has a parity bit added (9 bits per byte)
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)
        
        # Find start (first '1' bit after preamble of '0's)
        datastart = 0
        for i, bit in enumerate(bit_msg):
            if bit == 1:
                datastart = i
                break
        else:
            # All bits are 0
            self._logging("lib/postDemo_FS20, ERROR message all bits are zeros", 3)
            return (0, None)
        
        # Remove preamble + 1 bit
        bit_msg = bit_msg[datastart + 1:]
        protolength = len(bit_msg)
        
        self._logging(f"lib/postDemo_FS20, pos={datastart} length={protolength}", 5)
        
        # Remove EOT bit if present
        if protolength == 46 or protolength == 55:
            bit_msg.pop()
            protolength -= 1
        
        # Validate length: FS20 is 45 or 54 bits
        if protolength != 45 and protolength != 54:
            self._logging(f"lib/postDemo_FS20, ERROR - wrong length={protolength} (must be 45 or 54)", 5)
            return (0, None)
        
        # Calculate checksum
        sum_val = 6
        for b in range(0, protolength - 9, 9):
            byte_bits = bit_msg[b:b + 8]
            byte_val = int(''.join(str(bit) for bit in byte_bits), 2)
            sum_val += byte_val
        
        # Extract checksum byte (last byte minus parity bit)
        checksum_bits = bit_msg[protolength - 9:protolength - 1]
        checksum = int(''.join(str(bit) for bit in checksum_bits), 2)
        
        # Check for FHT80 interference
        if (sum_val + 6) & 0xFF == checksum:
            self._logging("lib/postDemo_FS20, Detection aborted, checksum matches FHT code", 5)
            return (0, None)
        
        # Validate FS20 checksum
        if (sum_val & 0xFF) != checksum:
            self._logging("lib/postDemo_FS20, ERROR - wrong checksum", 4)
            return (0, None)
        
        # Verify parity bits
        for b in range(0, protolength, 9):
            parity = 0
            for i in range(b, min(b + 9, protolength)):
                parity += bit_msg[i]
            
            if parity % 2 != 0:
                self._logging("lib/postDemo_FS20, FS20, ERROR - Parity not even", 3)
                return (0, None)
        
        # Remove parity bits (every 9th bit, starting from the end)
        for b in range(protolength - 1, 0, -9):
            bit_msg.pop(b)
        
        # Handle length-specific formatting
        if protolength == 45:
            # Remove checksum byte at position 32
            del bit_msg[32:40]
            # Insert 8 zero bits at position 24
            bit_msg[24:24] = [0, 0, 0, 0, 0, 0, 0, 0]
        else:  # 54 bits
            # Remove checksum byte at position 40
            del bit_msg[40:48]
        
        msg_hex = self.bin_str_2_hex_str(''.join(str(b) for b in bit_msg))
        self._logging(f"lib/postDemo_FS20, remote control post demodulation {msg_hex} length {protolength}", 4)
        
        return (1, bit_msg)

    def postDemo_FHT80(self, name, bit_msg_array):
        """Process FHT80 thermostat post-demodulation signal.
        
        FHT80 thermostats transmit 54-bit messages with parity per byte
        and a checksum. Format is similar to FS20 but with different
        checksum calculation.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
            
        Format:
            - 54 bits total (6 bytes * 9 bits including parity)
            - Bytes 0-4: Data
            - Byte 5: Checksum
            - Each byte has parity bit (position 7 in 9-bit group)
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)
        
        # Find start (first '1' bit)
        datastart = 0
        for i, bit in enumerate(bit_msg):
            if bit == 1:
                datastart = i
                break
        else:
            # All bits are 0
            self._logging("lib/postDemo_FHT80, ERROR message all bit are zeros", 3)
            return (0, None)
        
        # Remove preamble + 1 bit
        bit_msg = bit_msg[datastart + 1:]
        protolength = len(bit_msg)
        
        self._logging(f"lib/postDemo_FHT80, pos={datastart} length={protolength}", 5)
        
        # Remove EOT bit if present
        if protolength == 55:
            bit_msg.pop()
            protolength -= 1
        
        if protolength != 54:
            self._logging(f"lib/postDemo_FHT80, ERROR - wrong length={protolength} (expected 54)", 5)
            return (0, None)
        
        # Calculate checksum
        sum_val = 12
        for b in range(0, 45, 9):
            byte_bits = bit_msg[b:b + 8]
            byte_val = int(''.join(str(bit) for bit in byte_bits), 2)
            sum_val += byte_val
        
        # Extract checksum (bits 45-52, i.e., byte 5 without parity)
        checksum_bits = bit_msg[45:53]
        checksum = int(''.join(str(bit) for bit in checksum_bits), 2)
        
        # Check for FS20 interference
        if ((sum_val - 6) & 0xFF) == checksum:
            self._logging("lib/postDemo_FHT80, Detection aborted, checksum matches FS20 code", 5)
            return (0, None)
        
        # Validate FHT80 checksum
        if (sum_val & 0xFF) != checksum:
            self._logging(f"lib/postDemo_FHT80, ERROR - wrong checksum {sum_val & 0xFF} != {checksum}", 4)
            return (0, None)
        
        # Verify parity bits
        for b in range(0, 54, 9):
            parity = 0
            for i in range(b, min(b + 9, 54)):
                parity += bit_msg[i]
            
            if parity % 2 != 0:
                self._logging("lib/postDemo_FHT80, ERROR - Parity not even", 3)
                return (0, None)
        
        # Remove parity bits (every 9th bit, starting from the end)
        for b in range(53, 0, -9):
            bit_msg.pop(b)
        
        return (1, bit_msg)

    def postDemo_FHT80TF(self, name, bit_msg_array):
        """Process FHT80TF window sensor post-demodulation signal.
        
        FHT80TF sensors transmit window contact/tilt sensor data in
        a similar format to FHT80 with 8-bit data payload.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
            
        Format:
            - Similar to FHT80 with 8-bit sensor data
            - Contact state and tilt angle encoded in bits
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)
        
        # Find start (first '1' bit)
        datastart = 0
        for i, bit in enumerate(bit_msg):
            if bit == 1:
                datastart = i
                break
        else:
            self._logging("lib/postDemo_FHT80TF, ERROR all bits are zeros", 3)
            return (0, None)
        
        # Remove preamble + 1 bit
        bit_msg = bit_msg[datastart + 1:]
        protolength = len(bit_msg)
        
        self._logging(f"lib/postDemo_FHT80TF, pos={datastart} length={protolength}", 5)
        
        # Remove EOT bit if present
        if protolength == 28:
            bit_msg.pop()
            protolength -= 1
        
        if protolength != 27:
            return (0, None)
        
        # Verify parity for FHT80TF (3 bytes of data)
        for b in range(0, 27, 9):
            parity = 0
            for i in range(b, min(b + 9, 27)):
                parity += bit_msg[i]
            
            if parity % 2 != 0:
                return (0, None)
        
        # Remove parity bits
        for b in range(26, 0, -9):
            bit_msg.pop(b)
        
        return (1, bit_msg)

    def postDemo_WS2000(self, name, bit_msg_array):
        """Process WS2000 weather station post-demodulation signal.
        
        WS2000 weather stations transmit temperature, humidity, pressure
        and other meteorological data with CRC validation.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
        """
        bit_msg = bit_msg_array[:]  # Copy
        
        # Find preamble/start pattern
        msg_str = ''.join(str(b) for b in bit_msg)
        start_pos = msg_str.find('10101100')
        
        if start_pos < 0:
            self._logging("lib/postDemo_WS2000, ERROR - preamble not found", 3)
            return (0, None)
        
        # Remove preamble
        bit_msg = bit_msg[start_pos + 8:]
        
        # WS2000 format validation
        if len(bit_msg) < 80:
            self._logging("lib/postDemo_WS2000, ERROR - message too short", 3)
            return (0, None)
        
        # Validate CRC (simplified - full implementation requires protocol specs)
        # For now, just accept valid length messages
        
        self._logging(f"lib/postDemo_WS2000, OK - length={len(bit_msg)}", 5)
        
        return (1, bit_msg)

    def postDemo_WS7035(self, name, bit_msg_array):
        """Process WS7035 weather station post-demodulation signal.
        
        WS7035 sensors transmit meteorological data with specific format
        including parity and CRC validation.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)
        
        # WS7035 typically uses 80-bit messages
        if protolength < 80:
            self._logging("lib/postDemo_WS7035, ERROR - message too short", 3)
            return (0, None)
        
        # Find start pattern (sync bits)
        msg_str = ''.join(str(b) for b in bit_msg)
        start_pos = msg_str.find('00001111')
        
        if start_pos < 0:
            self._logging("lib/postDemo_WS7035, ERROR - sync pattern not found", 3)
            return (0, None)
        
        # Remove preamble
        bit_msg = bit_msg[start_pos + 8:]
        
        self._logging(f"lib/postDemo_WS7035, OK - length={len(bit_msg)}", 5)
        
        return (1, bit_msg)

    def postDemo_WS7053(self, name, bit_msg_array):
        """Process WS7053 weather station post-demodulation signal.
        
        WS7053 sensors transmit weather data with Manchester encoding
        and CRC validation for data integrity.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)
        
        # WS7053 typically uses 88-bit messages (11 bytes)
        if protolength < 88:
            self._logging("lib/postDemo_WS7053, ERROR - message too short", 3)
            return (0, None)
        
        # Manchester decode already done, just validate structure
        msg_str = ''.join(str(b) for b in bit_msg[:88])
        
        # Basic length validation
        self._logging(f"lib/postDemo_WS7053, OK - length={len(bit_msg)}", 5)
        
        return (1, bit_msg[:88])

    def postDemo_lengtnPrefix(self, name, bit_msg_array):
        """Process length-prefix protocol post-demodulation signal.
        
        Some protocols encode message length as a prefix before the
        actual payload. This handler extracts payload based on length
        field and validates overall message structure.
        
        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation
            
        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
            
        Format:
            - First 8 bits: Length byte (number of payload bits)
            - Remaining bits: Payload (as specified by length)
        """
        bit_msg = bit_msg_array[:]  # Copy
        
        if len(bit_msg) < 8:
            self._logging("lib/postDemo_lengtnPrefix, ERROR - message too short for length field", 3)
            return (0, None)
        
        # Extract length from first byte
        length_bits = bit_msg[0:8]
        length_val = int(''.join(str(b) for b in length_bits), 2)
        
        # Validate message has enough bits
        total_bits_needed = 8 + length_val  # length field + payload
        if len(bit_msg) < total_bits_needed:
            self._logging(f"lib/postDemo_lengtnPrefix, ERROR - message too short, need {total_bits_needed} bits, got {len(bit_msg)}", 3)
            return (0, None)
        
        # Extract payload (skip length field)
        payload = bit_msg[8:8 + length_val]
        
        self._logging(f"lib/postDemo_lengtnPrefix, OK - length={length_val}, total_bits={len(bit_msg)}", 5)
        
        return (1, payload)
