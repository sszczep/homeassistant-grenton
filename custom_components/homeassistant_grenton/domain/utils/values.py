def format_action_value(value: float, precision: int) -> str:
    """Format a numeric action value for sending to the CLU.

    round() always returns a float when called with an explicit precision,
    so precision-0 channels would receive "2.0" instead of "2". Integer
    channels (and Lua scripts matching on the string form of the value)
    silently ignore such values, so collapse them to a plain integer string.
    """
    rounded = round(value, precision)
    if precision == 0:
        return str(int(rounded))
    return str(rounded)
