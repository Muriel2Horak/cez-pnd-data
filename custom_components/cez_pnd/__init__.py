"""CEZ PND integration for Home Assistant."""

from .const import DOMAIN

PLATFORMS = ["sensor"]


async def async_setup_entry(hass, entry):
    """Set up CEZ PND from a config entry."""
    # This will be implemented in later tasks
    return True