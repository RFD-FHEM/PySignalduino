import pytest

@pytest.mark.timeout(5)
@pytest.mark.asyncio
async def test_send_raw_command(controller):
    """
    Tests that send_raw_command puts the correct command in the write queue.
    This corresponds to the 'set raw W0D23#W0B22' test in Perl.
    """
    await controller.commands.send_raw_message(command="W0D23#W0B22")

    # Verify that the command was put into the queue
    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload == "W0D23#W0B22"

@pytest.mark.timeout(5)
@pytest.mark.asyncio
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
async def test_set_message_type_enabled(controller, message_type, enabled, expected_command):
    """Test enabling and disabling message types."""
    await controller.commands.set_message_type_enabled(message_type, enabled)

    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload == expected_command

@pytest.mark.timeout(5)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name, value, expected_command_prefix",
    [
        ("set_bwidth", 102, "C10102"),
        ("set_rampl", 24, "W1D00"),
        ("set_sens", 8, "W1F91"),
        ("set_patable", "C0", "xC0"),
    ],
)
async def test_cc1101_commands(controller, method_name, value, expected_command_prefix):
    """Test various CC1101 set commands."""
    method = getattr(controller.commands, method_name)
    await method(value)

    # Get all calls and check if the expected command is among them
    calls = controller._write_queue.put.call_args_list
    assert any(call[0][0].payload.startswith(expected_command_prefix) for call in calls)


@pytest.mark.asyncio
async def test_send_message(controller):
    """Test sending a pre-encoded message."""
    message = "P3#is11111000000F#R6"
    await controller.commands.send_message(message)

    controller._write_queue.put.assert_called_once()
    queued_command = controller._write_queue.put.call_args[0][0]
    assert queued_command.payload == message
