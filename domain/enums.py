from enum import Enum

class GrentonUnit(str, Enum):
    UNKNOWN = "UNKNOWN"
    PERCENT = "PERCENT"
    DEGREE = "DEGREE"

class GrentonValueType(str, Enum):
    STRING = "STRING"
    FLOAT = "FLOAT"
    INTEGER = "INTEGER"

class GrentonValueCallType(str, Enum):
    VARIABLE = "VARIABLE"
    ATTRIBUTE = "ATTRIBUTE"

class GrentonActionEventType(str, Enum):
    CLICK = "CLICK"
    ON = "ON"
    OFF = "OFF"

class GrentonActionCallType(str, Enum):
    ATTRIBUTE = "ATTRIBUTE"
    METHOD = "METHOD"
    SCRIPT = "SCRIPT"
    VARIABLE = "VARIABLE"

class GrentonComponentIndication(str, Enum):
    ON_OFF = "ON_OFF"
    OPEN_CLOSED = "OPEN_CLOSED"
    OPEN_LOCKED = "OPEN_LOCKED"
    UP_DOWN = "UP_DOWN"

class GrentonTheme(str, Enum):
    GRENTON = "GRENTON"
    RED = "RED"
    ORANGE = "ORANGE"
    YELLOW = "YELLOW"
    LIME = "LIME"
    GREEN = "GREEN"
    STEEL = "STEEL"
    TURQUOISE = "TURQUOISE"
    BLUE = "BLUE"
    INDIGO = "INDIGO"
    VIOLET = "VIOLET"
    PURPLE = "PURPLE"
    PINK = "PINK"
    BEIGE = "BEIGE"
    BROWN = "BROWN"

class GrentonCluConnectionType(str, Enum):
    LOCAL_ONLY = "LOCAL_ONLY"
    CLOUD_CAPABLE = "CLOUD_CAPABLE"
    CLOUD = "CLOUD"