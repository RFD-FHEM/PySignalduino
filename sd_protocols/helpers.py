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
        if message_length < min_len:
            return (0, 'message is to short')
        
        # Check maximum length
        max_len = self.get_property(protocol_id, 'length_max')
        if max_len is not None and message_length > max_len:
            return (0, 'message is to long')
        
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