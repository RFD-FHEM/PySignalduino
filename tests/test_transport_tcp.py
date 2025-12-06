import socket
import unittest
from unittest.mock import MagicMock, patch
from signalduino.transport import TCPTransport
from signalduino.exceptions import SignalduinoConnectionError

class TestTCPTransport(unittest.TestCase):
    def setUp(self):
        self.host = "127.0.0.1"
        self.port = 8080
        self.transport = TCPTransport(self.host, self.port)

    @patch('socket.create_connection')
    def test_open(self, mock_create_connection):
        mock_sock = MagicMock()
        mock_create_connection.return_value = mock_sock
        
        self.transport.open()
        
        mock_create_connection.assert_called_with((self.host, self.port), timeout=5)
        self.assertTrue(self.transport.is_open)

    def test_readline_timeout(self):
        # Setup mock socket
        mock_sock = MagicMock()
        # Simulate timeout on recv
        mock_sock.recv.side_effect = socket.timeout
        
        self.transport._sock = mock_sock
        
        # Test
        result = self.transport.readline()
        self.assertIsNone(result)

    def test_readline_eof(self):
        # Setup mock socket
        mock_sock = MagicMock()
        # Simulate EOF (empty bytes)
        mock_sock.recv.return_value = b''
        
        self.transport._sock = mock_sock
        
        # Test
        with self.assertRaises(SignalduinoConnectionError):
            self.transport.readline()

    def test_readline_success(self):
        # Setup mock socket
        mock_sock = MagicMock()
        # Simulate data
        mock_sock.recv.return_value = b'test line\n'
        
        self.transport._sock = mock_sock
        
        # Test
        result = self.transport.readline()
        self.assertEqual(result, 'test line')