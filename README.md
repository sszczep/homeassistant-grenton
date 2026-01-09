# Grenton Home Assistant Integration

Custom integration for connecting Grenton smart home devices to Home Assistant.

## Features

- **Automatic Device Discovery**: Connects to Grenton Object Manager and automatically discovers configured devices
- **Multiple Device Types Support**:
  - On/Off Switches (single and double)
  - Dimmers (V2)
  - Value Sensors (single and double)
  - more to come
- **Per-Entity Configuration**: Customize each sensor's device class and unit of measurement through the UI
- **Real-time Updates**: Automatic state synchronization with Grenton system
- **Multi-language Support**: English and Polish translations included

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL and select "Integration" as the category
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Copy the `homeassistant_grenton` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Grenton"
4. Enter your Grenton Object Manager details:
   - **IP Address**: The IP address of your Grenton Object Manager
   - **Port**: Port number (default: 9998)
   - **PIN**: Your Object Manager PIN code

### Entity Configuration

After setup, you can configure individual sensor entities:

1. Go to **Settings** → **Devices & Services**
2. Find the Grenton integration
3. Click **Configure**
4. Select an entity from the dropdown
5. Follow the configuration steps:
   - **Step 1**: Choose the device class (temperature, humidity, power, etc.)
   - **Step 2**: Select the unit of measurement (automatically filtered based on device class)

The integration automatically skips the unit selection step for device classes that don't require units.

## Supported Device Classes

The integration supports all native Home Assistant sensor device classes including:

- **Environmental**: Temperature, Humidity, Atmospheric Pressure, Air Quality
- **Energy**: Power, Energy, Voltage, Current
- **Motion**: Distance, Speed, Acceleration
- **Light**: Illuminance, Irradiance
- **And many more...**

## Device Types

### Switches
- **On/Off Switch**: Single relay control
- **On/Off Double Switch**: Dual relay control

### Dimmers
- **Dimmer V2**: Brightness control with 0-100% range

### Sensors
- **Value Sensor V2**: Single numeric sensor
- **Value Double Sensor**: Dual numeric sensor

## Architecture

### Components

- **Coordinator**: Manages communication with Grenton Object Manager and handles state updates
- **Config Flow**: Handles initial integration setup
- **Options Flow**: Manages per-entity configuration with multi-step forms
- **Configurable Entities**: Mixin pattern for entities that support runtime configuration

### Configuration Persistence

Entity configurations are stored in the integration's options and persist across Home Assistant restarts. Each entity can be independently configured without affecting others.

## Translation Support

The integration includes full translation support:
- English (en)
- Polish (pl)

All UI elements, including selector options and step descriptions, are fully localized.

## Troubleshooting

### Connection Issues

If you cannot connect to your Grenton Object Manager:
1. Verify the IP address and port are correct
2. Ensure your Home Assistant instance can reach the Grenton network
3. Check that the PIN code is correct
4. Review Home Assistant logs for specific error messages

### Entity Configuration Not Saving

If entity configurations don't persist:
1. Ensure you complete all configuration steps
2. Check that you clicked "Submit" on the final step
3. Review logs for any errors during configuration save

## Development

### Project Structure

```
homeassistant_grenton/
├── __init__.py              # Integration setup
├── config_flow.py           # Initial configuration flow
├── options_flow.py          # Entity configuration flow
├── coordinator.py           # Update coordinator
├── const.py                 # Constants
├── manifest.json            # Integration metadata
├── domain/                  # Domain logic
│   ├── entities/           # Entity implementations
│   │   ├── base.py         # Base entity class
│   │   ├── configurable.py # Configurable entity mixin
│   │   ├── value.py        # Sensor entities
│   │   ├── dimmer.py       # Dimmer entities
│   │   └── bistable_switch.py # Switch entities
│   ├── devices/            # Device implementations
│   └── api/                # Grenton API client
├── translations/           # Localization files
│   ├── en.json
│   └── pl.json
└── README.md
```

### Configuration Schema

Entities use a schema-based configuration system with:
- **StepDefinition**: Defines each configuration step with explicit step IDs
- **StepResult**: Encapsulates form schema, placeholders, and completion flags
- **BaseGrentonEntityConfigurationSchema**: Base class for entity configuration schemas

## License

This integration is provided as-is for use with Grenton smart home systems.

## Support

For issues, questions, or contributions, please open an issue on the repository.
