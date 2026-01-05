from __future__ import annotations
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

from .pattern_utils import pattern_exists, is_in_tolerance

class MessageUnsyncedMixin:
    """Mixin providing Message Unsynced (MU) signal decoding methods."""

    def demodulate_mu(self, msg_data: Dict[str, Any], msg_type: str = "MU") -> List[Dict[str, Any]]:
        """
        Demodulates a Message Unsynced (MU) message.
        
        Args:
            msg_data: The parsed message data including P#, D, CP, etc.
            msg_type: The message type (e.g., "MU").
            
        Returns:
            List of decoded messages.
        """
        raw_data = msg_data.get('data', '')
        if not raw_data:
            self._logging(f"MU Demod: Invalid rawData D=: {raw_data}", 3)
            return []

        # Parse P# patterns
        patterns_raw = {}
        for key, val in msg_data.items():
            if key.startswith('P') and key[1:].isdigit():
                try:
                    pidx = str(int(key[1:]))
                    patterns_raw[pidx] = float(val)
                except ValueError:
                    pass
        
        if not patterns_raw:
             # Some MU messages might not have patterns if they rely purely on hardcoded checks, 
             # but usually they do. 
             pass

        decoded_messages = []
        
        # Iterate over protocols with 'clockabs' property (MU protocols)
        mu_protocols = self.get_keys('clockabs')
        
        for pid in mu_protocols:
            if not self.check_property(pid, 'active', True):
                continue
            self._logging(f"MU checking PID {pid}", 5)
            # Prepare working copy of raw_data and patterns
            # (Perl does this per protocol iteration because filterfunc might modify them)
            current_raw_data = raw_data
            current_patterns_raw = patterns_raw.copy()
            
            # TODO: filterfunc support
            # if defined($hash->{protocolObject}->getProperty($id,'filterfunc')) ...
            
            clock_abs = float(self.check_property(pid, 'clockabs', 1))
            
            # Normalize patterns
            patterns = {}
            for pidx, pval in current_patterns_raw.items():
                patterns[pidx] = round(pval / clock_abs, 1)
                
            # Check Start Pattern
            start_pattern = self.get_property(pid, 'start')
            start_str = ''
            message_start = 0
            
            if start_pattern and isinstance(start_pattern, list):
                # Perl: if (($startStr=SIGNALduino_PatternExists(...)) eq -1)
                pstr = pattern_exists([float(x) for x in start_pattern], patterns, current_raw_data)
                
                if pstr == -1:
                    # self._logging(f"MU Demod: Protocol {pid} start pattern not found", 5)
                    continue
                
                start_str = str(pstr)
                idx = current_raw_data.find(start_str)
                if idx == -1:
                    continue
                    
                message_start = idx
                # In Perl it slices substr($rawData, $message_start), but later it uses regex on the sliced data.
                # Here we can just note the start or slice it. 
                # Perl: $rawData = substr($rawData, $message_start);
                current_raw_data = current_raw_data[message_start:]
                
            
            # Build Pattern Lookups and Signal Regex
            pattern_lookup = {}
            end_pattern_lookup = {}
            
            signal_regex_parts = []
            match_failed = False
            
            # Check one, zero, float
            for key in ['one', 'zero', 'float']:
                # print(f"DEBUG: Checking {key} for PID {pid}")
                prop_val = self.get_property(pid, key)
                if not prop_val:
                    continue
                
                try:
                    search_pattern = [float(x) for x in prop_val]
                except (ValueError, TypeError):
                    match_failed = True
                    break
                
                symbol_map = {
                    'one': '1',
                    'zero': '0',
                    'float': 'F'
                }
                representation = symbol_map.get(key, '')
                
                pstr = pattern_exists(search_pattern, patterns, current_raw_data)
                
                if pstr != -1:
                    pstr = str(pstr)
                    pattern_lookup[pstr] = representation
                    
                    if len(pstr) > 0:
                        short_pstr = pstr[:-1]
                        if short_pstr not in end_pattern_lookup:
                            end_pattern_lookup[short_pstr] = representation
                    
                    # Build regex part
                    # Perl: if ($key eq "one") { $signalRegex .= $return_text; } else { $signalRegex .= "|$return_text" ... }
                    # This implies One is mandatory or main? Actually Perl logic loop:
                    # for my $key (qw(one zero float) ) ... if ($key eq "one") { ... } else { ... }
                    # This constructs (one_pattern|zero_pattern|float_pattern) but ensures 'one' is first?
                    # Let's just collect valid patterns and join them with OR.
                    signal_regex_parts.append(re.escape(pstr))
                    
                else:
                    if key != 'float':
                        # self._logging(f"MU Demod: Protocol {pid} key {key} not found", 5)
                        match_failed = True
                        break
            
            if match_failed or not signal_regex_parts:
                continue
                
            # Construct Regex
            # Perl: $regex="(?:$startStr)($signalRegex)"; where signalRegex is (one|zero|float){min,}
            
            # Build the base repeating pattern (signal_group_inner)
            # Optimization for catastrophic backtracking (e.g., P61: '12|11' -> '1(2|1)') 
            # Only apply if all parts share the same length and single-character prefix.
            
            unescaped_parts = list(pattern_lookup.keys())
            signal_group_inner = "|".join(signal_regex_parts) # Default: unoptimized
            
            try:
                # Check if optimization is possible (all same length, same prefix, length > 1)
                if unescaped_parts and all(len(p) == len(unescaped_parts[0]) for p in unescaped_parts) and len(unescaped_parts[0]) > 1:
                    first_part = unescaped_parts[0]
                    prefix = first_part[0]
                    
                    if all(p.startswith(prefix) for p in unescaped_parts):
                        suffixes = [p[1:] for p in unescaped_parts]
                        
                        # Reconstruct the inner group: prefix(?:suffix1|suffix2|...)
                        # Note: re.escape is safe even for single characters
                        signal_group_inner = re.escape(prefix) + "(?:" + "|".join(re.escape(s) for s in suffixes) + ")"
                        self._logging(f"MU Demod: Optimized repeating pattern for PID {pid}: {signal_group_inner}", 5)
            except Exception:
                # Fallback to default in case of unexpected pattern data
                pass
                
            # Handle reconstructBit logic for regex end
            reconstruct_part = ""
            if self.get_property(pid, 'reconstructBit') and end_pattern_lookup:
                reconstruct_part = "(?:" + "|".join([re.escape(k) for k in end_pattern_lookup.keys()]) + ")?"
            
            length_min = self.check_property(pid, 'length_min', 0)

            # Note: Python f-string braces need escaping
            regex_pattern = f"(?:{re.escape(start_str)})((?:{signal_group_inner}){{{length_min},}}{reconstruct_part})"

            try:
                # print(f"DEBUG: Compiling regex for {pid}: {regex_pattern[:50]}...")
                matcher = re.compile(regex_pattern)
            except re.error as e:
                self._logging(f"MU Demod: Invalid regex for {pid}: {e}", 3)
                continue
                
            # Perl iterates with /g
            # print(f"DEBUG: Executing finditer for {pid}")
            for match in matcher.finditer(current_raw_data):
                # print(f"DEBUG: Match found for {pid}")
                data_part = match.group(1)
                
                # Check length max
                length_max = self.check_property(pid, 'length_max', None)
                
                # Determine signal width (number of chars per bit)
                # Perl uses unpack "(a$signal_width)*"
                signal_width = 0
                if self.get_property(pid, 'one'):
                    signal_width = len(self.get_property(pid, 'one'))
                
                if signal_width == 0:
                    continue
                    
                # Split data_part into chunks
                chunks = [data_part[i:i+signal_width] for i in range(0, len(data_part), signal_width)]
                
                # Handle the last chunk if it's partial (reconstructBit)
                last_chunk = chunks[-1]
                if len(last_chunk) < signal_width:
                    # It might be a partial chunk
                    pass 
                
                if length_max and len(chunks) > int(length_max):
                    continue
                    
                bit_msg = []
                for chunk in chunks:
                    if chunk in pattern_lookup:
                        bit_msg.append(pattern_lookup[chunk])
                    elif self.get_property(pid, 'reconstructBit') and chunk in end_pattern_lookup:
                        bit_msg.append(end_pattern_lookup[chunk])
                    else:
                        # Should not happen if regex matched, unless regex was too loose
                        pass
                
                # Post Demodulation
                post_demod_method_name = self.check_property(pid, 'postDemodulation', None)
                if post_demod_method_name:
                    method_name = post_demod_method_name.split('.')[-1]
                    if hasattr(self, method_name):
                        method = getattr(self, method_name)
                        bit_msg_ints = [int(b) for b in bit_msg if b in '01'] # Filter 'F'?
                        # Perl passes @bit_msg which contains '0','1','F'. 
                        # postDemodulation usually expects ints 0/1. 
                        # For now assuming 0/1.
                        
                        try:
                            # Convert to ints, handle 'F' if necessary (skip or map)
                            # Most postDemo functions operate on bits.
                            bit_msg_ints = [int(b) for b in bit_msg]
                            rcode, ret_bits = method(f"Protocol_{pid}", bit_msg_ints)
                            if rcode < 1:
                                continue
                            bit_msg = [str(b) for b in ret_bits]
                        except ValueError:
                            pass # Handle non-int bits
                            
                
                # Formatting
                dispatch_bin = int(self.check_property(pid, 'dispatchBin', 0))
                
                # Padding
                pad_with = int(self.check_property(pid, 'paddingbits', 4))
                while len(bit_msg) % pad_with > 0:
                    bit_msg.append('0')
                
                bit_str = "".join(bit_msg)
                
                dmsg = ""
                if dispatch_bin == 1:
                    dmsg = bit_str
                else:
                    dmsg = self.bin_str_2_hex_str(bit_str)
                    if self.check_property(pid, 'remove_zero', 0):
                        dmsg = dmsg.lstrip('0')
                
                preamble = self.check_property(pid, 'preamble', '')
                postamble = self.check_property(pid, 'postamble', '')
                
                final_payload = f"{preamble}{dmsg}{postamble}"
                
                # Module Match (Regex check)
                module_match = self.check_property(pid, 'modulematch')
                if module_match:
                    if not re.search(module_match, final_payload):
                        continue
                        
                decoded_messages.append({
                    "protocol_id": pid,
                    "payload": final_payload,
                    "meta": {
                        "bit_length": len(bit_str),
                        "rssi": msg_data.get('R'),
                        "clock": clock_abs
                    }
                })
                
                # Max repeats check? 
                # Perl: last if ( $nrDispatch == AttrVal($name,'maxMuMsgRepeat', 4))
                # For now we yield all matches.
        
        return decoded_messages
