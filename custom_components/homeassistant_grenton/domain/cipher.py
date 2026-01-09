import logging
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from .encryption import GrentonEncryption

_LOGGER = logging.getLogger(__name__)

class GrentonCipher:
    def __init__(self, encryption: GrentonEncryption):
        self.encryption = encryption
        self._cipher = None
        self._initialize_cipher()
    
    def _initialize_cipher(self) -> None:
        try:
            # Decode base64 strings to bytes
            key = base64.b64decode(self.encryption.key)
            iv = base64.b64decode(self.encryption.iv)
            
            # Ensure key is 16/24/32 bytes (AES-128/192/256) and IV is 16 bytes
            if len(key) not in (16, 24, 32) or len(iv) != 16:
                _LOGGER.error("Invalid key or IV length: key=%d, iv=%d", len(key), len(iv))
                self._cipher = None
                return
            
            # Create base Cipher (contexts created per operation)
            self._cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        except Exception as e:
            _LOGGER.error("Failed to initialize cipher: %s", e)
            self._cipher = None
    
    def decrypt(self, encrypted_data: bytes) -> bytes | None:
        try:
            if self._cipher is None:
                return None
            
            # Decrypt
            decryptor = self._cipher.decryptor()
            decrypted = decryptor.update(encrypted_data) + decryptor.finalize()
            
            # Remove PKCS7 padding
            padding_length = decrypted[-1]
            if padding_length == 0 or padding_length > 16:
                _LOGGER.error("Invalid PKCS7 padding length: %d", padding_length)
                return None
            if decrypted[-padding_length:] != bytes([padding_length] * padding_length):
                _LOGGER.error("Invalid PKCS7 padding bytes")
                return None
            return decrypted[:-padding_length]
        except Exception as e:
            _LOGGER.error("Failed to decrypt message: %s", e)
            return None
    
    def encrypt(self, data: bytes) -> bytes | None:
        try:
            if self._cipher is None:
                return None
            
            # Add PKCS7 padding
            padding_length = 16 - (len(data) % 16)
            padded_data = data + bytes([padding_length] * padding_length)
            
            # Encrypt
            encryptor = self._cipher.encryptor()
            encrypted = encryptor.update(padded_data) + encryptor.finalize()
            return encrypted
        except Exception as e:
            _LOGGER.error("Failed to encrypt message: %s", e)
            return None
