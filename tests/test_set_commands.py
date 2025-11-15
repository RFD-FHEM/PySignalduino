from unittest.mock import MagicMock, Mock

import pytest

from signalduino.controller import SignalduinoController


@pytest.fixture
def mock_transport():
    transport = Mock()
    transport.is_open = True
    transport.write_line = Mock()
    return transport


@pytest.fixture
def controller(mock_transport):
    """Fixture for a SignalduinoController with a mocked transport."""
    ctrl = SignalduinoController(transport=mock_transport)
    # We don't want to test the full threading model here, so we mock the queue
    ctrl._write_queue = MagicMock()
    return ctrl


def test_send_raw_command(controller):
    """
    Tests that send_raw_command puts the correct command in the write queue.
    This corresponds to the 'set raw W0D23#W0B22' test in Perl.
    """
    controller.send_raw_command("W0D23#W0B22")

    # Verify that the command was put into the queue
    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload == "W0D23#W0B22"


@pytest.mark.parametrize(
    "message_type, enabled, expected_command",
    [
        ("MS", True, "CES"),
        ("MS", False, "CDS"),
        ("MU", True, "CEU"),
        ("MU", False, "CDU"),
        ("MC", True, "CEC"),
        ("MC", False, "CDC"),
    ],
)
def test_set_message_type_enabled(controller, message_type, enabled, expected_command):
    """Test enabling and disabling message types."""
    controller.set_message_type_enabled(message_type, enabled)

    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload == expected_command


@pytest.mark.parametrize(
    "method_name, value, expected_command_prefix",
    [
        ("set_bwidth", 102, "C10102"),
        ("set_rampl", 24, "W1D24"),
        ("set_sens", 8, "W1F8"),
        ("set_patable", "C0", "xC0"),
    ],
)
def test_cc1101_commands(controller, method_name, value, expected_command_prefix):
    """Test various CC1101 set commands."""
    method = getattr(controller, method_name)
    method(value)

    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload.startswith(expected_command_prefix)


def test_send_message(controller):
    """Test sending a pre-encoded message."""
    message = "P3#is11111000000F#R6"
    controller.send_message(message)

    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload == message
