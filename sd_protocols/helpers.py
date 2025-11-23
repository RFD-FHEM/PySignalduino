class ProtocolHelpersMixin:
    """Mixin class providing helper methods for protocol processing."""

    def mc2dmc(self, bit_data):
        """
        Helper for remodulation of a manchester signal to a differential manchester signal.
        
        Args:
            bit_data: Binary data string
        
        Returns:
            String of converted bits or tuple (-1, error_message) on failure
        """
        if bit_data is None:
            return (-1, 'no bitData provided')
        
        bit_data = bit_data.replace('1', 'lh').replace('0', 'hl')
        
        bitmsg = []
        for i in range(1, len(bit_data) - 1, 2):
            # Demodulated differential manchester: 0 if bits are equal, 1 if different
            bitmsg.append('0' if bit_data[i] == bit_data[i + 1] else '1')
        
        return ''.join(bitmsg)

    def bin_str_2_hex_str(self, num):
        """
        Convert binary string into its hex representation as string.
        
        Args:
            num: Binary string (e.g., '1111' -> 'F')
        
        Returns:
            Hex string or None if input is invalid
        """
        if num is None:
            return None
        # Handle empty string
        if not num:
            return ''
        # Check if input is valid binary
        if not isinstance(num, str) or not all(c in '01' for c in num):
            return None
        
        width = 4
        index = len(num) - width
        hex_result = ''
        
        while True:
            current_width = width
            if index < 0:
                current_width += index
                index = 0
            
            cut_string = num[index:index + current_width]
            hex_result = format(int(cut_string, 2), 'X') + hex_result
            index -= width
            
            if index <= -width:
                break
        
        return hex_result

    def dec_2_bin_ppari(self, num):
        """
        Convert decimal number to binary with parity bit appended.
        
        Args:
            num: Decimal number
        
        Returns:
            9-bit binary string with parity bit (8 bits + 1 parity bit)
            Example: 32 -> '001000001' (00100000 + parity bit 1)
        """
        if num is None:
            return None
        
        # Convert to 8-bit binary
        nbin = format(num, '08b')
        
        # Calculate parity (even parity)
        parity = 0
        for bit in nbin:
            parity ^= int(bit)
        
        return nbin + str(parity)

    def mcraw(self, name='anonymous', bit_data=None, protocol_id=None, mcbitnum=None):
        """
        Output helper for manchester signals.
        Checks length_max and returns hex string.
        
        Args:
            name: Signal name
            bit_data: Binary data string
            protocol_id: Protocol ID
            mcbitnum: Bit count (defaults to length of bit_data)
        
        Returns:
            tuple: (1, hex_string) on success or (-1, error_message) on failure
        """
        if bit_data is None:
            return (-1, 'no bitData provided')
        if protocol_id is None:
            return (-1, 'no protocolId provided')
        
        if mcbitnum is None:
            mcbitnum = len(bit_data)
        
        # Check length_max
        max_len = self.get_property(protocol_id, 'length_max')
        if max_len is not None and mcbitnum > max_len:
            return (-1, 'message is to long')
        
        # Convert to hex
        hex_result = self.bin_str_2_hex_str(bit_data)
        if hex_result is None:
            return (-1, 'invalid bit data')
        
        return (1, hex_result)

    def length_in_range(self, protocol_id, message_length):
        """
        Check if a given message length is within the valid range for a protocol.
        
        Args:
            protocol_id: Protocol ID
            message_length: Length of the message in bits
        
        Returns:
            tuple: (1, '') on success or (0, error_message) on failure
            Error messages:
                - 'protocol does not exists'
                - 'message is to short'
                - 'message is to long'
        """
        # Check if protocol exists
        if not self.protocol_exists(str(protocol_id)):
            return (0, 'protocol does not exists')
        
        # Check minimum length
        min_len = self.check_property(protocol_id, 'length_min', -1)
        if min_len is not None:
             try:
                 min_len = int(min_len)
             except (ValueError, TypeError):
                 # Log warning? For now, treat as no limit or skip check?
                 # Assuming data integrity, but let's be safe.
                 pass

        if min_len != -1 and message_length < min_len:
            return (0, 'message is too short')
        
        # Check maximum length
        max_len = self.get_property(protocol_id, 'length_max')
        if max_len is not None:
            try:
                max_len = int(max_len)
                if message_length > max_len:
                    return (0, 'message is too long')
            except (ValueError, TypeError):
                pass
        
        return (1, '')

    def hex_to_bin_str(self, hex_string):
        """
        Convert hex string to binary string.
        
        Args:
            hex_string: Hexadecimal string (e.g., '1A3F')
        
        Returns:
            Binary string (e.g., '0001101000111111') or None if input is invalid
        """
        if hex_string is None:
            return None
        
        try:
            # Convert hex to integer, then format as binary
            bin_string = bin(int(hex_string, 16))[2:]  # Remove '0b' prefix
            # Pad with leading zeros to make length a multiple of 4
            padded_length = ((len(bin_string) + 3) // 4) * 4
            return bin_string.zfill(padded_length)
        except ValueError:
            return None

    def lfsr_digest16(self, bytes_count, gen, key, raw_data):
        """
        Calculates 16-bit LFSR digest.
        
        Args:
            bytes_count: Number of bytes to process
            gen: Generator polynomial
            key: Initial key
            raw_data: Hex string of data
            
        Returns:
            int: Calculated LFSR value
        """
        if len(raw_data) < bytes_count * 2:
             return 0

        lfsr = 0
        for k in range(bytes_count):
            try:
                data = int(raw_data[k * 2 : k * 2 + 2], 16)
            except ValueError:
                return 0
                
            for i in range(7, -1, -1):
                if (data >> i) & 0x01:
                    lfsr ^= key
                
                if key & 0x01:
                    key = (key >> 1) ^ gen
                else:
                    key = (key >> 1)
        return lfsr

    def ConvBresser_lightning(self, msg_data, msg_type='MN'):
        """
        Process Bresser Lightning protocol data.
        
        Args:
            msg_data: Dictionary with 'data' (hex string)
            msg_type: 'MN'
            
        Returns:
            List containing decoded message dict or empty list on error.
        """
        hex_data = msg_data.get('data')
        if not hex_data:
            return []
            
        hex_length = len(hex_data)
        if hex_length < 20:
            self._logging("ConvBresser_lightning, hexData is too short", 3)
            return []

        hex_data_xor_a = ""
        for i in range(hex_length):
            try:
                xor = int(hex_data[i], 16) ^ 0xA
                hex_data_xor_a += f"{xor:X}"
            except ValueError:
                return []
            
        self._logging(f"ConvBresser_lightning, msg={hex_data}", 5)
        self._logging(f"ConvBresser_lightning, xor={hex_data_xor_a}", 5)
        
        # LFSR-16 gen 8810 key abf9 final xor 899e
        # Substr(hexDataXorA, 4, 16) means starting from index 4, take 16 chars (8 bytes)
        checksum = self.lfsr_digest16(8, 0x8810, 0xABF9, hex_data_xor_a[4:20])
        
        try:
            # substr(hexDataXorA, 0, 4) -> first 2 bytes (4 hex chars)
            first_2_bytes_xor = int(hex_data_xor_a[0:4], 16)
        except ValueError:
            return []
        
        checksum_calc = checksum ^ first_2_bytes_xor
        checksum_calc_hex = f"{checksum_calc:04X}"
        
        self._logging(f"ConvBresser_lightning, checksumCalc:0x{checksum_calc_hex}, must be 0x899E", 5)
        
        if checksum_calc_hex != '899E':
             self._logging(f"ConvBresser_lightning, checksumCalc:0x{checksum_calc_hex} != checksum:0x899E", 3)
             return []
             
        # Return first 20 chars (10 bytes)
        payload = hex_data_xor_a[:20]
        
        return [{
            "protocol_id": msg_data.get('protocol_id'),
            "payload": payload,
            "meta": {}
        }]