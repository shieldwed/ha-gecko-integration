"""Support for Gecko light entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from gecko_iot_client.models.zone_types import ZoneType

from .const import DOMAIN
from .coordinator import GeckoVesselCoordinator
from .entity import GeckoEntityAvailabilityMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gecko light entities from a config entry."""

    runtime_data = config_entry.runtime_data
    if not runtime_data or not runtime_data.coordinators:
        _LOGGER.error(
            "No coordinators found in runtime_data for config entry %s",
            config_entry.entry_id,
        )
        return

    created: set[str] = set()

    def create_discovery_callback(coordinator: GeckoVesselCoordinator):
        def discover():
            entities: list[GeckoLight] = []

            zones = coordinator.get_zones_by_type(
                ZoneType.LIGHTING_ZONE
            )

            for zone in zones:
                key = f"{coordinator.vessel_id}_{zone.id}"
                if key in created:
                    continue

                entities.append(
                    GeckoLight(coordinator, config_entry, zone)
                )
                created.add(key)

            if entities:
                async_add_entities(entities)

        return discover

    for coordinator in runtime_data.coordinators:
        cb = create_discovery_callback(coordinator)
        cb()
        coordinator.register_zone_update_callback(cb)


class GeckoLight(
    GeckoEntityAvailabilityMixin,
    CoordinatorEntity[GeckoVesselCoordinator],
    LightEntity,
):
    """Gecko lighting zone as Home Assistant light."""

    def __init__(
        self,
        coordinator: GeckoVesselCoordinator,
        config_entry: ConfigEntry,
        zone: Any,
    ) -> None:
        super().__init__(coordinator)

        self._zone = zone

        self._attr_name = f"{coordinator.vessel_name} Light {zone.id}"
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{coordinator.vessel_id}_light_{zone.id}"
        )

        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.vessel_id))},
        )

        # RGB only – no brightness, no color temp
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB

        self._attr_is_on = False
        self._attr_rgb_color = (255, 255, 255)
        self._attr_available = False

        self._update_state()

    def _get_zone_state(self) -> Any | None:
        try:
            zones = self.coordinator.get_zones_by_type(
                ZoneType.LIGHTING_ZONE
            )
            return next(
                (z for z in zones if z.id == self._zone.id),
                None,
            )
        except Exception as err:
            _LOGGER.warning(
                "Error getting zone state for %s: %s",
                self._attr_name,
                err,
            )
            return None

    def _update_state(self) -> None:
        zone = self._get_zone_state()
        if not zone:
            self._attr_is_on = None
            return

        self._attr_is_on = bool(getattr(zone, "active", False))

        if hasattr(zone, "color") and zone.color:
            try:
                r, g, b = zone.color
                self._attr_rgb_color = (int(r), int(g), int(b))
            except Exception as err:
                _LOGGER.debug(
                    "Invalid color from zone %s: %s",
                    zone.id,
                    err,
                )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        try:
            zone = self._get_zone_state()
            if not zone:
                _LOGGER.warning(
                    "Could not find lighting zone %s",
                    self._zone.id,
                )
                return

            if "rgb_color" in kwargs:
                rgb = kwargs["rgb_color"]
                r, g, b = map(int, rgb)

                set_color = getattr(zone, "set_color", None)
                if callable(set_color):
                    set_color(r, g, b)
                    self._attr_rgb_color = (r, g, b)
                else:
                    _LOGGER.warning(
                        "Zone %s does not support set_color",
                        zone.id,
                    )

            activate = getattr(zone, "activate", None)
            if callable(activate):
                activate()

            self._attr_is_on = True
            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error(
                "Error turning on light %s: %s",
                self._attr_name,
                err,
            )

    async def async_turn_off(self, **kwargs) -> None:
        try:
            zone = self._get_zone_state()
            if not zone:
                _LOGGER.warning(
                    "Could not find lighting zone %s",
                    self._zone.id,
                )
                return

            deactivate = getattr(zone, "deactivate", None)
            if callable(deactivate):
                deactivate()
            else:
                _LOGGER.warning(
                    "Zone %s does not support deactivate",
                    zone.id,
                )

            self._attr_is_on = False
            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error(
                "Error turning off light %s: %s",
                self._attr_name,
                err,
            )
