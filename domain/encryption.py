from dataclasses import dataclass

from ..dto.encryption import GrentonEncryptionDto

@dataclass
class GrentonEncryption:
    key: str
    iv: str

    @staticmethod
    def from_dto(dto: GrentonEncryptionDto) -> "GrentonEncryption":
        return GrentonEncryption(
            key=dto.key,
            iv=dto.iv,
        )