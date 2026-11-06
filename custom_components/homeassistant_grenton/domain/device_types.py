"""Known device types and their built-in attribute indexes."""

CLU_Z_WAVE = "CLU_Z_WAVE"
CLU_GATE_HTTP = "CLU_GATE_HTTP"

CLU_SERIAL_PREFIXES: dict[str, str] = {
    "221": CLU_Z_WAVE,
    "521": CLU_GATE_HTTP,
}

# Keep separate maps: supported attributes and indexes can differ by device type.
DEVICE_ATTRIBUTES: dict[str, dict[int, str]] = {
    CLU_Z_WAVE: {
        0: "Uptime",
        17: "FirmwareVersion",
        18: "UseCloud",
        19: "CloudConnection",
        27: "BusVoltage",
    },
    CLU_GATE_HTTP: {
        0: "Uptime",
        17: "FirmwareVersion",
        18: "UseCloud",
        19: "CloudConnection",
    },
}


def attribute_index(device_type: str | None, name: str) -> str | None:
    """Look up an attribute supported by a device type."""
    if device_type is None:
        return None
    for index, attribute in DEVICE_ATTRIBUTES.get(device_type, {}).items():
        if attribute == name:
            return str(index)
    return None


def clu_device_type(serial_number: str) -> str | None:
    """Identify supported CLU types without relying on configured names."""
    for prefix, device_type in CLU_SERIAL_PREFIXES.items():
        if serial_number.startswith(prefix):
            return device_type
    return None
