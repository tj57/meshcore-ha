"""Services for the MeshCore integration."""
import logging
import time
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN, 
    SERVICE_SEND_MESSAGE,
    ATTR_NODE_ID,
    ATTR_MESSAGE,
)
from .logbook import handle_log_message

_LOGGER = logging.getLogger(__name__)

# Schema for send_message service
SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NODE_ID): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
    }
)

async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for MeshCore integration."""
    
    async def async_send_message_service(call: ServiceCall) -> None:
        """Handle sending a message service call."""
        node_id = call.data[ATTR_NODE_ID]
        message = call.data[ATTR_MESSAGE]
        
        # Iterate through all registered config entries
        for entry_id, coordinator in hass.data[DOMAIN].items():
            # Get the API from coordinator
            api = coordinator.api
            if api and api._connected:
                try:
                    _LOGGER.debug(
                        "Sending message to node %s: %s", node_id, message
                    )
                    success = await api.send_message(node_id, message)
                    if success:
                        _LOGGER.info(
                            "Successfully sent message to node %s", node_id
                        )
                        
                        # Log outgoing message to logbook
                        outgoing_msg = {
                            "msg": message,
                            "sender": "self",  # Mark as sent by us
                            "receiver": node_id,
                            "timestamp": int(time.time()),
                            "outgoing": True,
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
                # Only attempt with the first available API
                return
    
    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        async_send_message_service,
        schema=SEND_MESSAGE_SCHEMA,
    )

async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload MeshCore services."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)