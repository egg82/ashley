"""Controls: the fake Bridge the suite rests on answers as IMAP and SMTP clients expect, driven here by the standard
library's own clients (`imaplib`, `smtplib`) with no `ashley` code between, so a green result from it means something."""

import imaplib
import smtplib
import socket
import ssl
from collections.abc import Generator

import pytest
from mail_proton_blind_bridge_support import FakeBridge
from mail_proton_blind_store_support import Account, compose, when

ME = "me@proton.test"
PW = "bridge-password"


def insecure() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


@pytest.fixture
def bridge() -> Generator[FakeBridge]:
    fake = FakeBridge()
    yield fake
    fake.stop()


@pytest.fixture
def stocked(bridge: FakeBridge) -> Generator[Account]:
    account = bridge.account(ME)
    account.seed("INBOX", compose("Trip money", "Pat <pat@school.test>", ME, when(3, 1), "bring ten dollars",
                                  message_id="<a1@school.test>"), labels=("School",), unread=True, when=when(3, 1))
    account.seed("INBOX", compose("Lunch menu", "Bob <bob@cafe.test>", ME, when(3, 5), "soup",
                                  message_id="<a2@cafe.test>", attachments=(("menu.pdf", "application/pdf", b"%PDF-x"),)),
                 when=when(3, 5))
    account.seed("Sent", compose("Re: Trip money", ME, "pat@school.test", when(3, 2), "ok", message_id="<a3@proton.test>"),
                 when=when(3, 2))
    yield account


def imap(bridge: FakeBridge) -> imaplib.IMAP4:
    client = imaplib.IMAP4("127.0.0.1", bridge.imap_port)
    assert client.login(ME, PW)[0] == "OK"
    return client


def uids(client: imaplib.IMAP4, *criteria: str) -> list[int]:
    typ, got = client.uid("SEARCH", *criteria)
    assert typ == "OK"
    return [int(x) for x in (got[0] or b"").split()]


def test_a_login_with_the_wrong_password_or_user_is_refused(bridge: FakeBridge, stocked: Account) -> None:
    client = imaplib.IMAP4("127.0.0.1", bridge.imap_port)
    with pytest.raises(imaplib.IMAP4.error):
        client.login(ME, "nope")
    with pytest.raises(imaplib.IMAP4.error):
        client.login("other@proton.test", PW)
    assert stocked.logins == 0


def test_list_names_folders_labels_and_all_mail(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    typ, listed = client.list()
    names = [line.decode().rsplit('"/" ', 1)[1].strip('"') for line in listed if isinstance(line, bytes)]
    assert typ == "OK" and {"INBOX", "Drafts", "Sent", "Archive", "Spam", "Trash", "All Mail", "Labels/School"} <= set(names)


def test_search_keys_filter_as_rfc_3501_says(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    client.select("INBOX")
    assert len(uids(client, "ALL")) == 2
    assert len(uids(client, "UNSEEN")) == 1 and len(uids(client, "SEEN")) == 1
    assert len(uids(client, "FROM", "pat")) == 1 and len(uids(client, "SUBJECT", "LUNCH")) == 1
    assert len(uids(client, "SINCE", "03-Mar-2026")) == 1 and len(uids(client, "BEFORE", "03-Mar-2026")) == 1
    assert len(uids(client, "TEXT", "\"ten dollars\"")) == 1 and len(uids(client, "BODY", "soup")) == 1
    assert len(uids(client, "OR", "FROM", "pat", "FROM", "bob")) == 2 and len(uids(client, "NOT", "FROM", "pat")) == 1
    assert len(uids(client, "HEADER", "Message-ID", "a2@cafe.test")) == 1 and uids(client, "FROM", "nobody") == []
    assert len(uids(client, "UNSEEN", "FROM", "pat")) == 1 and uids(client, "UNSEEN", "FROM", "bob") == []


def test_a_search_with_a_utf8_literal_works(bridge: FakeBridge, stocked: Account) -> None:
    stocked.seed("INBOX", compose("Café plans", "Zoë <zoe@x.test>", ME, when(3, 6), "crème brûlée",
                                  message_id="<a4@x.test>"))
    with socket.create_connection(("127.0.0.1", bridge.imap_port)) as raw:
        wire = raw.makefile("rwb")

        def say(data: bytes, until: bytes) -> bytes:
            wire.write(data)
            wire.flush()
            out = b""
            while until not in out:
                out += wire.readline()
            return out

        say(b"", b"* OK")
        say(f"a1 LOGIN {ME} {PW}\r\n".encode(), b"a1 OK")
        say(b"a2 SELECT INBOX\r\n", b"a2 OK")
        assert say(b"a3 UID SEARCH CHARSET UTF-8 SUBJECT {5}\r\n", b"+ ready")
        got = say("Café\r\n".encode(), b"a3 OK")
    assert b"* SEARCH 3\r\n" in got


def test_fetch_items_render_from_the_message(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    client.select("INBOX")
    (uid,) = uids(client, "HEADER", "Message-ID", "a2@cafe.test")
    typ, got = client.uid("FETCH", str(uid), "(UID FLAGS RFC822.SIZE ENVELOPE BODYSTRUCTURE "
                                             "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
    assert typ == "OK"
    flat = b" ".join(x if isinstance(x, bytes) else b"".join(x) for x in got if x)
    assert b"Bob" in flat and b"Lunch menu" in flat and b"menu.pdf" in flat and b"MIXED" in flat and b"<a2@cafe.test>" in flat
    typ, got = client.uid("FETCH", str(uid), "(BODY.PEEK[1])")
    assert isinstance(got[0], tuple) and b"soup" in got[0][1]


def test_peek_leaves_unread_and_a_plain_body_fetch_marks_read(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    client.select("INBOX")
    (uid,) = uids(client, "UNSEEN")
    client.uid("FETCH", str(uid), "(BODY.PEEK[])")
    assert stocked.unread("<a1@school.test>") is True
    client.uid("FETCH", str(uid), "(BODY[])")
    assert stocked.unread("<a1@school.test>") is False


def test_a_flag_is_the_messages_in_every_copy_and_deleted_is_a_copys_own(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    client.select("Labels/School")
    (uid,) = uids(client, "ALL")
    client.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Seen)")
    assert stocked.unread("<a1@school.test>") is False
    client.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
    client.expunge()
    assert stocked.where("<a1@school.test>") == ["INBOX"]


def test_copy_move_and_append_change_the_mailboxes(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    client.select("INBOX")
    (uid,) = uids(client, "HEADER", "Message-ID", "a2@cafe.test")
    assert client.uid("COPY", str(uid), "Labels/School")[0] == "OK"
    assert stocked.where("<a2@cafe.test>") == ["INBOX", "Labels/School"]
    assert client.uid("MOVE", str(uid), "Archive")[0] == "OK"
    assert stocked.where("<a2@cafe.test>") == ["Archive", "Labels/School"]
    raw = compose("Draft one", ME, "pat@school.test", when(3, 7), "hello", message_id="<d1@proton.test>")
    assert client.append("Drafts", "(\\Draft)", None, raw)[0] == "OK"
    assert stocked.where("<d1@proton.test>") == ["Drafts"]
    assert imap(bridge).select("Nope")[0] == "NO"


def test_all_mail_holds_each_message_once_and_not_spam_or_trash(bridge: FakeBridge, stocked: Account) -> None:
    stocked.seed("Trash", compose("Old", "x@y.test", ME, when(2, 1), "gone", message_id="<t1@y.test>"))
    client = imap(bridge)
    client.select('"All Mail"')
    assert len(uids(client, "ALL")) == 3


def test_a_resync_renumbers_every_uid_and_the_validity_but_keeps_the_messages(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    client.select("INBOX")
    before = uids(client, "ALL")
    stocked.renumber()
    client = imap(bridge)
    client.select("INBOX")
    after = uids(client, "ALL")
    assert sorted(before) != sorted(after) and len(after) == 2 and not set(before) & set(after)
    assert stocked.where("<a1@school.test>") == ["INBOX", "Labels/School"]


def test_commands_that_change_state_are_recorded_and_reads_are_not(bridge: FakeBridge, stocked: Account) -> None:
    client = imap(bridge)
    client.select("INBOX")
    uids(client, "ALL")
    client.uid("FETCH", "1:*", "(FLAGS)")
    assert stocked.commands == []
    client.create("Labels/New")
    assert stocked.commands == [("CREATE", "Labels/New")]


def test_a_connection_can_be_dropped_at_a_command_and_the_greeting_replaced(bridge: FakeBridge, stocked: Account) -> None:
    bridge.imap_behaviour.drop_on = "LOGIN"
    client = imaplib.IMAP4("127.0.0.1", bridge.imap_port)
    with pytest.raises((imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError)):
        client.login(ME, PW)
    bridge.imap_behaviour.drop_on, bridge.imap_behaviour.greeting = None, "HTTP/1.1 400 Bad Request"
    with pytest.raises((imaplib.IMAP4.error, OSError)):
        imaplib.IMAP4("127.0.0.1", bridge.imap_port)


@pytest.mark.parametrize("tls", ["implicit", "starttls"])
def test_imap_and_smtp_can_be_served_over_tls(tls: str) -> None:
    secure = FakeBridge(tls)
    try:
        secure.account(ME)
        if tls == "implicit":
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL("127.0.0.1", secure.imap_port, ssl_context=insecure())
            mail: smtplib.SMTP = smtplib.SMTP_SSL("127.0.0.1", secure.smtp_port, context=insecure())
        else:
            client = imaplib.IMAP4("127.0.0.1", secure.imap_port)
            with pytest.raises(imaplib.IMAP4.error):
                client.login(ME, PW)
            client.starttls(insecure())
            mail = smtplib.SMTP("127.0.0.1", secure.smtp_port)
            mail.starttls(context=insecure())
        assert client.login(ME, PW)[0] == "OK"
        mail.login(ME, PW)
        mail.sendmail(ME, ["a@b.test"], "Subject: hi\r\n\r\nbody\r\n")
        mail.quit()
        assert len(secure.smtp.delivered) == 1
    finally:
        secure.stop()


def test_smtp_records_the_envelope_and_saves_a_copy_in_sent(bridge: FakeBridge, stocked: Account) -> None:
    with smtplib.SMTP("127.0.0.1", bridge.smtp_port) as mail:
        mail.login(ME, PW)
        mail.sendmail(ME, ["a@b.test", "c@d.test"], "Subject: hi\r\nMessage-ID: <s1@x>\r\n\r\n.dot line\r\n")
    (done,) = bridge.smtp.delivered
    assert (done.user, done.mail_from, done.rcpts) == (ME, ME, ["a@b.test", "c@d.test"])
    assert b".dot line" in done.data and stocked.where("<s1@x>") == ["Sent"]


def test_smtp_refuses_what_it_is_told_to_and_needs_a_login(bridge: FakeBridge, stocked: Account) -> None:
    bridge.smtp_behaviour.refuse_rcpt = {"bad@b.test"}
    with smtplib.SMTP("127.0.0.1", bridge.smtp_port) as mail:
        with pytest.raises(smtplib.SMTPSenderRefused):
            mail.sendmail(ME, ["a@b.test"], "Subject: x\r\n\r\ny")
        with pytest.raises(smtplib.SMTPAuthenticationError):
            mail.login(ME, "wrong")
        mail.login(ME, PW)
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            mail.sendmail(ME, ["bad@b.test"], "Subject: x\r\n\r\ny")
    assert bridge.smtp.delivered == []


def test_a_data_failure_and_a_dropped_connection_are_counted_as_one_attempt_each(bridge: FakeBridge, stocked: Account) -> None:
    bridge.smtp_behaviour.data_code = 451
    with smtplib.SMTP("127.0.0.1", bridge.smtp_port) as mail:
        mail.login(ME, PW)
        with pytest.raises(smtplib.SMTPDataError):
            mail.sendmail(ME, ["a@b.test"], "Subject: x\r\n\r\ny")
    bridge.smtp_behaviour.data_code, bridge.smtp_behaviour.drop_after_data = 250, True
    with smtplib.SMTP("127.0.0.1", bridge.smtp_port) as mail:
        mail.login(ME, PW)
        with pytest.raises(smtplib.SMTPServerDisconnected):
            mail.sendmail(ME, ["a@b.test"], "Subject: x\r\n\r\ny")
    assert bridge.smtp.attempts == 2 and bridge.smtp.delivered == []
