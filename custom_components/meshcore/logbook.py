"""Logbook integration for MeshCore."""
import logging
import time
from typing import Dict, Any, Optional, Callable, Iterable
from datetime import datetime

from homeassistant.core import HomeAssistant, callback, Event

from .const import (
    DOMAIN,
    NODE_TYPE_CLIENT,
    NODE_TYPE_REPEATER,
    ENTITY_DOMAIN_BINARY_SENSOR,
    ENTITY_DOMAIN_SENSOR,
    CONTACT_SUFFIX,
    DEFAULT_DEVICE_NAME,
)
from .utils import (
    get_channel_entity_id,
    get_contact_entity_id,
    find_coordinator_with_device_name,
    sanitize_name,
)

_LOGGER = logging.getLogger(__name__)

# Event types for message tracking
EVENT_MESHCORE_MESSAGE = "meshcore_message"
EVENT_MESHCORE_CONTACT = "meshcore_contact"
EVENT_MESHCORE_CLIENT_MESSAGE = "meshcore_client_message"

# Message types
MESSAGE_TYPE_DIRECT = "direct"
MESSAGE_TYPE_CHANNEL = "channel"
MESSAGE_TYPE_CHATROOM = "chatroom"
MESSAGE_TYPE_CONTACT = "contact_discovery"
MESSAGE_TYPE_SYSTEM = "system"

@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe logbook events."""
    
    @callback
    def process_message_event(event: Event) -> dict[str, str]:
        """Process MeshCore message events for logbook."""
        data = event.data
        message = data.get("message", "")
        sender_name = data.get("sender_name", "Unknown")
        message_type = data.get("message_type", "message")
        channel = data.get("channel", "")
        outgoing = data.get("outgoing", False)
        
        # Format message based on type and direction
        if outgoing:
            receiver = data.get('receiver', 'Unknown')
            pub_key_short = data.get('client_public_key', '')[:6] if data.get('client_public_key') else ''
            description = f"Sent to {receiver}{f' ({pub_key_short})' if pub_key_short else ''}: {message}"
            icon = "mdi:message-arrow-right-outline"
        elif message_type == MESSAGE_TYPE_CHANNEL:
            # Format as <channel> Sender: Message
            channel_display = data.get("channel_display", f"<{channel}>")
            sender_display = data.get("sender_display", sender_name)
            description = f"{channel_display} {sender_display}: {message}"
            icon = "mdi:message-bulleted"
        else:
            pub_key_short = data.get('client_public_key', '')[:6] if data.get('client_public_key') else ''
            description = message
            icon = "mdi:message-text"

            
        return {
            "name": "",
            "message": description,
            "domain": DOMAIN,
            "icon": icon,
        }
        
    @callback
    def process_contact_event(event: Event) -> dict[str, str]:
        """Process MeshCore contact events for logbook."""
        data = event.data
        contact_name = data.get("contact_name", "Unknown")
        contact_type = data.get("contact_type", "Node")
        
        return {
            "name": contact_name,
            "message": f"New {contact_type} discovered",
            "domain": DOMAIN,
            "icon": "mdi:account-plus",
        }
    
    @callback
    def process_client_message_event(event: Event) -> dict[str, str]:
        """Process MeshCore client message events for logbook."""
        data = event.data
        message = data.get("message", "")
        sender_name = data.get("sender_name", "")
        receiver_name = data.get("receiver_name", "")
        is_incoming = data.get("is_incoming", True)
        
        if is_incoming:
            # For incoming messages, use sender's name as the display name
            name = f"{sender_name if sender_name else 'Unknown Sender'}:"
            # Just show the message content without repeating the name
            description = message
            icon = "mdi:message-text"
        else:
            # For outgoing messages, use receiver's name as the display name
            name = receiver_name if receiver_name else "Unknown Receiver"
            # Format as "To Receiver: Message" for outgoing DMs
            description = f"To {name}: {message}"
            icon = "mdi:message-arrow-right-outline"
        
        return {
            "name": name,
            "message": description,
            "domain": DOMAIN,
            "icon": icon,
        }
        
    async_describe_event(DOMAIN, EVENT_MESHCORE_MESSAGE, process_message_event)
    async_describe_event(DOMAIN, EVENT_MESHCORE_CONTACT, process_contact_event)
    async_describe_event(DOMAIN, EVENT_MESHCORE_CLIENT_MESSAGE, process_client_message_event)

def normalize_message_data(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize message data to a standard format."""
    if not message_data:
        return {}
    
    # Extract core message fields, handling different field names
    normalized = {
        "text": message_data.get("text", message_data.get("msg", "")),
        "sender_key": message_data.get("pubkey_prefix"),
        "sender_name": message_data.get("sender_name", ""),
        "receiver_name": message_data.get("receiver", ""),
        "channel": message_data.get("channel", ""),
        "channel_idx": message_data.get("channel_idx"),
        "outgoing": message_data.get("outgoing", False),
        "snr": message_data.get("snr"),
        "timestamp": datetime.now().isoformat(),
    }
    
    # Determine message type based on input data
    message_type = MESSAGE_TYPE_DIRECT
    
    # Log input data for debugging channel messages
    _LOGGER.info(f"Message data for type check: type={message_data.get('type')}, channel={message_data.get('channel')} or {message_data.get('channel_idx')}")
    
    if "type" in message_data:
        if message_data["type"] in ["CHAN", "channel"]:
            message_type = MESSAGE_TYPE_CHANNEL
        elif message_data["type"] in ["PRIV", "direct"]:
            message_type = MESSAGE_TYPE_DIRECT
        elif message_data["type"] == "chatroom":
            message_type = MESSAGE_TYPE_CHATROOM
    elif normalized["channel"]:
        message_type = MESSAGE_TYPE_CHANNEL
        
    normalized["message_type"] = message_type
    _LOGGER.info(f"Final message type: {message_type}, channel value: {normalized['channel']}")
    
    return normalized

def resolve_sender_info(hass: HomeAssistant, message: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve sender information from contacts list."""
    # Find coordinator with contacts data
    coordinator = None
    for entry_id, coord in hass.data[DOMAIN].items():
        if hasattr(coord, "data") and "contacts" in coord.data:
            coordinator = coord
            break
    
    if not coordinator:
        return message
    
    contacts = coordinator.data.get("contacts", [])
    sender_key = message["sender_key"]
    outgoing = message["outgoing"]
    receiver_name = message["receiver_name"]
    
    # For incoming messages, look up the sender
    if not outgoing and sender_key:
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
                
            # Check if this contact is the sender
            if isinstance(sender_key, (bytes, bytearray)) and contact.get("public_key", "").startswith(sender_key.hex()):
                message["sender_name"] = contact.get("adv_name", "Unknown")
                message["contact_public_key"] = contact.get("public_key")
                break
            elif isinstance(sender_key, str) and contact.get("public_key", "").startswith(sender_key):
                message["sender_name"] = contact.get("adv_name", "Unknown")
                message["contact_public_key"] = contact.get("public_key")
                break
    
    # For outgoing messages, look up the receiver
    elif outgoing and isinstance(receiver_name, str):
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            
            if contact.get("adv_name") == receiver_name:
                message["contact_public_key"] = contact.get("public_key")
                break
    
    # Extract sender name from channel message if applicable
    if message["message_type"] == MESSAGE_TYPE_CHANNEL and message["text"] and ":" in message["text"]:
        parts = message["text"].split(":", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            extracted_sender = parts[0].strip()
            extracted_message = parts[1].strip()
            # Always update sender for channel messages
            message["sender_name"] = extracted_sender
            _LOGGER.debug(f"Extracted sender name '{message['sender_name']}' from channel message")
            # Store both the original message and the extracted message
            message["original_text"] = message["text"]
            message["text"] = extracted_message
            message["extracted_sender"] = extracted_sender
    
    # Set client_name based on direction
    message["client_name"] = message["sender_name"] if not outgoing else message["receiver_name"]
    
    return message

def update_coordinator_data(hass: HomeAssistant) -> None:
    """Update coordinator data with the most recent message info."""
    # Get coordinator without storing messages in history
    coordinator = None
    for _, coord in hass.data[DOMAIN].items():
        if hasattr(coord, "data"):
            coordinator = coord
            break
            
    if coordinator:
        # Simply trigger coordinator update to refresh states
        coordinator.async_set_updated_data(coordinator.data)

def handle_log_message(hass: HomeAssistant, message_data: Dict[str, Any]) -> None:
    """Record message using Home Assistant events."""
    if not message_data:
        return
    
    # Find the coordinator and get the device name
    _, device_name = find_coordinator_with_device_name(hass.data)
    
    # Process message through the pipeline
    message = normalize_message_data(message_data)
    message = resolve_sender_info(hass, message)
    
    # Prepare core event data
    event_data = {
        "message": message["text"],
        "text": message["text"],
        "timestamp": message["timestamp"],
        "domain": DOMAIN,
        "message_type": message["message_type"],
        "outgoing": message["outgoing"],
    }
    
    # Only include fields that have values
    if message.get("sender_name"):
        event_data["sender_name"] = message["sender_name"]
    
    if message.get("receiver_name"):
        event_data["receiver_name"] = message["receiver_name"]
        
    if message.get("client_name"):
        event_data["client_name"] = message["client_name"]
        event_data["name"] = message["client_name"]
    
    # Add SNR if available
    if message.get("snr") is not None:
        event_data["snr"] = message["snr"]
    
    # Add client-specific fields
    if message.get("contact_public_key"):
        event_data["client_public_key"] = message["contact_public_key"]
    elif message.get("sender_key"):
        event_data["client_public_key"] = message["sender_key"]
    
    # Handle channel-specific messages
    # Check for channel_idx directly since that's what's in the data
    if message["message_type"] == MESSAGE_TYPE_CHANNEL:
        channel_idx = int(message.get("channel_idx", 0))
        event_data["channel_idx"] = channel_idx
        event_data["channel"] = f"{channel_idx}"
        # todo determine this from channel list
        if channel_idx == 0:
            event_data["channel"] = "public"

        # Get the correct entity_id for this channel
        entity_id = get_channel_entity_id(ENTITY_DOMAIN_BINARY_SENSOR, device_name, channel_idx)
        event_data["entity_id"] = entity_id
        
        # Just store the plain message text
        event_data["message"] = message["text"]
        # Store channel info separately
        event_data["channel_display"] = f"<{event_data["channel"]}>"
        event_data["sender_display"] = message.get("sender_name", "")
        
        # Debug log the channel event details
        _LOGGER.info(f"Firing channel message event with entity_id: {entity_id}, channel: {event_data["channel"]}")
        
        # Fire channel message event
        hass.bus.async_fire(EVENT_MESHCORE_MESSAGE, event_data)
    
    # Handle direct messages
    elif message["message_type"] == MESSAGE_TYPE_DIRECT:
        if message["client_name"] != "Unknown":
            # Get sanitized client name
            client_name = sanitize_name(message["client_name"])
            pub_key = message["sender_key"]
            # Add client-specific entity ID
            entity_id = get_contact_entity_id(ENTITY_DOMAIN_BINARY_SENSOR, device_name, pub_key)
            event_data["entity_id"] = entity_id
            
            # Add is_incoming flag for client messages
            event_data["is_incoming"] = not message["outgoing"]
            
            # Debug log the direct message event details  
            _LOGGER.info(f"Firing direct message event with entity_id: {entity_id}, client: {client_name}")
            
            # Fire direct message event
            hass.bus.async_fire(EVENT_MESHCORE_CLIENT_MESSAGE, event_data)
    
    # Update the message timestamps in the coordinator
    try:
        # Find coordinator
        coordinator = None
        for entry_id, coord in hass.data[DOMAIN].items():
            if hasattr(coord, "data"):
                coordinator = coord
                break
                
        if coordinator:
            # Initialize message timestamps if it doesn't exist
            if not hasattr(coordinator, "message_timestamps"):
                coordinator.message_timestamps = {}
                
            current_time = time.time()
            
            # Determine key based on message type
            key = None
            if message["message_type"] == MESSAGE_TYPE_CHANNEL:
                key = int(message.get("channel_idx", 0))
            elif message["message_type"] == MESSAGE_TYPE_DIRECT:
                key = message["contact_public_key"]
            
            # Update timestamp if we have a valid key
            if key is not None:
                coordinator.message_timestamps[key] = current_time
    except Exception as ex:
        _LOGGER.error(f"Error updating message timestamps: {ex}")
    
    # Update coordinator data (without storing history)
    update_coordinator_data(hass)
    
    # Log for debugging
    if message["outgoing"]:
        _LOGGER.debug("Logged outgoing %s message: %s to %s", 
            message["message_type"], message["text"], message["receiver_name"])
    else:
        _LOGGER.debug("Logged incoming %s message: %s from %s", 
            message["message_type"], message["text"], message["sender_name"])

def log_contact_seen(hass: HomeAssistant, contact_data: Dict[str, Any]) -> None:
    """Record contact discovery using Home Assistant events."""
    if not contact_data:
        return
    
    contact_name = contact_data.get("adv_name", "Unknown")
    node_type = contact_data.get("type")
    public_key = contact_data.get("public_key", "")
    
    # Determine contact type description
    contact_type = "Client" if node_type == NODE_TYPE_CLIENT else "Repeater" if node_type == NODE_TYPE_REPEATER else "Node"
    
    # Create event data for logbook
    contact_event_data = {
        "contact_name": contact_name,
        "contact_type": contact_type,
        "public_key": public_key,
        "node_type": node_type,
        "entity_id": get_contact_entity_id(ENTITY_DOMAIN_SENSOR, DEFAULT_DEVICE_NAME, public_key, CONTACT_SUFFIX),
        "domain": DOMAIN,
    }
    
    # Fire Home Assistant event for history/logbook
    hass.bus.async_fire(EVENT_MESHCORE_CONTACT, contact_event_data)
    
    # Create standard message for contact discovery
    discovery_text = f"New {contact_type.lower()} device discovered"
    
    # Create client event data
    client_event_data = {
        "client_name": contact_name,
        "message": discovery_text,
        "text": discovery_text,
        "is_incoming": False,
        "entity_id": get_contact_entity_id(ENTITY_DOMAIN_SENSOR, DEFAULT_DEVICE_NAME, contact_name, "message"),
        "domain": DOMAIN,
        "client_public_key": public_key,
        "timestamp": datetime.now().isoformat(),
        "message_type": MESSAGE_TYPE_CONTACT,
    }
    
    # Fire client message event
    hass.bus.async_fire(EVENT_MESHCORE_CLIENT_MESSAGE, client_event_data)
    
    # Update coordinator data
    update_coordinator_data(hass)
    
    # Log for debugging
    _LOGGER.info(
        "New %s contact discovered: %s", 
        contact_type.lower(), 
        contact_name
    )