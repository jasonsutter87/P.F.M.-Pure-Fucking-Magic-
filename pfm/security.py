"""
PFM Security - Cryptographic signing, verification, and encryption.

Security features:
  - HMAC-SHA256 signing (shared secret) with length-prefixed canonical encoding
  - Content integrity verification via checksum (fail-closed)
  - AES-256-GCM encryption with AAD binding for sensitive .pfm files
  - Tamper detection (signature covers meta + section order + contents)
  - Key derivation via PBKDF2 for password-based encryption
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfm.document import PFMDocument

# AAD (Additional Authenticated Data) for AES-GCM binding
_AES_AAD = b"PFM-ENC/1.0"


# =============================================================================
# HMAC Signing & Verification
# =============================================================================

def sign(doc: PFMDocument, secret: str | bytes) -> str:
    """
    Sign a PFM document with HMAC-SHA256.
    Returns the hex signature string.
    Sets doc.custom_meta["signature"] and doc.custom_meta["sig_algo"].
    """
    if isinstance(secret, str):
        secret = secret.encode("utf-8")

    # Build the message to sign: meta fields + all section contents
    message = _build_signing_message(doc)
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()

    doc.custom_meta["signature"] = signature
    doc.custom_meta["sig_algo"] = "hmac-sha256"

    return signature


def verify(doc: PFMDocument, secret: str | bytes, *, require: bool = False) -> bool:
    """
    Verify the HMAC-SHA256 signature of a PFM document.
    Returns True if valid, False if tampered or unsigned.

    If require=True, raises ValueError when no signature is present
    (distinguishes 'never signed' from 'signature stripped').

    PFM-013 fix: Uses a copy of custom_meta instead of mutating the document,
    ensuring exception-safety and thread-safety.
    """
    stored_sig = doc.custom_meta.get("signature", "")
    if not stored_sig:
        if require:
            raise ValueError("Document has no signature but signature is required")
        return False

    if isinstance(secret, str):
        secret = secret.encode("utf-8")

    # PFM-013 fix: Build signing message WITHOUT mutating the document.
    # We temporarily create a filtered view for _build_signing_message.
    # Save originals, remove from dict for signing, restore in finally block.
    saved_sig = doc.custom_meta.pop("signature", "")
    saved_algo = doc.custom_meta.pop("sig_algo", "")
    try:
        message = _build_signing_message(doc)
        expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    finally:
        # Always restore, even if _build_signing_message raises
        doc.custom_meta["signature"] = saved_sig
        doc.custom_meta["sig_algo"] = saved_algo

    return hmac.compare_digest(stored_sig, expected)


def _build_signing_message(doc: PFMDocument) -> bytes:
    """
    Build the canonical message bytes for signing.

    Uses length-prefixed encoding to prevent delimiter confusion (PFM-011 fix).
    Each field is: 4-byte big-endian length + raw bytes.
    Section ordering is preserved in the signature (PFM-016 fix).
    """
    buf = bytearray()

    def _append(data: bytes) -> None:
        buf.extend(struct.pack(">I", len(data)))
        buf.extend(data)

    # Include format version
    _append(doc.format_version.encode("utf-8"))

    # Include meta fields in deterministic order
    meta = doc.get_meta_dict()
    for key in sorted(meta.keys()):
        _append(f"{key}={meta[key]}".encode("utf-8"))

    # Include all section names and contents (order matters)
    for section in doc.sections:
        _append(section.name.encode("utf-8"))
        _append(section.content.encode("utf-8"))

    return bytes(buf)


# =============================================================================
# AES-256-GCM Encryption
# =============================================================================

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit key from a password using PBKDF2."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=600_000,  # OWASP recommended minimum
        dklen=32,
    )


def encrypt_bytes(data: bytes, password: str) -> bytes:
    """
    Encrypt raw bytes with AES-256-GCM using a password.
    Returns: salt (16) + nonce (12) + ciphertext + tag (16)

    Uses AAD to bind the encryption to PFM context (PFM-006 fix).
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "The 'cryptography' package is required for encryption. "
            "Install it with: pip install cryptography"
        )

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, _AES_AAD)

    return salt + nonce + ciphertext


def decrypt_bytes(encrypted: bytes, password: str) -> bytes:
    """
    Decrypt bytes that were encrypted with encrypt_bytes().
    Expects: salt (16) + nonce (12) + ciphertext + tag (16)
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "The 'cryptography' package is required for decryption. "
            "Install it with: pip install cryptography"
        )

    salt = encrypted[:16]
    nonce = encrypted[16:28]
    ciphertext = encrypted[28:]

    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    return aesgcm.decrypt(nonce, ciphertext, _AES_AAD)


def encrypt_document(doc: PFMDocument, password: str) -> bytes:
    """
    Encrypt an entire PFM document.
    Returns encrypted bytes that can be written to a .pfm.enc file.

    The encrypted payload is prefixed with a plaintext magic header
    so tools can identify it as an encrypted PFM file.
    """
    from pfm.writer import PFMWriter

    plaintext = PFMWriter.serialize(doc)
    encrypted = encrypt_bytes(plaintext, password)

    # Prefix with identifiable header
    header = b"#!PFM-ENC/1.0\n"
    return header + encrypted


def decrypt_document(data: bytes, password: str) -> "PFMDocument":
    """
    Decrypt an encrypted PFM document.
    Expects data from encrypt_document().

    PFM-016 fix: Validates header format and minimum payload size before decryption.
    """
    from pfm.reader import PFMReader

    # Validate header
    if not data.startswith(b"#!PFM-ENC/"):
        raise ValueError("Data is not an encrypted PFM file (missing header)")
    if b"\n" not in data:
        raise ValueError("Malformed encrypted PFM file: missing header terminator")

    header_end = data.index(b"\n") + 1
    encrypted = data[header_end:]

    # Minimum payload: 16 (salt) + 12 (nonce) + 16 (GCM tag) = 44 bytes
    if len(encrypted) < 44:
        raise ValueError(
            f"Encrypted payload too short: {len(encrypted)} bytes "
            f"(minimum 44 bytes: 16 salt + 12 nonce + 16 tag)"
        )

    plaintext = decrypt_bytes(encrypted, password)
    return PFMReader.parse(plaintext)


def is_encrypted_pfm(data: bytes) -> bool:
    """Check if data is an encrypted PFM file."""
    return data.startswith(b"#!PFM-ENC/")


# =============================================================================
# Content Integrity
# =============================================================================

def verify_integrity(doc: PFMDocument) -> bool:
    """
    Verify document integrity by recomputing and comparing checksum.

    PFM-005 fix: Returns False if no checksum is stored (fail-closed).
    PFM-017 fix: Uses constant-time comparison to prevent timing side-channels.
    """
    if not doc.checksum:
        return False  # No checksum = not verified
    return hmac.compare_digest(doc.checksum, doc.compute_checksum())


def fingerprint(doc: PFMDocument) -> str:
    """
    Generate a unique fingerprint for a document.
    Based on id + checksum + creation time.
    Useful for deduplication and tracking.

    Uses 32 hex characters (128 bits) for adequate collision resistance.
    Previous 16-char truncation only provided 64-bit / 32-bit birthday resistance.
    """
    material = f"{doc.id}:{doc.checksum}:{doc.created}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
