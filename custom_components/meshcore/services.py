"""Services for the MeshCore integration."""
import logging
import time
import voluptuous as vol
import json

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_PUBKEY_PREFIX,
    DOMAIN, 
    SERVICE_SEND_MESSAGE,
    SERVICE_SEND_CHANNEL_MESSAGE,
    SERVICE_CLI_COMMAND,
    ATTR_NODE_ID,
    ATTR_CHANNEL_IDX,
    ATTR_MESSAGE,
    ATTR_CLI_COMMAND,
    ATTR_ENTRY_ID,
    DEFAULT_DEVICE_NAME,
)
from .logbook import handle_log_message

_LOGGER = logging.getLogger(__name__)

# Schema for send_message service with either node_id or pubkey_prefix required
SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Exclusive(ATTR_NODE_ID, 'target'): cv.string,
        vol.Exclusive(ATTR_PUBKEY_PREFIX, 'target'): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
).extend({vol.Required: vol.Any(ATTR_NODE_ID, ATTR_PUBKEY_PREFIX)})

# Schema for send_channel_message service
SEND_CHANNEL_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CHANNEL_IDX): cv.positive_int,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)

# Schema for cli_command service
CLI_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CLI_COMMAND): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)

async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for MeshCore integration."""
    
    async def async_send_message_service(call: ServiceCall) -> None:
        """Handle sending a message service call."""
        message = call.data[ATTR_MESSAGE]
        entry_id = call.data.get(ATTR_ENTRY_ID)
        
        # Check which target identifier was provided
        if ATTR_NODE_ID in call.data:
            # Sending by node_id (friendly name)
            node_id = call.data[ATTR_NODE_ID]
            pubkey_prefix = None
            target_identifier = f"node_id '{node_id}'"
        else:
            # Sending by public key
            node_id = None
            pubkey_prefix = call.data[ATTR_PUBKEY_PREFIX]
            target_identifier = f"public key '{pubkey_prefix}'"
        
        # Iterate through all registered config entries
        for config_entry_id, coordinator in hass.data[DOMAIN].items():
            _LOGGER.debug("Entry ID: %s, coordinator: %s", config_entry_id, coordinator)
            # If entry_id is specified, only use the matching entry
            if entry_id and entry_id != config_entry_id:
                continue
                
            # Get the API from coordinator
            api = coordinator.api
            if api and api._connected:
                try:
                    _LOGGER.debug(
                        "Sending message to %s: %s", target_identifier, message
                    )
                    
                    if node_id is not None:
                        # Send the message by node name
                        success, pubkey, contact_name = await api.send_message(node_id, message)
                    else:
                        # Send the message by pubkey prefix
                        success, pubkey, contact_name = await api.send_message_by_pubkey(pubkey_prefix, message)
                    if success:
                        # Use the actual contact name for logging when available
                        display_name = contact_name if contact_name else target_identifier
                        _LOGGER.info("Successfully sent message to %s, pubkey: %s", display_name, pubkey)
                        
                        # Get device name from coordinator for outgoing message logs
                        device_name = DEFAULT_DEVICE_NAME
                        if hasattr(coordinator, "data") and "name" in coordinator.data:
                            device_name = coordinator.data.get("name", DEFAULT_DEVICE_NAME)
                        
                        # Determine the receiver name for the logbook
                        receiver_name = contact_name if contact_name else (node_id if node_id else f"pubkey:{pubkey_prefix}")
                        
                        # Log outgoing message to logbook with the contact's public key
                        outgoing_msg = {
                            "msg": message,
                            "sender": device_name,
                            "sender_name": device_name,
                            "receiver": receiver_name,
                            "type": "PRIV",
                            "timestamp": int(time.time()),
                            "outgoing": True,
                            # Include the contact's public key - most critical for entity_id generation
                            "contact_public_key": pubkey
                        }
                        handle_log_message(hass, outgoing_msg)
                    else:
                        _LOGGER.warning(
                            "Failed to send message to node %s", node_id
                        )
                except Exception as ex:
                    _LOGGER.error(
                        "Error sending message to node %s: %s", node_id, ex
                    )
                # Only attempt with the first available API if no entry_id specified
                if not entry_id:
                    return
    
    async def async_send_channel_message_service(call: ServiceCall) -> None:
        """Handle sending a channel message service call."""
        channel_idx = call.data[ATTR_CHANNEL_IDX]
        message = call.data[ATTR_MESSAGE]
        entry_id = call.data.get(ATTR_ENTRY_ID)
        
        # Iterate through all registered config entries
        for config_entry_id, coordinator in hass.data[DOMAIN].items():
            _LOGGER.debug("Entry ID: %s, coordinator: %s", config_entry_id, coordinator)
            # If entry_id is specified, only use the matching entry
            if entry_id and entry_id != config_entry_id:
                continue
                
            # Get the API from coordinator
            api = coordinator.api
            if api and api._connected:
                try:
                    _LOGGER.debug(
                        "Sending message to channel %s: %s", channel_idx, message
                    )
                    success = await api.send_channel_message(channel_idx, message)
                    if success:
                        _LOGGER.info(
                            "Successfully sent message to channel %s", channel_idx
                        )
                        
                        # Get device name from coordinator for outgoing message logs
                        device_name = DEFAULT_DEVICE_NAME
                        if hasattr(coordinator, "data") and "name" in coordinator.data:
                            device_name = coordinator.data.get("name", DEFAULT_DEVICE_NAME)
                        
                        # Log outgoing message to logbook
                        outgoing_msg = {
                            "msg": message,
                            "sender": device_name,
                            "sender_name": device_name,
                            "receiver": f"channel_{channel_idx}",
                            "type": "CHAN",
                            "channel_idx": channel_idx,
                            "timestamp": int(time.time()),
                            "outgoing": True,
                        }
                        handle_log_message(hass, outgoing_msg)
                    else:
                        _LOGGER.warning(
                            "Failed to send message to channel %s", channel_idx
                        )
                except Exception as ex:
                    _LOGGER.error(
                        "Error sending message to channel %s: %s", channel_idx, ex
                    )
                # Only attempt with the first available API if no entry_id specified
                if not entry_id:
                    return
    
    async def async_cli_command_service(call: ServiceCall) -> None:
        """Handle CLI command service call."""
        command = call.data[ATTR_CLI_COMMAND]
        entry_id = call.data.get(ATTR_ENTRY_ID)
        
        # Track if any command executed successfully
        command_success = False
        
        # Iterate through all registered config entries
        for config_entry_id, coordinator in hass.data[DOMAIN].items():            
            # If entry_id is specified, only use the matching entry
            if entry_id and entry_id != config_entry_id:
                continue
                
            # Get the API from coordinator
            api = coordinator.api
            if api and api._connected:
                try:
                    _LOGGER.debug(
                        "Executing CLI command: %s", command
                    )
                    
                    result = await api.send_cli_command(command)
                    
                    if result.get("success", False):
                        command_success = True
                        _LOGGER.info(
                            "Successfully executed CLI command: %s", command
                        )
                    else:
                        _LOGGER.warning(
                            "CLI command execution failed: %s, error: %s", 
                            command, result.get("error", "Unknown error")
                        )
                        
                except Exception as ex:
                    _LOGGER.error(
                        "Error executing CLI command %s: %s", command, ex
                    )
                
                # Only attempt with the first available API if no entry_id specified
                if not entry_id:
                    return
        
        if not command_success:
            _LOGGER.error("Failed to execute CLI command on any device: %s", command)

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        async_send_message_service,
        schema=SEND_MESSAGE_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_CHANNEL_MESSAGE,
        async_send_channel_message_service,
        schema=SEND_CHANNEL_MESSAGE_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLI_COMMAND,
        async_cli_command_service,
        schema=CLI_COMMAND_SCHEMA,
    )

async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload MeshCore services."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)
        
    if hass.services.has_service(DOMAIN, SERVICE_SEND_CHANNEL_MESSAGE):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_CHANNEL_MESSAGE)
        
    if hass.services.has_service(DOMAIN, SERVICE_CLI_COMMAND):
        hass.services.async_remove(DOMAIN, SERVICE_CLI_COMMAND)