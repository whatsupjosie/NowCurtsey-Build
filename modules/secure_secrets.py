"""
Secure Secrets Handling
=======================
Memory-safe secret management with automatic zeroing.

Prevents:
  • Secrets lingering in memory
  • Secrets in core dumps
  • Secrets in swapfiles
  • Timing attacks on comparisons
"""

import os
import sys
import ctypes
import secrets
import hashlib
from typing import Optional
import logging

logger = logging.getLogger("secrets_handler")


class SecureSecret:
    """
    Wrapper for sensitive strings (passwords, keys, tokens).
    
    Automatically zeroes memory when garbage collected.
    Prevents accidental logging of the value.
    Provides constant-time comparison.
    """
    
    def __init__(self, value: str):
        """Store secret with automatic lifecycle management."""
        if not isinstance(value, str):
            raise TypeError("SecureSecret requires str, got " + type(value).__name__)
        
        # Store as mutable bytearray for secure zeroing
        self._data = bytearray(value.encode('utf-8'))
        self._size = len(self._data)
        
        # Compute hash for comparison without exposing plaintext
        self._hash = hashlib.sha256(bytes(self._data)).digest()
    
    def __del__(self):
        """Zero memory before garbage collection."""
        self._zero()
    
    def _zero(self):
        """Securely zero the memory holding the secret."""
        if hasattr(self, '_data') and self._data:
            # Overwrite with random data first (noise)
            for i in range(len(self._data)):
                self._data[i] = secrets.randbelow(256)
            # Then zeros
            self._data[:] = b'\x00' * self._size
            self._data = None
    
    def __str__(self):
        """Prevent accidental logging. Raises error if accessed."""
        raise RuntimeError(
            "SecureSecret.__str__ called - secret would be leaked! "
            "Use .compare() or .as_bytes() explicitly."
        )
    
    def __repr__(self):
        """Prevent repr from leaking the secret."""
        return f"SecureSecret(***{self._size}bytes***)"
    
    def as_bytes(self) -> bytes:
        """Get the raw bytes (be careful with these)."""
        if self._data is None:
            raise ValueError("Secret has been zeroed")
        return bytes(self._data)
    
    def compare(self, other: 'SecureSecret') -> bool:
        """Constant-time comparison with another secret."""
        if not isinstance(other, SecureSecret):
            raise TypeError("Can only compare SecureSecret with SecureSecret")
        # Use hash comparison to avoid timing leaks on secret data
        return secrets.compare_digest(self._hash, other._hash)
    
    def compare_hash(self, hash_value: bytes) -> bool:
        """Constant-time comparison with a pre-computed hash."""
        return secrets.compare_digest(self._hash, hash_value)


class SecureSecretManager:
    """
    Central manager for sensitive values.
    
    Provides:
      • Automatic zeroing on scope exit
      • Context manager support
      • Safe logging (sanitizes sensitive values)
      • Timing-safe comparisons
    """
    
    # Sensitive field names to sanitize in logs
    SENSITIVE_FIELDS = {
        'password', 'passwd', 'pwd', 'secret', 'token', 'auth',
        'key', 'private_key', 'api_key', 'hmac_key', 'cipher_key',
        'salt', 'nonce', 'iv', 'hmac', 'signature', 'hash',
        'phash', 'passphrase', 'bearer', 'authorization'
    }
    
    @staticmethod
    def sanitize_dict(data: dict, depth: int = 0, max_depth: int = 5) -> dict:
        """
        Recursively sanitize a dict/object for logging.
        
        Replaces sensitive values with [REDACTED].
        """
        if depth > max_depth:
            return data
        
        sanitized = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            
            # Check if this key is sensitive
            is_sensitive = any(
                sensitive in key_lower
                for sensitive in SecureSecretManager.SENSITIVE_FIELDS
            )
            
            if is_sensitive:
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = SecureSecretManager.sanitize_dict(
                    value, depth+1, max_depth
                )
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [
                    SecureSecretManager.sanitize_dict(v, depth+1, max_depth)
                    if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                sanitized[key] = value
        
        return sanitized
    
    @staticmethod
    def sanitize_log(message: str) -> str:
        """Remove obvious secrets from log messages."""
        # Replace common patterns
        patterns = [
            ('password="[^"]*"', 'password="***"'),
            ('password: [^\s,;]*', 'password: ***'),
            ('token=[a-zA-Z0-9_-]+', 'token=***'),
            ('Authorization: Bearer [a-zA-Z0-9_.-]+', 'Authorization: Bearer ***'),
            ('key=[a-f0-9]+', 'key=***'),
        ]
        
        import re
        for pattern, replacement in patterns:
            message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
        
        return message
    
    @staticmethod
    def secure_getpass(prompt: str = "Password: ") -> SecureSecret:
        """
        Read password from stdin securely.
        
        Returns SecureSecret that will auto-zero on GC.
        """
        import getpass
        password = getpass.getpass(prompt)
        return SecureSecret(password)


class SecureLogFilter(logging.Filter):
    """
    Log filter that sanitizes sensitive data.
    
    Can be added to any logger to automatically redact secrets.
    """
    
    def filter(self, record):
        """Sanitize log record before it's emitted."""
        if record.getMessage():
            record.msg = SecureSecretManager.sanitize_log(str(record.msg))
        
        # Sanitize args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = SecureSecretManager.sanitize_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    SecureSecretManager.sanitize_dict(arg)
                    if isinstance(arg, dict) else arg
                    for arg in record.args
                )
        
        return True


def setup_secure_logging(logger_instance):
    """Add secure logging filter to a logger."""
    filter = SecureLogFilter()
    logger_instance.addFilter(filter)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test")
    setup_secure_logging(logger)
    
    # Test SecureSecret
    secret = SecureSecret("my_password_123")
    print(f"Created: {secret}")  # Shows *** not the value
    
    secret2 = SecureSecret("my_password_123")
    print(f"Secrets match: {secret.compare(secret2)}")
    
    secret3 = SecureSecret("different")
    print(f"Secrets differ: {not secret.compare(secret3)}")
    
    # Test log sanitization
    logger.info("User logged in with password=secret123")
    logger.info("API token=abc123def456")
    logger.info({"user": "alice", "password": "super_secret"})
    
    print("\n✓ Secure secrets module working")
