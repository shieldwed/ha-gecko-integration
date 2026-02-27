"""Support for Gecko light entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
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

from gecko_iot_client.models.zone_types import ZoneType
from gecko_iot_client.models.lighting_zone import RGB


_LOGGER = logging.getLogger(__name__)

# List of supported effects for Gecko lights
GECKO_EFFECTS = ["Rainbow Slow", "Rainbow Fast", "Slow Fade", "Fast Fade", "Loop"]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
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
    coordinator: GeckoVesselCoordinator

    def __init__(
        self,
        coordinator: GeckoVesselCoordinator,
        config_entry: ConfigEntry,
        zone: Any,  # LightingZone from coordinator
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)

        self._zone = zone
        self.entity_id = f"light.{coordinator.vessel_name}_light_{zone.id}".lower()

        self._attr_name = f"{coordinator.vessel_name} light zone {zone.id}"
        self._attr_unique_id = f"{config_entry.entry_id}_{coordinator.vessel_name}_light_{zone.id}"

        # Device info for grouping entities - reference the actual device created in __init__.py
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.vessel_id))},
        )

        # Set basic light features - Now supporting RGB and Effects
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB
        self._attr_supported_features = LightEntityFeature.EFFECT
        self._attr_effect_list = GECKO_EFFECTS

        # Initialize state and availability (will be set by async_added_to_hass event registration)
        self._attr_available = False
        self._attr_rgb_color = (255, 255, 255)
        self._attr_effect = None
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
            
            # Update effect if supported by zone and valid
            zone_effect = getattr(zone, "effect", None)
            _LOGGER.debug("Zone %s current effect: %s", zone.id, zone_effect)
            if zone_effect in GECKO_EFFECTS:
                self._attr_effect = zone_effect
            else:
                self._attr_effect = None

            # Update brightness/color if supported by zone and no effect is active
            if self._attr_effect:
                self._attr_rgb_color = None
                self._attr_brightness = 255  # Full brightness for effects
            elif hasattr(zone, "rgbi") and zone.rgbi:
                _LOGGER.debug("Zone %s current RGBI: r=%s, g=%s, b=%s, i=%s", 
                             zone.id, zone.rgbi.r, zone.rgbi.g, zone.rgbi.b, zone.rgbi.i)
                self._attr_rgb_color = (zone.rgbi.r, zone.rgbi.g, zone.rgbi.b)
                # Map intensity (0.0-1.0 or 0-255) to 0-255 brightness
                if zone.rgbi.i is not None:
                    if isinstance(zone.rgbi.i, float):
                        self._attr_brightness = int(zone.rgbi.i * 255)
                    else:
                        self._attr_brightness = int(zone.rgbi.i)
                else:
                    self._attr_brightness = 255
            else:
                self._attr_rgb_color = (255, 255, 255)
                self._attr_brightness = 255
        else:
            self._attr_is_on = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        # Availability is now updated via CONNECTIVITY_UPDATE events, not polling
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        try:
            # Check if gecko client is connected
            gecko_client = await self.coordinator.get_gecko_client()
            if not gecko_client:
                _LOGGER.error("No gecko client available for %s", self._attr_name)
                return

            # Get the light zone from coordinator
            light_zones = self.coordinator.get_zones_by_type(ZoneType.LIGHTING_ZONE)
            zone = next((z for z in light_zones if z.id == self._zone.id), None)
            if not zone:
                _LOGGER.warning("Could not find lighting zone %s", self._zone.id)
                return

            # Prepare state update payload
            payload = {"active": True}

            # Handle effect change
            if ATTR_EFFECT in kwargs:
                effect = kwargs[ATTR_EFFECT]
                if effect not in GECKO_EFFECTS:
                    _LOGGER.warning("Unsupported effect %s for %s", effect, self._attr_name)
                else:
                    _LOGGER.debug("Setting effect %s for %s", effect, self._attr_name)
                    payload["effect"] = effect

            # Handle color/brightness change
            if ATTR_RGB_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
                rgb = kwargs.get(ATTR_RGB_COLOR, self._attr_rgb_color or (255, 255, 255))
                brightness = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255)
                intensity = float(brightness / 255.0)
                
                _LOGGER.debug("Setting RGBI [r: %s, g: %s, b: %s, i: %s] for %s", 
                             int(rgb[0]), int(rgb[1]), int(rgb[2]), intensity, self._attr_name)
                
                # Use list format [r, g, b, i] which matches how the hardware reports state
                payload["rgbi"] = [int(rgb[0]), int(rgb[1]), int(rgb[2]), intensity]
                
                # Update local zone object to reflect desired state for immediate reporting
                zone.rgbi = RGB(r=int(rgb[0]), g=int(rgb[1]), b=int(rgb[2]), i=intensity)

            # Publish the combined state update
            publish_method = getattr(zone, "_publish_desired_state", None)
            if callable(publish_method):
                _LOGGER.debug("Publishing state update for %s: %s", self._attr_name, payload)
                publish_method(payload)
                zone.active = True
            else:
                # Fallback to standard library methods if publish_method is missing
                _LOGGER.warning("Using library fallback for %s state update", self._attr_name)
                if "effect" in payload:
                    zone.set_effect(payload["effect"])
                elif "rgbi" in payload:
                    c = payload["rgbi"]
                    zone.set_color(c[0], c[1], c[2], c[3])
                else:
                    zone.activate()

            self._attr_is_on = True
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error("Error turning on light %s: %s", self._attr_name, e)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        try:
            # Check if gecko client is connected
            gecko_client = await self.coordinator.get_gecko_client()
            if not gecko_client:
                _LOGGER.error("No gecko client available for %s", self._attr_name)
                return

            # Get the light zone from coordinator
            light_zones = self.coordinator.get_zones_by_type(ZoneType.LIGHTING_ZONE)
            zone = next((z for z in light_zones if z.id == self._zone.id), None)
            if zone:
                publish_method = getattr(zone, "_publish_desired_state", None)
                if callable(publish_method):
                    _LOGGER.debug("Publishing turn_off for %s", self._attr_name)
                    publish_method({"active": False})
                    zone.active = False
                else:
                    zone.deactivate()
            else:
                _LOGGER.warning("Could not find lighting zone %s", self._zone.id)
            
            self._attr_is_on = False
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning off light %s: %s", self._attr_name, e)
