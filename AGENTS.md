# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Core Architecture & Patterns (Manchester Parsing)
- **MC Parsing Chain:** `MCParser.parse()` calls `protocols.demodulate_mc()`, which uses `ManchesterMixin._demodulate_mc_data()` for length/clock checks before calling the specific `mcBit2*` method.
- **TFA Protocol Gotcha:** `mcBit2TFA` implements duplicate message detection by chunking the *entire* received bitstream, not just the expected message length.
- **Grothe Constraint:** `mcBit2Grothe` enforces an *exact* 32-bit length, overriding general length checks.
- **Test Mocking:** MC Parser tests mock `mock_protocols.demodulate` to simulate the output of the protocol layer, not `demodulate_mc` directly.
- **Bit Conversion:** `_convert_mc_hex_to_bits` handles `polarity_invert` and firmware version toggling for polarity.