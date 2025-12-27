import asyncio
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

# Command timing
SDUINO_CMD_TIMEOUT = 1.0

# Write queue timing
SDUINO_WRITEQUEUE_NEXT = 0.05
SDUINO_WRITEQUEUE_TIMEOUT = 1.0

# Define as empty dict first to avoid NameError in Command.__post_init__
CUSTOM_TIMEOUTS = {}

logger = logging.getLogger(__name__)


class CommandType(Enum):
    SET = auto()
    GET = auto()
    ACTION = auto()


@dataclass(frozen=True)
class Command:
    """
    Represents a single command that can be sent to the Signalduino device.
    """
    name: str
    raw_command: str
    command_type: CommandType
    expected_response: str | None = None
    timeout: float = SDUINO_CMD_TIMEOUT

    def __post_init__(self):
        # Update timeout from custom map if available
        if self in CUSTOM_TIMEOUTS:
            object.__setattr__(self, 'timeout', CUSTOM_TIMEOUTS[self])

    def is_success_response(self, response: str) -> bool:
        """
        Check if the response indicates a successful command execution.
        By default, for commands that return their own string (like 'XQ'),
        it checks for an exact match.
        """
        if self.expected_response:
            return self.expected_response.strip() == response.strip()
        # For commands that return version info (like 'V'), any non-empty
        # response is considered a success.
        return bool(response.strip())

    @classmethod
    def VERSION(cls) -> 'Command':
        """Retrieve the firmware version of the Signalduino."""
        return cls(
            name="VERSION",
            raw_command="V",
            command_type=CommandType.GET,
            expected_response=None,
        )

    @classmethod
    def SET_FREQUENCY(cls, frequency: float) -> 'Command':
        """Set the operating frequency (e.g., 433.92)."""
        return cls(
            name="SET_FREQUENCY",
            raw_command=f"b{frequency}",
            command_type=CommandType.SET,
            expected_response=f"b{frequency}",
        )


CUSTOM_TIMEOUTS.update({
    Command.VERSION(): 3.0,
})


CUSTOM_TIMEOUTS = {
    Command.VERSION(): 3.0,
}
