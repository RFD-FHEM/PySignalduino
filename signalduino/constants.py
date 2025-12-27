"""Constants used throughout the Signalduino project."""

# Command timing (moved from constants to commands to break circular dep)
# SDUINO_CMD_TIMEOUT = 1.0

# Write queue timing (moved from constants to commands to break circular dep)
# SDUINO_WRITEQUEUE_NEXT = 0.05
# SDUINO_WRITEQUEUE_TIMEOUT = 1.0

# Retry mechanism
SDUINO_INIT_MAXRETRY = 5
SDUINO_RETRY_INTERVAL = 5.0

# Default settings
DEFAULT_FREQUENCY = 433.92

# Message start marker (STX)
STX = "\x02"

# Removed:
# from signalduino.commands import Command
# CUSTOM_TIMEOUTS = {...}
