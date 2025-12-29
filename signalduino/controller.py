import json 
import logging
import re
import asyncio
import os
import traceback
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Awaitable,
    Callable,
    List,
    Optional,
    Pattern,
    Dict,
    Tuple,
)

# threading, queue, time entfernt
from .commands import SignalduinoCommands, MqttCommandDispatcher
from .constants import (
    SDUINO_CMD_TIMEOUT,
    SDUINO_INIT_MAXRETRY,
    SDUINO_INIT_WAIT,
    SDUINO_INIT_WAIT_XQ,
    SDUINO_STATUS_HEARTBEAT_INTERVAL,
)
from .exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError, CommandValidationError
from .mqtt import MqttPublisher # Muss jetzt async sein
from .parser import SignalParser
from .transport import BaseTransport # Muss jetzt async sein
from .types import DecodedMessage, PendingResponse, QueuedCommand


class SignalduinoController:
    """Orchestrates the connection, command queue and message parsing using asyncio."""

    def __init__(
        self,
        transport: BaseTransport, # Erwartet asynchrone Implementierung
        parser: Optional[SignalParser] = None,
        # Callback ist jetzt ein Awaitable, da es im Async-Kontext aufgerufen wird
        message_callback: Optional[Callable[[DecodedMessage], Awaitable[None]]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.transport = transport
        # send_command muss jetzt async sein
        self.commands = SignalduinoCommands(self.send_command)
        self.parser = parser or SignalParser()
        self.message_callback = message_callback
        self.logger = logger or logging.getLogger(__name__)

        self.mqtt_publisher: Optional[MqttPublisher] = None
        self.mqtt_dispatcher: Optional[MqttCommandDispatcher] = None # NEU
        if os.environ.get("MQTT_HOST"):
            self.mqtt_publisher = MqttPublisher(logger=self.logger)
            self.mqtt_dispatcher = MqttCommandDispatcher(self) # NEU: Initialisiere Dispatcher
            # handle_mqtt_command muss jetzt async sein
            self.mqtt_publisher.register_command_callback(self._handle_mqtt_command)

        # Ersetze threading-Objekte durch asyncio-Äquivalente
        self._stop_event = asyncio.Event()
        self._raw_message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._write_queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self._pending_responses: List[PendingResponse] = []
        self._pending_responses_lock = asyncio.Lock()
        self._init_complete_event = asyncio.Event() # NEU: Event für den Abschluss der Initialisierung

        # Timer-Handles (jetzt asyncio.Task anstelle von threading.Timer)
        self._heartbeat_task: Optional[asyncio.Task[Any]] = None
        self._init_task_xq: Optional[asyncio.Task[Any]] = None
        self._init_task_start: Optional[asyncio.Task[Any]] = None
        
        # Liste der Haupt-Tasks für die run-Methode
        self._main_tasks: List[asyncio.Task[Any]] = []

        self.init_retry_count = 0
        self.init_reset_flag = False
        self.init_version_response: Optional[str] = None # Hinzugefügt für _check_version_resp

    # Asynchroner Kontextmanager
    async def __aenter__(self) -> "SignalduinoController":
        """Opens transport and starts MQTT connection if configured."""