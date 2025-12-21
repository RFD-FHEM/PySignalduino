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
        self.logger.info("Entering SignalduinoController async context.")
        
        # 1. Transport öffnen (Nutzt den aenter des Transports)
        # NEU: Transport muss als Kontextmanager verwendet werden
        if self.transport:
            await self.transport.__aenter__()

        # 2. MQTT starten
        if self.mqtt_publisher:
            # Nutzt den aenter des MqttPublishers
            await self.mqtt_publisher.__aenter__()
            self.logger.info("MQTT publisher started.")
            
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        """Stops all tasks, closes transport and MQTT connection."""
        self.logger.info("Exiting SignalduinoController async context.")
        
        # 1. Stopp-Event setzen und alle Tasks abbrechen
        self._stop_event.set()
        
        # Tasks abbrechen (Heartbeat, Init-Tasks, etc.)
        tasks_to_cancel = [
            self._heartbeat_task,
            self._init_task_xq,
            self._init_task_start,
        ]
        
        # Haupt-Tasks abbrechen (Reader, Parser, Writer)
        # Wir warten nicht auf den Parser/Writer, da sie mit der Queue arbeiten.
        # Wir müssen nur die Task-Handles abbrechen, da run() bereits auf die kritischen gewartet hat.
        tasks_to_cancel.extend(self._main_tasks)

        for task in tasks_to_cancel:
            if task and not task.done():
                self.logger.debug("Cancelling task: %s", task.get_name())
                task.cancel()

        # Warte auf das Ende aller Tasks, ignoriere CancelledError
        # Füge einen kurzen Timeout hinzu, um zu verhindern, dass es unbegrenzt blockiert
        # Wir sammeln die Futures und warten darauf mit einem Timeout
        tasks = [t for t in tasks_to_cancel if t is not None and not t.done()]
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2.0)
            except asyncio.TimeoutError:
                self.logger.warning("Timeout waiting for controller tasks to finish.")
            
        self.logger.debug("All controller tasks cancelled.")

        # 2. Transport und MQTT schließen (Nutzt die aexit der Komponenten)
        if self.transport:
            # transport.__aexit__ aufrufen
            await self.transport.__aexit__(exc_type, exc_val, exc_tb)
            
        if self.mqtt_publisher:
            # mqtt_publisher.__aexit__ aufrufen
            await self.mqtt_publisher.__aexit__(exc_type, exc_val, exc_tb)

        # Lasse nur CancelledError und ConnectionError zu
        if exc_type and not issubclass(exc_type, (asyncio.CancelledError, SignalduinoConnectionError)):
            self.logger.error("Exception occurred in async context: %s: %s", exc_type.__name__, exc_val)
            # Rückgabe False, um die Exception weiterzuleiten
            return False 
        
        return None # Unterdrücke die Exception (CancelledError/ConnectionError sind erwartet/ok)


    async def initialize(self) -> None:
        """Starts the initialization process."""
        self.logger.info("Initializing device...")
        self.init_retry_count = 0
        self.init_reset_flag = False
        self.init_version_response = None
        self._init_complete_event.clear() # NEU: Event für erneute Initialisierung zurücksetzen

        if self._stop_event.is_set():
            self.logger.warning("initialize called but stop event is set.")
            return

        # Plane Disable Receiver (XQ) und warte kurz
        if self._init_task_xq and not self._init_task_xq.done():
            self._init_task_xq.cancel()
        # Verwende asyncio.create_task für verzögerte Ausführung
        self._init_task_xq = asyncio.create_task(self._delay_and_send_xq())
        self._init_task_xq.set_name("sd-init-xq")
        
        # Plane StartInit (Get Version)
        if self._init_task_start and not self._init_task_start.done():
            self._init_task_start.cancel()
        self._init_task_start = asyncio.create_task(self._delay_and_start_init())
        self._init_task_start.set_name("sd-init-start")
        
    async def _delay_and_send_xq(self) -> None:
        """Helper to delay before sending XQ."""
        try:
            await asyncio.sleep(SDUINO_INIT_WAIT_XQ)
            await self._send_xq()
        except asyncio.CancelledError:
            self.logger.debug("_delay_and_send_xq cancelled.")
        except Exception as e:
            self.logger.exception("Error in _delay_and_send_xq: %s", e)

    async def _delay_and_start_init(self) -> None:
        """Helper to delay before starting init."""
        try:
            await asyncio.sleep(SDUINO_INIT_WAIT)
            await self._start_init()
        except asyncio.CancelledError:
            self.logger.debug("_delay_and_start_init cancelled.")
        except Exception as e:
            self.logger.exception("Error in _delay_and_start_init: %s", e)

    async def _send_xq(self) -> None:
        """Sends XQ command."""
        if self._stop_event.is_set():
            return
        try:
            self.logger.debug("Sending XQ to disable receiver during init")
            # commands.disable_receiver ist jetzt ein awaitable
            await self.commands.disable_receiver()
        except Exception as e:
            self.logger.warning("Failed to send XQ: %s", e)

    async def _start_init(self) -> None:
        """Attempts to get the device version to confirm initialization."""
        if self._stop_event.is_set():
            return

        self.logger.info("StartInit, get version, retry = %d", self.init_retry_count)

        if self.init_retry_count >= SDUINO_INIT_MAXRETRY:
            if not self.init_reset_flag:
                self.logger.warning("StartInit, retry count reached. Resetting device.")
                self.init_reset_flag = True
                await self._reset_device()
            else:
                self.logger.error("StartInit, retry count reached after reset. Stopping controller.")
                self._stop_event.set() # Setze Stopp-Event, aexit wird das Schließen übernehmen
            return

        response: Optional[str] = None
        try:
            # commands.get_version ist jetzt ein awaitable
            response = await self.commands.get_version(timeout=2.0)
        except Exception as e:
            self.logger.debug("StartInit: Exception during version check: %s", e)

        await self._check_version_resp(response)

    async def _check_version_resp(self, msg: Optional[str]) -> None:
        """Handles the response from the version command."""
        if self._stop_event.is_set():
            return

        if msg:
            self.logger.info("Initialized %s", msg.strip())
            self.init_reset_flag = False
            self.init_retry_count = 0
            self.init_version_response = msg

            # NEU: Versionsmeldung per MQTT veröffentlichen
            if self.mqtt_publisher:
                # publish_simple ist jetzt awaitable
                await self.mqtt_publisher.publish_simple("status/version", msg.strip(), retain=True)

            # Enable Receiver XE
            try:
                self.logger.info("Enabling receiver (XE)")
                # commands.enable_receiver ist jetzt ein awaitable
                await self.commands.enable_receiver()
            except Exception as e:
                self.logger.warning("Failed to enable receiver: %s", e)

            # Check for CC1101
            if "cc1101" in msg.lower():
                self.logger.info("CC1101 detected")
            
            # NEU: Starte Heartbeat-Task
            await self._start_heartbeat_task()
            
            # NEU: Signalisiere den Abschluss der Initialisierung
            self._init_complete_event.set()

        else:
            self.logger.warning("StartInit: No valid version response.")
            self.init_retry_count += 1
            # Initialisierung wiederholen
            # Verzögere den Aufruf, um eine Busy-Loop bei Verbindungsfehlern zu vermeiden
            await asyncio.sleep(1.0) 
            await self._start_init()

    async def _reset_device(self) -> None:
        """Resets the device by closing and reopening the transport."""
        self.logger.info("Resetting device...")
        # Nutze aexit/aenter Logik, um die Verbindung zu schließen/wiederherzustellen
        await self.__aexit__(None, None, None) # Schließt Transport und stoppt Tasks/Publisher
        # Kurze Pause für den Reset
        await asyncio.sleep(2.0)
        # NEU: Der Controller ist neu gestartet und muss wieder in den async Kontext eintreten
        await self.__aenter__()
        
        # Manuell die Initialisierung starten
        self.init_version_response = None
        self._init_complete_event.clear() # NEU: Event für erneute Initialisierung zurücksetzen
        
        try:
            await self._send_xq()
            await self._start_init()
        except Exception as e:
            self.logger.error("Failed to re-initialize device after reset: %s", e)
            self._stop_event.set()

    async def _reader_task(self) -> None:
        """Continuously reads from the transport and puts lines into a queue."""
        self.logger.debug("Reader task started.")
        while not self._stop_event.is_set():
            try:
                # Nutze await für die asynchrone Transport-Leseoperation
                # Setze ein Timeout, um CancelledError zu erhalten, falls nötig, und um andere Events zu ermöglichen
                line = await asyncio.wait_for(self.transport.readline(), timeout=0.1)
                
                if line:
                    self.logger.debug("RX RAW: %r", line)
                    await self._raw_message_queue.put(line)
            except asyncio.TimeoutError:
                continue # Queue ist leer, Schleife fortsetzen
            except SignalduinoConnectionError as e:
                # Im Falle eines Verbindungsfehlers das Stopp-Event setzen und die Schleife beenden.
                self.logger.error("Connection error in reader task: %s", e)
                self._stop_event.set()
                break # Schleife verlassen
            except asyncio.CancelledError:
                break # Bei Abbruch beenden
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in reader task")
                # Kurze Pause, um eine Endlosschleife zu vermeiden
                await asyncio.sleep(0.1) 
        self.logger.debug("Reader task finished.")

    async def _parser_task(self) -> None:
        """Continuously processes raw messages from the queue."""
        self.logger.debug("Parser task started.")
        while not self._stop_event.is_set():
            try:
                # Nutze await für das asynchrone Lesen aus der Queue
                raw_line = await asyncio.wait_for(self._raw_message_queue.get(), timeout=0.1)
                self._raw_message_queue.task_done() # Wichtig für asyncio.Queue
                
                if self._stop_event.is_set():
                    continue

                line_data = raw_line.strip()
                
                # Nachrichten, die mit \x02 (STX) beginnen, sind Sensordaten und sollten nie als Kommandoantworten behandelt werden.
                if line_data.startswith("\x02"):
                    pass # Gehe direkt zum Parsen
                elif await self._handle_as_command_response(line_data): # _handle_as_command_response muss async sein
                    continue

                if line_data.startswith("XQ") or line_data.startswith("XR"):
                    # Abfangen der Receiver-Statusmeldungen XQ/XR
                    self.logger.debug("Found receiver status: %s", line_data)
                    continue

                decoded_messages = self.parser.parse_line(line_data)
                for message in decoded_messages:
                    if self.mqtt_publisher:
                        try:
                            # publish ist jetzt awaitable
                            await self.mqtt_publisher.publish(message)
                        except Exception:
                            self.logger.exception("Error in MQTT publish")

                    if self.message_callback:
                        try:
                            # message_callback ist jetzt awaitable
                            await self.message_callback(message)
                        except Exception:
                            self.logger.exception("Error in message callback")

            except asyncio.TimeoutError:
                continue # Queue ist leer, Schleife fortsetzen
            except asyncio.CancelledError:
                break # Bei Abbruch beenden
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in parser task")
        self.logger.debug("Parser task finished.")

    async def _writer_task(self) -> None:
        """Continuously processes the write queue."""
        self.logger.debug("Writer task started.")
        while not self._stop_event.is_set():
            try:
                # Nutze await für das asynchrone Lesen aus der Queue
                command = await asyncio.wait_for(self._write_queue.get(), timeout=0.1)
                self._write_queue.task_done()
                
                if not command.payload or self._stop_event.is_set():
                    continue

                await self._send_and_wait(command)
            except asyncio.TimeoutError:
                continue # Queue ist leer, Schleife fortsetzen
            except asyncio.CancelledError:
                break # Bei Abbruch beenden
            except SignalduinoCommandTimeout as e:
                self.logger.warning("Writer task: %s", e)
            except Exception:
                if not self._stop_event.is_set():
                    self.logger.exception("Unhandled exception in writer task")
        self.logger.debug("Writer task finished.")

    async def _send_and_wait(self, command: QueuedCommand) -> None:
        """Sends a command and waits for a response if required."""
        if not command.expect_response:
            self.logger.debug("Sending command (fire-and-forget): %s", command.payload)
            # transport.write_line ist jetzt awaitable
            await self.transport.write_line(command.payload)
            return

        pending = PendingResponse(
            command=command,
            event=asyncio.Event(), # Füge ein asyncio.Event hinzu
            deadline=datetime.now(timezone.utc) + timedelta(seconds=command.timeout),
            response=None
        )
        # Nutze asyncio.Lock für asynchrone Sperren
        async with self._pending_responses_lock:
            self._pending_responses.append(pending)

        self.logger.debug("Sending command (expect response): %s", command.payload)
        await self.transport.write_line(command.payload)

        try:
            # Warte auf das Event mit Timeout
            await asyncio.wait_for(pending.event.wait(), timeout=command.timeout)

            if command.on_response and pending.response:
                # on_response ist ein synchrones Callable und kann direkt aufgerufen werden
                command.on_response(pending.response)

        except asyncio.TimeoutError:
            raise SignalduinoCommandTimeout(
                f"Command '{command.description or command.payload}' timed out"
            ) from None
        finally:
            async with self._pending_responses_lock:
                if pending in self._pending_responses:
                    self._pending_responses.remove(pending)

    async def _handle_as_command_response(self, line: str) -> bool:
        """Checks if a line matches any pending command response."""
        # Nutze asyncio.Lock
        async with self._pending_responses_lock:
            # Iteriere rückwärts, um sicheres Entfernen zu ermöglichen
            for i in range(len(self._pending_responses) - 1, -1, -1):
                pending = self._pending_responses[i]

                if datetime.now(timezone.utc) > pending.deadline:
                    self.logger.warning("Pending response for '%s' expired.", pending.command.payload)
                    del self._pending_responses[i]
                    continue

                if pending.command.response_pattern and pending.command.response_pattern.search(line):
                    self.logger.debug("Matched response for '%s': %s", pending.command.payload, line)
                    pending.response = line
                    # Setze das asyncio.Event
                    pending.event.set()
                    del self._pending_responses[i]
                    return True
        return False

    async def send_raw_command(self, command: str, expect_response: bool = False, timeout: float = 2.0) -> Optional[str]:
        """Queues a raw command and optionally waits for a specific response."""
        # send_command ist jetzt awaitable
        return await self.send_command(payload=command, expect_response=expect_response, timeout=timeout)

    async def send_command(
        self,
        payload: str,
        expect_response: bool = False,
        timeout: float = 2.0,
        response_pattern: Optional[Pattern[str]] = None,
    ) -> Optional[str]:
        """Queues a command and optionally waits for a specific response."""
        
        if not expect_response:
            # Nutze await für asynchrone Queue-Operation
            await self._write_queue.put(QueuedCommand(payload=payload, timeout=0))
            return None

        # NEU: Verwende asyncio.Future anstelle einer threading.Queue
        response_future: asyncio.Future[str] = asyncio.Future()

        def on_response(response: str):
            # Prüfe, ob das Future nicht bereits abgeschlossen ist (z.B. durch Timeout im Caller)
            if not response_future.done():
                response_future.set_result(response)

        if response_pattern is None:
            response_pattern = re.compile(
                f".*{re.escape(payload)}.*|.*OK.*", re.IGNORECASE
            )

        command = QueuedCommand(
            payload=payload,
            timeout=timeout,
            expect_response=True,
            response_pattern=response_pattern,
            on_response=on_response,
            description=payload,
        )

        await self._write_queue.put(command)

        try:
            # Warte auf das Future mit Timeout
            return await asyncio.wait_for(response_future, timeout=timeout)
        except asyncio.TimeoutError:
            await asyncio.sleep(0)  # Gib dem Event-Loop eine Chance, _stop_event zu setzen.
            # Code Refactor: Timeout vs. dead connection
            self.logger.debug("Command timeout reached for %s", payload)
            # Differentiate between connection drop and normal command timeout
            # Check for a closed transport or a stopped controller
            if self._stop_event.is_set() or (self.transport and self.transport.closed()):
                self.logger.error(
                    "Command '%s' timed out. Connection appears to be dead (transport closed or controller stopping).", payload
                )
                raise SignalduinoConnectionError(
                    f"Command '{payload}' failed: Connection dropped."
                ) from None
            else:
                # Annahme: Transport-API wirft SignalduinoConnectionError bei Trennung.
                # Wenn dies nicht der Fall ist, wird ein Timeout angenommen.
                self.logger.warning(
                    "Command '%s' timed out. Treating as no response from device.", payload
                )
                raise SignalduinoCommandTimeout(f"Command '{payload}' timed out") from None

    async def _start_heartbeat_task(self) -> None:
        """Schedules the periodic status heartbeat task."""
        if not self.mqtt_publisher:
            return

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._heartbeat_task.set_name("sd-heartbeat")
        self.logger.info("Heartbeat task started, interval: %d seconds.", SDUINO_STATUS_HEARTBEAT_INTERVAL)

    async def _heartbeat_loop(self) -> None:
        """The main loop for the periodic status heartbeat."""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(SDUINO_STATUS_HEARTBEAT_INTERVAL)
                await self._publish_status_heartbeat()
        except asyncio.CancelledError:
            self.logger.debug("Heartbeat loop cancelled.")
        except Exception as e:
            self.logger.exception("Unhandled exception in heartbeat loop: %s", e)
            
    async def _publish_status_heartbeat(self) -> None:
        """Publishes the current device status."""
        if not self.mqtt_publisher or not await self.mqtt_publisher.is_connected():
            self.logger.warning("Cannot publish heartbeat; publisher not connected.")
            return
            
        try:
            # 1. Heartbeat/Alive message (Retain: True)
            await self.mqtt_publisher.publish_simple("status/alive", "online", retain=True)
            self.logger.info("Heartbeat executed. Status: alive")

            # 2. Status data (version, ram, uptime)
            status_data = {}
            
            # Version
            if self.init_version_response:
                status_data["version"] = self.init_version_response.strip()
            
            # Free RAM
            try:
                # commands.get_free_ram ist awaitable
                ram_resp = await self.commands.get_free_ram()
                # Format: R: 1234
                if ":" in ram_resp:
                    status_data["free_ram"] = ram_resp.split(":")[-1].strip()
                else:
                    status_data["free_ram"] = ram_resp.strip()
            except SignalduinoConnectionError:
                 # Bei Verbindungsfehler: Controller anweisen zu stoppen/neu zu verbinden
                self.logger.error(
                    "Heartbeat failed: Connection dropped during get_free_ram. Triggering stop."
                )
                self._stop_event.set() # Stopp-Event setzen, aexit wird das Schließen übernehmen
                return
            except Exception as e:
                self.logger.warning("Could not get free RAM for heartbeat: %s", e)
                status_data["free_ram"] = "error"
                
            # Uptime
            try:
                # commands.get_uptime ist awaitable
                uptime_resp = await self.commands.get_uptime()
                # Format: t: 1234
                if ":" in uptime_resp:
                    status_data["uptime"] = uptime_resp.split(":")[-1].strip()
                else:
                    status_data["uptime"] = uptime_resp.strip()
            except SignalduinoConnectionError:
                self.logger.error(
                    "Heartbeat failed: Connection dropped during get_uptime. Triggering stop."
                )
                self._stop_event.set() # Stopp-Event setzen, aexit wird das Schließen übernehmen
                return
            except Exception as e:
                self.logger.warning("Could not get uptime for heartbeat: %s", e)
                status_data["uptime"] = "error"
            
            # Publish all collected data
            if status_data:
                payload = json.dumps(status_data)
                await self.mqtt_publisher.publish_simple("status/data", payload)
            
        except Exception as e:
            self.logger.error("Error during status heartbeat: %s", e)

    # --- INTERNE HELPER FÜR SEND MSG (PHASE 2) ---

    def _hex_to_bits(self, hex_str: str) -> str:
        """Converts a hex string to a binary string."""
        scale = 16
        num_of_bits = len(hex_str) * 4
        return bin(int(hex_str, scale))[2:].zfill(num_of_bits)

    def _tristate_to_bit(self, tristate_str: str) -> str:
        """Converts IT V1 tristate (0, 1, F) to binary bits."""
        # Placeholder: This logic needs access to the protocols implementation, 
        # which is not available in the controller.
        # We assume for now that if the data contains non-binary characters, it's invalid.
        return tristate_str
            
    # --- INTERNE HELPER FÜR CC1101 BERECHNUNGEN (PHASE 2) ---

    def _calc_data_rate_regs(self, target_datarate: float, mdcfg4_hex: str) -> Tuple[str, str]:
        """Calculates MDMCFG4 (4:0) and MDMCFG3 (7:0) from target data rate (kBaud). (0x10, 0x11)"""
        F_XOSC = 26000000 
        target_dr_hz = target_datarate * 1000 # target in Hz
        
        drate_e = 0
        drate_m = 0
        best_diff = float('inf')
        best_drate_e = 0
        best_drate_m = 0

        for drate_e_test in range(16): # DRATE_E von 0 bis 15
            for drate_m_test in range(256): # DRATE_M von 0 bis 255
                calculated_dr = (256 + drate_m_test) * (2**drate_e_test) * F_XOSC / (2**28)
                
                diff = abs(calculated_dr - target_dr_hz)
                
                if diff < best_diff:
                    best_diff = diff
                    best_drate_e = drate_e_test
                    best_drate_m = drate_m_test

        # Setze MDMCFG4 (Bits 3:0 sind DRATE_E)
        mdcfg4_current = int(mdcfg4_hex, 16)
        mdcfg4_new_val = (mdcfg4_current & 0xF0) | best_drate_e
        
        return f"{mdcfg4_new_val:02X}", f"{best_drate_m:02X}"

    def _calc_bandwidth_reg(self, target_bw: float, mdcfg4_hex: str) -> str:
        """Calculates MDMCFG4 (BITS 7:4) from target bandwidth (kHz). (0x10)"""
        
        # BW = 26000 / (8 * (4 + M) * 2^E)
        # M = MDMCFG4[5:4], E = MDMCFG4[7:6]
        
        best_diff = float('inf')
        best_e = 0
        best_m = 0

        for e in range(4): # E von 0 bis 3
            for m in range(4): # M von 0 bis 3
                calculated_bw = 26000 / (8 * (4 + m) * (2**e))
                diff = abs(calculated_bw - target_bw)
                
                if diff < best_diff:
                    best_diff = diff
                    best_e = e
                    best_m = m
        
        # Die Registerbits 7:4 setzen
        bits = (best_e << 6) + (best_m << 4)

        # Setze MDMCFG4 (Bits 7:4 sind E und M)
        mdcfg4_current = int(mdcfg4_hex, 16)
        mdcfg4_new_val = (mdcfg4_current & 0x0F) | bits # Bewahre Bits 3:0
        
        return f"{mdcfg4_new_val:02X}" 

    def _calc_deviation_reg(self, target_dev: float) -> str:
        """Calculates DEVIATN (15) register value from target deviation (kHz)."""
        
        # DEVIATION = (8 + M) * 2^E * F_XOSC / 2^17
        # M = DEVIATN[2:0], E = DEVIATN[6:4]
        
        best_diff = float('inf')
        best_e = 0
        best_m = 0

        for e in range(8): # E von 0 bis 7 (3 Bits)
            for m in range(8): # M von 0 bis 7 (3 Bits)
                calculated_dev = (8 + m) * (2**e) * 26000 / (2**17)
                diff = abs(calculated_dev - target_dev)
                
                if diff < best_diff:
                    best_diff = diff
                    best_e = e
                    best_m = m
        
        # Die Registerbits setzen: M (3:0) und E (7:4)
        bits = best_m + (best_e << 4)
        
        return f"{bits:02X}"

    def _extract_req_id_from_payload(self, payload: str) -> Optional[str]:
        """Tries to extract the req_id from a raw JSON payload string for error correlation."""
        try:
            payload_dict = json.loads(payload)
            return payload_dict.get("req_id")
        except json.JSONDecodeError:
            return None # Cannot parse JSON to find req_id

    async def _handle_mqtt_command(self, command_path: str, payload: str) -> None:
        """
        Handles commands received via MQTT by dispatching them to the MqttCommandDispatcher.
        This method sends structured responses/errors based on the result.
        """
        self.logger.info("Handling MQTT command: %s (payload: %s)", command_path, payload)

        if not self.mqtt_publisher or not self.mqtt_dispatcher:
            self.logger.warning("Cannot handle MQTT command; publisher or dispatcher not initialized.")
            return
        
        req_id = self._extract_req_id_from_payload(payload)
        
        try:
            # 1. Dispatch (Validierung und Ausführung)
            if self.mqtt_dispatcher is None:
                self.logger.error("MqttCommandDispatcher not available during command execution.")
                raise RuntimeError("MqttCommandDispatcher not initialized for command processing.")
            
            response = await self.mqtt_dispatcher.dispatch(command_path, payload)
            
            # 2. Publish Response
            topic = f"{self.mqtt_publisher.response_topic}/{command_path}"
            await self.mqtt_publisher.publish_simple(topic, json.dumps(response))
            self.logger.debug("Executed MQTT command %s. Response published.", command_path)

        except CommandValidationError as e:
            # 3. Handle Validation Error (400 Bad Request)
            error_payload = {
                "error_code": 400,
                "error_message": str(e),
                "req_id": req_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            topic = f"{self.mqtt_publisher.error_topic}/{command_path}"
            await self.mqtt_publisher.publish_simple(topic, json.dumps(error_payload))
            self.logger.warning("Validation failed for command %s: %s", command_path, e)
            
        except SignalduinoCommandTimeout:
            # 4. Handle Timeout (502 Bad Gateway)
            error_payload = {
                "error_code": 502,
                "error_message": "Command timed out while waiting for a firmware response.",
                "req_id": req_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            topic = f"{self.mqtt_publisher.error_topic}/{command_path}"
            await self.mqtt_publisher.publish_simple(topic, json.dumps(error_payload))
            self.logger.error("Timeout for command: %s", command_path)
            
        except Exception as e:
            # 5. Handle Internal Error (500 Internal Server Error)
            error_payload = {
                "error_code": 500,
                "error_message": f"Internal server error: {type(e).__name__}: {str(e)}",
                "req_id": req_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            topic = f"{self.mqtt_publisher.error_topic}/{command_path}"
            await self.mqtt_publisher.publish_simple(topic, json.dumps(error_payload))
            self.logger.exception("Error executing command %s", command_path)

    # --- PHASE 1: Implementierung der Dispatcher-Methoden im Controller ---
    
    async def get_version(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'get/system/version'."""
        return await self.commands.get_version(timeout=SDUINO_CMD_TIMEOUT)
        
    async def get_freeram(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'get/system/freeram'."""
        return await self.commands.get_free_ram(timeout=SDUINO_CMD_TIMEOUT)
        
    async def get_uptime(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'get/system/uptime'."""
        return await self.commands.get_uptime(timeout=SDUINO_CMD_TIMEOUT)
        
    async def get_config_decoder(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'get/config/decoder'."""
        return await self.commands.get_config(timeout=SDUINO_CMD_TIMEOUT)
        
    async def get_cc1101_config(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'get/cc1101/config'."""
        return await self.commands.get_ccconf(timeout=SDUINO_CMD_TIMEOUT)
        
    async def get_cc1101_patable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'get/cc1101/patable'."""
        return await self.commands.get_ccpatable(timeout=SDUINO_CMD_TIMEOUT)
        
    async def get_cc1101_register(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'get/cc1101/register' (e.g., /2A or /99)."""
        register_addr = payload.get("value")
        if register_addr is None:
            # Wenn kein Wert übergeben wird, nimm 99 (Alle Register)
            register_addr = 99
        
        # Konvertiere in Integer
        if isinstance(register_addr, str):
            try:
                if register_addr.startswith("0x"):
                    register_addr = int(register_addr, 16)
                else:
                    register_addr = int(register_addr) if register_addr.isdigit() else int(register_addr, 16)
            except ValueError:
                raise CommandValidationError(f"Invalid register address format: {register_addr}. Must be integer or hexadecimal string.") from None
        
        if not (0 <= register_addr <= 255):
             raise CommandValidationError(f"Invalid register address {register_addr}. Must be between 0 and 255.") from None
        
        return await self.commands.read_cc1101_register(register_addr, timeout=SDUINO_CMD_TIMEOUT)

    # --- Decoder Enable/Disable (CE/CD) ---
    
    async def set_decoder_ms_enable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/config/decoder_ms_enable'."""
        await self.commands.set_decoder_enable("S")
        return await self.commands.get_config(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_decoder_ms_disable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/config/decoder_ms_disable'."""
        await self.commands.set_decoder_disable("S")
        return await self.commands.get_config(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_decoder_mu_enable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/config/decoder_mu_enable'."""
        await self.commands.set_decoder_enable("U")
        return await self.commands.get_config(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_decoder_mu_disable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/config/decoder_mu_disable'."""
        await self.commands.set_decoder_disable("U")
        return await self.commands.get_config(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_decoder_mc_enable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/config/decoder_mc_enable'."""
        await self.commands.set_decoder_enable("C")
        return await self.commands.get_config(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_decoder_mc_disable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/config/decoder_mc_disable'."""
        await self.commands.set_decoder_disable("C")
        return await self.commands.get_config(timeout=SDUINO_CMD_TIMEOUT)


    # --- PHASE 2: CC1101 SETTER METHODEN ---

    async def set_cc1101_frequency(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/cc1101/frequency' (W0Fxx, W10xx, W11xx)."""
        # Logik aus cc1101::SetFreq in 00_SIGNALduino.pm
        freq_mhz = payload["value"]
        
        # Berechnung der Registerwerte
        # FREQ = freq_mhz * 2^16 / 26
        freq_val = int(freq_mhz * (2**16) / 26)
        
        f2 = freq_val // 65536
        f1 = (freq_val % 65536) // 256
        f0 = freq_val % 256
        
        # Senden der Befehle: W0F<F2>, W10<F1>, W11<F0> (Adressen 0D, 0E, 0F mit Offset 2)
        await self.commands._send_command(payload=f"W0F{f2:02X}", expect_response=False)
        await self.commands._send_command(payload=f"W10{f1:02X}", expect_response=False)
        await self.commands._send_command(payload=f"W11{f0:02X}", expect_response=False)
        
        # Initialisierung des CC1101 nach Register-Änderung (SIDLE, SFRX, SRX)
        await self.commands.cc1101_write_init()
        
        return await self.commands.get_ccconf(timeout=SDUINO_CMD_TIMEOUT) # Konfiguration zurückgeben
        
    async def set_cc1101_rampl(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/cc1101/rampl' (AGCCTRL2, 1B)."""
        # Logik aus cc1101::setrAmpl in 00_SIGNALduino.pm (v = Index 0-7)
        rampl_db = payload["value"]
        
        ampllist = [24, 27, 30, 33, 36, 38, 40, 42]
        v = 0
        for i, val in enumerate(ampllist):
            if val > rampl_db:
                break
            v = i
        
        reg_val = f"{v:02d}" # Index 0-7
        
        # FHEM sendet W1D<v>. AGCCTRL2 ist 1B. Die Adresse W1D ist die FHEM-Konvention.
        await self.commands._send_command(payload=f"W1D{reg_val}", expect_response=False)
        await self.commands.cc1101_write_init()
        return await self.commands.get_ccconf(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_cc1101_patable(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/cc1101/patable' (x<val>)."""
        # Logik aus cc1101::SetPatable in 00_SIGNALduino.pm
        patable_str = payload["value"]
        
        # Mapping von String zu Hex-Wert (433MHz-Werte aus 00_SIGNALduino.pm, Zeile 94ff)
        patable_map = {
            '-30_dBm': '12', '-20_dBm': '0E', '-15_dBm': '1D', '-10_dBm': '34',
            '-5_dBm': '68', '0_dBm': '60', '5_dBm': '84', '7_dBm': 'C8', '10_dBm': 'C0',
        }
        
        pa_hex = patable_map.get(patable_str, 'C0') # Default 10_dBm
        
        # Befehl x<val> sendet den Wert an die PA Table.
        await self.commands._send_command(payload=f"x{pa_hex}", expect_response=False)
        await self.commands.cc1101_write_init()
        return await self.commands.get_ccpatable(timeout=SDUINO_CMD_TIMEOUT) # PA Table zurückgeben
        
    async def set_cc1101_sensitivity(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/cc1101/sens' (AGCCTRL0, 1D)."""
        # Logik aus cc1101::SetSens in 00_SIGNALduino.pm
        sens_db = payload["value"]
        
        # Die FHEM-Logik: $v = sprintf("9%d",$a[1]/4-1)
        v_idx = int(sens_db / 4) - 1
        reg_val = f"9{v_idx}"
        
        # FHEM sendet W1F<v> an AGCCTRL0 (1D)
        await self.commands._send_command(payload=f"W1F{reg_val}", expect_response=False)
        await self.commands.cc1101_write_init()
        return await self.commands.get_ccconf(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_cc1101_deviation(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/cc1101/deviatn' (DEVIATN, 15)."""
        # Logik nutzt _calc_deviation_reg
        deviation_khz = payload["value"]
        
        reg_hex = self._calc_deviation_reg(deviation_khz)
        
        # FHEM sendet W17<reg_hex> (Adresse 15 mit Offset 2 ist 17)
        await self.commands._send_command(payload=f"W17{reg_hex}", expect_response=False)
        await self.commands.cc1101_write_init()
        return await self.commands.get_ccconf(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_cc1101_datarate(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/cc1101/dataRate' (MDMCFG4, MDMCFG3)."""
        # Logik nutzt _calc_data_rate_regs
        datarate_kbaud = payload["value"]
        
        # 1. MDMCFG4 (0x10) lesen
        try:
            mdcfg4_resp = await self.commands.read_cc1101_register(0x10, timeout=SDUINO_CMD_TIMEOUT)
        except SignalduinoCommandTimeout:
            raise CommandValidationError("CC1101 register 0x10 read failed (timeout). Cannot set data rate.") from None
        
        # Ergebnis-Format: C10 = 57. Wir brauchen nur 57
        match = re.search(r'C10\s=\s([A-Fa-f0-9]{2})$', mdcfg4_resp)
        if not match:
            raise CommandValidationError(f"Failed to parse current MDMCFG4 (0x10) value from firmware response: {mdcfg4_resp}") from None
        
        mdcfg4_hex = match.group(1)
        
        # Schritt 2: Register neu berechnen
        mdcfg4_new_hex, mdcfg3_new_hex = self._calc_data_rate_regs(datarate_kbaud, mdcfg4_hex)
        
        # Schritt 3: Schreiben (0x10 -> W12, 0x11 -> W13)
        await self.commands._send_command(payload=f"W12{mdcfg4_new_hex}", expect_response=False)
        await self.commands._send_command(payload=f"W13{mdcfg3_new_hex}", expect_response=False)
        
        await self.commands.cc1101_write_init()
        return await self.commands.get_ccconf(timeout=SDUINO_CMD_TIMEOUT)
        
    async def set_cc1101_bandwidth(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'set/cc1101/bWidth' (MDMCFG4)."""
        # Logik nutzt _calc_bandwidth_reg
        bandwidth_khz = payload["value"]
        
        # 1. MDMCFG4 (0x10) lesen
        try:
            mdcfg4_resp = await self.commands.read_cc1101_register(0x10, timeout=SDUINO_CMD_TIMEOUT)
        except SignalduinoCommandTimeout:
            raise CommandValidationError("CC1101 register 0x10 read failed (timeout). Cannot set bandwidth.") from None
        
        match = re.search(r'C10\s=\s([A-Fa-f0-9]{2})$', mdcfg4_resp)
        if not match:
            raise CommandValidationError(f"Failed to parse current MDMCFG4 (0x10) value from firmware response: {mdcfg4_resp}") from None
        
        mdcfg4_hex = match.group(1)

        # Schritt 2: Register 0x10 neu berechnen (nur Bits 7:4)
        mdcfg4_new_hex = self._calc_bandwidth_reg(bandwidth_khz, mdcfg4_hex)

        # Schritt 3: Schreiben (0x10 -> W12)
        await self.commands._send_command(payload=f"W12{mdcfg4_new_hex}", expect_response=False)
        
        await self.commands.cc1101_write_init()
        return await self.commands.get_ccconf(timeout=SDUINO_CMD_TIMEOUT)

    async def command_send_msg(self, payload: Dict[str, Any]) -> str:
        """Controller implementation for 'command/send/msg' (SR, SM, SN)."""
        # Logik aus SIGNALduino_Set_sendMsg in 00_SIGNALduino.pm
        
        params = payload["parameters"]
        protocol_id = params["protocol_id"]
        data = params["data"]
        repeats = params.get("repeats", 1)
        clock_us = params.get("clock_us")
        frequency_mhz = params.get("frequency_mhz")
        
        # 1. Datenvorverarbeitung (Hex zu Bin, Tristate zu Bin)
        data_is_hex = data.startswith("0x")
        if data_is_hex:
            data = data[2:]
            # Konvertierung zu Bits erfolgt hier nicht, da wir oft Hex für SM/SN benötigen.
        elif protocol_id in [3]: # IT V1 (Protokoll 3) verwendet Tristate (0, 1, F) in FHEM
            # Wir behandeln tristate direkt als Datenstring, der an die Firmware gesendet wird.
            # Im FHEM-Modul wird hier die Konvertierung zu Binär durchgeführt, was wir hier
            # überspringen müssen, da wir die Protokoll-Objekte nicht haben.
            pass # Platzhalter für _tristate_to_bit(data)
            
        # 2. Protokoll-Abhängige Befehlsgenerierung (Hier stark vereinfacht)
        
        freq_part = ""
        if frequency_mhz is not None:
            # Berechnung der Frequenzregisterwerte (wie in set_cc1101_frequency)
            freq_val = int(frequency_mhz * (2**16) / 26)
            f2 = freq_val // 65536
            f1 = (freq_val % 65536) // 256
            f0 = freq_val % 256
            freq_part = f"F={f2:02X}{f1:02X}{f0:02X};"
            
        # Wenn eine Clock gegeben ist, nehmen wir Manchester (SM), andernfalls SN (xFSK/Raw-Data)
        if clock_us is not None:
            # SM: Send Manchester (braucht Clock C=<us>, Data D=<hex>)
            # data muss Hex-kodiert sein
            if not data_is_hex:
                 raise CommandValidationError("Manchester send requires hex data in 'data' field (prefixed with 0x...).")
            raw_cmd = f"SM;R={repeats};C={clock_us};D={data};{freq_part}"
        else:
            # SN/SR: Send xFSK/Raw Data
            # Wir verwenden SN, wenn die Daten Hex sind, da es die einfachste Übertragung ist.
            if not data_is_hex:
                 # Dies ist der komplizierte Fall (MS/MU), da Protokoll-Details (P-Buckets) fehlen.
                 raise CommandValidationError("Cannot process raw (MS/MU) data without protocol details. Only Hex-based (SN) or Clocked (SM) sends are currently supported.")

            # SN: Send xFSK
            raw_cmd = f"SN;R={repeats};D={data};{freq_part}"
        
        # 3. Befehl senden
        response = await self.commands.send_raw_message(raw_cmd, timeout=SDUINO_CMD_TIMEOUT)
        
        return response

    async def run(self, timeout: Optional[float] = None) -> None:
        """
        Starts the main asynchronous tasks (reader, parser, writer) 
        and waits for them to complete or for a connection loss.
        """
        self.logger.info("Starting main controller tasks...")

        # 1. Haupt-Tasks erstellen und starten (Muss VOR initialize() erfolgen, damit der Reader
        # die Initialisierungsantwort empfangen kann)
        reader_task = asyncio.create_task(self._reader_task(), name="sd-reader")
        parser_task = asyncio.create_task(self._parser_task(), name="sd-parser")
        writer_task = asyncio.create_task(self._writer_task(), name="sd-writer")
        
        self._main_tasks = [reader_task, parser_task, writer_task]
        
        # 2. Initialisierung starten (führt Versionsprüfung durch und startet Heartbeat)
        await self.initialize()
        
        # 3. Auf den Abschluss der Initialisierung warten (mit zusätzlichem Timeout)
        try:
            self.logger.info("Waiting for initialization to complete...")
            await asyncio.wait_for(self._init_complete_event.wait(), timeout=SDUINO_CMD_TIMEOUT * 2)
            self.logger.info("Initialization complete.")
        except asyncio.TimeoutError:
            self.logger.error("Initialization timed out after %s seconds.", SDUINO_CMD_TIMEOUT * 2)
            # Wenn die Initialisierung fehlschlägt, stoppen wir den Controller (aexit)
            self._stop_event.set()
            # Der Timeout kann dazu führen, dass die await-Kette unterbrochen wird. Wir fahren fort.

        # 4. Auf eine der kritischen Haupt-Tasks warten (Reader/Writer werden bei Verbindungsabbruch beendet)
        # Parser sollte weiterlaufen, bis die Queue leer ist. Reader/Writer sind die kritischen Tasks.
        critical_tasks = [reader_task, writer_task]

        # Führe ein Wait mit optionalem Timeout aus, das mit `asyncio.wait_for` implementiert wird
        if timeout is not None:
            try:
                # Warten auf die kritischen Tasks, bis sie fertig sind oder ein Timeout eintritt
                done, pending = await asyncio.wait_for(
                    asyncio.wait(critical_tasks, return_when=asyncio.FIRST_COMPLETED),
                    timeout=timeout
                )
                self.logger.info("Run finished due to timeout or task completion.")

            except asyncio.TimeoutError:
                self.logger.info("Run finished due to timeout (%s seconds).", timeout)
                # Das aexit wird sich um das Aufräumen kümmern
            
        else:
            # Warten, bis eine der kritischen Tasks abgeschlossen ist
            done, pending = await asyncio.wait(
                critical_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            # Wenn ein Task unerwartet beendet wird (z.B. durch Fehler), sollte er in `done` sein.
            # Wenn das Stopp-Event nicht gesetzt ist, war es ein Fehler.
            if any(t.exception() for t in done) and not self._stop_event.is_set():
                self.logger.error("A critical controller task finished with an exception.")

        # Das aexit im async with Block wird sich um das Aufräumen kümmern
        # (Schließen des Transports, Abbrechen aller Tasks).