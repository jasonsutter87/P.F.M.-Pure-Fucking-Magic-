"""
Security Tests - Signing, verification, encryption, integrity.
"""

import pytest

from pfm.document import PFMDocument
from pfm.security import (
    sign,
    verify,
    verify_integrity,
    fingerprint,
)


class TestSigning:

    def test_sign_and_verify(self):
        doc = PFMDocument.create(agent="secure-agent")
        doc.add_section("content", "sensitive data")

        sig = sign(doc, "my-secret-key")
        assert sig  # Non-empty
        assert doc.custom_meta["signature"] == sig
        assert doc.custom_meta["sig_algo"] == "hmac-sha256"

        assert verify(doc, "my-secret-key") is True

    def test_verify_wrong_key(self):
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "data")

        sign(doc, "correct-key")
        assert verify(doc, "wrong-key") is False

    def test_verify_tampered_content(self):
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "original")

        sign(doc, "key")

        # Tamper with content
        doc.sections[0].content = "tampered"
        assert verify(doc, "key") is False

    def test_verify_tampered_meta(self):
        doc = PFMDocument.create(agent="original-agent")
        doc.add_section("content", "data")

        sign(doc, "key")

        # Tamper with meta
        doc.agent = "evil-agent"
        assert verify(doc, "key") is False

    def test_verify_unsigned(self):
        doc = PFMDocument.create()
        doc.add_section("content", "unsigned")
        assert verify(doc, "any-key") is False

    def test_sign_preserves_through_write_read(self):
        """Sign, write, read back, verify.

        Important: compute checksum before signing, since write() updates
        the checksum which would invalidate a signature computed earlier.
        """
        import tempfile
        from pathlib import Path
        from pfm.reader import PFMReader
        from pfm.writer import PFMWriter

        doc = PFMDocument.create(agent="persist-test")
        doc.add_section("content", "persistent security")

        # Compute checksum first (writer does this too, but we need it stable before signing)
        doc.checksum = doc.compute_checksum()
        sign(doc, "persist-key")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        # Write raw bytes (serialize already computed, checksum matches)
        data = PFMWriter.serialize(doc)
        Path(path).write_bytes(data)

        loaded = PFMReader.read(path)

        assert verify(loaded, "persist-key") is True
        assert verify(loaded, "wrong-key") is False

        Path(path).unlink()

    def test_sign_with_bytes_key(self):
        doc = PFMDocument.create()
        doc.add_section("content", "bytes key test")

        sign(doc, b"\x00\x01\x02\x03")
        assert verify(doc, b"\x00\x01\x02\x03") is True


class TestEncryption:
    """Tests require the `cryptography` package."""

    @pytest.fixture(autouse=True)
    def check_cryptography(self):
        try:
            import cryptography
        except ImportError:
            pytest.skip("cryptography package not installed")

    def test_encrypt_decrypt_bytes(self):
        from pfm.security import encrypt_bytes, decrypt_bytes

        data = b"hello encrypted world"
        password = "strong-password-123"

        encrypted = encrypt_bytes(data, password)
        assert encrypted != data
        assert len(encrypted) > len(data)

        decrypted = decrypt_bytes(encrypted, password)
        assert decrypted == data

    def test_encrypt_decrypt_wrong_password(self):
        from pfm.security import encrypt_bytes, decrypt_bytes

        encrypted = encrypt_bytes(b"secret", "right-password")

        with pytest.raises(Exception):  # InvalidTag from AES-GCM
            decrypt_bytes(encrypted, "wrong-password")

    def test_encrypt_decrypt_document(self):
        from pfm.security import encrypt_document, decrypt_document, is_encrypted_pfm

        doc = PFMDocument.create(agent="encrypted-agent")
        doc.add_section("content", "top secret content")
        doc.add_section("chain", "classified chain")

        password = "ultra-secret-2024"
        encrypted = encrypt_document(doc, password)

        # Should be identifiable
        assert is_encrypted_pfm(encrypted)
        assert encrypted.startswith(b"#!PFM-ENC/1.0\n")

        # Should not contain plaintext
        assert b"top secret content" not in encrypted
        assert b"classified chain" not in encrypted
        assert b"encrypted-agent" not in encrypted

        # Should decrypt back
        decrypted = decrypt_document(encrypted, password)
        assert decrypted.agent == "encrypted-agent"
        assert decrypted.content == "top secret content"
        assert decrypted.chain == "classified chain"

    def test_encrypted_file_roundtrip(self):
        import tempfile
        from pathlib import Path
        from pfm.security import encrypt_document, decrypt_document

        doc = PFMDocument.create(agent="file-enc")
        doc.add_section("content", "file-level encryption")

        encrypted = encrypt_document(doc, "file-password")

        with tempfile.NamedTemporaryFile(suffix=".pfm.enc", delete=False) as f:
            f.write(encrypted)
            path = f.name

        loaded_bytes = Path(path).read_bytes()
        decrypted = decrypt_document(loaded_bytes, "file-password")
        assert decrypted.content == "file-level encryption"

        Path(path).unlink()

    def test_each_encryption_unique(self):
        """Same plaintext + password should produce different ciphertext (random salt/nonce)."""
        from pfm.security import encrypt_bytes

        data = b"same data"
        enc1 = encrypt_bytes(data, "same-password")
        enc2 = encrypt_bytes(data, "same-password")
        assert enc1 != enc2  # Different salt/nonce each time


class TestIntegrity:

    def test_verify_integrity_valid(self):
        doc = PFMDocument.create()
        doc.add_section("content", "intact")
        doc.checksum = doc.compute_checksum()

        assert verify_integrity(doc) is True

    def test_verify_integrity_tampered(self):
        doc = PFMDocument.create()
        doc.add_section("content", "original")
        doc.checksum = doc.compute_checksum()

        doc.sections[0].content = "tampered"
        assert verify_integrity(doc) is False

    def test_verify_integrity_no_checksum(self):
        doc = PFMDocument.create()
        doc.add_section("content", "no checksum")
        assert verify_integrity(doc) is True


class TestFingerprint:

    def test_fingerprint_stable(self):
        doc = PFMDocument.create()
        doc.add_section("content", "data")
        doc.checksum = doc.compute_checksum()

        fp1 = fingerprint(doc)
        fp2 = fingerprint(doc)
        assert fp1 == fp2
        assert len(fp1) == 16  # 16 hex chars

    def test_fingerprint_different_docs(self):
        doc1 = PFMDocument.create()
        doc1.add_section("content", "a")
        doc1.checksum = doc1.compute_checksum()

        doc2 = PFMDocument.create()
        doc2.add_section("content", "b")
        doc2.checksum = doc2.compute_checksum()

        assert fingerprint(doc1) != fingerprint(doc2)
