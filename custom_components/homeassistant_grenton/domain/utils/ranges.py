def map_range(from_range: tuple[float, float], to_range: tuple[float, float], value: float) -> float:
    """
    Map a value from one range to another.
    
    Args:
        from_range: Tuple of (min, max) for the source range
        to_range: Tuple of (min, max) for the target range
        value: The value to map
    
    Returns:
        The mapped value in the target range
    """
    from_min, from_max = from_range
    to_min, to_max = to_range
    
    # Normalize the value to 0-1 range
    from_range_size = from_max - from_min
    normalized = (value - from_min) / from_range_size if from_range_size > 0 else 0
    
    # Scale to the target range
    to_range_size = to_max - to_min
    return to_min + normalized * to_range_size

