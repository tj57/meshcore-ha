"""Binary sensor platform for MeshCore integration."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
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
    CONTACT_SUFFIX,
    NodeType,
)
from .utils import (
    get_device_key,
    sanitize_name,
    format_entity_id,
    extract_channel_idx,
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
    
    # Track diagnostic contacts we've already created binary sensors for
    if not hasattr(coordinator, "tracked_diagnostic_binary_contacts"):
        coordinator.tracked_diagnostic_binary_contacts = set()
    
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
    
    # Function to create and add contact diagnostic binary sensors
    @callback
    def create_contact_diagnostic_binary_sensors(contacts=None):
        _LOGGER.info(f"Creating contact diagnostic binary sensors with {len(contacts) if contacts else 0} contacts")
        new_entities = []
        
        # Only proceed if we have contacts
        if not contacts:
            _LOGGER.warning("No contacts provided for diagnostic binary sensor creation")
            return
            
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
                
            try:
                name = contact.get("adv_name", "Unknown")
                public_key = contact.get("public_key", "")
                
                if not public_key:
                    continue
                    
                # Skip if we already have a binary sensor for this contact
                if public_key in coordinator.tracked_diagnostic_binary_contacts:
                    continue
                    
                # Track this contact
                coordinator.tracked_diagnostic_binary_contacts.add(public_key)
                
                _LOGGER.info(f"Creating diagnostic binary sensor for contact: {name}")
                
                # Create diagnostic binary sensor for this contact
                sensor = MeshCoreContactDiagnosticBinarySensor(
                    coordinator, 
                    name,
                    public_key,
                    public_key[:12]
                )
                
                new_entities.append(sensor)
                
            except Exception as ex:
                _LOGGER.error("Error setting up contact diagnostic binary sensor: %s", ex)
        
        # Add entities if any were created
        if new_entities:
            _LOGGER.info(f"Adding {len(new_entities)} new contact diagnostic binary sensors")
            async_add_entities(new_entities)
    
    # Function to create and add repeater binary sensors
    @callback
    def create_repeater_binary_sensors(repeater_subscriptions=None):
        _LOGGER.info(f"Creating repeater binary sensors with {len(repeater_subscriptions) if repeater_subscriptions else 0} repeaters")
        new_entities = []
        
        # Only proceed if we have repeaters
        if not repeater_subscriptions:
            _LOGGER.warning("No repeaters provided for binary sensor creation")
            return
            
        for repeater in repeater_subscriptions:
            if not repeater.get("enabled", True):
                continue
                
            repeater_name = repeater.get("name")
            if not repeater_name:
                continue
                
            _LOGGER.info(f"Creating binary sensor for repeater: {repeater_name}")
            
            # Create repeater status binary sensor
            try:
                sensor = MeshCoreRepeaterBinarySensor(
                    coordinator,
                    repeater_name,
                    "status"
                )
                new_entities.append(sensor)
            except Exception as ex:
                _LOGGER.error(f"Error creating repeater binary sensor: {ex}")
        
        # Add entities if any were created
        if new_entities:
            _LOGGER.info(f"Adding {len(new_entities)} new repeater binary sensors")
            async_add_entities(new_entities)
    
    # Run initially with the current contacts
    initial_contacts = coordinator.data.get("contacts", [])
    create_contact_entities(initial_contacts)
    
    # Create contact diagnostic binary sensors
    create_contact_diagnostic_binary_sensors(initial_contacts)
    
    # Create repeater binary sensors if any repeaters are configured
    repeater_subscriptions = entry.data.get("repeater_subscriptions", [])
    if repeater_subscriptions:
        create_repeater_binary_sensors(repeater_subscriptions)
    
    # Store the functions on the coordinator for future calls
    coordinator.create_binary_sensor_entities = create_contact_entities
    coordinator.create_contact_diagnostic_binary_sensors = create_contact_diagnostic_binary_sensors
    coordinator.create_repeater_binary_sensors = create_repeater_binary_sensors


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
        device_key = get_device_key(coordinator)
        
        # Set unique ID with device key included - ensure consistent format with no empty parts
        parts = [part for part in [coordinator.config_entry.entry_id, device_key[:6], entity_key[:6], MESSAGES_SUFFIX] if part]
        self._attr_unique_id = "_".join(parts)
        
        # Manually set entity_id to match logbook entity_id format
        self.entity_id = format_entity_id(
            ENTITY_DOMAIN_BINARY_SENSOR, 
            device_key[:6], 
            entity_key[:6], 
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


class MeshCoreContactDiagnosticBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """A diagnostic binary sensor for a single MeshCore contact."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        contact_name: str,
        public_key: str,
        contact_id: str,
    ) -> None:
        """Initialize the contact diagnostic binary sensor."""
        super().__init__(coordinator)
        
        self.contact_name = contact_name
        self.public_key = public_key
        
        # Set unique ID
        self._attr_unique_id = contact_id
        
        self.entity_id = format_entity_id(
            ENTITY_DOMAIN_BINARY_SENSOR,
            contact_name,
            public_key[:12],
            CONTACT_SUFFIX
        )

        # Initial name (will be updated in _update_attributes)
        self._attr_name = contact_name
        
        # Set device info to link to the main device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        )
        
        # Set entity category to diagnostic
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        
        # Set device class to connectivity
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        
        # Icon will be set dynamically in the _update_attributes method
        self._update_attributes()

    def _get_contact_data(self) -> Dict[str, Any]:
        """Get the data for this contact from the coordinator."""
        if not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            return {}
            
        contacts = self.coordinator.data.get("contacts", [])
        if not contacts:
            return {}
            
        # Find this contact by name or by public key
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
                
            # Match by public key prefix
            if contact.get("public_key", "").startswith(self.public_key):
                return contact

            # Match by name
            if contact.get("adv_name") == self.contact_name:
                return contact
                
        return {}

    def _update_attributes(self) -> Dict[str, Any]:
        """Update the attributes and icon based on contact data."""
        contact = self._get_contact_data()
        if not contact:
            # If contact not found, use default icon
            self._attr_icon = "mdi:radio-tower"
            self._attr_name = self.contact_name
            return {"status": "unknown"}
            
        # Create a copy of the contact data for attributes
        attributes = {}
        
        # Add all contact properties directly as attributes
        for key, value in contact.items():
            attributes[key] = value
            
        # Get the node type and set icon accordingly
        node_type = contact.get("type")
        
        # Set different icons and names based on node type and state
        is_fresh = self.is_on
        
        if node_type == NodeType.CLIENT:  # Client
            self._attr_icon = "mdi:account" if is_fresh else "mdi:account-off"
            self._attr_name = f"{self.contact_name} (Client)"
            icon_file = "client-green.svg" if is_fresh else "client.svg"
            attributes["entity_picture"] = f"/api/meshcore/static/{icon_file}"
            attributes["node_type_str"] = "Client"
            
        elif node_type == NodeType.REPEATER:  # Repeater
            self._attr_icon = "mdi:radio-tower" if is_fresh else "mdi:radio-tower-off"
            self._attr_name = f"{self.contact_name} (Repeater)"
            icon_file = "repeater-green.svg" if is_fresh else "repeater.svg"
            attributes["entity_picture"] = f"/api/meshcore/static/{icon_file}"
            attributes["node_type_str"] = "Repeater"
            
        elif node_type == NodeType.ROOM_SERVER:  # Room Server
            self._attr_icon = "mdi:forum" if is_fresh else "mdi:forum-outline"
            self._attr_name = f"{self.contact_name} (Room Server)"
            icon_file = "room_server-green.svg" if is_fresh else "room_server.svg"
            attributes["entity_picture"] = f"/api/meshcore/static/{icon_file}"
            attributes["node_type_str"] = "Room Server"
            
        else:
            # Default icon if type is unknown
            self._attr_icon = "mdi:help-network"
            self._attr_name = f"{self.contact_name} (Unknown)"
            attributes["node_type_str"] = "Unknown"
        

        
        # Format last advertisement time if available
        if "last_advert" in attributes and attributes["last_advert"] > 0:
            last_advert_time = datetime.fromtimestamp(attributes["last_advert"])
            attributes["last_advert_formatted"] = last_advert_time.isoformat()

        return attributes
    
        """Return the icon for this contact."""
        return self._attr_icon

    @property
    def is_on(self) -> bool:
        """Return True if the contact is fresh/active."""
        contact = self._get_contact_data()
        if not contact:
            return False
            
        # Check last advertisement time for contact status
        last_advert = contact.get("last_advert", 0)
        if last_advert > 0:
            # Calculate time since last advert
            time_since = time.time() - last_advert
            # If less than 12 hour, consider fresh/active
            if time_since < 3600*12:
                return True
        
        return False
        
    @property
    def state(self) -> str:
        """Return the state of the binary sensor as "fresh" or "stale"."""
        return "fresh" if self.is_on else "stale"
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the raw contact data as attributes."""
        return self._update_attributes()


class MeshCoreRepeaterBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for repeater status."""
    
    def __init__(
        self, 
        coordinator: DataUpdateCoordinator,
        repeater_name: str,
        stat_key: str,
    ) -> None:
        """Initialize the repeater binary sensor."""
        super().__init__(coordinator)
        self.repeater_name = repeater_name
        self.stat_key = stat_key
        
        # Create sanitized names
        safe_name = sanitize_name(repeater_name)
        
        # Generate a unique device_id for this repeater
        self.device_id = f"{coordinator.config_entry.entry_id}_repeater_{safe_name}"
        
        # Set unique ID
        self._attr_unique_id = f"{self.device_id}_{stat_key}"
        
        # Set friendly name
        self._attr_name = f"{stat_key.replace('_', ' ').title()}"
        
        # Set device class to connectivity
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        
        # Set entity ID
        self.entity_id = format_entity_id(
            ENTITY_DOMAIN_BINARY_SENSOR,
            safe_name,
            stat_key
        )
        
        # Get repeater stats if available
        repeater_stats = coordinator.data.get("repeater_stats", {}).get(repeater_name, {})
        
        # Default device name, include public key if available
        device_name = f"MeshCore Repeater: {repeater_name}"
        if repeater_stats and "public_key" in repeater_stats:
            public_key_short = repeater_stats.get("public_key_short", repeater_stats["public_key"][:10])
            device_name = f"MeshCore Repeater: {repeater_name} ({public_key_short})"
        
        # Set device info to create a separate device for this repeater
        device_info = {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": device_name,
            "manufacturer": repeater_stats.get("manufacturer_name", "MeshCore") if repeater_stats else "MeshCore",
            "model": "Mesh Repeater",
            "via_device": (DOMAIN, coordinator.config_entry.entry_id),  # Link to the main device
        }
        
        # Add version information if available
        if repeater_stats:
            # Prefer firmware_version if available, fall back to version
            if "firmware_version" in repeater_stats:
                device_info["sw_version"] = repeater_stats["firmware_version"]
            elif "version" in repeater_stats:
                device_info["sw_version"] = repeater_stats["version"]
                
            # Add build date as hardware version if available
            if "firmware_build_date" in repeater_stats:
                device_info["hw_version"] = repeater_stats["firmware_build_date"]
            
        self._attr_device_info = DeviceInfo(**device_info)
        
        # Set icon based on stat key
        self._attr_icon = "mdi:radio-tower"
    
    @property
    def is_on(self) -> bool:
        """Return if the repeater is active."""
        if not self.coordinator.data or "repeater_stats" not in self.coordinator.data:
            return False
            
        # Get the repeater stats for this repeater
        repeater_stats = self.coordinator.data.get("repeater_stats", {}).get(self.repeater_name, {})
        if not repeater_stats:
            return False
            
        # Check last updated time if available
        if "last_updated" in repeater_stats:
            # Calculate time since last update
            time_since = time.time() - repeater_stats["last_updated"]
            # If less than 1 hour, consider active
            if time_since < 3600:
                return True
                
        return False
        
    @property
    def state(self) -> str:
        """Return the state of the binary sensor as "fresh" or "stale"."""
        return "fresh" if self.is_on else "stale"
        
    @property
    def available(self) -> bool:
        """Return if the sensor is available."""
        # Check if coordinator is available and we have data for this repeater
        if not super().available or not self.coordinator.data:
            return False
            
        # Check if we have stats for this repeater
        repeater_stats = self.coordinator.data.get("repeater_stats", {})
        return self.repeater_name in repeater_stats
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data or "repeater_stats" not in self.coordinator.data:
            return {}
            
        # Get the repeater stats for this repeater
        repeater_stats = self.coordinator.data.get("repeater_stats", {}).get(self.repeater_name, {})
        if not repeater_stats:
            return {}
            
        attributes = {}
        
        # Add key stats as attributes
        for key in ["uptime", "airtime", "nb_sent", "nb_recv", "bat"]:
            if key in repeater_stats:
                attributes[key] = repeater_stats[key]
                
                # Format uptime if available
                if key == "uptime" and isinstance(repeater_stats[key], (int, float)):
                    seconds = repeater_stats[key]
                    days = seconds // 86400
                    hours = (seconds % 86400) // 3600
                    minutes = (seconds % 3600) // 60
                    secs = seconds % 60
                    attributes["uptime_formatted"] = f"{days}d {hours}h {minutes}m {secs}s"
                    
        # Add last updated timestamp if available
        if "last_updated" in repeater_stats:
            attributes["last_updated"] = datetime.fromtimestamp(repeater_stats["last_updated"]).isoformat()
            
        return attributes