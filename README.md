# 🦎 Gecko Integration for Home Assistant

[![GitHub Release](https://img.shields.io/github/release/geckoal/gecko-iot-client.svg?style=flat-square)](https://github.com/geckoal/gecko-iot-client/releases)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

Control and monitor your Gecko-powered spas, hot tubs, and pool equipment directly from Home Assistant.

## Features

- 🌡️ **Climate Control**: Set and monitor spa temperature with precision
- 💡 **Lighting Control**: Manage multi-zone LED lighting systems
- 💨 **Fan/Pump Control**: Control pumps, blowers, and circulation systems
- 📊 **Real-time Monitoring**: Track RF signal strength, gateway status, and water quality
- 🔄 **Watercare Modes**: Switch between Away, Standard, Savings, and Weekender modes
- ☁️ **Cloud Integration**: Secure OAuth2 authentication with AWS IoT backend

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL and select "Integration" as the category
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Copy the `gecko` folder to your `custom_components` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services
4. Click "+ ADD INTEGRATION"
5. Search for "Gecko"

## Configuration

The integration uses OAuth2 for authentication:

1. Click "+ ADD INTEGRATION" in Home Assistant
2. Search for "Gecko"
3. Follow the OAuth2 flow to authorize access
4. Your spa(s) will be automatically discovered

## Supported Entities

### Climate
- Temperature control with heat modes
- Current and target temperature monitoring
- HVAC action tracking (heating/idle)

### Light
- Multi-zone LED lighting
- Brightness control
- Color temperature support

### Fan
- Pump speed control (Low/High)
- Blower operation
- Circulation system management

### Sensor
- RF signal strength
- RF channel
- Gateway connection status
- Spa operational status

### Select
- Watercare mode selection
- Operating mode presets

## Support

- 🐛 [Report Issues](https://github.com/geckoal/gecko-iot-client/issues)
- 📖 [Documentation](https://github.com/geckoal/gecko-iot-client)
- 💬 [Discussions](https://github.com/geckoal/gecko-iot-client/discussions)

## Credits

Built with [gecko-iot-client](https://github.com/geckoal/gecko-iot-client) library.

## License

This integration is licensed under the GPL-3.0 license. See [LICENSE](LICENSE) for details.
