"""A browser session service that records what it was asked and answers from a script, for the tools over it."""

from dataclasses import dataclass, field

from ashley.looks.session import Acted, Act, BrowserSessions, Node, SessionUnavailable, Snapshot, Who

NODES = (Node("e0", "textbox", "Email"), Node("e1", "textbox", "Password", secret=True),
         Node("e2", "combobox", "Size", options=("S", "L")), Node("e3", "button", "Buy", disabled=True, checked=True))
SEEN = Snapshot("https://shop.example/cart", "Cart", NODES, True, 540, 55)


@dataclass
class ScriptedSessions(BrowserSessions):
    fails: str | None = None
    acts: list[Act] = field(default_factory=lambda: list[Act]())
    asked: list[Who] = field(default_factory=lambda: list[Who]())
    ended: list[Who] = field(default_factory=lambda: list[Who]())
    there: bool = True

    def drives(self) -> bool:
        return True

    async def snapshot(self, who: Who) -> Snapshot:
        self.asked.append(who)
        if self.fails:
            raise SessionUnavailable(self.fails)
        return SEEN

    async def act(self, who: Who, act: Act) -> Acted:
        self.asked.append(who)
        if self.fails:
            raise SessionUnavailable(self.fails)
        self.acts.append(act)
        return Acted(500, 54)

    async def end(self, who: Who) -> bool:
        self.ended.append(who)
        return self.there
