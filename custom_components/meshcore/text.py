"""Text platform for MeshCore integration."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up MeshCore text entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [MeshCoreMessageInput(coordinator), MeshCoreCliCommandInput(coordinator)]
    async_add_entities(entities)


class MeshCoreMessageInput(CoordinatorEntity, TextEntity):
    """Text input entity for composing MeshCore messages."""
    
    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        """Initialize the message input entity."""
        super().__init__(coordinator)
        
        # Set unique ID and entity ID
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_message_input"
        self.entity_id = "text.meshcore_message"
        
        # Set name and icon
        self._attr_name = "MeshCore Message"
        self._attr_icon = "mdi:message-text"
        
        # Hide from device page
        self._attr_entity_registry_visible_default = False
        
        # Set validation properties
        self._attr_native_max = 200
        self._attr_mode = "text"
        self._attr_native_value = ""
        
        # Don't associate with device to keep it off device page
        # self._attr_device_info = DeviceInfo(
        #     identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        # )
    
    async def async_set_value(self, value: str) -> None:
        """Set the value of the text entity."""
        self._attr_native_value = value
        self.async_write_ha_state()


class MeshCoreCliCommandInput(CoordinatorEntity, TextEntity):
    """Text input entity for CLI commands."""
    
    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        """Initialize the CLI command input entity."""
        super().__init__(coordinator)
        
        # Set unique ID and entity ID
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_cli_command_input"
        self.entity_id = "text.meshcore_cli_command"
        
        # Set name and icon
        self._attr_name = "MeshCore CLI Command"
        self._attr_icon = "mdi:console"
        
        # Hide from device page
        self._attr_entity_registry_visible_default = False
        
        # Set validation properties
        self._attr_native_max = 255
        self._attr_mode = "text"
        self._attr_native_value = ""
        
        # Don't associate with device to keep it off device page
        # self._attr_device_info = DeviceInfo(
        #     identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        # )
    
    async def async_set_value(self, value: str) -> None:
        """Set the value of the text entity."""
        self._attr_native_value = value
        self.async_write_ha_state()