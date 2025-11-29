import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import tempfile
import os
from signalduino.firmware import (
    check_for_updates,
    download_firmware,
    prepare_flash_command,
    flash_firmware,
    FirmwareError,
    FirmwareDownloadError,
    FirmwareFlashError
)
from signalduino.hardware import HardwareType

# Mock GitHub response
MOCK_RELEASES = [
    {
        "tag_name": "3.3.1-RC10",
        "prerelease": True,
        "assets": [
            {
                "name": "SIGNALDuino_nanocc1101.hex",
                "browser_download_url": "http://example.com/SIGNALDuino_nanocc1101.hex",
                "created_at": "2021-01-01T00:00:00Z"
            }
        ]
    },
    {
        "tag_name": "3.3.1",
        "prerelease": False,
        "assets": [
            {
                "name": "SIGNALDuino_nanocc1101.hex",
                "browser_download_url": "http://example.com/stable/SIGNALDuino_nanocc1101.hex",
                "created_at": "2021-02-01T00:00:00Z"
            }
        ]
    }
]

@pytest.mark.asyncio
async def test_check_for_updates_stable():
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = MOCK_RELEASES
        mock_get.return_value.status_code = 200
        
        updates = await check_for_updates(HardwareType.NANO_CC1101, channel="stable")
        
        assert len(updates) == 1
        assert updates[0]["version"] == "3.3.1"
        assert updates[0]["filename"] == "SIGNALDuino_nanocc1101.hex"

@pytest.mark.asyncio
async def test_check_for_updates_testing():
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = MOCK_RELEASES
        mock_get.return_value.status_code = 200
        
        updates = await check_for_updates(HardwareType.NANO_CC1101, channel="testing")
        
        # Should return both stable and testing
        assert len(updates) == 2
        versions = [u["version"] for u in updates]
        assert "3.3.1-RC10" in versions
        assert "3.3.1" in versions

@pytest.mark.asyncio
async def test_download_firmware():
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.iter_content.return_value = [b"firmware_data"]
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            target_path = tmp.name
            
        try:
            path = await download_firmware("http://example.com/fw.hex", target_path)
            assert path == target_path
            with open(path, "rb") as f:
                assert f.read() == b"firmware_data"
        finally:
            if os.path.exists(target_path):
                os.remove(target_path)

def test_prepare_flash_command():
    with patch("shutil.which", return_value="/usr/bin/avrdude"):
        cmd, context = prepare_flash_command(
            device_port="/dev/ttyUSB0",
            hex_file="/tmp/fw.hex",
            hardware_type=HardwareType.NANO_CC1101
        )
        
        assert "avrdude" in cmd
        assert "-c arduino" in cmd
        assert "-P /dev/ttyUSB0" in cmd
        assert "-p atmega328p" in cmd
        assert "/tmp/fw.hex" in cmd
        assert context.get("requires_1200bps_reset") is False

@pytest.mark.asyncio
async def test_flash_firmware_success():
    with patch("shutil.which", return_value="/usr/bin/avrdude"), \
         patch("asyncio.create_subprocess_shell") as mock_subprocess:
        
        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"avrdude done.  Thank you.", b"")
        process_mock.returncode = 0
        mock_subprocess.return_value = process_mock
        
        output = await flash_firmware(
            device_port="/dev/ttyUSB0",
            hex_file="/tmp/fw.hex",
            hardware_type=HardwareType.NANO_CC1101
        )
        
        assert "avrdude done" in output
        mock_subprocess.assert_called_once()

@pytest.mark.asyncio
async def test_flash_firmware_failure():
    with patch("shutil.which", return_value="/usr/bin/avrdude"), \
         patch("asyncio.create_subprocess_shell") as mock_subprocess:
        
        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"", b"Error flashing")
        process_mock.returncode = 1
        mock_subprocess.return_value = process_mock
        
        with pytest.raises(FirmwareFlashError):
            await flash_firmware(
                device_port="/dev/ttyUSB0",
                hex_file="/tmp/fw.hex",
                hardware_type=HardwareType.NANO_CC1101
            )