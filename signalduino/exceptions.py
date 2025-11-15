"""Custom exception hierarchy for the Signalduino Python port."""


class SignalduinoError(Exception):
    """Base class for all Signalduino-specific errors."""


class SignalduinoConnectionError(SignalduinoError):
    """Raised when a transport cannot be opened or is unexpectedly closed."""


class SignalduinoCommandTimeout(SignalduinoError):
    """Raised when a queued command does not receive the expected response in time."""


class SignalduinoParserError(SignalduinoError):
    """Raised when a firmware line cannot be parsed."""
