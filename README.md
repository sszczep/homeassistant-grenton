# Home Assistant Grenton

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/sszczep/homeassistant-grenton?style=for-the-badge)](https://github.com/sszczep/homeassistant-grenton/releases)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg?style=for-the-badge)](https://github.com/sszczep/homeassistant-grenton/graphs/commit-activity)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-%E2%9D%A4-red?style=for-the-badge&logo=github)](https://github.com/sponsors/sszczep)

Custom Home Assistant integration for **Grenton Smart Home** system. Seamlessly connect and control your Grenton devices through Home Assistant with automatic discovery, real-time updates, and full configuration support.

![Grenton Integration](assets/dashboard.png)

## 💖 Sponsor

If you find this integration helpful, please consider supporting ongoing development via [**GitHub Sponsors**](https://github.com/sponsors/sszczep).

Your support helps maintain features, fix bugs, and improve documentation.

## ✨ Features

- **🔌 Automatic Device Discovery** - Connects to Grenton Object Manager and automatically discovers all configured devices
- **🏠 Multiple Widget Types** - Support for lights, switches, dimmers, sensors, covers, and more
- **⚙️ Per-Entity Configuration** - Customize device class and unit of measurement for each supported entity through the UI
- **🔄 Real-time Updates** - Automatic state synchronization with Grenton system
- **🌍 Multi-language Support** - Fully translated UI in English and Polish
- **📱 Modern UI** - Native Home Assistant integration with clean configuration flows

## 📦 Supported Widgets

| Widget Type (Literal) | Description |
|-----------------------|-------------|
| **VALUE_V2** | Single numeric value exposed as `sensor` with configurable device class/unit. |
| **VALUE_DOUBLE** | Dual numeric values exposed as two `sensor` entities (A/B). |
| **ON_OFF** | Single relay exposed as `switch`. |
| **ON_OFF_DOUBLE** | Dual relays exposed as two `switch` entities. |
| **DIMMER_V2** | Dimmable light exposed as `light` with brightness (0-100%). |
| **LED** | LED or RGB/RGBW light exposed as `light` with brightness and color where available. |
| **CONTACT_SENSOR** | Contact/door/window sensor exposed as `binary_sensor`. |
| **CONTACT_SENSOR_DOUBLE** | Dual contact channels exposed as two `binary_sensor` entities. |
| **SLIDER** | User-configurable numeric control exposed as `number` (slider/box/auto modes). |
| **MULTISENSOR** | Composite multi-channel sensor mapped to multiple `sensor` entities (as provided). |
| **ROLLER_SHUTTER** | Legacy roller shutter exposed as `sensor` (state enum) plus a `button` action entity. |
| **ROLLER_SHUTTER_V3** | Roller shutter V3 exposed as a single `cover` entity (position; lamel/tilt when available). |
| **CAMERA** | Camera stream exposed as `camera`. |

## 🚀 Installation

### Option 1: HACS (Recommended)

1. Open [HACS](https://www.hacs.xyz/docs/use/download/download/) in your Home Assistant instance
2. Go to **Integrations**
3. Click the three dots in the top right corner
4. Select **Custom repositories**
5. Add this repository URL: `https://github.com/sszczep/homeassistant-grenton`
6. Select **Integration** as the category
7. Click **Install**
8. Restart Home Assistant

### Option 2: Manual Installation

1. Download the latest release from the [Releases](https://github.com/sszczep/homeassistant-grenton/releases) section
2. Extract the zip file
3. Copy the `homeassistant_grenton` folder into your `custom_components` directory (usually `/config/custom_components/`)
4. Restart Home Assistant

## 📖 Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **"Grenton"**
4. Enter your Grenton Object Manager connection details:
   - **IP Address**: IP address of your Grenton Object Manager
   - **Port**: Port number (default: `9998`)
   - **PIN**: Your Object Manager PIN code

### Entity Configuration

After initial setup, you can customize individual entities:

1. Navigate to **Settings** → **Devices & Services** → **Grenton**
2. Click **Configure** on the integration
3. Select an entity from the dropdown menu
4. Configure entity properties:
   - **Sensors**: Choose device class and unit of measurement
   - **Sliders (Numbers)**: Set display mode, device class, and unit
   - **Binary Sensors**: Select appropriate device class

The integration intelligently filters available options based on your selections and automatically skips unnecessary configuration steps.

### Custom names and areas

During setup (and reconfiguration) you can tick **Customize names and areas**.
You then get one form per interface page: the page becomes the suggested area
and every widget gets a name field prefilled from its label.

### Manually added objects (UDP or Gate HTTP)

Objects that are not widgets in the myGrenton interface can be added in
**Configure → Add object manually** using the `CLU->OBJECT` identifier
(e.g. `CLU221001234->DOU5678`, `CLU221001234->myScript` for a button,
`CLU221001234->myFeature` for a user feature/variable).

Supported kinds: switch / on-off light (DOUT), dimmer (DIMMER), LED RGB,
LED RGBW, single LED channel (R/G/B/W), roller shutter, thermostat
(THERMOSTAT → climate), sensor, binary sensor, script button. Z-Wave objects
(`ZWA…`) are detected by name and use their own indexes (dimmer, LED colour,
roller shutter without tilt).

Each object chooses its connection:

| Connection | Requirements | State updates |
|---|---|---|
| **UDP** | CLU present in the imported interface | instant (CLU subscription) |
| **Gate HTTP** | GATE HTTP module + HttpListener below | polling (Gate settings) |

#### Gate HTTP setup

1. On the Gate create an `HttpListener` virtual object named
   `HA_Integration_Listener`, path `/HAlistener`, ResponseType `JSON`.
2. Attach a script to its `OnRequest` event that evaluates each JSON value as
   Lua and returns the results under the same keys, plus `g_status = "OK"`.
   The format is compatible with the listener used by
   [Grenton Objects](https://github.com/jnalepka/grenton-objects-home-assistant),
   so an existing listener can be reused as is.
3. In **Configure → Gate HTTP settings** enter the listener URL,
   e.g. `http://192.168.1.50/HAlistener`.

#### Instant updates from the Gate (webhook)

Polling works out of the box. For instant state changes enable
**Receive changes from the Gate via webhook** in the Gate settings; the form
then shows the webhook URL (`http://<HA>:8123/api/webhook/<id>`, LAN only).
The Gate sends a JSON `POST` with one update or a list of them:

```json
{"clu": "CLU221001234", "object": "DOU5678", "index": 0, "value": 1}
[{"id": "CLU221001234->THE0001", "index": 12, "value": 21.5},
 {"clu": "CLU221001234", "variable": "trybDomu", "value": 2}]
```

Example on the Gate: an `HttpRequest` virtual object `HA_Webhook`
(Host `http://<HA>:8123`, Path `/api/webhook/<id>`, Method `POST`,
RequestType/ResponseType `JSON`) and a script `HA_Push(clu, object, index, value)`:

```lua
GATE_HTTP->HA_Webhook->SetRequestBody({clu = clu, object = object, index = index, value = value})
GATE_HTTP->HA_Webhook->SendRequest()
```

Call it from the object's `OnValueChange` event, e.g.
`GATE_HTTP->HA_Push("CLU221001234", "DOU5678", 0, CLU221001234->DOU5678->Value)`.
An `HttpRequest` sends one request at a time, so events that arrive while it
is busy can be lost; polling stays active as a fallback (a long interval such
as 300 s is enough).

> ⚠️ Such a listener executes any Lua it receives, without authentication.
> Keep the Gate in a trusted network segment and never expose it to the internet.

## 🎨 Device Classes & Units

### Sensor Device Classes

The integration supports all Home Assistant sensor device classes:

- **Environmental**: Temperature, Humidity, Atmospheric Pressure, Air Quality Index
- **Energy**: Power, Energy, Voltage, Current, Apparent Power, Reactive Power
- **Environmental Monitoring**: CO, CO2, VOC, PM1, PM10, PM2.5
- **Physical**: Distance, Speed, Weight, Volume, Pressure
- **And many more...**

### Number (Slider) Device Classes

Configure sliders with appropriate device classes for proper representation:

- Display modes: Auto, Slider, Box
- Device classes: Temperature, Humidity, Power, Voltage, Current, etc.
- Automatic unit filtering based on device class

### Binary Sensor Device Classes

- **Safety**: Battery, Cold, Heat, Gas, Smoke, CO
- **Security**: Door, Window, Opening, Lock, Motion, Occupancy
- **Connectivity**: Connectivity, Power, Plug
- **System**: Problem, Running, Update, Vibration

## 🐛 Troubleshooting

### Connection Issues

**Cannot connect to Grenton Object Manager:**

1. Verify IP address and port are correct
2. Ensure Home Assistant can reach the Grenton network
3. Check PIN code is correct
4. Review Home Assistant logs: **Settings** → **System** → **Logs**

### Configuration Not Saving

**Entity configurations don't persist:**

1. Complete all configuration steps
2. Ensure you clicked **Submit** on the final step
3. Check integration logs for errors
4. Restart Home Assistant and try again

### Device Not Appearing

**Device discovered but not showing in UI:**

1. Check device is properly configured in Grenton Object Manager
2. Verify device type is supported (see Supported Devices table)
3. Review coordinator logs for device mapping errors
4. Force integration reload: **Settings** → **Devices & Services** → **Grenton** → **⋮** → **Reload**

### State Not Updating

**Device state not synchronized:**

1. Check Grenton Object Manager is running and accessible
2. Verify network connectivity between Home Assistant and Grenton
3. Review coordinator update interval (default: 30 seconds)
4. Check Grenton device is responding to queries

## 📝 License

This project is licensed under the **GNU General Public License v3.0**.

- You may run, study, share, and modify the software under the terms of GPL-3.0.
- Redistributions and derivative works must also be licensed under GPL-3.0 and include the source code.

See the full text in the [LICENSE](LICENSE) file.

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📧 Support

For issues, questions, or contributions:

- **GitHub Issues**: [Report a bug or request a feature](https://github.com/sszczep/homeassistant-grenton/issues)
- **Discussions**: [Ask questions and share ideas](https://github.com/sszczep/homeassistant-grenton/discussions)
- **GitHub Sponsors**: [Sponsor ongoing development](https://github.com/sponsors/sszczep)

## 💖 Sponsor

If you find this integration helpful, please consider supporting ongoing development via [**GitHub Sponsors**](https://github.com/sponsors/sszczep).

Your support helps maintain features, fix bugs, and improve documentation.

## 🙏 Acknowledgments

- Home Assistant community for the excellent platform
- Grenton for their smart home system
- All contributors and users of this integration

---

<div align="center">

**Made with ❤️ for the Home Assistant community**

[Report Bug](https://github.com/sszczep/homeassistant-grenton/issues) · [Request Feature](https://github.com/sszczep/homeassistant-grenton/issues) · [Discuss](https://github.com/sszczep/homeassistant-grenton/discussions)

</div>
