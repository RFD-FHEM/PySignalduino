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
        msg_str = "".join(str(b) for b in bit_msg)

        # Find start of message (preamble)
        msg_start = msg_str.find("0000000001")

        if msg_start < 0:
            self._logging("lib/postDemo_EM, protocol - Start not found", 3)
            return (0, None)

        # Remove preamble + 1 bit
        msg_str = msg_str[msg_start + 10 :]
        msg_length = len(msg_str)

        if msg_length != 89:
            self._logging(
                f"lib/postDemo_EM, protocol - length {msg_length} not correct (expected 89)",
                3,
            )
            return (0, None)

        # Extract and validate CRC
        new_msg = []
        msgcrc = 0

        for count in range(0, msg_length, 9):
            if count + 8 < msg_length:
                crcbyte_str = msg_str[count : count + 8]
                crcbyte = int(crcbyte_str, 2)

                if count < (msg_length - 10):
                    # Reverse the 8 bits and add to new message
                    new_msg.extend(reversed([int(b) for b in crcbyte_str]))
                    msgcrc ^= crcbyte

        # Verify CRC
        final_crc_str = msg_str[msg_length - 8 : msg_length]
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
        checksum = int("".join(str(b) for b in checksum_bits), 2)

        self._logging(f"lib/postDemo_Revolt, length={protolength}", 5)

        # Calculate checksum from first 88 bits
        calculated_sum = 0
        for b in range(0, 88, 8):
            byte_bits = bit_msg[b : b + 8]
            byte_val = int("".join(str(bit) for bit in byte_bits), 2)
            calculated_sum += byte_val

        calculated_sum = calculated_sum & 0xFF

        if calculated_sum != checksum:
            msg_hex = self.bin_str_2_hex_str("".join(str(b) for b in bit_msg[0:96]))
            self._logging(
                f"lib/postDemo_Revolt, ERROR checksum mismatch, {calculated_sum} != {checksum} in msg {msg_hex}",
                3,
            )
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
        bit_msg = bit_msg[datastart + 1 :]
        protolength = len(bit_msg)

        self._logging(f"lib/postDemo_FS20, pos={datastart} length={protolength}", 5)

        # Remove EOT bit if present
        if protolength == 46 or protolength == 55:
            bit_msg.pop()
            protolength -= 1

        # Validate length: FS20 is 45 or 54 bits
        if protolength != 45 and protolength != 54:
            self._logging(
                f"lib/postDemo_FS20, ERROR - wrong length={protolength} (must be 45 or 54)",
                5,
            )
            return (0, None)

        # Calculate checksum
        sum_val = 6
        for b in range(0, protolength - 9, 9):
            byte_bits = bit_msg[b : b + 8]
            byte_val = int("".join(str(bit) for bit in byte_bits), 2)
            sum_val += byte_val

        # Extract checksum byte (last byte minus parity bit)
        checksum_bits = bit_msg[protolength - 9 : protolength - 1]
        checksum = int("".join(str(bit) for bit in checksum_bits), 2)

        # Check for FHT80 interference
        if (sum_val + 6) & 0xFF == checksum:
            self._logging(
                "lib/postDemo_FS20, Detection aborted, checksum matches FHT code", 5
            )
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

        msg_hex = self.bin_str_2_hex_str("".join(str(b) for b in bit_msg))
        self._logging(
            f"lib/postDemo_FS20, remote control post demodulation {msg_hex} length {protolength}",
            4,
        )

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
        bit_msg = bit_msg[datastart + 1 :]
        protolength = len(bit_msg)

        self._logging(f"lib/postDemo_FHT80, pos={datastart} length={protolength}", 5)

        # Remove EOT bit if present
        if protolength == 55:
            bit_msg.pop()
            protolength -= 1

        if protolength != 54:
            self._logging(
                f"lib/postDemo_FHT80, ERROR - wrong length={protolength} (expected 54)",
                5,
            )
            return (0, None)

        # Calculate checksum
        sum_val = 12
        for b in range(0, 45, 9):
            byte_bits = bit_msg[b : b + 8]
            byte_val = int("".join(str(bit) for bit in byte_bits), 2)
            sum_val += byte_val

        # Extract checksum (bits 45-52, i.e., byte 5 without parity)
        checksum_bits = bit_msg[45:53]
        checksum = int("".join(str(bit) for bit in checksum_bits), 2)

        # Check for FS20 interference
        if ((sum_val - 6) & 0xFF) == checksum:
            self._logging(
                "lib/postDemo_FHT80, Detection aborted, checksum matches FS20 code", 5
            )
            return (0, None)

        # Validate FHT80 checksum
        if (sum_val & 0xFF) != checksum:
            self._logging(
                f"lib/postDemo_FHT80, ERROR - wrong checksum {sum_val & 0xFF} != {checksum}",
                4,
            )
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

        FHT80TF sensors transmit door/window contact sensor data with
        checksum and parity validation.

        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation

        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure

        Format:
            - 45 bits after preamble removal
            - Checksum over first 4 bytes
            - Parity per 9-bit group
            - Specific bit validation
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)

        if protolength < 46:  # min 5 bytes + 6 bits
            self._logging("lib/postDemo_FHT80TF, ERROR lenght of message < 46", 4)
            return (0, None)

        # Find start (first '1' bit)
        datastart = 0
        for i, bit in enumerate(bit_msg):
            if bit == 1:
                datastart = i
                break
        else:
            # All bits are 0
            self._logging("lib/postDemo_FHT80TF, ERROR message all bit are zeros", 3)
            return (0, None)

        # Remove preamble + 1 bit
        bit_msg = bit_msg[datastart + 1 :]
        protolength = len(bit_msg)

        if protolength == 45:  # FHT80TF fixed length
            # Build sum over first 4 bytes
            sum_val = 12
            for b in range(0, 36, 9):
                byte_bits = bit_msg[b : b + 8]
                byte_val = int("".join(str(bit) for bit in byte_bits), 2)
                sum_val += byte_val

            # Checksum Byte 5
            checksum_bits = bit_msg[36:44]
            checksum = int("".join(str(bit) for bit in checksum_bits), 2)

            if (sum_val & 0xFF) == checksum:  # FHT80TF door/window contact
                # Check parity over 5 bytes
                for b in range(0, 45, 9):
                    parity = 0  # Parity even
                    for i in range(b, min(b + 9, 45)):
                        parity += bit_msg[i]

                    if parity % 2 != 0:
                        self._logging("lib/postDemo_FHT80TF, ERROR Parity not even", 4)
                        return (0, None)

                # Parity ok, remove 5 parity bits
                for b in range(44, 0, -9):
                    bit_msg.pop(b)

                # Bit 5 Byte 3 must 0
                if bit_msg[26] != 0:
                    self._logging("lib/postDemo_FHT80TF, ERROR - byte 3 bit 5 not 0", 3)
                    return (0, None)

                # Delete checksum
                del bit_msg[32:40]

                msg_hex = self.bin_str_2_hex_str("".join(str(b) for b in bit_msg))
                self._logging(
                    f"lib/postDemo_FHT80TF, door/window switch post demodulation {msg_hex}",
                    4,
                )

                return (1, bit_msg)

        return (0, None)

    def postDemo_WS2000(self, name, bit_msg_array):
        """Process WS2000 weather station post-demodulation signal.

        WS2000 weather stations transmit temperature, humidity, pressure
        and other meteorological data with specific validation.

        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation

        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure
        """
        bit_msg = bit_msg_array[:]  # Copy
        protolength = len(bit_msg)
        new_bit_msg = []  # Start with empty list, will append as needed
        datalenghtws = [35, 50, 35, 50, 70, 40, 40, 85]
        datastart = 0
        datalength = 0
        datalength1 = 0
        index = 0
        data = 0
        dataindex = 0
        check = 0
        sum_val = 5
        typ = 0
        adr = 0

        # Find start (first '1' bit)
        for datastart in range(protolength):
            if bit_msg[datastart] == 1:
                break
        else:
            self._logging("lib/postDemo_WS2000, ERROR message all bit are zeros", 4)
            return (0, None)

        datalength = protolength - datastart
        datalength1 = datalength - (datalength % 5)  # modulo 5

        self._logging(
            f"lib/postDemo_WS2000, protolength: {protolength}, datastart: {datastart}, datalength {datalength}",
            5,
        )

        # Extract sensor type
        typ_bits = bit_msg[datastart + 1 : datastart + 5]
        typ = int("".join(str(b) for b in reversed(typ_bits)), 2)

        if typ > 7:
            self._logging(
                f"lib/postDemo_WS2000, Sensortyp {typ} - ERROR typ to big (0-7)", 5
            )
            return (0, None)

        # Special case for type 1
        if typ == 1 and (datalength == 45 or datalength == 46):
            datalength1 += 5

        # Check length
        if datalenghtws[typ] != datalength1:
            self._logging(
                f"lib/postDemo_WS2000, Sensortyp {typ} - ERROR lenght of message {datalength1} ({datalenghtws[typ]})",
                4,
            )
            return (0, None)
        elif datastart > 10:
            self._logging(f"lib/postDemo_WS2000, ERROR preamble > 10 ({datastart})", 4)
            return (0, None)

        # Process message
        while index < datalength - 1:
            if bit_msg[index + datastart] != 1:
                self._logging(
                    f"lib/postDemo_WS2000, Sensortyp {typ} - ERROR checking bit {index}",
                    4,
                )
                return (0, None)

            dataindex = index + datastart + 1
            rest = protolength - dataindex
            if rest < 4:
                self._logging(
                    f"lib/postDemo_WS2000, Sensortyp {typ} - ERROR rest of message < 4 ({rest})",
                    4,
                )
                return (0, None)

            data_bits = bit_msg[dataindex : dataindex + 4]
            data = int("".join(str(b) for b in reversed(data_bits)), 2)

            if index == 5:
                adr = data & 0x07  # Sensor address

            # Checksum calculation
            if datalength == 45 or datalength == 46:
                if index <= datalength - 5:
                    check ^= data
            else:
                if index <= datalength - 10:
                    check ^= data
                    sum_val += data

            index += 5

        if check != 0:
            self._logging(
                f"lib/postDemo_WS2000, Sensortyp {typ} Adr {adr} - ERROR check XOR", 4
            )
            return (0, None)

        # Sum check for non-type-1 messages
        if datalength < 45 or datalength > 46:
            data_bits = bit_msg[dataindex : dataindex + 4]
            data = int("".join(str(b) for b in reversed(data_bits)), 2)
            if data != (sum_val & 0x0F):
                self._logging(
                    f"lib/postDemo_WS2000, Sensortyp {typ} Adr {adr} - ERROR sum", 4
                )
                return (0, None)

        self._logging(f"lib/postDemo_WS2000, Sensortyp {typ} Adr {adr}", 4)

        # Rearrange bits - build the output array dynamically - match Perl exactly
        datastart += 1

        # Initialize with zeros for the fixed positions - match Perl order
        # First, create array with 16 zeros (4 bytes)
        new_bit_msg = [0] * 16

        # Sensoradresse (4 bits) - positions 0-3
        new_bit_msg[0:4] = reversed(bit_msg[datastart + 5 : datastart + 9])
        # Sensortyp (4 bits) - positions 4-7
        new_bit_msg[4:8] = reversed(bit_msg[datastart : datastart + 4])
        # T 1, R MID, Wi 1, B 10, Py 10 (4 bits) - positions 8-11
        new_bit_msg[8:12] = reversed(bit_msg[datastart + 15 : datastart + 19])
        # T 0.1, R LSN, Wi 0.1, B 1, Py 1 (4 bits) - positions 12-15
        new_bit_msg[12:16] = reversed(bit_msg[datastart + 10 : datastart + 14])

        # Type-specific data
        if typ in [0, 2]:  # Thermo, Rain
            new_bit_msg.extend(reversed(bit_msg[datastart + 20 : datastart + 24]))
        elif typ in [1, 3, 4, 7]:  # Thermo/Hygro, Wind, Thermo/Hygro/Baro, Kombi
            new_bit_msg.extend(reversed(bit_msg[datastart + 25 : datastart + 29]))
            new_bit_msg.extend(reversed(bit_msg[datastart + 20 : datastart + 24]))
            if typ in [1, 3, 4, 7]:
                new_bit_msg.extend(reversed(bit_msg[datastart + 35 : datastart + 39]))
                new_bit_msg.extend(reversed(bit_msg[datastart + 30 : datastart + 34]))
                if typ == 4:  # Thermo/Hygro/Baro
                    new_bit_msg.extend(reversed(bit_msg[datastart + 55 : datastart + 59]))
                    new_bit_msg.extend(reversed(bit_msg[datastart + 50 : datastart + 54]))
                    new_bit_msg.extend(reversed(bit_msg[datastart + 45 : datastart + 49]))
                    new_bit_msg.extend(reversed(bit_msg[datastart + 40 : datastart + 44]))

        return (1, new_bit_msg)

    def postDemo_WS7035(self, name, bit_msg_array):
        """Process WS7035 weather station post-demodulation signal.

        WS7035 sensors transmit meteorological data with a fixed identifier,
        even parity over the whole message and a 4‑bit checksum (mod‑16 sum of
        the first 40 bits). The function validates these constraints and returns
        the original bit list when the message is valid.

        Args:
            name: Device/message name for logging (unused here)
            bit_msg_array: List of bits received after demodulation

        Returns:
            (1, bit_list) on success, (0, None) on failure.
        """
        bit_msg = bit_msg_array[:]  # work on a copy
        msg_str = "".join(str(b) for b in bit_msg)

        # 1. Identifier must be exactly '10100000' at the start of the message
        ident = "10100000"
        if not msg_str.startswith(ident):
            self._logging("lib/postDemo_WS7035, ERROR - Ident" + ident + "not found", 3)
            return (0, None)

        # Expected total length for WS7035 is 44 bits (40 data + 4 checksum)
        if len(msg_str) != 44:
            self._logging(
                f"lib/postDemo_WS7035, ERROR - wrong length {len(msg_str)} (expected 44)",
                3,
            )
            return (0, None)

        # 2. Even parity over bits 15‑27 (13 bits) as defined by the protocol
        parity = sum(int(msg_str[i]) for i in range(15, 28)) % 2
        if parity != 0:
            self._logging("lib/postDemo_WS7035, ERROR - parity not even", 3)
            return (0, None)


        # 3. Checksum: last 4 bits are sum of the first 10 nibbles (4‑bit groups) modulo 16
        data_bits = msg_str[:40]
        checksum_bits = msg_str[40:]
        # Compute sum of each 4‑bit nibble
        nibble_sum = 0
        for i in range(0, 40, 4):
            nibble = data_bits[i:i+4]
            nibble_sum += int(nibble, 2)
        calculated_checksum = nibble_sum % 16
        received_checksum = int(checksum_bits, 2)
        if calculated_checksum != received_checksum:
            self._logging("lib/postDemo_WS7035, ERROR - checksum mismatch", 3)
            return (0, None)

        # All checks passed – return the original bit list
        # skip nibble 8 = index 28 - 31
        skip_start = 27
        skip_end = 31
        return (
            1,
            [int(b) for i, b in enumerate(msg_str) if not skip_start <= i < skip_end]
        )
    
    def postDemo_WS7053(self, name, bit_msg_array):
        """Process WS7053 weather station post-demodulation signal.

        WS7053 sensors transmit weather data with specific sync pattern,
        parity validation, and bit rearrangement for CUL_TX format.

        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation

        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure

        Format:
            - Sync pattern: '10100000' (ident)
            - Parity over bits 15-27 (temperature)
            - Rearrangement: ident + rolling code + temp + temp copy + zero
        """
        bit_msg = bit_msg_array[:]  # Copy

        msg_str = "".join(str(b) for b in bit_msg)

        self._logging(f"lib/postDemo_WS7053, MSG = {msg_str}", 4)

        start_pos = msg_str.find("10100000")

        if start_pos > 0:
            msg_str = msg_str[start_pos:]
            msg_str += "0"
            self._logging(f"lib/postDemo_WS7053, cut {start_pos} char(s) at begin", 5)

        if start_pos < 0:
            self._logging("lib/postDemo_WS7053, ERROR - Ident 10100000 not found", 3)
            return (0, None)

        if len(msg_str) < 32:
            self._logging(
                f"lib/postDemo_WS7053, ERROR - msg too short, length {len(msg_str)}", 3
            )
            return (0, None)

        # Parity over bits 15-27
        parity = 0
        for i in range(15, 28):
            parity += int(msg_str[i])

        if parity % 2 != 0:
            self._logging(
                f"lib/postDemo_WS7053, ERROR - Parity not even {len(msg_str)}", 3
            )
            return (0, None)

        # Rearrange: ident(0-7) + rolling(8-15) + temp(16-27) + temp(16-23) + zero(28-31)
        new_msg = msg_str[0:28] + msg_str[16:24] + msg_str[28:32]

        self._logging(
            f"lib/postDemo_WS7053, before: {msg_str[0:4]} {msg_str[4:8]} {msg_str[8:12]} {msg_str[12:16]} {msg_str[16:20]} {msg_str[20:24]} {msg_str[24:28]} {msg_str[28:32]}",
            5,
        )
        self._logging(
            f"lib/postDemo_WS7053, after: {new_msg[0:4]} {new_msg[4:8]} {new_msg[8:12]} {new_msg[12:16]} {new_msg[16:20]} {new_msg[20:24]} {new_msg[24:28]} {new_msg[28:32]} {new_msg[32:36]} {new_msg[36:40]}",
            5,
        )

        return (1, [int(b) for b in new_msg])

    def postDemo_lengtnPrefix(self, name, bit_msg_array):
        """Process length-prefix protocol post-demodulation signal.

        This function calculates the hex (in bits) and adds it at the beginning of the message.

        Args:
            name: Device/message name for logging
            bit_msg_array: Array/list of individual bits from demodulation

        Returns:
            Tuple: (1, processed_bit_list) on success or (0, None) on failure

        Format:
            - Prepends 8-bit binary representation of message length
            - Returns the full message with length prefix
        """
        bit_msg = bit_msg_array[:]  # Copy

        msg_str = "".join(str(b) for b in bit_msg)
        length_bin = format(len(msg_str), "08b")
        new_msg = length_bin + msg_str

        return (1, [int(b) for b in new_msg])
