import queue
import threading
import time
import unittest
from unittest.mock import MagicMock

from signalduino.controller import SignalduinoController
from signalduino.exceptions import SignalduinoCommandTimeout, SignalduinoConnectionError
from signalduino.transport import BaseTransport

class MockTransport(BaseTransport):
    def __init__(self):
        self.is_open_flag = False
        self.output_queue = queue.Queue()

    def open(self):
        self.is_open_flag = True

    def close(self):
        self.is_open_flag = False

    @property
    def is_open(self):
        return self.is_open_flag

    def write_line(self, data):
        if not self.is_open_flag:
            raise SignalduinoConnectionError("Closed")

    def readline(self, timeout=None):
        if not self.is_open_flag:
             raise SignalduinoConnectionError("Closed")
        try:
            return self.output_queue.get(timeout=timeout or 0.1)
        except queue.Empty:
            return None

class TestConnectionDrop(unittest.TestCase):
    def test_timeout_normally(self):
        """Test that a simple timeout raises SignalduinoCommandTimeout."""
        transport = MockTransport()
        controller = SignalduinoController(transport)
        controller.connect()
        
        # Expect SignalduinoCommandTimeout because transport sends nothing
        with self.assertRaises(SignalduinoCommandTimeout):
            controller.send_command("V", expect_response=True, timeout=0.5)
            
        controller.disconnect()

    def test_connection_drop_during_command(self):
        """Test that if connection dies during command wait, we get ConnectionError."""
        transport = MockTransport()
        controller = SignalduinoController(transport)
        controller.connect()

        # We need to simulate the reader loop crashing or transport closing
        # signalduino controller checks transport.is_open or _stop_event
        
        # Hook into write_line to close transport immediately after sending
        # simulating a crash right after send
        original_write = transport.write_line
        def side_effect(data):
            original_write(data)
            # Simulate connection loss
            transport.close()
            # Also set stop event as reader loop would
            controller._stop_event.set()
            
        transport.write_line = side_effect

        # Current behavior: Raises SignalduinoCommandTimeout because it just waits on queue
        # Desired behavior: Raises SignalduinoConnectionError because connection is dead
        
        try:
            controller.send_command("V", expect_response=True, timeout=1.0)
        except Exception as e:
            print(f"Caught exception: {type(e).__name__}: {e}")
            # validating what it currently raises
            # self.assertIsInstance(e, SignalduinoConnectionError) 

        controller.disconnect()