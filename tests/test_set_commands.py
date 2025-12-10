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

    def mock_put(queued_command):
        # Simulate an immediate response for commands that expect one.
        # This is necessary because we mock the internal thread queue.
        if queued_command.expect_response and queued_command.on_response:
            # For Set-Commands, the response is often an echo of the command itself or 'OK'.
            # We use the command payload as the response.
            queued_command.on_response(queued_command.payload)

    # We don't want to test the full threading model here, so we mock the queue
    ctrl._write_queue = MagicMock()
    ctrl._write_queue.put.side_effect = mock_put
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
        ("MS", True, "CEMS"),
        ("MS", False, "CDMS"),
        ("MU", True, "CEMU"),
        ("MU", False, "CDMU"),
        ("MC", True, "CEMC"),
        ("MC", False, "CDMC"),
    ],
)
def test_set_message_type_enabled(controller, message_type, enabled, expected_command):
    """Test enabling and disabling message types."""
    controller.commands.set_message_type_enabled(message_type, enabled)

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
    method = getattr(controller.commands, method_name)
    method(value)

    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload.startswith(expected_command_prefix)


def test_send_message(controller):
    """Test sending a pre-encoded message."""
    message = "P3#is11111000000F#R6"
    controller.commands.send_message(message)

    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload == message
