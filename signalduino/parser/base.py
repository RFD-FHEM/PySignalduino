"""Shared helpers for parsing firmware messages."""

from __future__ import annotations

import re
from typing import Optional, List, Tuple

from ..exceptions import SignalduinoParserError

_STX_ETX = re.compile(r"^\x02(M[sSuUcCNOo];.*;)\x03$")


def decompress_payload(compressed_payload: str) -> str:
    """
    Decompresses a compressed Signalduino payload (Mred=1).

    The Perl logic is in 00_SIGNALduino.pm around line 1784.
    """
    # Check if the message is actually compressed (contains high-bit chars)
    # The Perl logic runs a decompression loop on any MS/MU/MO, but the compression
    # logic only works if high-bit chars are present, otherwise it mangles standard fields.
    # We will only run decompression if we detect at least one high-bit character (ord > 127)
    # in any part that is not the header (first 3 chars).
    if not compressed_payload.upper().startswith(("MS;", "MU;", "MO;", "MN;")):
        return compressed_payload
    
    # Check for compression marker (a character with high-bit set)
    is_compressed = False
    if len(compressed_payload) > 3:
        for char in compressed_payload[3:]:
            if ord(char) > 127:
                is_compressed = True
                break

    if not is_compressed:
        return compressed_payload

    # Split message parts by ';'
    # This split is problematic if ';' exists in the D= binary payload.
    # The fix is to merge all consecutive sections starting with 'D' or 'd' into one.
    msg_parts: List[str] = compressed_payload.split(';')
    decompressed_parts: List[str] = []

    i = 0
    while i < len(msg_parts):
        msg_part = msg_parts[i]
        
        if not msg_part:
            i += 1
            continue
        
        m0 = msg_part[0] if len(msg_part) > 0 else ''
        m1 = msg_part[1:] if len(msg_part) > 1 else ''
        mnr0 = ord(m0) if m0 else 0

        # --- Data Reduction logic (D= or d= - Perl line 1819) ---
        if m0 in ('D', 'd'):
            
            # Merge consecutive split parts that likely belong to the D= payload
            current_data_payload = msg_part
            j = i + 1
            while j < len(msg_parts):
                next_part = msg_parts[j]
                if not next_part:
                    j += 1
                    continue
                
                # Check if next_part looks like a valid field which breaks the D= sequence
                # Valid fields start with a letter.
                # Special case: Fxx (1-2 hex digits) -> F=...
                # Special case: C=, R=, Px=
                
                # Heuristic: If it starts with a letter and is short (likely a command/field)
                # or matches specific patterns, we stop merging.
                # However, binary data can also look like this.
                # The most robust check based on Perl code is to check for specific field patterns.
                
                # Perl fields:
                # P[0-7]=...
                # C=... / S=... (length 1 value)
                # o... / m...
                # Xyy (1 letter + 1-2 hex digits) -> X=dec(yy)
                # X... (1 letter + anything) -> X=...
                
                next_m0 = next_part[0] if next_part else ''
                next_m1 = next_part[1:] if len(next_part) > 1 else ''
                
                is_field = False
                
                if not next_m0.isalpha():
                     pass # Not a field start
                elif next_m0 in ('D', 'd'):
                     # Start of a NEW data block (unlikely in valid compressed stream but possible)
                     is_field = True
                elif ord(next_m0) > 127:
                     # Pattern definition
                     is_field = True
                elif next_m0 == 'M':
                     is_field = True
                elif next_m0 in ('C', 'S') and len(next_m1) == 1:
                     is_field = True
                elif next_m0 in ('o', 'm'):
                     is_field = True
                elif re.match(r"^[0-9A-F]{1,2}$", next_m1.upper()):
                     # Matches Xyy format (e.g. F64)
                     is_field = True
                elif next_m0.isalnum() and '=' in next_part: # R=..., C=...
                     is_field = True

                if is_field:
                    break
                    
                current_data_payload += ';' + next_part
                j += 1
            
            # The actual content for decompressing is EVERYTHING after the initial D/d.
            m1 = current_data_payload[1:]
            m0 = current_data_payload[0] # Corrected: m0 must be 'D' or 'd'
            i = j - 1 # Update main loop counter to skip merged parts
            
            part_d = ""
            # Perl logic: 1823-1827
            for char_d in m1:
                char_ord = ord(char_d)
                m_h = (char_ord >> 4) & 0xF
                m_l = char_ord & 0x7
                part_d += f"{m_h}{m_l}"
            
            # Perl logic: 1829-1831 (remove last digit if odd number of digits - when d= for MU)
            if m0 == 'd':
                part_d = part_d[:-1]
            
            # Perl logic: 1832 (remove leading 8)
            if part_d.startswith('8'):
                part_d = part_d[1:]
            
            decompressed_parts.append(f"D={part_d}")
            
        # --- M-part (M, m) ---
        elif m0 == 'M':
            # M-part is always uc in Perl's decompressed message
            decompressed_parts.append(f"M{m1.upper()}")
        
        # --- Pattern compression logic (mnr0 > 127 - Perl line 1801) ---
        elif mnr0 > 127:
            # Perl logic: 1802-1814
            decompressed_part = f"P{mnr0 & 7}="
            # In Perl, m1 is a 2-char string. 
            if len(m1) == 2:
                # Assuming the two characters contain the high and low pattern bytes
                # We use ord() on single characters now (after encoding fix)
                m_l_ord = ord(m1[0])
                m_h_ord = ord(m1[1])
                
                m_l = m_l_ord & 127
                m_h = m_h_ord & 127

                if (mnr0 & 0b00100000) != 0: # Vorzeichen 32
                    decompressed_part += "-"
                if (mnr0 & 0b00010000):      # Bit 7 von Pattern low 16
                    m_l += 128
                
                # mH * 256 + mL is the final pulse length
                decompressed_part += str(m_h * 256 + m_l)
            decompressed_parts.append(decompressed_part)

        # --- C/S Pulse compression (C= or S= - Perl line 1836) ---
        elif m0 in ('C', 'S') and len(m1) == 1:
            decompressed_parts.append(f"{m0}P={m1}")

        # --- o/m fields (Perl line 1840) ---
        elif m0 in ('o', 'm'):
            decompressed_parts.append(f"{m0}{m1}")

        # --- Hex to Dec conversion for 1 or 2 Hex Digits (Perl line 1842) ---
        elif m1 and re.match(r"^[0-9A-F]{1,2}$", m1.upper()):
             decompressed_parts.append(f"{m0}={int(m1, 16)}")

        # --- Other fields (R=, B=, t=, etc. - Perl line 1845) ---
        elif m0.isalnum():
            decompressed_parts.append(f"{m0}{'=' if m1 else ''}{m1}")
        
        i += 1

    # The final message is concatenated and the trailing semicolon is added
    return ";".join(decompressed_parts) + ";"


def extract_payload(line: str) -> Optional[str]:
    """
    Return the payload between STX/ETX markers if present.

    Includes logic for decompressing the Mred=1 format.
    """
    if not line:
        return None
        
    line_stripped = line.strip()
    match = _STX_ETX.match(line_stripped)
    
    if not match:
        return None
    
    payload = match.group(1)

    # All framed messages are passed through the decompression logic in Perl (L1784)
    # The result is the final payload without STX/ETX, which matches the required output.
    return decompress_payload(payload)


def ensure_message_type(payload: str, expected: str) -> None:
    if not payload.upper().startswith(expected.upper()):
        raise SignalduinoParserError(f"expected {expected} message, got {payload[:2]}")


def calc_rssi(raw_rssi: int) -> float:
    """Match Perl's RSSI conversion formula."""

    if raw_rssi >= 128:
        return ((raw_rssi - 256) / 2) - 74
    return (raw_rssi / 2) - 74


def calc_afc(raw_afc: int) -> float:
    """Match Perl's AFC conversion formula."""

    if raw_afc >= 128:
        return (raw_afc - 256) / 2
    return raw_afc / 2
