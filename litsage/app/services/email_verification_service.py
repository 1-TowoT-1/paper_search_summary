import secrets
from datetime import UTC, datetime, timedelta


class EmailVerificationService:
    _codes: dict[str, tuple[str, datetime]] = {}
    _ttl_minutes = 10

    def create_code(self, email: str) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.now(UTC) + timedelta(minutes=self._ttl_minutes)
        self._codes[self._normalize(email)] = (code, expires_at)
        return code

    def verify_code(self, email: str, code: str) -> bool:
        key = self._normalize(email)
        stored = self._codes.get(key)
        if not stored:
            return False

        expected_code, expires_at = stored
        if datetime.now(UTC) > expires_at:
            self._codes.pop(key, None)
            return False

        if secrets.compare_digest(expected_code, code.strip()):
            self._codes.pop(key, None)
            return True
        return False

    def _normalize(self, email: str) -> str:
        return email.strip().lower()


email_verification_service = EmailVerificationService()
