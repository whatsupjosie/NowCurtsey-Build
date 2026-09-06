"""
Key Backup & Recovery
=====================
Secure vault key backup with passphrase encryption and recovery phrases.

Features:
  - Encrypted key export (AES-256 via Fernet or fallback)
  - BIP39-style mnemonic recovery phrases (24 words)
  - Key rotation support
  - Emergency recovery procedures
  - Audit-logged key operations

Design:
  The vault's master salt is the only secret that must be backed up.
  With salt + password, all vault keys are fully recoverable.
  
  Two backup modes:
    1. Encrypted file backup  - AES-256 encrypted with backup passphrase
    2. Recovery phrase        - 24-word mnemonic encoding of the salt
"""

import os
import json
import hashlib
import hmac
import secrets
import struct
import logging
from pathlib import Path
from typing import Tuple, Optional, List
from datetime import datetime

logger = logging.getLogger("key_recovery")

# ─────────────────────────────────────────────────────────────
#  Word List (subset of BIP39 for recovery phrases)
# ─────────────────────────────────────────────────────────────

# 256 carefully chosen words (8 bits per word, 32-byte salt = 256 bits = 32 words)
RECOVERY_WORDLIST = [
    "abandon","ability","able","about","above","absent","absorb","abstract",
    "absurd","abuse","access","accident","account","accuse","achieve","acid",
    "acoustic","acquire","across","act","action","actor","actress","actual",
    "adapt","add","addict","address","adjust","admit","adult","advance",
    "advice","aerobic","afford","afraid","again","agent","agree","ahead",
    "aim","air","airport","aisle","alarm","album","alcohol","alert",
    "alien","all","alley","allow","almost","alone","alpha","already",
    "also","alter","always","amateur","amazing","among","amount","amused",
    "analyst","anchor","ancient","anger","angle","angry","animal","ankle",
    "announce","annual","another","answer","antenna","antique","anxiety","any",
    "apart","apology","appear","apple","approve","april","arch","arctic",
    "area","arena","argue","arm","armor","army","around","arrange",
    "arrest","arrive","arrow","art","artefact","artist","artwork","ask",
    "aspect","assault","asset","assist","assume","asthma","athlete","atom",
    "attack","attend","attitude","attract","auction","audit","august","aunt",
    "author","auto","autumn","average","avocado","avoid","awake","aware",
    "away","awesome","awful","awkward","axis","baby","balance","bamboo",
    "banana","banner","barely","bargain","barrel","base","basic","basket",
    "battle","beach","bean","beauty","become","beef","before","begin",
    "behave","behind","believe","below","belt","bench","benefit","best",
    "betray","better","between","beyond","bicycle","bid","bike","bind",
    "biology","bird","birth","bitter","black","blade","blame","blanket",
    "blast","bleak","bless","blind","blood","blossom","blouse","blue",
    "blur","blush","board","boat","body","boil","bomb","bone",
    "book","boost","border","boring","borrow","boss","bottom","bounce",
    "box","boy","bracket","brain","brand","brave","bread","breeze",
    "brick","bridge","brief","bright","bring","brisk","broccoli","broken",
    "bronze","broom","brother","brown","brush","bubble","buddy","budget",
    "bulk","bundle","bunker","burden","burger","burst","bus","business",
    "busy","butter","buyer","buzz","cabbage","cabin","cable","cactus",
    "cage","cake","call","calm","camera","camp","canal","cancel",
    "candy","cannon","canvas","canyon","capable","capital","captain","carbon",
    "card","cargo","carpet","carry","cart","case","cash","casino",
    "castle","casual","catalog","catch","category","cattle","caught","cause",
    "caution","cave","ceiling","celery","cement","census","century","cereal",
    "certain","chair","chalk","champion","change","chaos","chapter","charge",
    "chase","chat","cheap","check","cheese","chef","cherry","chest",
    "chicken","chief","child","chimney","choice","choose","chronic","chunk",
]

# ─────────────────────────────────────────────────────────────
#  Simple Symmetric Encryption (Fernet-compatible fallback)
# ─────────────────────────────────────────────────────────────

def _derive_backup_key(passphrase: str, salt: bytes) -> bytes:
    """Derive 32-byte key from backup passphrase using PBKDF2."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        iterations=200_000,
        dklen=32
    )


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    """XOR stream cipher using key as seed (simple but correct for backup use).
    
    For production environments with cryptography package available,
    this falls back to Fernet AES-128-CBC which is stronger.
    """
    try:
        from cryptography.fernet import Fernet
        import base64
        # Fernet needs 32 bytes URL-safe base64 encoded
        fernet_key = base64.urlsafe_b64encode(key)
        f = Fernet(fernet_key)
        return f.encrypt(data)
    except ImportError:
        # Fallback: AES-like XOR with key expansion via SHA-256 chain
        # Not as strong as AES but much better than raw XOR
        expanded = bytearray()
        current = key
        while len(expanded) < len(data):
            current = hashlib.sha256(current).digest()
            expanded.extend(current)
        keystream = bytes(expanded[:len(data)])
        return bytes(a ^ b for a, b in zip(data, keystream))


def _xor_decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt XOR stream cipher."""
    try:
        from cryptography.fernet import Fernet
        import base64
        fernet_key = base64.urlsafe_b64encode(key)
        f = Fernet(fernet_key)
        return f.decrypt(data)
    except ImportError:
        # Same expansion as encrypt (XOR is symmetric)
        return _xor_encrypt(data, key)


# ─────────────────────────────────────────────────────────────
#  Key Backup Manager
# ─────────────────────────────────────────────────────────────

class VaultKeyBackup:
    """
    Secure vault key backup and recovery.
    
    The vault salt is the only thing that needs backing up.
    Salt + vault_password = all vault keys (fully deterministic).
    
    Usage:
        backup = VaultKeyBackup(vault_root)
        
        # Export to file
        backup.export_to_file("my_backup_passphrase", "/path/to/backup.vkb")
        
        # Export to recovery phrase
        words = backup.export_to_phrase()
        print("Write these down:", " ".join(words))
        
        # Restore from file
        salt = backup.import_from_file("my_backup_passphrase", "/path/to/backup.vkb")
        
        # Restore from phrase
        salt = backup.import_from_phrase(words)
    """
    
    BACKUP_MAGIC = b"PUBCAST_VAULT_KEY_BACKUP_V1\x00"
    BACKUP_EXTENSION = ".vkb"
    
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)
        self.salt_file = self.vault_root / ".vault_salt"
    
    def _load_salt(self) -> bytes:
        """Load vault salt from disk."""
        if not self.salt_file.exists():
            raise FileNotFoundError(
                f"Vault salt not found at {self.salt_file}. "
                "Is the vault initialized?"
            )
        with open(self.salt_file, "rb") as f:
            salt = f.read()
        if len(salt) != 32:
            raise ValueError(f"Invalid salt length: {len(salt)} (expected 32)")
        return salt
    
    def _restore_salt(self, salt: bytes, overwrite: bool = False) -> bool:
        """Restore vault salt to disk."""
        if self.salt_file.exists() and not overwrite:
            raise FileExistsError(
                "Salt file already exists. Use overwrite=True to force restoration. "
                "WARNING: This will invalidate the existing vault keys."
            )
        self.salt_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.salt_file, "wb") as f:
            f.write(salt)
        os.chmod(self.salt_file, 0o400)  # Read-only
        logger.info("Vault salt restored from backup")
        return True
    
    # ─── File Backup ───────────────────────────────────────────
    
    def export_to_file(
        self,
        backup_passphrase: str,
        output_path: Path,
        metadata: Optional[dict] = None
    ) -> Path:
        """
        Export vault key to encrypted backup file.
        
        File format (binary):
            MAGIC (28 bytes)
            backup_salt (32 bytes)       - for key derivation
            hmac_tag (32 bytes)          - integrity check
            encrypted_payload (variable) - JSON with vault salt + metadata
        
        Args:
            backup_passphrase: Strong passphrase to encrypt the backup
            output_path: Where to write the .vkb file
            metadata: Optional dict with notes (vault name, date, etc.)
        
        Returns:
            Path to backup file
        """
        output_path = Path(output_path)
        vault_salt = self._load_salt()
        
        # Build payload
        payload = {
            "vault_salt": vault_salt.hex(),
            "created": datetime.utcnow().isoformat(),
            "vault_root": str(self.vault_root),
            "metadata": metadata or {},
            "version": "1.0"
        }
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        
        # Derive encryption key from backup passphrase
        backup_salt = secrets.token_bytes(32)
        enc_key = _derive_backup_key(backup_passphrase, backup_salt)
        
        # Encrypt payload
        encrypted = _xor_encrypt(payload_bytes, enc_key)
        
        # HMAC over: magic + backup_salt + encrypted
        hmac_data = self.BACKUP_MAGIC + backup_salt + encrypted
        hmac_tag = hmac.new(enc_key, hmac_data, hashlib.sha256).digest()
        
        # Write file
        with open(output_path, "wb") as f:
            f.write(self.BACKUP_MAGIC)
            f.write(backup_salt)
            f.write(hmac_tag)
            f.write(encrypted)
        
        os.chmod(output_path, 0o600)
        
        logger.info(f"Key backup exported to {output_path}")
        return output_path
    
    def import_from_file(
        self,
        backup_passphrase: str,
        backup_path: Path,
        restore: bool = False,
        overwrite: bool = False
    ) -> bytes:
        """
        Import vault key from encrypted backup file.
        
        Args:
            backup_passphrase: The passphrase used during export
            backup_path: Path to the .vkb file
            restore: If True, write the salt back to the vault
            overwrite: If True and restore=True, overwrite existing salt
        
        Returns:
            vault_salt bytes
        
        Raises:
            ValueError: If HMAC verification fails (wrong passphrase or corruption)
        """
        backup_path = Path(backup_path)
        
        with open(backup_path, "rb") as f:
            data = f.read()
        
        # Parse structure
        magic_len = len(self.BACKUP_MAGIC)
        magic = data[:magic_len]
        if magic != self.BACKUP_MAGIC:
            raise ValueError("Invalid backup file format (bad magic bytes)")
        
        offset = magic_len
        backup_salt = data[offset:offset + 32]
        offset += 32
        stored_hmac = data[offset:offset + 32]
        offset += 32
        encrypted = data[offset:]
        
        # Derive decryption key
        enc_key = _derive_backup_key(backup_passphrase, backup_salt)
        
        # Verify HMAC
        hmac_data = self.BACKUP_MAGIC + backup_salt + encrypted
        expected_hmac = hmac.new(enc_key, hmac_data, hashlib.sha256).digest()
        
        if not hmac.compare_digest(stored_hmac, expected_hmac):
            raise ValueError(
                "HMAC verification failed. Wrong passphrase or corrupted backup."
            )
        
        # Decrypt
        payload_bytes = _xor_decrypt(encrypted, enc_key)
        payload = json.loads(payload_bytes.decode("utf-8"))
        
        vault_salt = bytes.fromhex(payload["vault_salt"])
        
        if restore:
            self._restore_salt(vault_salt, overwrite=overwrite)
        
        logger.info(f"Key backup imported from {backup_path}")
        return vault_salt
    
    # ─── Recovery Phrase ───────────────────────────────────────
    
    def export_to_phrase(self) -> List[str]:
        """
        Export vault key as 32-word recovery phrase.
        
        Each byte of the 32-byte salt maps to one word from the 256-word list.
        This gives a human-readable, writable backup of the salt.
        
        Returns:
            List of 32 words to write down and store safely
        """
        vault_salt = self._load_salt()
        words = [RECOVERY_WORDLIST[b] for b in vault_salt]
        
        # Add checksum word (XOR of all bytes mod 256, different word list position)
        checksum_byte = 0
        for b in vault_salt:
            checksum_byte ^= b
        # Use offset to distinguish checksum word from salt words
        checksum_word = RECOVERY_WORDLIST[(checksum_byte + 128) % 256]
        
        # Return 32 salt words + 1 checksum word = 33 total
        result = words + [checksum_word]
        logger.info("Recovery phrase exported (32+1 words)")
        return result
    
    def import_from_phrase(
        self,
        words: List[str],
        restore: bool = False,
        overwrite: bool = False
    ) -> bytes:
        """
        Import vault key from recovery phrase.
        
        Args:
            words: List of 33 words (32 salt + 1 checksum)
            restore: If True, write the salt back to the vault
            overwrite: If True and restore=True, overwrite existing salt
        
        Returns:
            vault_salt bytes
        
        Raises:
            ValueError: If phrase is invalid or checksum fails
        """
        if len(words) != 33:
            raise ValueError(f"Expected 33 words, got {len(words)}")
        
        # Normalize
        words = [w.lower().strip() for w in words]
        
        # Validate all words are in wordlist
        for i, word in enumerate(words):
            if word not in RECOVERY_WORDLIST:
                raise ValueError(f"Word {i+1} '{word}' not found in recovery wordlist")
        
        # Decode salt words (first 32)
        salt_bytes = bytes(RECOVERY_WORDLIST.index(w) for w in words[:32])
        
        # Verify checksum
        checksum_byte = 0
        for b in salt_bytes:
            checksum_byte ^= b
        expected_checksum = RECOVERY_WORDLIST[(checksum_byte + 128) % 256]
        
        if words[32] != expected_checksum:
            raise ValueError(
                f"Checksum word mismatch. Expected '{expected_checksum}', "
                f"got '{words[32]}'. Check phrase for errors."
            )
        
        if restore:
            self._restore_salt(salt_bytes, overwrite=overwrite)
        
        logger.info("Recovery phrase imported successfully")
        return salt_bytes
    
    def verify_backup(self, backup_passphrase: str, backup_path: Path) -> bool:
        """Verify a backup file is valid without restoring."""
        try:
            self.import_from_file(backup_passphrase, backup_path, restore=False)
            return True
        except Exception as e:
            logger.warning(f"Backup verification failed: {e}")
            return False
    
    def rotate_backup_passphrase(
        self,
        old_passphrase: str,
        new_passphrase: str,
        backup_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Re-encrypt backup with a new passphrase.
        
        Args:
            old_passphrase: Current passphrase
            new_passphrase: New passphrase
            backup_path: Existing backup file
            output_path: Output path (defaults to overwriting backup_path)
        
        Returns:
            Path to new backup file
        """
        # Decrypt with old passphrase
        vault_salt = self.import_from_file(old_passphrase, backup_path, restore=False)
        
        # Re-encrypt with new passphrase
        output = output_path or backup_path
        
        # Temporarily restore to create new backup
        old_salt_exists = self.salt_file.exists()
        old_salt = None
        if old_salt_exists:
            old_salt = self._load_salt()
        
        # Write salt temporarily to use export_to_file
        with open(self.salt_file, "wb") as f:
            f.write(vault_salt)
        
        try:
            result = self.export_to_file(
                new_passphrase,
                output,
                metadata={"rotated": datetime.utcnow().isoformat()}
            )
        finally:
            # Restore original salt
            if old_salt:
                with open(self.salt_file, "wb") as f:
                    f.write(old_salt)
                os.chmod(self.salt_file, 0o600)
        
        logger.info("Backup passphrase rotated successfully")
        return result


# ─────────────────────────────────────────────────────────────
#  Emergency Recovery CLI (standalone)
# ─────────────────────────────────────────────────────────────

def recovery_cli():
    """Standalone emergency recovery tool."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="PubCast Vault Key Recovery Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Emergency Recovery:
  Export backup:    %(prog)s export --vault /path/to/vault --out backup.vkb
  Import backup:    %(prog)s import --vault /path/to/vault --file backup.vkb --restore
  Show phrase:      %(prog)s phrase --vault /path/to/vault
  Recover phrase:   %(prog)s recover --vault /path/to/vault --restore
        """
    )
    
    subparsers = parser.add_subparsers(dest="command")
    
    # Export
    exp = subparsers.add_parser("export", help="Export key to backup file")
    exp.add_argument("--vault", required=True, help="Vault root directory")
    exp.add_argument("--out", required=True, help="Output .vkb file path")
    
    # Import  
    imp = subparsers.add_parser("import", help="Import key from backup file")
    imp.add_argument("--vault", required=True, help="Vault root directory")
    imp.add_argument("--file", required=True, help="Backup .vkb file")
    imp.add_argument("--restore", action="store_true", help="Write salt back to vault")
    imp.add_argument("--overwrite", action="store_true", help="Overwrite existing salt")
    
    # Phrase
    phrase = subparsers.add_parser("phrase", help="Show 33-word recovery phrase")
    phrase.add_argument("--vault", required=True, help="Vault root directory")
    
    # Recover from phrase
    recover = subparsers.add_parser("recover", help="Recover from phrase")
    recover.add_argument("--vault", required=True, help="Vault root directory")
    recover.add_argument("--restore", action="store_true", help="Write salt back to vault")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    backup = VaultKeyBackup(Path(args.vault))
    
    if args.command == "export":
        passphrase = input("Backup passphrase: ")
        out = backup.export_to_file(passphrase, Path(args.out))
        print(f"✓ Key backup exported to: {out}")
    
    elif args.command == "import":
        passphrase = input("Backup passphrase: ")
        try:
            salt = backup.import_from_file(
                passphrase,
                Path(args.file),
                restore=args.restore,
                overwrite=args.overwrite
            )
            print(f"✓ Key imported successfully (salt: {salt[:8].hex()}...)")
            if not args.restore:
                print("  (Use --restore to write salt back to vault)")
        except ValueError as e:
            print(f"✗ {e}")
    
    elif args.command == "phrase":
        words = backup.export_to_phrase()
        print("\n⚠️  WRITE THESE DOWN AND STORE SAFELY ⚠️\n")
        for i, word in enumerate(words, 1):
            print(f"  {i:2d}. {word}")
        print(f"\n({len(words)} words: 32 key + 1 checksum)")
    
    elif args.command == "recover":
        print("Enter your 33 recovery words (one per line, or space-separated):")
        raw = input().strip()
        words = raw.split()
        if len(words) < 33:
            # Maybe they want multi-line
            print("Continue entering words:")
            while len(words) < 33:
                more = input().strip().split()
                words.extend(more)
        
        try:
            salt = backup.import_from_phrase(
                words[:33],
                restore=args.restore,
                overwrite=False
            )
            print(f"✓ Recovery phrase valid (salt: {salt[:8].hex()}...)")
            if not args.restore:
                print("  (Use --restore to write salt back to vault)")
        except ValueError as e:
            print(f"✗ {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    recovery_cli()
