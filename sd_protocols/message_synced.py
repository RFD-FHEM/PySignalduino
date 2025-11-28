from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from .pattern_utils import pattern_exists

class MessageSyncedMixin:
    """Mixin providing Message Synced (MS) signal decoding methods."""

    def demodulate_ms(self, msg_data: Dict[str, Any], msg_type: str = "MS") -> List[Dict[str, Any]]:
        """
        Demodulates a Message Synced (MS) message.
        
        Args:
            msg_data: The parsed message data including P#, D, CP, etc.
            msg_type: The message type (e.g., "MS").
            
        Returns:
            List of decoded messages.
        """
        raw_data = msg_data.get('data', '')
        # Perl: my $rawData  = _limit_to_number($msg_parts{rawData})
        if not raw_data or not raw_data.isdigit():
            self._logging(f"MS Demod: Invalid rawData D=: {raw_data}", 3)
            return []

        clock_idx_str = msg_data.get('CP', '')
        # Perl: my $clockidx = _limit_to_number($msg_parts{clockidx})
        if not clock_idx_str or not clock_idx_str.isdigit():
            self._logging(f"MS Demod: Invalid CP: {clock_idx_str}", 3)
            return []
        
        clock_idx = int(clock_idx_str)

        sync_idx_str = msg_data.get('SP', '')
        # Perl: my $syncidx  = _limit_to_number($msg_parts{syncidx})
        if not sync_idx_str or not sync_idx_str.isdigit():
            self._logging(f"MS Demod: Invalid SP: {sync_idx_str}", 3)
            return []
        
        # Check RSSI if present
        if 'R' in msg_data:
            rssi_str = msg_data.get('R', '')
            # Perl: $rssi = _limit_to_number($msg_parts{rssi})
            if not rssi_str.isdigit():
                 self._logging(f"MS Demod: Invalid RSSI R=: {rssi_str}", 3)
                 return []

        # Parse P# patterns
        patterns = {}
        for key, val in msg_data.items():
            if key.startswith('P') and key[1:].isdigit():
                try:
                    pidx = str(int(key[1:])) # Keep IDs as strings for pattern_exists
                    patterns[pidx] = float(val)
                except ValueError:
                    pass
        
        str_clock_idx = str(clock_idx)
        if str_clock_idx not in patterns:
            # self._logging(f"MS Demod: CP {clock_idx} not in patterns", 3)
            return []

        clock_abs = abs(patterns[str_clock_idx])
        if clock_abs == 0:
            return []

        # Normalize patterns relative to clock
        # Perl: round($msg_parts{pattern}{$_}/$clockabs,1)
        norm_patterns = {}
        for pidx, pval in patterns.items():
            norm_patterns[pidx] = round(pval / clock_abs, 1)
        
        print(f"DEBUG: Patterns: {patterns}, Clock: {clock_abs}, Norm: {norm_patterns}")

        decoded_messages = []
        
        # Iterate over protocols with 'sync' property
        ms_protocols = self.get_keys('sync') 
        
        for pid in ms_protocols:
            # Check Clock Tolerance
            proto_clock = float(self.check_property(pid, 'clockabs', 0))
            if proto_clock > 0:
                # Perl: SIGNALduino_inTol(prop_clock, clockabs, clockabs*0.30)
                if abs(proto_clock - clock_abs) > (clock_abs * 0.3):
                    print(f"DEBUG: Protocol {pid} clock mismatch: {proto_clock} vs {clock_abs}")
                    continue

            # Check Patterns
            pattern_lookup = {}
            end_pattern_lookup = {} # For reconstructBit
            
            message_start = 0
            match_failed = False
            signal_width = 0
            
            # Pre-fetch properties
            props = {
                'sync': self.get_property(pid, 'sync'),
                'one': self.get_property(pid, 'one'),
                'zero': self.get_property(pid, 'zero'),
                'float': self.get_property(pid, 'float')
            }
            
            if props['one']:
                signal_width = len(props['one'])
            
            for key in ['sync', 'one', 'zero', 'float']:
                search_pattern = props[key]
                if not search_pattern:
                    continue
                
                try:
                    search_pattern = [float(x) for x in search_pattern]
                except (ValueError, TypeError):
                    match_failed = True
                    break

                symbol_map = {
                    'one': '1',
                    'zero': '0',
                    'sync': '', # Sync doesn't map to a data bit in the output
                    'float': 'F'
                }
                representation = symbol_map.get(key, '')

                pstr = pattern_exists(search_pattern, norm_patterns, raw_data)
                
                print(f"DEBUG: Protocol {pid} Key {key} Pattern {search_pattern} Result {pstr}")

                if pstr != -1:
                    pattern_lookup[pstr] = representation
                    
                    if len(pstr) > 0:
                        short_pstr = pstr[:-1]
                        if short_pstr not in end_pattern_lookup:
                            end_pattern_lookup[short_pstr] = representation
                            
                    if key == 'sync':
                        idx = raw_data.find(str(pstr))
                        if idx >= 0:
                            message_start = idx + len(str(pstr))
                        else:
                            # Should not happen if pattern_exists returned success
                            match_failed = True
                            break
                        
                        # Check length min
                        signal_len = len(raw_data)
                        bit_length = (signal_len - message_start) / signal_width if signal_width > 0 else 0
                        length_min = int(self.check_property(pid, 'length_min', -1))
                        
                        if length_min > bit_length:
                            match_failed = True
                            break
                            
                        end_pattern_lookup = {}
                        
                else:
                    if key != 'float':
                        match_failed = True
                        break
            
            if match_failed:
                continue
                
            if not pattern_lookup:
                continue
                
            # Demodulation
            bit_msg = []
            
            for i in range(message_start, len(raw_data), signal_width):
                chunk = raw_data[i : i + signal_width]
                
                if chunk in pattern_lookup:
                    val = pattern_lookup[chunk]
                    if val:
                        bit_msg.append(val)
                elif self.get_property(pid, 'reconstructBit'):
                    check_chunk = chunk[:-1] if len(chunk) == signal_width else chunk
                    
                    if check_chunk in end_pattern_lookup:
                        bit_msg.append(end_pattern_lookup[check_chunk])
                    else:
                        break
                else:
                    break
                    
            if not bit_msg:
                continue
                
            length_range_code, _ = self.length_in_range(pid, len(bit_msg))
            if not length_range_code:
                continue
                
            pad_with = int(self.check_property(pid, 'paddingbits', 4))
            while len(bit_msg) % pad_with > 0:
                bit_msg.append('0')
            
            # Post Demodulation
            post_demod_method_name = self.check_property(pid, 'postDemodulation', None)
            if post_demod_method_name:
                method_name = post_demod_method_name.split('.')[-1]
                if hasattr(self, method_name):
                    method = getattr(self, method_name)
                    # Convert to ints for postDemo methods
                    bit_msg_ints = [int(b) for b in bit_msg]
                    
                    # Call postDemo method
                    # TODO: Handle evalcheck/developId if necessary
                    rcode, ret_bits = method(f"Protocol_{pid}", bit_msg_ints)
                    
                    if rcode < 1:
                        continue
                    
                    if ret_bits:
                        bit_msg = [str(b) for b in ret_bits]

            bit_str = "".join(bit_msg)
            
            try:
                hex_val = f"{int(bit_str, 2):X}"
                dmsg = hex_val
            except ValueError:
                continue
                
            preamble = self.check_property(pid, 'preamble', '')
            postamble = self.check_property(pid, 'postamble', '')
            
            final_payload = f"{preamble}{dmsg}{postamble}"
            
            decoded_messages.append({
                "protocol_id": pid,
                "payload": final_payload,
                "meta": {
                    "bit_length": len(bit_str),
                    "rssi": msg_data.get('R'),
                    "clock": clock_abs
                }
            })
            
        return decoded_messages
