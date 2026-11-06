"""Split imported Lua arguments without evaluating expressions."""

import math
import re


def split_lua_arguments(value: str) -> list[str]:
    """Split only top-level commas, preserving strings and nested expressions.

    Ambiguous or unfinished Lua stays as one raw expression. In particular,
    function bodies and comments are not interpreted by this small scanner.
    """
    if not value.strip():
        return []
    parts, stack = [], []
    start = position = 0
    while position < len(value):
        char = value[position]
        if char in "\"'":
            quote = char
            position += 1
            while position < len(value):
                if value[position] == "\\":
                    position += 2
                elif value[position] == quote:
                    position += 1
                    break
                else:
                    position += 1
            else:
                return [value]
            continue
        if char == "[" and (match := re.match(r"\[(=*)\[", value[position:])):
            closing = "]" + match[1] + "]"
            end = value.find(closing, position + len(match[0]))
            if end < 0:
                return [value]
            position = end + len(closing)
            continue
        if value.startswith("--", position):
            return [value]
        if char.isalpha() or char == "_":
            word = re.match(r"[\w]+", value[position:])[0]
            if word in ("function", "end"):
                return [value]
            position += len(word)
            continue
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[char]:
                return [value]
        elif char == "," and not stack:
            parts.append(value[start:position].strip())
            start = position + 1
        position += 1
    parts.append(value[start:].strip())
    return [value] if stack or any(not part for part in parts) else parts


def imported_lua_argument(expression: str) -> dict:
    """Expose simple literals as typed values, keeping other Lua verbatim."""
    if expression in ("true", "false"):
        return {"type": "boolean", "value": expression == "true"}
    if expression == "nil":
        return {"type": "nil", "value": None}
    if re.fullmatch(r"[+-]?\d+", expression):
        return {"type": "number", "value": int(expression)}
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", expression):
        number = float(expression)
        if math.isfinite(number):
            return {"type": "float", "value": number}
    if (
        len(expression) >= 2
        and expression[0] in "\"'"
        and expression[-1] == expression[0]
    ):
        contents = expression[1:-1]
        # Decode only known Lua escapes. Unrecognized syntax stays raw Lua.
        escapes = {
            "a": "\a",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "v": "\v",
            "\\": "\\",
            '"': '"',
            "'": "'",
        }
        result, position = [], 0
        while position < len(contents):
            if contents[position] != "\\":
                if contents[position] in (expression[0], "\n", "\r"):
                    break
                result.append(contents[position])
                position += 1
                continue
            position += 1
            if position == len(contents):
                break
            char = contents[position]
            if char in escapes:
                result.append(escapes[char])
                position += 1
            elif char.isascii() and char.isdigit():
                match = re.match(r"\d{1,3}", contents[position:])[0]
                if int(match) > 255:
                    break
                result.append(chr(int(match)))
                position += len(match)
            else:
                break
        else:
            return {"type": "string", "value": "".join(result)}
    return {"type": "lua", "value": expression}
