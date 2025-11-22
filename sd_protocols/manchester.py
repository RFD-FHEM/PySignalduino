
"""
Manchester encoding/decoding and protocol-specific signal handlers.

This module contains a mixin class with Manchester-format signal processing
methods. Manchester encoding is used by various radio frequency protocols
for robust signal transmission.

The mcBit2* methods are output handlers that convert Manchester-encoded
bit data into protocol-specific message formats.
"""


from __future__ import annotations

import logging
from typing import Any, Dict, Iterable


# from signalduino.types import DecodedMessage, RawFrame


class ManchesterMixin:
    """Mixin providing Manchester signal encoding/decoding methods.
    
    Manchester signals represent binary data where:
    - 0 is represented as "10" (high-to-low transition)
    - 1 is represented as "01" (low-to-high transition)
    
    Methods in this mixin handle protocol-specific variations of Manchester
    encoding and conversion to hex or other output formats.
    """
    
    def _convert_mc_hex_to_bits(self, name: str, raw_hex: str, polarity_invert: bool, hlen: int) -> tuple[int, str | None]:
        """Converts raw hex data to a bit string, applying polarity inversion if necessary.
        
        This encapsulates the logic from Perl lines 2851-2876.
        
        Args:
            name: Device name for logging.
            raw_hex: The raw data as hex string (D=...).
            polarity_invert: Whether to invert the hex string before conversion.
            hlen: Length of the hex string.
            
        Returns:
            Tuple: (1, bit_string) on success or (-1, error_message) on failure.
        """
        blen = hlen * 4
        
        if polarity_invert:
            # Perl: $rawDataInverted =~ tr/0123456789ABCDEF/FEDCBA9876543210/;
            raw_hex_to_use = raw_hex.translate(str.maketrans('0123456789ABCDEF', 'FEDCBA9876543210'))
        else:
            raw_hex_to_use = raw_hex
            
        # Perl: unpack("B$blen", pack("H$hlen", $rawData))
        try:
            bit_data = self.hex_to_bin_str(raw_hex_to_use, blen)
            self._logging(f"{name}: extracted data {bit_data} (bin)", 5)
            return (1, bit_data)
        except Exception as e:
            self._logging(f"{name}: Error during hex to bin conversion: {e}", 3)
            return (-1, f"Hex to bin conversion failed: {e}")

    def _demodulate_mc_data(self, name: str, protocol_id: int, clock: int, raw_hex: str, mcbitnum: int, messagetype: str, version: str | None) -> tuple[int, str, dict[str, Any]]:
        """
        Performs common MC checks (clock/length/polarity/conversion) and delegates final decoding.
        
        This encapsulates the logic from SIGNALduino_Parse_MC (lines 2854-2917).
        
        Args:
            name: Device name for logging.
            protocol_id: The ID of the protocol being tested.
            clock: The clock value (C=...).
            raw_hex: The raw data as hex string (D=...).
            mcbitnum: The expected bit length (L=...).
            messagetype: The message type ('MC' or 'Mc').
            version: The firmware version string.
            
        Returns:
            List of tuples: [(rcode, dmsg, metadata)] where rcode is 1 on success.
        """
        from sd_protocols import SDProtocols
        
        # 1. Clock/Length Check (Perl lines 2857-2859)
        length_min = self.check_property(protocol_id, 'length_min', -1)
        if mcbitnum < length_min:
            self._logging(f"{name}: Parse_MC, bit_length {mcbitnum} too short (min {length_min})", 5)
            return ( -1, 'message is too short', {})

        clockrange = self.get_property(protocol_id, 'clockrange')
        if clockrange and len(clockrange) >= 2:
            clock_min, clock_max = clockrange, clockrange
            if not (clock > clock_min and clock < clock_max):
                self._logging(f"{name}: Parse_MC, clock {clock} not in range ({clock_min}..{clock_max})", 5)
                return (-1, 'clock out of range', {})
        
        self._logging(f"{name}: Parse_MC, clock and min length matched", 5)

        # 2. Polarity Check (Perl lines 2865-2871)
        polarity_invert = (self.check_property(protocol_id, 'polarity', '') == 'invert')
        self._logging(f"{name}: polarityInvert={polarity_invert}", 5)
        
        if messagetype == 'Mc' or (version and version[:6] == 'V 3.2.'):
            polarity_invert = polarity_invert ^ 1
            self._logging(f"{name}: polarityInvert toggled to {polarity_invert}", 5)

        # 3. Convert Hex to Bit Data (Perl lines 2873-2878)
        hlen = len(raw_hex)
        rcode, bit_data = self._convert_mc_hex_to_bits(name, raw_hex, polarity_invert, hlen)
        if rcode == -1:
            return (rcode, bit_data, {})

        # 4. Call protocol-specific method (Perl lines 2880-2915)
        method_name_full = self.get_property(protocol_id, 'method')
        
        if not method_name_full:
            self._logging(f"{name}: Parse_MC, Error: Unknown method referenced by '{protocol_id}'", 5)
            return [(-1, 'Protocol method not defined', {})]
            
        # Extract method name part, assuming format 'module.method_name' or just 'method_name'
        method_name = method_name_full.split('.')[-1]
        
        if hasattr(self, method_name) and callable(getattr(self, method_name)):
            method_func = getattr(self, method_name)
            # Perl call: $method->($hash->{protocolObject},$name,$bitData,$id,$mcbitnum)
            # Python call: method_func(self, name, bit_data, protocol_id, len(bit_data))
            
            # Note: mcbitnum passed here is the length of the *decoded* bit string, which is what Perl uses as the 5th argument.
            rcode, res = method_func(self, name, bit_data, protocol_id, len(bit_data))
        else:
            self._logging(f"{name}: Parse_MC, Error: Unknown method {method_name} referenced by '{method_name_full}'. Please define it or check protocol configuration.", 5)
            return (-1, f'Unknown protocol method {method_name_full}', {})

        if rcode == -1:
            res = res if res is not None else 'Decoding failed'
            self._logging(f"{name}: Parse_MC, protocol does not match return from method: ({res})", 5)
            return (-1, res, {})
        
        # 5. Formatting $dmsg (Perl lines 2888-2889)
        preamble = self.check_property(protocol_id, 'preamble', '')
        dmsg = f"{preamble}{res}"
        
        self._logging(f"{name}: Parse_MC, Decoded payload: {res}", 4)
        
        metadata = {
            "protocol_id": protocol_id,
            "rssi": None,
            "freq_afc": None,
        }
        
        self._logging(f"{name}: Parse_MC, successfully decoded MC protocol id {protocol_id} dmsg {dmsg}", 4)
        
        return (1, dmsg, metadata)


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
        
        self._logging(f"lib/mcBitFunkbus, {name} Funkbus: len={len(s_bitmsg)} parity={parity} result={result} chk={hex_data}", 4)
        
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
        
        # Wenn kein Sync-Pattern gefunden wird, aber die Länge ok ist, konvertiere trotzdem
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        ashex = self.bin_str_2_hex_str(bit_data)
        return (1, ashex)

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
        This implementation includes duplicate message detection based on Perl logic.
        
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
        
        preamble_pos = -1
        message_end = -1
        retmsg = ''
        messages = []
        i = 1
        
        # Perl pattern for initial sync: if ($bitData =~ m/(1{9}101)/xms )
        # Python equivalent for the start pattern is hard to use directly with index()
        # Using string search for the known start sequence, similar to Perl's $+ offset:
        # We look for '111111111101' which is the end pattern in Perl's loop,
        # but the logic seems to start *after* the preamble '1{9}101' which is 10 bits long.
        # Since the Perl code starts searching from $preamble_pos, we need to find that start first.
        # Let's assume the initial sync is 10 bits: '1111111111' or similar, followed by '101'.
        # Perl uses: if ($bitData =~ m/(1{9}101)/xms ) -> $preamble_pos=$+; which is the position *after* the match.
        # The match is 10 bits long.
        # Let's search for the end pattern '1111111111101' (13 bits) as a message separator in a do-while loop,
        # starting the search from a point determined by the first pattern match.
        
        # In Perl, the first check finds the start: $preamble_pos = index($bitData,'1111111111101',$preamble_pos);
        # It seems the first '1{9}101' is used to *initialize* $preamble_pos, but the loop logic is critical.
        # The loop starts by *finding* the end pattern '1111111111101' starting from the current $preamble_pos.
        # A simpler interpretation matching the Python structure is to look for the first valid *message* start.
        # Given the Python structure, the direct port of the Perl do-while loop structure is needed.
        
        # Find first occurrence of the end pattern, which acts as a message separator/end marker in the loop.
        # The initial $preamble_pos is set by the regex match (which is not directly copied here for simplicity,
        # using the Perl logic's reliance on index() inside the loop).
        
        # Replicating Perl's setup: find the first '1{9}101' to set the starting point.
        # In Perl: if ($bitData =~ m/(1{9}101)/xms ) { $preamble_pos=$+; ... }
        start_match_pos = bit_data.find('111111111101')
        if start_match_pos == -1:
            return (-1, 'sync not found')
        preamble_pos = start_match_pos + 12 # Position after the *first* end pattern found.
        
        # Replicating the do-while loop logic
        # Perl: do { ... } while ($message_end < $mcbitnum);
        # The loop iterates as long as the found end ($message_end) is before the total length ($mcbitnum).

        while message_end < mcbitnum:
            # Perl: $message_end = index($bitData,'1111111111101',$preamble_pos);
            message_end = bit_data.find('1111111111101', preamble_pos)
            
            if message_end < preamble_pos:
                message_end = mcbitnum # If not found, use the total length as the end marker
            
            message_length = message_end - preamble_pos
            
            part_str = bit_data[preamble_pos:message_end]
            
            self._logging(f"{name}: lib/mcBit2TFA, message start({i})={preamble_pos} end={message_end} with length={message_length}", 4)
            self._logging(f"{name}: lib/mcBit2TFA, message part({i})={part_str}", 5)
            
            # Perl: my ($rcode, $rtxt) = $self->LengthInRange($id, $message_length);
            rcode, rtxt = self.length_in_range(protocol_id, message_length)
            
            if rcode: # if ($rcode)
                hex_val = self.bin_str_2_hex_str(part_str)
                messages.append(hex_val)
                self._logging(f"{name}: lib/mcBit2TFA, message part({i})={hex_val}", 4)
            else: # else { $retmsg = q[, ] . $rtxt; }
                retmsg = ', ' + rtxt
            
            # Perl: $preamble_pos=index($bitData,'1101',$message_end)+4;
            # The Perl code searches for '1101' after the end and adds 4. This looks like another sync pattern.
            preamble_pos = bit_data.find('1101', message_end)
            if preamble_pos != -1:
                preamble_pos += 4
            else:
                # If the next sync '1101' isn't found, stop looping to prevent infinite loop if end wasn't mcbitnum.
                message_end = mcbitnum
            
            i += 1
        
        # Perl: return ($i,q[loop error, please report this data $bitData]) if ($i==10);
        if i == 10:
            return (-1, f'loop error, please report this data {bit_data}')
            
        # Perl: my %seen; my @dupmessages = map { 1==$seen{$_}++ ? $_ : () } @messages;
        seen = {}
        dupmessages = []
        for msg in messages:
            if seen.get(msg, 0) == 1:
                dupmessages.append(msg)
            seen[msg] = seen.get(msg, 0) + 1
            
        # Perl: if (scalar(@dupmessages) > 0 ) { return (1,$dupmessages); } else { return (-1,qq[ no duplicate found$retmsg]); }
        if len(dupmessages) > 0:
            hex_msg = dupmessages[0] # Return the first duplicate found
            self._logging(f"{name}: TFA converted to hex (duplicate found): {hex_msg}", 4)
            return (1, hex_msg)
        else:
            return (-1, f' no duplicate found{retmsg}')
            
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
        
        self._logging(f"lib/mcBitFunkbus, {name} Funkbus: len={len(s_bitmsg)} parity={parity} result={result} chk={hex_data}", 4)
        
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
        
        # Wenn kein Sync-Pattern gefunden wird, aber die Länge ok ist, konvertiere trotzdem
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        ashex = self.bin_str_2_hex_str(bit_data)
        return (1, ashex)

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
        
        self._logging(f"lib/mcBitFunkbus, {name} Funkbus: len={len(s_bitmsg)} parity={parity} result={result} chk={hex_data}", 4)
        
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
        
        # Wenn kein Sync-Pattern gefunden wird, aber die Länge ok ist, konvertiere trotzdem
        length_min = self.check_property(protocol_id, "length_min", -1)
        if mcbitnum < length_min:
            return (-1, ' message is to short')
        
        length_max = self.get_property(protocol_id, "length_max")
        if length_max is not None and mcbitnum > length_max:
            return (-1, ' message is to long')
        
        ashex = self.bin_str_2_hex_str(bit_data)
        return (1, ashex)

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
        
