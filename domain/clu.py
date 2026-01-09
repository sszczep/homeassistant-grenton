from dataclasses import dataclass

from ..dto.clu import GrentonCluDto

@dataclass
class GrentonClu:
    id: str
    serial_number: str
    name: str
    ip: str
    port: int

    @staticmethod
    def from_dto(dto: GrentonCluDto) -> "GrentonClu":
        return GrentonClu(
            id=dto.id,
            serial_number=dto.serialNumber,
            name=dto.name,
            ip=dto.ip,
            port=dto.port,
        )