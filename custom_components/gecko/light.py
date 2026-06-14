"""Support for Gecko light entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import callback

from .const import DOMAIN
from .coordinator import GeckoVesselCoordinator
from .entity import GeckoEntityAvailabilityMixin
from . import GeckoConfigEntry

from gecko_iot_client.models.zone_types import ZoneType


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GeckoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gecko light entities from a config entry."""
    
    # Get runtime data with per-vessel coordinators
    runtime_data = config_entry.runtime_data
    if not runtime_data or not runtime_data.coordinators:
        _LOGGER.error("No coordinators found in runtime_data for config entry %s", config_entry.entry_id)
        return
    
    # Track created entities to avoid duplicates
    created_entity_ids = set()
    
    # Create entity discovery function for each coordinator
    def create_discovery_callback(coordinator: GeckoVesselCoordinator):
        """Create a discovery callback for a specific coordinator."""
        def discover_new_light_entities():
            """Discover new light entities for new zones."""
            new_entities = []
            
            # Get light zones for this vessel's coordinator (no monitor_id needed)
            light_zones = coordinator.get_zones_by_type(ZoneType.LIGHTING_ZONE)
            
            for zone in light_zones:
                # Check if entity already exists
                entity_id = f"{coordinator.vessel_name}_light_{zone.id}".lower()
                if entity_id not in created_entity_ids:
                    entity = GeckoLight(coordinator, config_entry, zone)
                    new_entities.append(entity)
                    created_entity_ids.add(entity_id)
            
            if new_entities:
                async_add_entities(new_entities)
        
        return discover_new_light_entities
    
    # Set up entities for each vessel coordinator
    for coordinator in runtime_data.coordinators:
        # Initial entity discovery for this coordinator
        discovery_callback = create_discovery_callback(coordinator)
        discovery_callback()
        
        # Register callback for dynamic entity creation
        coordinator.register_zone_update_callback(discovery_callback)


class GeckoLight(GeckoEntityAvailabilityMixin, CoordinatorEntity, LightEntity):
    """Representation of a Gecko light."""

    _attr_has_entity_name = True
    coordinator: GeckoVesselCoordinator

    def __init__(
        self,
        coordinator: GeckoVesselCoordinator,
        config_entry: GeckoConfigEntry,
        zone: Any,  # LightingZone from coordinator
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)

        self._zone = zone
        self._attr_name = f"Light {zone.id}"
        self._attr_unique_id = f"{config_entry.entry_id}_{coordinator.vessel_id}_light_{zone.id}"

        # Device info for grouping entities
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.vessel_id))},
        )
        
        # Set basic light features - Now supporting only RGB
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB
        
        # Initialize state
        self._attr_available = False
        self._attr_rgb_color = (255, 255, 255)
        self._update_state()

    def _get_zone_state(self) -> Any | None:
        """Get the current zone state from coordinator."""
        try:
            light_zones = self.coordinator.get_zones_by_type(ZoneType.LIGHTING_ZONE)
            return next((z for z in light_zones if z.id == self._zone.id), None)
        except Exception as e:
            _LOGGER.warning("Error getting zone state for %s: %s", self._attr_name, e)
        return None

    def _update_state(self) -> None:
        """Update entity state from zone data."""
        zone = self._get_zone_state()
        if zone:
            self._attr_is_on = getattr(zone, 'active', False)
            
            # Update brightness/color if supported by zone
            if hasattr(zone, "rgbi") and zone.rgbi:
                # Log state to help debug brightness issues
                _LOGGER.debug("Zone %s current RGBI: %s", zone.id, zone.rgbi)
                
                try:
                    if hasattr(zone.rgbi, 'r'):
                        self._attr_rgb_color = (zone.rgbi.r, zone.rgbi.g, zone.rgbi.b)
                        intensity = zone.rgbi.i
                    else:
                        self._attr_rgb_color = (zone.rgbi[0], zone.rgbi[1], zone.rgbi[2])
                        intensity = zone.rgbi[3]

                    # Map intensity (0.0-1.0 or 0-255) to 0-255 brightness
                    if intensity is not None:
                        if isinstance(intensity, float):
                            self._attr_brightness = int(intensity * 255)
                        else:
                            self._attr_brightness = int(intensity)
                    else:
                        self._attr_brightness = 255
                except (IndexError, AttributeError) as e:
                    _LOGGER.warning("Error parsing RGBI data for %s: %s", self._attr_name, e)
            else:
                self._attr_rgb_color = (255, 255, 255)
                self._attr_brightness = 255
        else:
            self._attr_is_on = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        try:
            # Get the light zone from coordinator
            light_zones = self.coordinator.get_zones_by_type(ZoneType.LIGHTING_ZONE)
            zone = next((z for z in light_zones if z.id == self._zone.id), None)
            if not zone:
                _LOGGER.warning("Could not find lighting zone %s", self._zone.id)
                return

            # Handle color/brightness change
            if ATTR_RGB_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
                rgb = kwargs.get(ATTR_RGB_COLOR, self._attr_rgb_color or (255, 255, 255))
                brightness = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255)
                intensity = float(brightness / 255.0)
                
                _LOGGER.debug("Setting color RGBI [%s, %s, %s, %s] for %s", 
                             int(rgb[0]), int(rgb[1]), int(rgb[2]), intensity, self._attr_name)
                
                if hasattr(zone, "set_color"):
                    # High-level library method
                    zone.set_color(int(rgb[0]), int(rgb[1]), int(rgb[2]), intensity)
                else:
                    # Fallback to direct state publishing
                    publish_method = getattr(zone, "_publish_desired_state", None)
                    if callable(publish_method):
                        # Use raw list to avoid serialization errors seen in logs
                        publish_method({"active": True, "rgbi": [int(rgb[0]), int(rgb[1]), int(rgb[2]), intensity]})
            else:
                # Default: just turn on
                if hasattr(zone, "activate"):
                    zone.activate()
                else:
                    publish_method = getattr(zone, "_publish_desired_state", None)
                    if callable(publish_method):
                        publish_method({"active": True})

            self._attr_is_on = True
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Error turning on light %s: %s", self._attr_name, e)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        try:
            # Get the light zone from coordinator
            light_zones = self.coordinator.get_zones_by_type(ZoneType.LIGHTING_ZONE)
            zone = next((z for z in light_zones if z.id == self._zone.id), None)
            if zone:
                if hasattr(zone, "deactivate"):
                    _LOGGER.debug("Calling deactivate for %s", self._attr_name)
                    zone.deactivate()
                else:
                    publish_method = getattr(zone, "_publish_desired_state", None)
                    if callable(publish_method):
                        _LOGGER.debug("Publishing turn_off for %s", self._attr_name)
                        publish_method({"active": False})
            else:
                _LOGGER.warning("Could not find lighting zone %s", self._zone.id)
            
            self._attr_is_on = False
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning off light %s: %s", self._attr_name, e)
