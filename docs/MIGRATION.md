# Helper Functions Migration

## Overview
This document describes the migration of Perl protocol helper functions to Python.

## Migrated Functions

### 1. `mc2dmc()` - Manchester to Differential Manchester Conversion
- **Perl Location**: `lib/SD_Protocols.pm:522`
- **Python Location**: `sd_protocols/helpers.py:ProtocolHelpersMixin.mc2dmc()`
- **Purpose**: Remodulation of manchester signals to differential manchester signals
- **Test**: `tests/test_funkbus.py` (used by mcBit2Funkbus)

### 2. `bin_str_2_hex_str()` - Binary String to Hexadecimal Conversion
- **Perl Location**: `lib/SD_Protocols.pm:365`
- **Python Location**: `sd_protocols/helpers.py:ProtocolHelpersMixin.bin_str_2_hex_str()`
- **Purpose**: Convert binary string (e.g., '1111') to hex string (e.g., 'F')
- **Test Coverage**: 
  - Basic conversions: '1111' → 'F', '1010' → 'A'
  - Long binary strings
  - Invalid input handling
  - Tests in: `tests/test_helpers.py:TestBinStr2HexStr`

### 3. `dec_2_bin_ppari()` - Decimal to Binary with Parity
- **Perl Location**: `lib/SD_Protocols.pm:645`
- **Python Location**: `sd_protocols/helpers.py:ProtocolHelpersMixin.dec_2_bin_ppari()`
- **Purpose**: Convert decimal number to 8-bit binary with parity bit appended
- **Examples**:
  - 32 → '001000001' (00100000 + parity=1)
  - 204 → '110011000' (11001100 + parity=0)
- **Test Coverage**:
  - Basic conversions
  - Edge cases (0, 255, 1)
  - Parity bit calculation
  - Tests in: `tests/test_helpers.py:TestDec2BinPpari`

### 4. `mcraw()` - Manchester Signal Output Handler
- **Perl Location**: `lib/SD_Protocols.pm:538`
- **Python Location**: `sd_protocols/helpers.py:ProtocolHelpersMixin.mcraw()`
- **Purpose**: Output helper for manchester signals with length validation
- **Features**:
  - Validates length_max against protocol definition
  - Returns hex string on success
  - Error handling for invalid input
- **Test Coverage**:
  - Good message conversion
  - Message length validation
  - Error cases (no bit data, no protocol ID)
  - Tests in: `tests/test_helpers.py:TestMCRAW`

## Architecture

All helper functions are implemented as methods in the `ProtocolHelpersMixin` class in `sd_protocols/helpers.py`. 
The `SDProtocols` class inherits from this mixin, making all helper methods available as instance methods:

```python
class SDProtocols(ProtocolHelpersMixin):
    # All mixin methods are inherited
    pass
```

This approach provides:
- ✅ Clean separation of concerns (helpers in separate module)
- ✅ No naming conflicts
- ✅ Easy to extend with more helpers
- ✅ Pythonic and idiomatic

## Testing

All migrated functions have comprehensive test coverage:

```bash
# Run all tests
pytest -v

# Run helper tests only
pytest tests/test_helpers.py -v

# Run funkbus tests
pytest tests/test_funkbus.py -v
```

## Test Results

✅ **24/24 tests passing**
- 10 helper function tests (bin_str_2_hex_str, dec_2_bin_ppari, mcraw)
- 3 funkbus tests (using mc2dmc)
- 11 existing tests (loader, sd_protocols)

## Perl Test References

Original Perl tests from the RFFHEM repository:
- `t/SD_Protocols/01_binStr2hexStr.t` - Binary to hex conversion
- `t/SD_Protocols/01_dec2binppari.t` - Decimal to binary with parity
- `t/SD_Protocols/02_MCRAW.t` - MCRAW protocol handler
- `t/SD_Protocols/02_mcBit2Funkbus.t` - Funkbus protocol handler (uses mc2dmc)
