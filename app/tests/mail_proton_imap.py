"""The fake Bridge's IMAP side: the commands `imaplib` sends, answered from `Bridge`. Part of `mail_proton_support`, which
says what is unverified."""

import re
import ssl
from datetime import datetime
from email import policy
from email.parser import BytesParser
from typing import Any

from ashley.mail import imap_names
from mail_proton_state import Bridge, Stored, Wire


def _header(raw: bytes, name: str) -> str:
    return str(BytesParser(policy=policy.default).parsebytes(raw).get(name, ""))


def _fields(raw: bytes, names: list[str]) -> bytes:
    head = raw.split(b"\r\n\r\n", 1)[0].decode("utf-8", "replace")
    kept: list[str] = []
    keep = False
    for line in head.split("\r\n"):
        if line[:1] not in (" ", "\t"):
            keep = line.split(":", 1)[0].lower() in names
        if keep:
            kept.append(line)
    return ("\r\n".join(kept) + "\r\n\r\n").encode()


def _day(text: str) -> Any:
    return datetime.strptime(text, "%d-%b-%Y").date()


def _matches(item: Stored, criteria: list[str]) -> bool:
    i = 0
    while i < len(criteria):
        key = criteria[i].upper()
        if key in ("ALL", "CHARSET"):
            i += 2 if key == "CHARSET" else 1
        elif key in ("SEEN", "UNSEEN"):
            if ("\\seen" in {f.lower() for f in item.flags}) != (key == "SEEN"):
                return False
            i += 1
        elif key in ("SINCE", "BEFORE"):
            when = datetime.strptime(item.received, "%d-%b-%Y %H:%M:%S %z").date()
            if (when < _day(criteria[i + 1])) if key == "SINCE" else (when >= _day(criteria[i + 1])):
                return False
            i += 2
        elif key == "HEADER":
            if criteria[i + 2].lower() not in _header(item.raw, criteria[i + 1]).lower():
                return False
            i += 3
        else:
            text = item.raw.decode("utf-8", "replace") if key == "TEXT" else _header(item.raw, key.title())
            if criteria[i + 1].lower() not in text.lower():
                return False
            i += 2
    return True


def _tokens(line: str, literals: list[bytes]) -> list[str]:
    found = re.findall(r'"((?:[^"\\]|\\.)*)"|\x00LIT(\d+)\x00|([^\s"]+)', line)
    return [re.sub(r"\\(.)", r"\1", q) if q or (not n and not a) else literals[int(n)].decode() if n else a
            for q, n, a in found]


def _uids(spec: str) -> set[int]:
    return {int(u) for u in spec.split(",") if u.isdigit()}


class ImapSide:
    def __init__(self, bridge: Bridge, context: ssl.SSLContext, wire: Wire) -> None:
        self.bridge, self.context, self.wire = bridge, context, wire
        self.selected = ""
        self.authed = False
        self.refusal = ""

    def command(self) -> tuple[str, list[bytes]] | None:
        line = self.wire.line()
        literals: list[bytes] = []
        while line is not None and (m := re.search(rb"\{(\d+)\}$", line)):
            self.wire.send(b"+ go\r\n")
            literals.append(self.wire.take(int(m.group(1))))
            rest = self.wire.line() or b""
            line = line[:m.start()] + b"\x00LIT%d\x00" % (len(literals) - 1) + rest
        return None if line is None else (line.decode("utf-8", "replace"), literals)

    def reply(self, tag: str, text: str = "OK done") -> None:
        self.wire.send(f"{tag} {text}\r\n".encode())

    def run(self) -> None:
        self.wire.send(b"* OK IMAP4rev1 fake bridge ready\r\n")
        while (got := self.command()) is not None:
            line, literals = got
            tag, _, rest = line.partition(" ")
            word, _, args = rest.partition(" ")
            if word.upper() == "UID":
                word, _, args = args.partition(" ")
                word = "UID " + word.upper()
            if not self.handle(tag, word.upper(), args, literals):
                return

    def handle(self, tag: str, word: str, args: str, literals: list[bytes]) -> bool:
        toks = _tokens(args, literals)
        self.bridge.commands.append(" ".join([word, *(t for t in toks[:1] if word in ("SELECT", "EXAMINE", "APPEND",
                                                                                      "UID COPY", "UID STORE"))]))
        if word == "STARTTLS":
            self.reply(tag, "OK begin TLS")
            self.wire.secure(self.context)
        elif word == "LOGOUT":
            self.wire.send(b"* BYE\r\n")
            self.reply(tag, "OK bye")
            return False
        elif word == "LOGIN":
            self.bridge.logins += 1
            self.authed = toks[:2] == [self.bridge.user, self.bridge.password]
            self.reply(tag, "OK logged in" if self.authed else "NO login refused")
        elif word == "CAPABILITY":
            self.wire.send(b"* CAPABILITY IMAP4rev1 STARTTLS\r\n")
            self.reply(tag)
        elif not self.authed:
            self.reply(tag, "BAD log in first")
        else:
            self.authed_command(tag, word, args, toks)
        return True

    def authed_command(self, tag: str, word: str, args: str, toks: list[str]) -> None:
        stored = self.bridge.folders
        if word == "LIST":
            for name in stored:
                self.wire.send(f'* LIST (\\HasNoChildren) "/" "{imap_names.encode(name)}"\r\n'.encode())
        elif word in ("SELECT", "EXAMINE"):
            name = imap_names.decode(toks[0])
            if name not in stored:
                self.reply(tag, "NO no such folder")
                return
            self.selected = name
            self.wire.send(f"* {len(stored[name])} EXISTS\r\n".encode())
        elif word == "UID SEARCH":
            found = [s.uid for s in stored.get(self.selected, []) if _matches(s, toks)]
            self.wire.send(("* SEARCH" + "".join(f" {u}" for u in found) + "\r\n").encode())
        elif word == "UID FETCH":
            self.fetch(args, toks)
        elif word == "UID STORE":
            self.store(toks)
        elif word == "UID COPY":
            self.copy(toks)
        elif word == "EXPUNGE":
            stored[self.selected] = [s for s in stored[self.selected] if "\\Deleted" not in s.flags]
        elif word == "APPEND":
            self.append(toks, args)
        elif word != "NOOP":
            self.reply(tag, "BAD unknown command")
            return
        self.reply(tag, self.refusal or "OK done")
        self.refusal = ""

    def fetch(self, args: str, toks: list[str]) -> None:
        wanted = _uids(toks[0])
        peek = re.search(r"BODY\.PEEK\[([^\]]*)\](<0\.(\d+)>)?", args)
        names = re.findall(r"[A-Za-z-]+", peek.group(1).replace("HEADER.FIELDS", "")) if peek and peek.group(1) else []
        for seq, s in enumerate(self.bridge.folders[self.selected], 1):
            if s.uid not in wanted:
                continue
            flags = " ".join(sorted(s.flags))
            meta = f'FLAGS ({flags}) INTERNALDATE "{s.received}"'
            lead, tail = (meta, f" UID {s.uid}") if self.bridge.uid_last else (f"UID {s.uid} {meta}", "")
            if peek is None:
                self.wire.send(f"* {seq} FETCH ({lead}{tail})\r\n".encode())
                continue
            data = _fields(s.raw, [n.lower() for n in names]) if names else s.raw[:int(peek.group(3) or len(s.raw))]
            what = f"BODY[{peek.group(1)}]" + ("<0>" if peek.group(2) else "")
            self.wire.send(f"* {seq} FETCH ({lead} {what} {{{len(data)}}}\r\n".encode() + data + f"{tail})\r\n".encode())

    def store(self, toks: list[str]) -> None:
        flags = {f.strip("()") for f in toks[2:]}
        for s in self.bridge.folders[self.selected]:
            if s.uid in _uids(toks[0]):
                (s.flags.update if toks[1].startswith("+") else s.flags.difference_update)(flags)

    def copy(self, toks: list[str]) -> None:
        target = imap_names.decode(toks[1])
        if target not in self.bridge.folders:
            self.refusal = "NO [TRYCREATE] no such folder"
            return
        for s in self.bridge.folders[self.selected]:
            if s.uid in _uids(toks[0]):
                self.bridge.add(target, s.raw, tuple(s.flags), s.received)

    def append(self, toks: list[str], args: str) -> None:
        folder = imap_names.decode(toks[0])
        if folder not in self.bridge.folders:
            self.refusal = "NO [TRYCREATE] no such folder"
            return
        flags = tuple(re.findall(r"\\\w+", args.split("\x00", 1)[0]))
        self.bridge.add(folder, toks[-1].encode("utf-8", "surrogateescape"), flags)
