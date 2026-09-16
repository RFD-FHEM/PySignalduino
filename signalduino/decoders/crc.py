"""Checksum algorithms used by the decoder specifications (ADR-006).

FHEM implements its checks inside each client module, so the same CRC-8 turns
up several times in slightly different spellings. Here they live once, as pure
functions over bytes, addressed by name from a specification.

Adding an algorithm means adding a function and one ALGORITHMS entry. Anything
irregular enough that it cannot be expressed as "digest over a byte range,
compared against another byte range" belongs in a custom decoder instead.
"""

from __future__ import annotations

from typing import Callable

ChecksumFunc = Callable[..., int]


def _reflect(value: int, width: int) -> int:
    """Reverses the bit order of ``value`` within ``width`` bits."""
    result = 0
    for _ in range(width):
        result = (result << 1) | (value & 1)
        value >>= 1
    return result


def crc8(data: bytes, poly: int = 0x31, init: int = 0x00,
         reflect_in: bool = False, reflect_out: bool = False,
         xor_out: int = 0x00) -> int:
    """CRC-8 with configurable parameters.

    The default is polynomial 0x31 with initial value 0, neither input nor
    output reflected, which is what the Fine Offset and EuroChron sensors use
    and what Digest::CRC produces for ``width => 8, poly => 0x31`` in FHEM.
    """
    crc = init
    for byte in data:
        if reflect_in:
            byte = _reflect(byte, 8)
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    if reflect_out:
        crc = _reflect(crc, 8)
    return crc ^ xor_out


def crc16(data: bytes, poly: int = 0x8005, init: int = 0xFFFF,
          reflect_in: bool = False, reflect_out: bool = False,
          xor_out: int = 0x0000) -> int:
    """CRC-16 with configurable parameters."""
    crc = init
    for byte in data:
        if reflect_in:
            byte = _reflect(byte, 8)
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    if reflect_out:
        crc = _reflect(crc, 16)
    return crc ^ xor_out


def crc16lsb(data: bytes, poly: int = 0x8810, init: int = 0x0000) -> int:
    """CRC-16 processed least significant bit first.

    Mirrors SD_WS_crc16lsb from 14_SD_WS.pm, used by several weather sensors.
    """
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    return crc & 0xFFFF


def sum8(data: bytes, init: int = 0x00) -> int:
    """Sum of all bytes, truncated to 8 bits."""
    return (init + sum(data)) & 0xFF


def xor8(data: bytes, init: int = 0x00) -> int:
    """XOR over all bytes."""
    result = init
    for byte in data:
        result ^= byte
    return result & 0xFF


def lfsr_digest8(data: bytes, gen: int = 0x31, key: int = 0xF4) -> int:
    """Galois LFSR digest, bits processed most significant first.

    Mirrors the digest used by Bresser style sensors: for every set bit the
    current key is XORed into the sum, and the key advances through the LFSR
    on each bit.
    """
    result = 0
    current = key
    for byte in data:
        for bit in range(7, -1, -1):
            if (byte >> bit) & 1:
                result ^= current
            current = (current >> 1) ^ gen if current & 1 else current >> 1
    return result & 0xFF


def lfsr_digest8_reflect(data: bytes, gen: int = 0x31, key: int = 0xF4) -> int:
    """Galois LFSR digest over the bytes in reverse order, bits least first.

    Mirrors SD_WS_LFSR_digest8_reflect from 14_SD_WS.pm.
    """
    result = 0
    current = key
    for byte in reversed(data):
        for bit in range(8):
            if (byte >> bit) & 1:
                result ^= current
            current = ((current << 1) ^ gen) & 0xFF if current & 0x80 else (current << 1) & 0xFF
    return result & 0xFF


ALGORITHMS: dict[str, ChecksumFunc] = {
    "crc8": crc8,
    "crc16": crc16,
    "crc16lsb": crc16lsb,
    "sum8": sum8,
    "xor8": xor8,
    "lfsr_digest8": lfsr_digest8,
    "lfsr_digest8_reflect": lfsr_digest8_reflect,
}


def compute(algorithm: str, data: bytes, **params) -> int:
    """Runs a named algorithm over ``data``.

    Raises:
        KeyError: if the algorithm is unknown. Specifications are validated
            against the schema, so this only happens for custom decoders.
    """
    try:
        func = ALGORITHMS[algorithm]
    except KeyError:
        raise KeyError(
            f"Unknown checksum algorithm '{algorithm}'. Known: {', '.join(sorted(ALGORITHMS))}"
        ) from None
    return func(data, **params)
