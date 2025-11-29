"""
Hardware definitions for SIGNALduino.
"""
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional

class HardwareType(str, Enum):
    """Supported hardware types."""
    NANO_328 = "nano328"
    NANO_CC1101 = "nanoCC1101"
    MINI_CUL_CC1101 = "miniculCC1101"
    PRO_MINI_8_S = "promini8s"
    PRO_MINI_8_CC1101 = "promini8cc1101"
    PRO_MINI_16_S = "promini16s"
    PRO_MINI_16_CC1101 = "promini16cc1101"
    RADINO_CC1101 = "radinoCC1101"
    # ESP types are listed but flashing is not fully supported via module logic in Perl yet,
    # but we list them for completeness and future support.
    ESP32_S = "esp32s"
    ESP32_CC1101 = "esp32cc1101"
    ESP8266_S = "esp8266s"
    ESP8266_CC1101 = "esp8266cc1101"
    MAPLE_MINI_F103CB_S = "MAPLEMINI_F103CBs"
    MAPLE_MINI_F103CB_CC1101 = "MAPLEMINI_F103CBcc1101"

@dataclass
class HardwareConfig:
    """Configuration for a specific hardware type."""
    name: str
    avrdude_programmer: str
    avrdude_partno: str
    baudrate: int
    requires_1200bps_reset: bool = False
    
    # Default flash command template
    # Placeholders: [BAUDRATE], [PORT], [HEXFILE], [LOGFILE]
    flash_cmd_template: str = "avrdude -c [PROGRAMMER] -b [BAUDRATE] -P [PORT] -p [PARTNO] -vv -U flash:w:[HEXFILE] 2>[LOGFILE]"

# Mapping of hardware types to their configuration
HARDWARE_CONFIGS: Dict[str, HardwareConfig] = {
    HardwareType.NANO_328: HardwareConfig(
        name="Arduino Nano 328",
        avrdude_programmer="arduino",
        avrdude_partno="atmega328p",
        baudrate=57600
    ),
    HardwareType.NANO_CC1101: HardwareConfig(
        name="Arduino Nano 328 with CC1101",
        avrdude_programmer="arduino",
        avrdude_partno="atmega328p",
        baudrate=57600
    ),
    HardwareType.MINI_CUL_CC1101: HardwareConfig(
        name="Arduino Pro Mini with CC1101 (MiniCUL)",
        avrdude_programmer="arduino",
        avrdude_partno="atmega328p",
        baudrate=57600
    ),
    HardwareType.PRO_MINI_8_S: HardwareConfig(
        name="Arduino Pro Mini 328 8Mhz",
        avrdude_programmer="arduino",
        avrdude_partno="atmega328p",
        baudrate=57600
    ),
    HardwareType.PRO_MINI_8_CC1101: HardwareConfig(
        name="Arduino Pro Mini 328 8Mhz with CC1101",
        avrdude_programmer="arduino",
        avrdude_partno="atmega328p",
        baudrate=57600
    ),
    HardwareType.PRO_MINI_16_S: HardwareConfig(
        name="Arduino Pro Mini 328 16Mhz",
        avrdude_programmer="arduino",
        avrdude_partno="atmega328p",
        baudrate=57600
    ),
    HardwareType.PRO_MINI_16_CC1101: HardwareConfig(
        name="Arduino Pro Mini 328 16Mhz with CC1101",
        avrdude_programmer="arduino",
        avrdude_partno="atmega328p",
        baudrate=57600
    ),
    HardwareType.RADINO_CC1101: HardwareConfig(
        name="Radino CC1101",
        avrdude_programmer="avr109",
        avrdude_partno="atmega32u4",
        baudrate=57600,
        requires_1200bps_reset=True,
        # Radino needs -D flag (disable auto erase) typically? Perl code says:
        # avrdude -c avr109 -b [BAUDRATE] -P [PORT] -p atmega32u4 -vv -D -U flash:w:[HEXFILE] 2>[LOGFILE]
        flash_cmd_template="avrdude -c [PROGRAMMER] -b [BAUDRATE] -P [PORT] -p [PARTNO] -vv -D -U flash:w:[HEXFILE] 2>[LOGFILE]"
    ),
}

def get_hardware_config(hardware_type: str) -> Optional[HardwareConfig]:
    """Get configuration for a hardware type."""
    return HARDWARE_CONFIGS.get(hardware_type)

def is_supported_for_flashing(hardware_type: str) -> bool:
    """Check if the hardware type is supported for flashing via this module."""
    # Currently only AVR based boards are supported for flashing via avrdude
    return hardware_type in HARDWARE_CONFIGS