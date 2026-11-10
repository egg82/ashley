"""A fake IMAP4rev1 server (RFC 3501 with UIDPLUS, MOVE, UNSELECT, IDLE-less) for the fake Bridge, with no import from
`ashley`: LOGIN and AUTHENTICATE PLAIN against the bridge's accounts, LIST/LSUB, SELECT/EXAMINE/STATUS, FETCH, STORE,
SEARCH, COPY, MOVE and APPEND (each also as UID commands), EXPUNGE and UID EXPUNGE, CLOSE, CREATE, DELETE, RENAME,
NAMESPACE, ID, ENABLE, NOOP, LOGOUT and, in 'starttls' mode, STARTTLS with LOGINDISABLED before it. Literals, `{n}` and
`{n+}`, are read in commands. Every state-changing command is recorded on the account (`Account.commands`); text a client
must never send on is echoed in the error replies (`echo_in_errors`) so a log that copies a server's reply shows it.
Hand-written from the RFCs; unverified against Bridge."""

import base64
import re
from collections.abc import Callable

from mail_proton_blind_fetch_support import Searcher, Token, item, seqset
from mail_proton_blind_store_support import SPECIAL, Account, Copy
from mail_proton_blind_wire_support import Cert, Wire

CAPS = "IMAP4rev1 UIDPLUS MOVE UNSELECT ID ENABLE NAMESPACE"
LEAK = "swordfish-9917"


def tokenize(text: str, literals: list[str]) -> list[Token]:
    """The command's tokens: atoms (`BODY.PEEK[HEADER.FIELDS (A B)]<0.10>` is one), quoted strings and literals as str,
    and parenthesised lists as lists."""
    out: list[Token] = []
    stack: list[list[Token]] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == " ":
            i += 1
        elif c == "(":
            stack.append(out)
            out = []
            i += 1
        elif c == ")":
            done, out = out, stack.pop()
            out.append(done)
            i += 1
        elif c == '"':
            j, chars = i + 1, list[str]()
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                chars.append(text[j])
                j += 1
            out.append("".join(chars))
            i = j + 1
        elif c == "\x00":
            j = text.index("\x00", i + 1)
            out.append(literals[int(text[i + 1:j])])
            i = j + 1
        else:
            j = i
            while j < len(text) and text[j] not in " ()":
                if text[j] == "[":
                    j = text.index("]", j)
                j += 1
            out.append(text[i:j])
            i = j
    return out


class Session:
    def __init__(self, wire: Wire, accounts: dict[str, Account], cert: Cert, tls: str,
                 hooks: Callable[[], "Behaviour"]) -> None:
        self.w, self.accounts, self.cert, self.tls, self.hooks = wire, accounts, cert, tls, hooks
        self.me: Account | None = None
        self.folder: str | None = None
        self.readonly = False
        self.secure = tls != "starttls"

    # -- I/O --------------------------------------------------------------------------------------------------------

    def say(self, text: str) -> None:
        self.w.write(text.encode("utf-8") + b"\r\n")

    def command(self) -> tuple[str, list[Token], list[bytes]] | None:
        raw = self.w.line()
        if raw is None:
            return None
        literals: list[bytes] = []
        line = raw.decode("utf-8", errors="replace")
        while (m := re.search(r"\{(\d+)(\+?)\}$", line)):
            if not m.group(2):
                self.say("+ ready")
            data = self.w.read(int(m.group(1)))
            nxt = self.w.line()
            if data is None or nxt is None:
                return None
            literals.append(data)
            line = line[:m.start()] + f"\x00{len(literals) - 1}\x00" + nxt.decode("utf-8", errors="replace")
        tag, _, rest = line.partition(" ")
        strings = [d.decode("utf-8", errors="replace") for d in literals]
        return tag, tokenize(rest, strings), literals

    def run(self) -> None:
        behaviour = self.hooks()
        if behaviour.greeting is not None:
            self.say(behaviour.greeting)
            return
        self.say(f"* OK [CAPABILITY {self.caps()}] Bridge ready")
        while (got := self.command()) is not None:
            tag, tokens, literals = got
            if not tokens or not isinstance(tokens[0], str):
                self.say(f"{tag} BAD empty")
                continue
            verb = tokens[0].upper()
            if behaviour.drop_on == verb or (behaviour.drop_on == "SELECT" and verb == "EXAMINE"):
                return
            try:
                done = self.dispatch(tag, verb, tokens[1:], literals)
            except (ValueError, IndexError, KeyError) as e:
                self.say(f"{tag} BAD {type(e).__name__} {e}")
                continue
            if done:
                return

    def caps(self) -> str:
        if self.tls == "starttls" and not self.secure:
            return CAPS + " STARTTLS LOGINDISABLED"
        return CAPS + " AUTH=PLAIN"

    # -- commands ---------------------------------------------------------------------------------------------------

    def dispatch(self, tag: str, verb: str, args: list[Token], literals: list[bytes]) -> bool:
        if verb == "UID" and isinstance(args[0], str):
            return self.selected(tag, args[0].upper(), args[1:], True, literals)
        simple: dict[str, Callable[[], None]] = {
            "CAPABILITY": lambda: self.say(f"* CAPABILITY {self.caps()}"),
            "NOOP": lambda: None, "ID": lambda: self.say("* ID NIL"),
            "ENABLE": lambda: None, "NAMESPACE": lambda: self.say('* NAMESPACE (("" "/")) NIL NIL')}
        if verb in simple:
            simple[verb]()
            self.say(f"{tag} OK {verb} done")
        elif verb == "LOGOUT":
            self.say("* BYE bye")
            self.say(f"{tag} OK LOGOUT done")
            return True
        elif verb == "STARTTLS":
            return self.starttls(tag)
        elif verb == "LOGIN":
            self.login(tag, str(args[0]), str(args[1]))
        elif verb == "AUTHENTICATE":
            self.authenticate(tag, args)
        elif self.me is None:
            self.say(f"{tag} BAD login first")
        else:
            return self.selected(tag, verb, args, False, literals)
        return False

    def starttls(self, tag: str) -> bool:
        if self.tls != "starttls" or self.secure:
            self.say(f"{tag} BAD no STARTTLS")
            return False
        self.say(f"{tag} OK begin TLS")
        self.w.upgrade(self.cert.context)
        self.secure = True
        return False

    def login(self, tag: str, user: str, password: str) -> None:
        if not self.secure:
            self.say(f"{tag} NO [PRIVACYREQUIRED] STARTTLS first")
            return
        account = self.accounts.get(user.lower())
        if account is None or account.password != password:
            self.say(f"{tag} NO [AUTHENTICATIONFAILED] login for {user} refused, {LEAK}")
            return
        account.logins += 1
        self.me = account
        self.say(f"{tag} OK [CAPABILITY {CAPS}] logged in")

    def authenticate(self, tag: str, args: list[Token]) -> None:
        if str(args[0]).upper() != "PLAIN":
            self.say(f"{tag} NO mechanism")
            return
        if len(args) > 1:
            blob = str(args[1])
        else:
            self.say("+ ")
            line = self.w.line()
            blob = (line or b"").decode()
        _, user, password = base64.b64decode(blob).decode().split("\x00")
        self.login(tag, user, password)

    def selected(self, tag: str, verb: str, args: list[Token], uid: bool, literals: list[bytes]) -> bool:
        table: dict[str, Callable[[str, list[Token], bool], None]] = {
            "LIST": self.list_, "LSUB": self.list_, "SELECT": lambda t, a, u: self.select(t, a, u, "SELECT"),
            "EXAMINE": lambda t, a, u: self.select(t, a, u, "EXAMINE"),
            "STATUS": self.status, "CREATE": self.create, "DELETE": self.delete, "RENAME": self.rename,
            "FETCH": self.fetch, "STORE": self.store, "SEARCH": self.search, "COPY": self.copy, "MOVE": self.move,
            "EXPUNGE": self.expunge, "CLOSE": self.close, "UNSELECT": self.close}
        if verb == "APPEND":
            self.append(tag, args, literals)
        elif verb in table:
            if verb in ("FETCH", "STORE", "SEARCH", "COPY", "MOVE", "EXPUNGE", "CLOSE", "UNSELECT") and self.folder is None:
                self.say(f"{tag} BAD select a mailbox first")
            elif verb in ("STORE", "MOVE", "EXPUNGE") and self.readonly:
                self.say(f"{tag} NO [READ-ONLY] mailbox is read-only")
            else:
                table[verb](tag, args, uid)
        else:
            self.say(f"{tag} BAD unknown command {verb}")
        return False

    # -- mailbox commands -------------------------------------------------------------------------------------------

    def list_(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None
        pattern = str(args[1]) if len(args) > 1 else "*"
        regex = re.compile("^" + re.escape(pattern).replace(r"\*", ".*").replace("%", "[^/]*") + "$")
        for name in sorted(self.me.folders, key=lambda n: (n != "INBOX", n)):
            if regex.match(name):
                special = SPECIAL.get(name, "")
                self.say(f'* LIST (\\HasNoChildren{" " + special if special else ""}) "/" "{name}"')
        self.say(f"{tag} OK LIST done")

    def select(self, tag: str, args: list[Token], uid: bool, verb: str = "SELECT") -> None:
        assert self.me is not None
        name = str(args[0])
        if not self.me.has(name):
            self.say(f"{tag} NO [NONEXISTENT] no such mailbox {name}")
            return
        folder = self.me.folders[name]
        self.folder, self.readonly = name, verb == "EXAMINE"
        self.say("* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft)")
        self.say(f"* {len(folder.copies)} EXISTS\r\n* 0 RECENT")
        self.say(f"* OK [UIDVALIDITY {folder.uidvalidity}] ok\r\n* OK [UIDNEXT {folder.next_uid}] ok")
        self.say(f"{tag} OK [READ-ONLY] EXAMINE done" if self.readonly else f"{tag} OK [READ-WRITE] SELECT done")

    def status(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None
        name = str(args[0])
        if not self.me.has(name):
            self.say(f"{tag} NO [NONEXISTENT] no such mailbox")
            return
        f = self.me.folders[name]
        values = {"MESSAGES": len(f.copies), "UIDNEXT": f.next_uid, "UIDVALIDITY": f.uidvalidity,
                  "UNSEEN": sum("\\Seen" not in c.flags for c in f.copies), "RECENT": 0}
        asked = args[1] if isinstance(args[1], list) else []
        self.say(f'* STATUS "{name}" (' + " ".join(f"{k} {values[k]}" for k in map(str, asked)) + ")")
        self.say(f"{tag} OK STATUS done")

    def create(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None
        self.me.commands.append(("CREATE", str(args[0])))
        self.me.make(str(args[0]))
        self.say(f"{tag} OK CREATE done")

    def delete(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None
        self.me.commands.append(("DELETE", str(args[0])))
        self.me.folders.pop(str(args[0]), None)
        self.me.settle()
        self.say(f"{tag} OK DELETE done")

    def rename(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None
        self.me.commands.append(("RENAME", str(args[0])))
        self.me.folders[str(args[1])] = self.me.folders.pop(str(args[0]))
        self.say(f"{tag} OK RENAME done")

    def close(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None and self.folder is not None
        if not self.readonly:
            self.me.commands.append(("CLOSE-EXPUNGE", self.folder))
            self.me.expunge(self.folder)
        self.folder = None
        self.say(f"{tag} OK done")

    # -- messages ---------------------------------------------------------------------------------------------------

    def chosen(self, spec: str, uid: bool) -> list[tuple[int, Copy]]:
        assert self.me is not None and self.folder is not None
        copies = self.me.folders[self.folder].copies
        if uid:
            top = max((c.uid for c in copies), default=0)
            wanted = seqset(spec, top)
            return [(n + 1, c) for n, c in enumerate(copies) if c.uid in wanted]
        wanted = seqset(spec, len(copies))
        return [(n + 1, c) for n, c in enumerate(copies) if n + 1 in wanted]

    def fetch(self, tag: str, args: list[Token], uid: bool) -> None:
        names = args[1] if isinstance(args[1], list) else [args[1]]
        asked = [str(n) for n in names]
        macros = {"ALL": ["FLAGS", "INTERNALDATE", "RFC822.SIZE", "ENVELOPE"], "FAST": ["FLAGS", "INTERNALDATE", "RFC822.SIZE"],
                  "FULL": ["FLAGS", "INTERNALDATE", "RFC822.SIZE", "ENVELOPE", "BODY"]}
        asked = macros.get(asked[0].upper(), asked) if len(asked) == 1 else asked
        if uid and "UID" not in [a.upper() for a in asked]:
            asked = ["UID", *asked]
        for n, copy in self.chosen(str(args[0]), uid):
            parts: list[bytes] = []
            sets_seen = False
            for name in asked:
                data, seen = item(copy, name, self.flag_list)
                parts.append(data)
                sets_seen = sets_seen or seen
            if sets_seen and not self.readonly and "\\Seen" not in copy.mail.flags:
                copy.mail.flags.add("\\Seen")
                parts.append(b"FLAGS " + self.flag_list(copy).encode())
            self.w.write(b"* %d FETCH (" % n + b" ".join(parts) + b")\r\n")
        self.say(f"{tag} OK FETCH done")

    def flag_list(self, copy: Copy) -> str:
        return "(" + " ".join(sorted(copy.flags)) + ")"

    def store(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None and self.folder is not None
        mode = str(args[1]).upper()
        flags = {str(f) for f in (args[2] if isinstance(args[2], list) else [args[2]])}
        self.me.commands.append(("STORE", self.folder))
        for n, copy in self.chosen(str(args[0]), uid):
            held = copy.flags
            now = flags if mode.startswith("FLAGS") else (held | flags if mode.startswith("+") else held - flags)
            copy.deleted = "\\Deleted" in now
            copy.mail.flags = now - {"\\Deleted"}
            if "SILENT" not in mode:
                self.say(f"* {n} FETCH (" + (f"UID {copy.uid} " if uid else "") + f"FLAGS {self.flag_list(copy)})")
        self.say(f"{tag} OK STORE done")

    def search(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None and self.folder is not None
        copies = self.me.folders[self.folder].copies
        try:
            test = Searcher(list(args), len(copies)).parse()
        except ValueError as e:
            self.say(f"{tag} BAD {e}")
            return
        hits = [(n + 1, c) for n, c in enumerate(copies) if test(c, n + 1)]
        self.say("* SEARCH" + "".join(f" {c.uid if uid else n}" for n, c in hits))
        self.say(f"{tag} OK SEARCH done")

    def copy(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None and self.folder is not None
        target = str(args[1])
        if not self.me.has(target):
            self.say(f"{tag} NO [TRYCREATE] no such mailbox")
            return
        self.me.commands.append(("COPY", target))
        for _, c in self.chosen(str(args[0]), uid):
            self.me.add(target, b"", share=c.mail)
        self.say(f"{tag} OK COPY done")

    def move(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None and self.folder is not None
        target = str(args[1])
        if not self.me.has(target):
            self.say(f"{tag} NO [TRYCREATE] no such mailbox")
            return
        self.me.commands.append(("MOVE", target))
        moved = self.chosen(str(args[0]), uid)
        for _, c in moved:
            self.me.add(target, b"", share=c.mail)
            c.deleted = True
        gone = self.me.expunge(self.folder, {c.uid for _, c in moved})
        self.say("".join(f"* {n} EXPUNGE\r\n" for n in reversed(gone)) + f"{tag} OK MOVE done")

    def expunge(self, tag: str, args: list[Token], uid: bool) -> None:
        assert self.me is not None and self.folder is not None
        self.me.commands.append(("EXPUNGE", self.folder))
        only = {c.uid for _, c in self.chosen(str(args[0]), True)} if uid and args else None
        gone = self.me.expunge(self.folder, only)
        self.say("".join(f"* {n} EXPUNGE\r\n" for n in reversed(gone)) + f"{tag} OK EXPUNGE done")

    def append(self, tag: str, args: list[Token], literals: list[bytes]) -> None:
        assert self.me is not None
        name = str(args[0])
        flags = tuple(str(f) for f in args[1]) if len(args) > 2 and isinstance(args[1], list) else ()
        if not self.me.has(name):
            self.say(f"{tag} NO [TRYCREATE] no such mailbox")
            return
        self.me.commands.append(("APPEND", name))
        copy = self.me.add(name, literals[-1], tuple(f for f in flags if f != "\\Deleted"))
        folder = self.me.folders[name]
        self.say(f"{tag} OK [APPENDUID {folder.uidvalidity} {copy.uid}] APPEND done")


class Behaviour:
    """What a test makes the fake do wrongly: a greeting that is not IMAP's, or a connection dropped at a command."""

    def __init__(self) -> None:
        self.greeting: str | None = None
        self.drop_on: str | None = None


def serve_imap(accounts: dict[str, Account], cert: Cert, tls: str, behaviour: Behaviour) -> Callable[[Wire], None]:
    def serve(wire: Wire) -> None:
        Session(wire, accounts, cert, tls, lambda: behaviour).run()

    return serve
