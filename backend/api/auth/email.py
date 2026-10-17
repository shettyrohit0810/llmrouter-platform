"""Email sending -- stub only, per the approved Phase 4 spec.

`EmailSender` is the interface every call site (password reset, email
verification) depends on; `ConsoleEmailSender` is Phase 4's only
implementation (logs instead of sending). A real provider (SES, Postmark,
SendGrid, ...) can be swapped in behind this same interface later without
changing any calling code.
"""

import logging
from typing import Protocol

logger = logging.getLogger("backend.auth.email")


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    """Logs the email instead of sending it. Sufficient for Phase 4's
    stubbed verification/reset flows; swap for a real provider in a later
    phase without touching backend/api/auth/service.py."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("Email to=%s subject=%r body=%r", to, subject, body)


_sender: EmailSender = ConsoleEmailSender()


def get_email_sender() -> EmailSender:
    return _sender
