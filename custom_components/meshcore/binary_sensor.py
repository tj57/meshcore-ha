"""Binary sensor platform for MeshCore integration."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    ENTITY_DOMAIN_BINARY_SENSOR,
    MESSAGES_SUFFIX,
    CHANNEL_PREFIX,
    NodeType,
)
from .utils import (
    sanitize_name,
    get_device_name,
    format_entity_id,
    extract_channel_idx,
)
from .logbook import (
    EVENT_MESHCORE_MESSAGE,
    EVENT_MESHCORE_CLIENT_MESSAGE,
)

_LOGGER = logging.getLogger(__name__)

# How far back to check for messages (2 weeks, matching activity window)
MESSAGE_ACTIVITY_WINDOW = timedelta(days=14)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up MeshCore message entities from config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Store the async_add_entities function for later use
    coordinator.binary_sensor_add_entities = async_add_entities
    
    # Track contacts we've already created entities for
    coordinator.tracked_contacts = set()
    
    # Function to create and add entities for all contacts
    @callback
    def create_contact_entities(contacts=None):
        _LOGGER.info(f"Creating contact message entities with {len(contacts) if contacts else 0} contacts")
        entities = []
        
        # Add channel entities (only first time)
        if not hasattr(coordinator, "channels_added") or not coordinator.channels_added:
            # Add channel message entities for channels 0-3
            for channel_idx in range(4):
                safe_channel = f"{CHANNEL_PREFIX}{channel_idx}"
                entities.append(MeshCoreMessageEntity(
                    coordinator, safe_channel, f"Channel {channel_idx} Messages"
                ))
            coordinator.channels_added = True
        
        # Only proceed if we have contacts
        if not contacts:
            _LOGGER.warning("No contacts provided for entity creation")
            return
        for contact in contacts:
            if not isinstance(contact, dict):
                continue

            if contact.get("type") == NodeType.REPEATER:
                continue
                
            contact_name = contact.get("adv_name", "")
            public_key = contact.get("public_key", "")
            public_key_prefix = public_key[:12] if public_key else ""
            # Skip if we already have an entity for this contact
            contact_id = public_key or contact_name
            if contact_id in coordinator.tracked_contacts:
                continue
                
            if contact_name:
                _LOGGER.info(f"Creating message entity for contact: {contact_name}")
                new_entity = MeshCoreMessageEntity(
                    coordinator, public_key_prefix, f"{contact_name} Messages", 
                    public_key=public_key
                )
                entities.append(new_entity)
                coordinator.tracked_contacts.add(contact_id)
        
        # Add entities if any were created
        if entities:
            _LOGGER.info(f"Adding {len(entities)} new contact message entities")
            async_add_entities(entities)
    
    # Run initially with the current contacts
    initial_contacts = coordinator.data.get("contacts", [])
    create_contact_entities(initial_contacts)
    
    # Store the function on the coordinator for future calls
    coordinator.create_binary_sensor_entities = create_contact_entities


class MeshCoreMessageEntity(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor entity that tracks mesh network messages."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    
    @property
    def state(self) -> str:
        """Return the state of the entity."""
        return "Active" if self.is_on else "Inactive"
    
    def __init__(
        self, 
        coordinator: DataUpdateCoordinator, 
        entity_key: str,
        name: str,
        public_key: str = ""
    ) -> None:
        """Initialize the message entity."""
        super().__init__(coordinator)
        
        # Store entity type and public key if applicable
        self.entity_key = entity_key
        self.public_key = public_key
        
        # Get device name for unique ID and entity_id
        device_name = get_device_name(coordinator)
        
        # Set unique ID with device name included - ensure consistent format with no empty parts
        parts = [part for part in [coordinator.config_entry.entry_id, device_name, entity_key, MESSAGES_SUFFIX] if part]
        self._attr_unique_id = "_".join(parts)
        
        # Manually set entity_id to match logbook entity_id format
        self.entity_id = format_entity_id(
            ENTITY_DOMAIN_BINARY_SENSOR, 
            device_name, 
            entity_key, 
            MESSAGES_SUFFIX
        )
        
        # Debug: Log the entity ID for troubleshooting
        _LOGGER.debug(f"Created entity with ID: {self.entity_id}")
        
        self._attr_name = name
        
        # Set icon based on entity type
        if self.entity_key.startswith(CHANNEL_PREFIX):
            self._attr_icon = "mdi:message-bulleted"
        else:
            self._attr_icon = "mdi:message-text-outline"
        
        # Set device info to link to the main device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        )
        
        
    def _check_message_activity(self) -> bool:
        """Check for recent message activity using coordinator timestamp data."""
        # If message_timestamps doesn't exist, initialize it
        if not hasattr(self.coordinator, "message_timestamps"):
            self.coordinator.message_timestamps = {}
            return False
        
        # Calculate cutoff time for activity window
        cutoff_time = time.time() - MESSAGE_ACTIVITY_WINDOW.total_seconds()
        
        # Determine key to check
        key = None
        if self.entity_key.startswith(CHANNEL_PREFIX):
            key = extract_channel_idx(self.entity_key)
        elif self.public_key:
            key = self.public_key
        
        # Check if we have recent messages
        if key is not None and key in self.coordinator.message_timestamps:
            return self.coordinator.message_timestamps[key] > cutoff_time
        
        return False
    
    @property
    def is_on(self) -> bool:
        """Return true if there are recent messages in the activity window."""
        # Use our helper method to check message activity
        # This ensures we always get the latest state
        return self._check_message_activity()
    
    async def async_update(self) -> None:
        """Update message status."""
        await super().async_update()
        
        # We no longer need to do anything here since is_on
        # directly checks for message activity when called

    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return message details as attributes."""
        attributes = {
            "last_updated": datetime.now().isoformat()
        }
        
        # Add appropriate attributes based on entity type
        if self.entity_key.startswith(CHANNEL_PREFIX):
            # For channel-specific message entities
            try:
                channel_idx = extract_channel_idx(self.entity_key)
                attributes["channel_index"] = f"{channel_idx}"
            except (ValueError, TypeError):
                _LOGGER.warning(f"Could not get channel index from {self.entity_key}")
        elif self.public_key:
            # For contact-specific message entities
            attributes["public_key"] = self.public_key
            
        # Add timestamp of last message if available
        key = None
        if self.entity_key.startswith(CHANNEL_PREFIX):
            key = extract_channel_idx(self.entity_key)
        elif self.public_key:
            key = self.public_key
            
        if key is not None and hasattr(self.coordinator, "message_timestamps") and key in self.coordinator.message_timestamps:
            timestamp = self.coordinator.message_timestamps[key]
            attributes["last_message"] = datetime.fromtimestamp(timestamp).isoformat()
            
        return attributes