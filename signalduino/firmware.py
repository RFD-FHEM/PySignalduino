"""
Firmware management for SIGNALduino.
Handles checking for updates, downloading firmware, and flashing devices.
"""
import os
import logging
import subprocess
import shutil
import tempfile
import requests
import asyncio
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path

from .hardware import get_hardware_config, is_supported_for_flashing

_LOGGER = logging.getLogger(__name__)

GITHUB_RELEASES_URL = "https://api.github.com/repos/RFD-FHEM/SIGNALDuino/releases"

class FirmwareError(Exception):
    """Base exception for firmware operations."""
    pass

class FirmwareDownloadError(FirmwareError):
    """Error during firmware download."""
    pass

class FirmwareFlashError(FirmwareError):
    """Error during firmware flashing."""
    pass

async def check_for_updates(hardware_type: str, channel: str = "stable") -> List[Dict[str, Any]]:
    """
    Check for available firmware updates on GitHub.
    
    Args:
        hardware_type: The hardware type to filter for (e.g. 'nanoCC1101').
        channel: Update channel ('stable' or 'testing'). 'testing' includes pre-releases.
        
    Returns:
        List of available firmware assets matching the hardware type.
    """
    try:
        response = requests.get(GITHUB_RELEASES_URL, timeout=10)
        response.raise_for_status()
        releases = response.json()
    except requests.RequestException as e:
        _LOGGER.error(f"Failed to fetch releases from GitHub: {e}")
        return []

    available_firmware = []
    
    for release in releases:
        # Filter by channel
        if channel == "stable" and release.get("prerelease", False):
            continue
            
        tag_name = release.get("tag_name", "")
        
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            # Case-insensitive match for hardware type in filename
            if hardware_type.lower() in name.lower() and name.endswith(".hex"):
                available_firmware.append({
                    "version": tag_name,
                    "filename": name,
                    "download_url": asset.get("browser_download_url"),
                    "date": asset.get("created_at"),
                    "prerelease": release.get("prerelease", False)
                })
                # Only take the first matching asset per release? 
                # Perl implementation seems to take the first match per release.
                break
                
    return available_firmware

async def download_firmware(url: str, target_path: Optional[str] = None) -> str:
    """
    Download firmware from a URL.
    
    Args:
        url: The URL to download from.
        target_path: Optional local path to save to. If None, a temporary file is created.
        
    Returns:
        Path to the downloaded file.
    """
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        if target_path is None:
            # Create a temp file
            filename = url.split("/")[-1]
            if not filename.endswith(".hex"):
                filename += ".hex"
            
            # Use a named temporary file that persists so we can return the path
            # The caller is responsible for cleanup if needed, but for firmware flashing usually we keep it or overwrite
            fd, path = tempfile.mkstemp(suffix=".hex", prefix="signalduino_fw_")
            os.close(fd)
            target_path = path
            
        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        _LOGGER.info(f"Downloaded firmware to {target_path}")
        return target_path
        
    except requests.RequestException as e:
        raise FirmwareDownloadError(f"Failed to download firmware: {e}")
    except IOError as e:
        raise FirmwareDownloadError(f"Failed to save firmware file: {e}")

def prepare_flash_command(
    device_port: str,
    hex_file: str,
    hardware_type: str,
    custom_flash_cmd: Optional[str] = None
) -> Tuple[str, dict]:
    """
    Construct the avrdude command for flashing.
    
    Args:
        device_port: Serial port (e.g. /dev/ttyUSB0).
        hex_file: Path to the .hex file.
        hardware_type: The hardware type identifier.
        custom_flash_cmd: Optional user-provided flash command template.
        
    Returns:
        Tuple containing the command string (for logging) and execution context.
    """
    config = get_hardware_config(hardware_type)
    if not config:
        raise FirmwareError(f"Unsupported hardware type for flashing: {hardware_type}")
        
    if not shutil.which("avrdude"):
        raise FirmwareError("avrdude tool not found. Please install it (e.g., 'sudo apt-get install avrdude').")

    cmd_template = custom_flash_cmd if custom_flash_cmd else config.flash_cmd_template
    
    # We need a logfile for avrdude output capture if we want to parse it later, 
    # but for now we might just want to capture stdout/stderr via subprocess.
    # The Perl module uses 2>[LOGFILE]. Here we will let subprocess handle capture.
    # We strip the redirection part if present in custom command for Python execution compatibility,
    # or better, we construct our own clean command list.
    
    # For simplicity and robustness, we'll construct the command arguments list if using default,
    # or parse the string if custom.
    
    # Let's simple replace placeholders in the string.
    # [BAUDRATE], [PORT], [HEXFILE], [LOGFILE], [PROGRAMMER], [PARTNO]
    
    cmd_str = cmd_template.replace("[BAUDRATE]", str(config.baudrate))
    cmd_str = cmd_str.replace("[PORT]", device_port)
    cmd_str = cmd_str.replace("[HEXFILE]", hex_file)
    cmd_str = cmd_str.replace("[PROGRAMMER]", config.avrdude_programmer)
    cmd_str = cmd_str.replace("[PARTNO]", config.avrdude_partno)
    
    # Handle LOGFILE placeholder by removing it or redirecting to a temp file?
    # Python subprocess captures output directly, so we might want to remove file redirection
    # if it exists in the template.
    # Simple regex to remove '2>[LOGFILE]' or similar might be needed if users copy-paste Perl attributes.
    # For now, let's assume we replace it with a temp file path if present, or ignore.
    log_file = os.path.join(tempfile.gettempdir(), "signalduino_flash.log")
    cmd_str = cmd_str.replace("[LOGFILE]", log_file)
    
    return cmd_str, {"requires_1200bps_reset": config.requires_1200bps_reset}

async def flash_firmware(
    device_port: str,
    hex_file: str,
    hardware_type: str,
    custom_flash_cmd: Optional[str] = None
) -> str:
    """
    Flash the firmware to the device.
    
    Args:
        device_port: Serial port.
        hex_file: Path to firmware file.
        hardware_type: Hardware identifier.
        custom_flash_cmd: Optional custom command template.
        
    Returns:
        Output log from the flashing process.
    """
    if not is_supported_for_flashing(hardware_type):
        raise FirmwareError(f"Flashing not supported for hardware: {hardware_type}")
        
    cmd_str, context = prepare_flash_command(device_port, hex_file, hardware_type, custom_flash_cmd)
    
    _LOGGER.info(f"Preparing to flash {hardware_type} on {device_port}")
    
    # Handle 1200bps reset for Radino/Leonardo/ProMicro if needed
    if context.get("requires_1200bps_reset"):
        _LOGGER.info("Performing 1200bps reset trigger...")
        try:
            # Open port at 1200 baud and close it to trigger bootloader
            import serial
            with serial.Serial(device_port, 1200) as ser:
                pass
            # Wait for bootloader to activate
            await asyncio.sleep(2) 
            
            # Radino might change port name on Linux/Windows? 
            # Perl code mentions port change logic: "$port =~ s/usb-Unknown_radino/usb-In-Circuit_radino/g;"
            # We will rely on persistent device paths (e.g. /dev/serial/by-id/...) for stability if possible.
            # If the user provided a raw /dev/ttyACM0 it might change index. 
            # For now, we assume the port stays valid or the user uses by-id links.
            
        except Exception as e:
            _LOGGER.warning(f"1200bps reset trigger failed: {e}")
    
    _LOGGER.info(f"Executing flash command: {cmd_str}")
    
    # Execute the command
    # Use shell=True because cmd_str is a full string potentially with redirections (though we tried to handle logfile)
    # Ideally we should split into args for security, but custom commands make that hard.
    
    process = await asyncio.create_subprocess_shell(
        cmd_str,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    output = ""
    if stdout:
        output += stdout.decode('utf-8', errors='replace')
    if stderr:
        output += stderr.decode('utf-8', errors='replace')
        
    # Also read from logfile if it was used in command
    if "[LOGFILE]" in (custom_flash_cmd or "") or "2>" in cmd_str:
         # Check if we defined a logfile path in prepare_flash_command
         log_file = os.path.join(tempfile.gettempdir(), "signalduino_flash.log")
         if os.path.exists(log_file):
             with open(log_file, 'r') as f:
                 output += "\n--- Logfile Content ---\n"
                 output += f.read()
    
    if process.returncode != 0:
        _LOGGER.error(f"Flashing failed with code {process.returncode}")
        _LOGGER.error(output)
        raise FirmwareFlashError(f"Flashing failed: {output}")
        
    _LOGGER.info("Flashing successful")
    return output