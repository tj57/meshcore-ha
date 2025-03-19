"""API for communicating with MeshCore devices using direct import."""
import logging
import asyncio
import json
import time
import os
import sys
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
from asyncio import Lock

# Import directly from the vendor module
from .vendor.mccli import (
    MeshCore, 
    BLEConnection, 
    SerialConnection, 
    TCPConnection,
    UART_SERVICE_UUID,
    UART_RX_CHAR_UUID,
    UART_TX_CHAR_UUID
)

from .const import (
    CONNECTION_TYPE_USB,
    CONNECTION_TYPE_BLE,
    CONNECTION_TYPE_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_TCP_PORT,
)

_LOGGER = logging.getLogger(__name__)

class MeshCoreAPI:
    """API for interacting with MeshCore devices by directly using the MeshCore class."""

    def __init__(
        self,
        connection_type: str,
        usb_path: Optional[str] = None,
        baudrate: int = DEFAULT_BAUDRATE,
        ble_address: Optional[str] = None,
        tcp_host: Optional[str] = None,
        tcp_port: int = DEFAULT_TCP_PORT,
    ) -> None:
        """Initialize the API."""
        self.connection_type = connection_type
        self.usb_path = usb_path
        self.baudrate = baudrate
        self.ble_address = ble_address
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        
        self._connected = False
        self._connection = None
        self._mesh_core = None
        self._node_info = {}
        self._cached_contacts = {}
        self._cached_messages = []
        
        # Add a lock to prevent concurrent access to the device
        self._device_lock = Lock()
        
    async def connect(self) -> bool:
        """Connect to the MeshCore device using the appropriate connection type."""
        try:
            # Reset state first
            self._connected = False
            self._connection = None
            self._mesh_core = None
            
            _LOGGER.info("Connecting to MeshCore device...")
            
            # Create the appropriate connection object based on connection type
            if self.connection_type == CONNECTION_TYPE_USB and self.usb_path:
                _LOGGER.info(f"Using USB connection at {self.usb_path} with baudrate {self.baudrate}")
                self._connection = SerialConnection(self.usb_path, self.baudrate)
                
                # Establish the connection
                address = await self._connection.connect()
                _LOGGER.info(f"Established Address {address}")
                
                # Add a longer delay for serial connection to stabilize
                # Increased from the original implementation for more stability
                await asyncio.sleep(0.5)
                
            elif self.connection_type == CONNECTION_TYPE_BLE:
                _LOGGER.info(f"Using BLE connection with address {self.ble_address}")
                self._connection = BLEConnection(self.ble_address if self.ble_address else "")
                
                # Establish the connection
                address = await self._connection.connect()
                
            elif self.connection_type == CONNECTION_TYPE_TCP and self.tcp_host:
                _LOGGER.info(f"Using TCP connection to {self.tcp_host}:{self.tcp_port}")
                self._connection = TCPConnection(self.tcp_host, self.tcp_port)
                
                # Establish the connection
                address = await self._connection.connect()
                
            else:
                _LOGGER.error("Invalid connection configuration")
                return False
                
            if address is None:
                _LOGGER.error("Failed to connect to MeshCore device")
                return False
                
            # Create MeshCore instance with the connection and logger
            self._mesh_core = MeshCore(self._connection, logger=_LOGGER)
            
            # Wait a bit before initializing
            await asyncio.sleep(0.1)
            
            # Initialize the connection to the device
            _LOGGER.info("Initializing connection to MeshCore device...")

            init_success = await self._mesh_core.connect()
            if not init_success:
                _LOGGER.error("Failed to initialize MeshCore connection")
                return False
            
            # Sync time to ensure proper authentication
            try:
                _LOGGER.info("Synchronizing device time...")
                current_time = int(time.time())
                time_result = await self._mesh_core.set_time(current_time)
                if time_result:
                    _LOGGER.info(f"Successfully synchronized device time to {current_time}")
                    # Wait a moment for the time change to take effect
                    await asyncio.sleep(0.2)
                else:
                    _LOGGER.warning("Time synchronization failed, authentication might not work properly")
            except Exception as time_ex:
                _LOGGER.warning(f"Error during time synchronization: {time_ex}")
                
            self._connected = True
            _LOGGER.info("Successfully connected to MeshCore device")
            return True
            
        except Exception as ex:
            _LOGGER.error("Error connecting to MeshCore device: %s", ex)
            self._connected = False
            self._connection = None
            self._mesh_core = None
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from the MeshCore device."""
        try:
            # Ensure proper cleanup of any transport objects
            if self._connection and hasattr(self._connection, 'transport') and self._connection.transport: # type: ignore
                try:
                    if hasattr(self._connection.transport, 'close'): # type: ignore
                        self._connection.transport.close() # type: ignore
                    elif hasattr(self._connection.transport, 'serial') and hasattr(self._connection.transport.serial, 'close'): # type: ignore
                        self._connection.transport.serial.close() # type: ignore
                except Exception as ex:
                    _LOGGER.error(f"Error while closing transport: {ex}")
                    
            # For BLE connection, ensure the client is disconnected
            if self._connection and isinstance(self._connection, BLEConnection) and self._connection.client:
                try:
                    if self._connection.client.is_connected:
                        await self._connection.client.disconnect()
                except Exception as ex:
                    _LOGGER.error(f"Error while disconnecting BLE client: {ex}")
        except Exception as ex:
            _LOGGER.error(f"Error during disconnect: {ex}")
        finally:
            # Always reset these values
            self._connected = False
            self._connection = None
            self._mesh_core = None
            _LOGGER.info("Disconnected from MeshCore device")
        return
    
    async def get_node_info(self) -> Dict[str, Any]:
        """Get information about the node."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return {}
            
        async with self._device_lock:
            try:
                # Retrieve node info using the MeshCore instance
                _LOGGER.info("Requesting full node information via APPSTART command")
                success = await self._mesh_core.send_appstart()
                if not success:
                    _LOGGER.error("Failed to initialize app session to get node info")
                    return {}
                
                # Display helpful info about key node parameters
                radio_freq = self._mesh_core.self_info.get("radio_freq", 0) / 1000
                tx_power = self._mesh_core.self_info.get("tx_power", 0)
                node_name = self._mesh_core.self_info.get("name", "Unknown")
                
                _LOGGER.info(f"Node info received - Name: {node_name}, Freq: {radio_freq}MHz, Power: {tx_power}dBm")
                
                # The self_info attribute is updated when appstart is called
                # We need to make a copy to avoid reference issues
                self._node_info = self._mesh_core.self_info.copy()
                
                # Try to get device firmware info
                try:
                    _LOGGER.info("Requesting device firmware and hardware info")
                    device_info = await self._mesh_core.send_device_query()
                    if device_info and isinstance(device_info, dict):
                        _LOGGER.info(f"Device firmware info: version={device_info.get('firmware_version', 'Unknown')}, "
                                    f"manufacturer={device_info.get('manufacturer_name', 'Unknown')}")
                        # Merge device info into node info
                        self._node_info.update(device_info)
                except Exception as device_ex:
                    _LOGGER.warning(f"Could not get device info: {device_ex}")
                
                return self._node_info
                
            except Exception as ex:
                _LOGGER.error("Error getting node info: %s", ex)
                return {}
    
    async def get_battery(self) -> int:
        """Get battery level (raw value)."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return 0
            
        async with self._device_lock:
            try:
                _LOGGER.debug("Getting battery level...")
                battery = await self._mesh_core.get_bat()
                if battery is False:
                    _LOGGER.error("Failed to get battery level")
                    return 0
                    
                return battery
                
            except Exception as ex:
                _LOGGER.error("Error getting battery level: %s", ex)
                return 0
    
    async def get_contacts(self) -> Dict[str, Any]:
        """Get list of contacts/nodes in the mesh network."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return {}
            
        async with self._device_lock:
            try:
                # Retrieve contacts using the MeshCore instance
                _LOGGER.info("Requesting contacts list from device...")
                contacts = await self._mesh_core.get_contacts()
                
                if contacts and isinstance(contacts, dict):
                    self._cached_contacts = contacts
                    contact_count = len(contacts)
                    
                    if contact_count > 0:
                        _LOGGER.info(f"Retrieved {contact_count} contacts")
                        
                        # Log details about each contact for debugging
                        for name, contact in contacts.items():
                            node_type = "Client" if contact.get("type") == 1 else "Repeater" if contact.get("type") == 2 else "Unknown"
                            last_seen = contact.get("last_advert", 0)
                            
                            # Convert to human-readable time if available
                            if last_seen > 0:
                                from datetime import datetime
                                last_seen_str = datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M:%S")
                            else:
                                last_seen_str = "Never"
                                
                            _LOGGER.info(f"Contact: '{name}' ({node_type}), Last seen: {last_seen_str}")
                    else:
                        _LOGGER.info("No contacts found in device")
                        
                    return contacts
                else:
                    _LOGGER.warning("No contacts found or invalid contacts format")
                    return {}
                    
            except Exception as ex:
                _LOGGER.error("Error getting contacts: %s", ex)
                return {}
    
    async def get_new_messages(self) -> List[Dict[str, Any]]:
        """Get new messages from the mesh network.
        
        This implementation matches the approach used in mccli.py's sync_msgs command.
        It repeatedly calls get_msg() until it returns False, collecting all messages.
        """
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return []
            
        async with self._device_lock:
            try:
                messages = []
                
                _LOGGER.info("===== Syncing messages from device (like mccli.py sync_msgs) =====")
                
                # Use a very simple approach that matches the CLI tool's sync_msgs command
                res = True
                while res:
                    res = await self._mesh_core.get_msg()
                    
                    if res is False:
                        _LOGGER.debug("No more messages (received False)")
                        break
                        
                    if res:
                        # Log message details
                        if isinstance(res, dict):
                            if "msg" in res:
                                text = res.get("msg", "")
                                sender = res.get("sender", "Unknown") 
                                if hasattr(sender, "hex"):
                                    sender = sender.hex()
                                timestamp = res.get("sender_timestamp", "Unknown")
                                
                                _LOGGER.info(f"Retrieved message: '{text}' from {sender}")
                            else:
                                _LOGGER.info(f"Retrieved non-text message: {res}")
                        else:
                            _LOGGER.warning(f"Retrieved non-dict result: {res}")
                        
                        # Add to our message list
                        messages.append(res)
                        
                        # Add to cached messages
                        self._cached_messages.append(res)
                        # Keep only the latest 50 messages
                        if len(self._cached_messages) > 50:
                            self._cached_messages = self._cached_messages[-50:]
                    
                _LOGGER.info(f"===== Retrieved {len(messages)} messages from device =====")
                return messages
                
            except Exception as ex:
                _LOGGER.error(f"Error getting new messages: {ex}")
                return []
        
    async def wait_for_message(self, timeout: int = 10) -> Optional[Dict[str, Any]]:
        """Wait for a new message to arrive."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return None
            
        # We'll use a shorter timeout to avoid blocking the device for too long
        actual_timeout = min(timeout, 2)
            
        async with self._device_lock:
            try:
                _LOGGER.debug(f"Waiting for messages with {actual_timeout}s timeout...")
                
                # Wait for message notification
                got_message = await self._mesh_core.wait_msg(actual_timeout)
                if not got_message:
                    # Timeout waiting for message
                    _LOGGER.debug("No messages received within timeout period")
                    return None
                    
                _LOGGER.info("Message notification received, fetching message...")
                
                # Get the message
                msg = await self._mesh_core.get_msg()
                if msg:
                    _LOGGER.info(f"Message received: {msg}")
                    
                    # Add to cached messages
                    self._cached_messages.append(msg)
                    # Keep only the latest 50 messages
                    if len(self._cached_messages) > 50:
                        self._cached_messages = self._cached_messages[-50:]
                    
                    # We won't check for additional messages here to avoid
                    # blocking the device for too long
                    return msg
                
                _LOGGER.debug("Message notification received but no message data found")
                return None
                
            except Exception as ex:
                _LOGGER.error(f"Error waiting for message: {ex}")
                return None
    
    async def request_status(self) -> Dict[str, Any]:
        """Request status from all nodes.
        
        Note: Currently disabled to avoid potential device issues.
        """
        # Skipping status requests due to device issues
        _LOGGER.debug("Status requests are disabled to avoid device issues")
        return {}  # Return empty status results
        
    async def login_to_repeater(self, repeater_name: str, password: str) -> bool:
        """Login to a specific repeater using its name and password."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return False
            
        async with self._device_lock:
            try:
                # Find the repeater in contacts
                repeater_found = False
                repeater_key = None
                
                # First ensure we have contacts
                if not self._cached_contacts:
                    # Get contacts if we don't have them cached
                    _LOGGER.info(f"No cached contacts, fetching contacts before login to {repeater_name}")
                    self._cached_contacts = await self.get_contacts()
                
                # Log the cached contacts for debugging
                _LOGGER.info(f"Cached contacts: {list(self._cached_contacts.keys())}")
                
                # Look for the repeater by name
                for name, contact in self._cached_contacts.items():
                    _LOGGER.debug(f"Checking contact: {name}, type: {contact.get('type')}")
                    if name == repeater_name:
                        repeater_found = True
                        # IMPORTANT: Use the full public key as in the CLI code
                        repeater_key = bytes.fromhex(contact["public_key"])
                        _LOGGER.info(f"Found repeater {repeater_name} with key: {repeater_key.hex()}")
                        break
                
                if not repeater_found or not repeater_key:
                    _LOGGER.error(f"Repeater {repeater_name} not found in contacts")
                    return False
                
                # Send login command
                _LOGGER.info(f"Logging into repeater {repeater_name} with password: {'guest login' if not password else '****'}")
                # Handle empty password as guest login
                send_result = await self._mesh_core.send_login(repeater_key, password if password else "")
                _LOGGER.info(f"Login command result: {send_result}")
                
                # Send_login returns True on success, which may be all we need
                # Some repeaters respond directly to the login command without sending a notification
                if send_result is True:
                    _LOGGER.info(f"Login command to repeater {repeater_name} succeeded directly")
                    return True
                    
                # If direct response wasn't success, try waiting for a notification
                _LOGGER.info(f"Waiting for login notification from repeater {repeater_name}")
                login_success = await self._mesh_core.wait_login(timeout=5)
                
                if login_success:
                    _LOGGER.info(f"Successfully logged into repeater {repeater_name}")
                    return True
                else:
                    _LOGGER.error(f"Failed to login to repeater {repeater_name}, timeout or login denied")
                    return False
                    
            except Exception as ex:
                _LOGGER.error(f"Error logging into repeater: {ex}")
                _LOGGER.exception("Detailed exception")
                return False
    
    async def get_repeater_stats(self, repeater_name: str) -> Dict[str, Any]:
        """Get stats from a repeater after login."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return {}
            
        async with self._device_lock:
            try:
                # Find the repeater in contacts
                repeater_found = False
                repeater_key = None
                
                # First ensure we have contacts
                if not self._cached_contacts:
                    # Get contacts if we don't have them cached
                    _LOGGER.info(f"No cached contacts, fetching contacts before getting stats for {repeater_name}")
                    self._cached_contacts = await self.get_contacts()
                
                # Log the cached contacts for debugging
                _LOGGER.info(f"Cached contacts for stats: {list(self._cached_contacts.keys())}")
                
                # Look for the repeater by name
                for name, contact in self._cached_contacts.items():
                    if name == repeater_name:
                        repeater_found = True
                        # IMPORTANT: Use the full public key as in the CLI code
                        repeater_key = bytes.fromhex(contact["public_key"])
                        _LOGGER.info(f"Found repeater {repeater_name} with key: {repeater_key.hex()} for stats")
                        break
                
                if not repeater_found or not repeater_key:
                    _LOGGER.error(f"Repeater {repeater_name} not found in contacts for stats")
                    return {}
                
                # Send status request
                _LOGGER.info(f"Requesting stats from repeater {repeater_name}")
                await self._mesh_core.send_statusreq(repeater_key)
                
                # Wait for status response
                _LOGGER.info(f"Waiting for stats response from repeater {repeater_name}")
                status = await self._mesh_core.wait_status(timeout=5)
                
                if status:
                    _LOGGER.info(f"Received stats from repeater {repeater_name}: {status}")
                    return status
                else:
                    _LOGGER.warning(f"No stats received from repeater {repeater_name} - timeout waiting for status")
                    return {}
                    
            except Exception as ex:
                _LOGGER.error(f"Error getting repeater stats: {ex}")
                _LOGGER.exception("Detailed exception for stats")
                return {}
                
    async def get_repeater_version(self, repeater_name: str) -> Optional[str]:
        """Get version information from a repeater using the 'ver' command."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return None
            
        async with self._device_lock:
            try:
                # Find the repeater in contacts
                repeater_found = False
                repeater_key = None
                
                # First ensure we have contacts
                if not self._cached_contacts:
                    # Get contacts if we don't have them cached
                    _LOGGER.info(f"No cached contacts, fetching contacts before getting version for {repeater_name}")
                    self._cached_contacts = await self.get_contacts()
                
                # Look for the repeater by name
                for name, contact in self._cached_contacts.items():
                    if name == repeater_name:
                        repeater_found = True
                        # IMPORTANT: Use the full public key as in the CLI code
                        repeater_key = bytes.fromhex(contact["public_key"])
                        _LOGGER.info(f"Found repeater {repeater_name} with key: {repeater_key.hex()} for version info")
                        break
                
                if not repeater_found or not repeater_key:
                    _LOGGER.error(f"Repeater {repeater_name} not found in contacts for version check")
                    return None
                
                # Send 'ver' command
                _LOGGER.info(f"Sending 'ver' command to repeater {repeater_name}")
                # Using send_cmd equivalent to "cmd RepeaterName ver" in mccli.py
                cmd_result = await self._mesh_core.send_cmd(repeater_key[:6], "ver")
                _LOGGER.info(f"Ver command result: {cmd_result}")
                
                # Wait for message response (with a reasonable timeout)
                _LOGGER.info(f"Waiting for version message from repeater {repeater_name}")
                wait_result = await self._mesh_core.wait_msg(timeout=5)
                
                if wait_result:
                    # Get the message
                    message = await self._mesh_core.get_msg()
                    
                    # Check if it's a valid version message
                    if message and isinstance(message, dict) and "text" in message:
                        version_text = message.get("text", "")
                        _LOGGER.info(f"Received version from repeater {repeater_name}: {version_text}")
                        return version_text
                    else:
                        _LOGGER.warning(f"Received non-version message from repeater {repeater_name}: {message}")
                        return None
                else:
                    _LOGGER.warning(f"No version message received from repeater {repeater_name} - timeout waiting for response")
                    return None
                    
            except Exception as ex:
                _LOGGER.error(f"Error getting repeater version: {ex}")
                _LOGGER.exception("Detailed exception for version check")
                return None
    
    async def send_message(self, node_name: str, message: str) -> bool:
        """Send message to a specific node by name."""
        if not self._connected or not self._mesh_core:
            _LOGGER.error("Not connected to MeshCore device")
            return False
            
        async with self._device_lock:
            try:
                # First ensure we have contacts
                if not self._cached_contacts:
                    # We're behind a lock, so avoid calling another locked method
                    _LOGGER.error("No cached contacts available - call get_contacts first")
                    return False
                    
                # Check if the node exists
                if node_name not in self._cached_contacts:
                    _LOGGER.error("Node %s not found in contacts", node_name)
                    return False
                    
                # Send the message using the MeshCore instance
                _LOGGER.info(f"Sending message to {node_name}: {message}")
                result = await self._mesh_core.send_msg(
                    bytes.fromhex(self._cached_contacts[node_name]["public_key"])[:6],
                    message
                )
                
                if not result:
                    _LOGGER.error(f"Failed to send message to {node_name}")
                    return False
                    
                # Wait for the message ACK with shorter timeout
                _LOGGER.debug(f"Waiting for ACK from {node_name}...")
                ack_received = await self._mesh_core.wait_ack(3)  # reduced timeout
                
                if ack_received:
                    _LOGGER.info(f"Message to {node_name} acknowledged")
                else:
                    _LOGGER.warning(f"No ACK received from {node_name}")
                
                return ack_received
                
            except Exception as ex:
                _LOGGER.error(f"Error sending message: {ex}")
                return False