"""Shared dataclasses for the Signalduino Python port."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Pattern, Awaitable, Any
# threading.Event wird im asynchronen Controller ersetzt
# von asyncio.Event, das dort erstellt werden muss.


@dataclass(slots=True)
class RawFrame:
    """Single line emitted by the firmware before decoding."""

    line: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    rssi: Optional[float] = None
    freq_afc: Optional[float] = None
    message_type: Optional[str] = None


@dataclass(slots=True)
class DecodedMessage:
    """Higher-level frame after running through the parser."""

    protocol_id: str
    payload: str
    raw: RawFrame
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class QueuedCommand:
    """Command entry waiting to be picked up by the writer thread."""

    payload: str
    timeout: float
    expect_response: bool = False
    response_pattern: Optional[Pattern[str]] = None
    on_response: Optional[Callable[[str], None]] = None
    description: str = ""
    inserted_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class PendingResponse:
    """Tracks the state of a command that is waiting for a response."""

    command: QueuedCommand
    deadline: datetime
    event: Any # Wird durch asyncio.Event im Controller gesetzt
    response: Optional[str] = None
