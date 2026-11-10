"""Sending through Bridge's SMTP: STARTTLS under the pinned certificate (`proton_endpoint`), then the account's address
and Bridge password. A message is handed over once, to the first host that accepts a connection, and never again: a
refusal by the server is `refused`, a rejected login `needs_reconnect`, and anything that goes wrong once the message
has begun to go (a timeout, a dropped connection) is `unreachable`, which leaves open whether it went."""

import smtplib
import ssl
from collections.abc import Sequence

from . import proton_endpoint
from .model import MailFailed


def send(login: proton_endpoint.Login, recipients: Sequence[str], message: bytes, timeout_s: float) -> None:
    """Raises MailFailed."""
    for host in login.hosts:
        try:
            smtp = smtplib.SMTP(host, login.smtp_port, timeout=timeout_s)
        except OSError:
            continue
        try:
            _deliver(smtp, login, recipients, message)
        finally:
            try:
                smtp.close()
            except OSError:
                pass
        return
    raise MailFailed("unreachable")


def _deliver(smtp: smtplib.SMTP, login: proton_endpoint.Login, recipients: Sequence[str], message: bytes) -> None:
    try:
        smtp.ehlo()
        smtp.starttls(context=proton_endpoint.context())
        if smtp.sock is None:
            raise MailFailed("unreachable")
        proton_endpoint.pinned(smtp.sock, login.fingerprint)
        smtp.ehlo()
        smtp.login(login.address, login.password)
        smtp.sendmail(login.address, list(recipients), message)
    except smtplib.SMTPAuthenticationError as e:
        raise MailFailed("needs_reconnect") from e
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError, smtplib.SMTPHeloError,
            smtplib.SMTPNotSupportedError) as e:
        raise MailFailed("refused") from e
    except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
        raise MailFailed("unreachable") from e
