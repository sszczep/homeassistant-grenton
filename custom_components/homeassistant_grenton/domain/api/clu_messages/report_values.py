"""Split CLU report values, including firmware strings with unescaped quotes."""

from functools import cache

from ...lua_arguments import split_lua_arguments


def split_report_values(content: str, expected_count: int | None) -> list[str]:
    """Prefer normal Lua syntax, using the key count for ambiguous quoted text."""
    values = split_lua_arguments(content)
    if expected_count is None or len(values) == expected_count:
        return values

    def ambiguous_quotes(token: str) -> bool:
        escaped, quotes = False, 0
        for char in token:
            if char == '"' and not escaped:
                quotes += 1
            escaped = char == "\\" and not escaped
        return (
            quotes > 2
            or quotes % 2 != 0
            or bool(quotes and not (token.startswith('"') and token.endswith('"')))
        )

    # Do not "repair" an ordinary short/long response by merging real values.
    if not any(ambiguous_quotes(value) for value in values):
        raise ValueError(
            f"Expected {expected_count} report values, received {len(values)}"
        )

    @cache
    def split(start: int, remaining: int) -> tuple[str, ...] | None:
        while start < len(content) and content[start].isspace():
            start += 1
        if remaining < 1 or start >= len(content):
            return None
        if content[start] == '"':
            # A candidate closes a string only before a separator or the end.
            candidates = []
            escaped = False
            for index in range(start + 1, len(content)):
                char = content[index]
                if char == '"' and not escaped:
                    end = index + 1
                    while end < len(content) and content[end].isspace():
                        end += 1
                    if end == len(content):
                        if remaining == 1:
                            return (content[start : index + 1],)
                    elif content[end] == ",":
                        candidates.append((index, end))
                escaped = char == "\\" and not escaped
            for index, separator in reversed(candidates):
                if tail := split(separator + 1, remaining - 1):
                    return (content[start : index + 1], *tail)
            return None
        # Ordinary unquoted tokens still obey Lua's nested-expression rules.
        parts = split_lua_arguments(content[start:])
        if len(parts) == remaining:
            return tuple(parts)
        if remaining > 1 and len(parts) > 1:
            separator = start + len(parts[0])
            while separator < len(content) and content[separator].isspace():
                separator += 1
            if (
                separator < len(content)
                and content[separator] == ","
                and (tail := split(separator + 1, remaining - 1))
            ):
                return (parts[0], *tail)
        return None

    result = split(0, expected_count)
    if result is None:
        raise ValueError(f"Could not split clientReport into {expected_count} values")
    return list(result)
