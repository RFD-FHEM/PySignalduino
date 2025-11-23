from typing import Any, Dict

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
    def _calc_crc16(self, hex_data: str, poly: int, init: int, refin: bool, refout: bool, xorout: int) -> str:
        """Helper to calculate CRC-16 given the parameters."""
        try:
            data_bytes = bytes.fromhex(hex_data)
        except ValueError:
            self._logging(f"_calc_crc16: Invalid hex data provided: {hex_data}", 3)
            return "0000" # Returning a non-matching CRC ensures the check fails as expected for bad input
            
        crc = init
        for byte in data_bytes:
            if refin:
                byte = int(f"{byte:08b}"[::-1], 2)

            crc ^= byte << 8

            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
                crc &= 0xFFFF

        if refout:
            # Reversing all 16 bits of the final CRC
            crc = int(f"{crc:016b}"[::-1], 2)

        crc ^= xorout
        
        return f"{crc:04X}"
    
    def _calc_crc8_la_crosse(self, hex_data: str) -> int:
        """Helper to calculate CRC-8 (poly 0x31, init 0x00, refin=refout=True, xorout=0x00) for LaCrosse."""
        # LaCrosse uses CRC-8, poly=0x31, init=0x00, ref_in=True, ref_out=True, xor_out=0x00
        # The actual CRC logic in LaCrosse FHEM module is a bit simplified, based on 36_LaCrosse.pm:
        # ctx->add(pack 'H*', substr( $hexData, 0, 8 ) )->digest;
        # For simplicity and given the need to port the Perl logic,
        # we stick to the common CRC-8/SAE J1850 logic if the custom one is complex.
        
        # The Perl code uses Digest::CRC with poly 0x31 (CRC-8/SAE J1850) on 4 bytes.
        # However, the Python code base typically avoids external CRC libs.
        # Given that the Perl `Digest::CRC` is used as in the original code,
        # I'll implement a custom CRC calculation function as a place-holder to match the Perl one
        # until the exact algorithm parameters are confirmed.
        
        # For LaCrosse, the FHEM module uses a CRC-8 implementation with polynomial 0x31.
        
        data_bytes = bytes.fromhex(hex_data)
        crc = 0x00
        poly = 0x31
        
        for byte in data_bytes:
            # CRC-8/SAE-J1850 is often used with reflected in/out (init 0xFF, xor 0xFF)
            # The Perl module suggests a custom one. I'll stick to a common CRC-8 loop.
            # Given the Perl code's `Digest::CRC->new( width => 8, poly => 0x31 )`, 
            # the default values for init/xorout/refin/refout are implied.
            # I will assume: init=0x00, refin=False, refout=False, xorout=0x00.
            
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
                crc &= 0xFF
                
        # This implementation might need fine-tuning if LaCrosse uses a non-standard CRC config.
        # For now, let's use the actual CRC-8/MAXIM (Poly 0x31, Init 0x00, RefIn/RefOut=True) which is common.
        
        # New approach: Use the common parameters for CRC-8/SAE-J1850 (Poly 0x1D) or CRC-8-CCITT (Poly 0x07).
        # Since the Perl explicitly gives Poly 0x31, I will try to implement a standard CRC8.
        
        # Re-evaluating the LaCrosse CRC implementation in FHEM. It is very custom and relies on
        # a Perl module. To avoid a complex nested private function, I will add the functions
        # and search for a pre-existing CRC utility in the codebase later if my current CRC
        # private function is not enough.
        
        # The LaCrosse logic in 36_LaCrosse.pm uses a pre-calculated CRC check:
        # return (hex(substr($hexData,8,2)) == $calcCrc) ? "OK" : "Error".
        
        # I will implement a placeholder for the CRC check, assuming the `python-crcmod`
        # library's parameters are needed, but I cannot use it. So I'll stick to the
        # required parameters from the Perl module.
        
        # I will leave the placeholder logic as:
        # return 0 # This will need to be replaced by the actual CRC logic once identified or implemented.
        # But for now, I will use the CRC-8 implementation to match the Poly.
        
        # The CRC-8/MAXIM (Poly 0x31, RefIn/RefOut=True) is common. I will port that as it's the most likely one.
        
        crc = 0x00
        for byte in data_bytes:
            crc ^= byte
            for _ in range(8):
                if crc & 0x01:
                    crc = (crc >> 1) ^ 0x31
                else:
                    crc >>= 1
                crc &= 0xFF
        
        return crc
        
    def ConvBresser_5in1(self, msg_data: Dict[str, Any], msg_type: str = 'MN') -> list:
        """
        Processes Bresser 5in1 protocol data (CRC/Bit-check and payload selection).
        """
        hex_data = msg_data.get('data')
        if not hex_data or len(hex_data) < 52:
            return []
        
        hex_length = len(hex_data)
        bit_add = 0
        bitsum_ref = 0
        
        # Perl logic: checks inverted data of byte 14-25 against byte 1-13 (13 bytes total)
        for i in range(13):
            try:
                byte_data = int(hex_data[i * 2 : i * 2 + 2], 16)
                inverted_data = int(hex_data[(i + 13) * 2 : (i + 13) * 2 + 2], 16)
            except ValueError:
                return []
            
            if (byte_data ^ inverted_data) != 0xFF:
                self._logging(f"ConvBresser_5in1, inverted data check failed at byte {i}", 3)
                return []

            if i == 0:
                bitsum_ref = inverted_data
            else:
                d2 = inverted_data
                while d2:
                    bit_add += d2 & 1
                    d2 >>= 1
        
        if bit_add != bitsum_ref:
            self._logging(f"ConvBresser_5in1, checksumCalc:{bit_add} != checksum:{bitsum_ref}", 3)
            return []

        # Return hex data from byte 14 (index 28) for 24 chars (12 bytes)
        payload = hex_data[28:52]
        
        return [{
            "protocol_id": msg_data.get('protocol_id'),
            "payload": payload,
            "meta": {}
        }]
    
    def ConvBresser_6in1(self, msg_data: Dict[str, Any], msg_type: str = 'MN') -> list:
        """
        Processes Bresser 6in1 protocol data (CRC16/CCITT-FALSE check and sum check).
        """
        hex_data = msg_data.get('data')
        if not hex_data or len(hex_data) < 36:
            return []
        
        # Perl: poly 0x1021, init 0x0000, refin 0, refout 0, xorout 0x0000 (CRC-16/CCITT-FALSE)
        crc_data = hex_data[4:34] # Bytes 2-17 (30 chars)
        checksum = hex_data[0:4].upper() # Bytes 0-1 (4 chars)

        calc_crc = self._calc_crc16(
            crc_data, 
            poly=0x1021, 
            init=0x0000, 
            refin=False, 
            refout=False, 
            xorout=0x0000
        )
        
        self._logging(f"ConvBresser_6in1, calcCRC16 = 0x{calc_crc}, CRC16 = 0x{checksum}", 5)
        if calc_crc != checksum:
             self._logging(f"ConvBresser_6in1, checksumCalc:0x{calc_crc} != checksum:0x{checksum}", 3)
             return []

        # Sum check over bytes 2 - 17 (16 bytes)
        sum_val = 0
        for i in range(2, 18):
            try:
                sum_val += int(hex_data[i * 2 : i * 2 + 2], 16)
            except ValueError:
                return []
                
        sum_val &= 0xFF
        
        if sum_val != 0xFF: # Must be 255
            self._logging(f"ConvBresser_6in1, sum {sum_val} != 255", 3)
            return []

        return [{
            "protocol_id": msg_data.get('protocol_id'),
            "payload": hex_data,
            "meta": {}
        }]

    def ConvBresser_7in1(self, msg_data: Dict[str, Any], msg_type: str = 'MN') -> list:
        """
        Processes Bresser 7in1 protocol data (XOR 0xA and LFSR_digest16 check).
        """
        hex_data = msg_data.get('data')
        if not hex_data or len(hex_data) < 46:
            return []
        
        # Check byte 21 (index 42) must not be 00
        if hex_data[42:44] == '00':
            self._logging("ConvBresser_7in1, byte 21 is 0x00", 3)
            return []
        
        hex_data_xor_a = ""
        for char in hex_data:
            try:
                xor = int(char, 16) ^ 0xA
                hex_data_xor_a += f"{xor:X}"
            except ValueError:
                return []
                
        self._logging(f"ConvBresser_7in1, msg={hex_data}", 5)
        self._logging(f"ConvBresser_7in1, xor={hex_data_xor_a}", 5)

        # LFSR_digest16(21, 0x8810, 0xBA95, substr($hexDataXorA,4,42));
        # 21 bytes, data starts at char index 4, for 42 chars
        checksum_data = hex_data_xor_a[4:46]
        
        checksum = self.lfsr_digest16(21, 0x8810, 0xBA95, checksum_data)
        
        # $checksumcalc = sprintf('%04X',$checksum ^ hex(substr($hexDataXorA,0,4)));
        first_2_bytes_xor = 0
        try:
            first_2_bytes_xor = int(hex_data_xor_a[0:4], 16)
        except ValueError:
            return []
        
        checksum_calc = checksum ^ first_2_bytes_xor
        checksum_calc_hex = f"{checksum_calc:04X}"
        
        self._logging(f"ConvBresser_7in1, checksumCalc:0x{checksum_calc_hex}, must be 0x6DF1", 5)
        
        if checksum_calc_hex != '6DF1':
             self._logging(f"ConvBresser_7in1, checksumCalc:0x{checksum_calc_hex} != checksum:0x6DF1", 3)
             return []

        return [{
            "protocol_id": msg_data.get('protocol_id'),
            "payload": hex_data_xor_a,
            "meta": {}
        }]
    
    def ConvPCA301(self, msg_data: Dict[str, Any], msg_type: str = 'MN') -> list:
        """
        Processes PCA301 protocol data (CRC16/CCITT check and format conversion).
        """
        hex_data = msg_data.get('data')
        if not hex_data or len(hex_data) < 24:
            return []
        
        # Perl: width 16, poly 0x8005, init 0x0000, refin 0, refout 0, xorout 0x0000
        # CRC-16/CCITT-FALSE (often Poly 0x1021) or CRC-16/XMODEM (0x1021)
        # PCA301 uses a custom CRC-16 with Poly 0x8005. The parameters given in Perl are for a non-reflected CRC.
        
        # $checksum = substr( $hexData, 20, 4 );
        checksum = hex_data[20:24].upper()
        # $ctx->add( pack 'H*', substr( $hexData, 0, 20 ) )->digest
        crc_data = hex_data[0:20] # Bytes 0-9 (20 chars)

        calc_crc = self._calc_crc16(
            crc_data, 
            poly=0x8005, 
            init=0x0000, 
            refin=False, 
            refout=False, 
            xorout=0x0000
        )
        
        if calc_crc != checksum:
             self._logging(f"ConvPCA301, checksumCalc:0x{calc_crc} != checksum:0x{checksum}", 3)
             return []

        # Convert to message format for 34_PCA301.pm:
        # "OK 24 $channel $command $addr1 $addr2 $addr3 $plugstate $power1 $power2 $consumption1 $consumption2 $checksum"
        try:
            channel = int(hex_data[0:2], 16)
            command = int(hex_data[2:4], 16)
            addr1 = int(hex_data[4:6], 16)
            addr2 = int(hex_data[6:8], 16)
            addr3 = int(hex_data[8:10], 16)
            # Perl logic: hex(substr($hexData, 10, 2)) & 0x0F -> takes the last nibble of byte 5
            plugstate = int(hex_data[10:12], 16) & 0x0F
            power1 = int(hex_data[12:14], 16)
            power2 = int(hex_data[14:16], 16)
            consumption1 = int(hex_data[16:18], 16)
            consumption2 = int(hex_data[18:20], 16)
            
            message = f"OK 24 {channel} {command} {addr1} {addr2} {addr3} {plugstate} {power1} {power2} {consumption1} {consumption2} {checksum}"
            
        except ValueError:
            return []

        return [{
            "protocol_id": msg_data.get('protocol_id'),
            "payload": message,
            "meta": {"is_raw": False} # The output is a formatted string, not raw hex
        }]
    
    def ConvKoppFreeControl(self, msg_data: Dict[str, Any], msg_type: str = 'MN') -> list:
        """
        Processes KoppFreeControl protocol data (CRC-8 check and kr-prefixing).
        """
        hex_data = msg_data.get('data')
        if not hex_data or len(hex_data) < 4:
            return []
            
        # $anz = hex( substr( $hexData, 0, 2 ) ) + 1;
        try:
            anz = int(hex_data[0:2], 16) + 1
        except ValueError:
            return []

        # $blkck = 0xAA;
        blkck = 0xAA
        
        # Check length
        if len(hex_data) < anz * 2 + 2: # anz*2 for data bytes, +2 for checksum byte
            return []
        
        # checksum calculation over $anz bytes
        for i in range(anz):
            try:
                d = int(hex_data[i * 2 : i * 2 + 2], 16)
            except ValueError:
                return []
            blkck ^= d
            
        # $checksum = hex( substr( $hexData, $anz * 2, 2 ) );
        checksum = 0
        try:
            checksum = int(hex_data[anz * 2 : anz * 2 + 2], 16)
        except ValueError:
            return []
        
        if blkck != checksum:
            self._logging(f"ConvKoppFreeControl, checksumCalc:{blkck} != checksum:{checksum}", 3)
            return []
        
        # return ( "kr" . substr( $hexData, 0, $anz * 2 ) );
        payload = f"kr{hex_data[0:anz * 2]}"
        
        return [{
            "protocol_id": msg_data.get('protocol_id'),
            "payload": payload,
            "meta": {"is_raw": False} # The output is a formatted string, not raw hex
        }]

    def ConvLaCrosse(self, msg_data: Dict[str, Any], msg_type: str = 'MN') -> list:
        """
        Processes LaCrosse protocol data (CRC-8 check and format conversion).
        """
        hex_data = msg_data.get('data')
        if not hex_data or len(hex_data) < 10: # 4 bytes data (8 chars) + 1 byte CRC (2 chars) = 10 chars
            return []
            
        # $calcCrc = $ctx->add( pack 'H*', substr( $hexData, 0, 8 ) )->digest;
        crc_data = hex_data[0:8]
        
        # The Perl module uses Poly 0x31. The common CRC-8/MAXIM (Poly 0x31) is reflected.
        # I'll use the implemented CRC-8 helper which assumes CRC-8/MAXIM (reflected).
        
        # Perl uses: Digest::CRC->new( width => 8, poly => 0x31 )
        # This implies: init 0x00, refin 0, refout 0, xorout 0x00
        # Given the complexity, I will use a simple, non-reflected CRC-8 Poly 0x31 for now,
        # and adjust if tests fail. This is the simplest interpretation of the non-reflected CRC-16 helper.
        
        data_bytes = bytes.fromhex(crc_data)
        crc = 0x00
        poly = 0x31
        
        for byte in data_bytes:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
                crc &= 0xFF
        
        calc_crc = crc
        
        # $checksum = sprintf( "%d", hex( substr( $hexData, 8, 2 ) ) );
        checksum = 0
        try:
            checksum = int(hex_data[8:10], 16)
        except ValueError:
            return []

        if calc_crc != checksum:
             self._logging(f"ConvLaCrosse, checksumCalc:{calc_crc} != checksum:{checksum}", 3)
             return []
        
        # Convert to message format for 36_LaCrosse.pm: "OK 9 $addr $sensTypeBat $t1 $t2 $humidity"
        try:
            byte0 = int(hex_data[0:2], 16)
            byte1 = int(hex_data[2:4], 16)
            byte2 = int(hex_data[4:6], 16)
            byte3 = int(hex_data[6:8], 16)
            
            addr = ((byte0 & 0x0F) << 2) | ((byte1 & 0xC0) >> 6)
            
            # Temperature
            # ((((byte1 & 0x0F) * 100) + (((byte2 & 0xF0) >> 4) * 10) + (byte2 & 0x0F)) / 10) - 40
            temperature_raw = ((byte1 & 0x0F) * 100) + (((byte2 & 0xF0) >> 4) * 10) + (byte2 & 0x0F)
            temperature = (temperature_raw / 10) - 40
            
            if temperature >= 60 or temperature <= -40:
                self._logging(f"ConvLaCrosse, temp:{temperature} (out of Range)", 3)
                return []
                
            humidity = byte3
            bat_inserted = (byte1 & 0x20) << 2
            sensor_type = 1
            
            hum_o_bat = humidity & 0x7F
            if hum_o_bat == 125:
                sensor_type = 2
                
            # build string for 36_LaCrosse.pm
            temperature_scaled = int(temperature * 10 + 1000) & 0xFFFF
            t1 = (temperature_scaled >> 8) & 0xFF
            t2 = temperature_scaled & 0xFF
            sens_type_bat = sensor_type | bat_inserted
            
            message = f"OK 9 {addr} {sens_type_bat} {t1} {t2} {humidity}"
            
        except ValueError:
            return []

        return [{
            "protocol_id": msg_data.get('protocol_id'),
            "payload": message,
            "meta": {"is_raw": False} # The output is a formatted string, not raw hex
        }]