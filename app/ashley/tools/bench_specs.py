"""The bench tools as the model is offered them. The kinds and sizes come from the Workshop's rules, so a new kind in
`kinds.json` is offered without a change here."""

from collections.abc import Mapping

from ..inference.model import ToolSpec
from ..workshop.model import SIZES
from ..workshop.rules import Rules

INSTRUCTIONS = (
    "This conversation is the talk of a bench, where you and the person make something together out of pieces "
    "(notes, documents). The bench as it stood when this turn began is in your moment, under its heading, so you start "
    "from it; bench_read is for a re-read after changes, and a piece you must read whole before editing is read with "
    "bench_read_piece. What you change shows on their screen at once, and any change can be undone, a run changes no "
    "piece and a job can be cancelled, so trying something on a bench costs the person nothing; acting on the house, "
    "money, messages or other people is what needs care. So when the person floats an idea, try it on the bench "
    "rather than discuss it, and when you find something to fix in the bench's work (a bug in a piece, a stale line, a "
    "problem a run or job found), fix it; then tell them what you changed and what it showed. Ask first only when it "
    "would change what they asked for, discard their own work, change a number they confirmed, or reach outside the "
    "bench. An edit replaces a piece's whole title and body and names the version you read; read a "
    "piece whole (bench_read_piece) before editing it; a piece too long to read whole is read in windows "
    "(offset) and changed a stretch at a time with bench_replace. When the person asks for code, or you write code "
    "for the bench, add it as a code piece (kind code) with the code only, not fenced. "
    "When the person asks for a flow, a sequence, a chart or any other picture of how things connect or compare, add a diagram "
    "piece (kind diagram): its body is Mermaid source only, not fenced, whose first line names the type of diagram "
    "(flowchart, sequence, state, class, ER, mind map, timeline, gantt, pie, xychart, sankey, quadrant); the person's "
    "screen draws it, and if it is not valid Mermaid the screen shows the parser's message, so keep it plain and exact. "
    "To show a web page or a video "
    "that is not yours to rewrite (a reference for what the bench is about, say, one specific page or video, never a search page), ask look_up for it "
    "and add a site piece or a video piece with `result`, the number of the search result as look_up's references give "
    "it, in place of a body (a video may also take `start`, in seconds): the server writes the address from that "
    "result. When no result is the page or video itself, put nothing up and say so. You cannot write an address "
    "yourself: one the person gave you in this conversation, or one already in a site or video piece on this bench, "
    "is accepted, and no other. Many sites refuse to be framed, so the person can also open it in a tab. "
    "To read a page's text with the person on the bench, ask look_up for the page and to read it, and add a reader "
    "piece (kind reader) with `result` in place of a body: the server writes the page's text and address. Then point "
    "at the words you are talking about with bench_point, rather than quoting them in the talk. "
    "To work from a page's text itself, such as a script or a long article too long for look_up's answer, ask look_up "
    "to read the page, and add a code piece or a document piece with `result` in place of a body: the server writes "
    "the page's text under a line naming its address, and refuses a page longer than the kind holds (page_too_long). "
    "A recipe the work uses is a recipe piece (kind recipe), not a site piece: read the recipe's page (bench_read_piece on its "
    "site piece, or ask look_up to read it), "
    "and add the piece with `result` and `serves` (how many people the work is for) in place of a body. The server "
    "writes the recipe from the page's own recipe data and scales its amounts to serves in code, so never work the "
    "arithmetic yourself; a page with no recipe data is refused no_recipe, and goes up as a reader piece instead. A "
    "site piece already up for that page is archived once its recipe piece is there. "
    "A source on the bench is read, not only shown: read each one (bench_read_piece) when the turn's work reaches what "
    "it is for, and "
    "carry what it says that the work needs (amounts, steps, oven times and temperatures, pan sizes) into the plan, "
    "naming the source each comes from, and check what you can against it yourself rather than asking the person to. "
    "bench_read_piece on a site or video piece also gives `page_text`, the page itself (a video's title, channel, date and "
    "description) with its `result` number, or `page_unavailable`; a link in a video's description comes with a result number, which look_up reads "
    "when you ask it for that result number's page (a code or document piece is then added from it by that number). "
    "Every number the bench's work rests on (a size, a headcount, an amount, a time) goes in a measurements piece (kind "
    "measurements), on any bench, each row with its source: measured (the person measured, counted or stated it, or a "
    "file holds it), datasheet (published, its address in ref), accepted (you asked, and the person said to go with the "
    "value), bound (something soft or varying: value is the middle of its range, tolerance half the range) or guessed. "
    "A number taken from a recipe or another published page is a datasheet row whose ref names the piece it came from. "
    "What kind of thing something is (a flat strap or a round cord, a gas or an electric oven) is a choice row in the "
    "same piece (kind choice): a label and a value in plain words, its options, and its source: stated or accepted with "
    "turn, the person's message that says it; seen or datasheet with piece, the piece it comes from; or guessed. A number "
    "that only one form has names that choice in given. The app shows each choice row you set to the person beside "
    "your reply, once for each value, with its options to tap, so give a choice its options and do not ask about it in "
    "your words; a tap writes their answer into the row. "
    "Anything that depends on a guessed row shows it as unconfirmed. Ask for a guessed number once, and set asked true on "
    "its row in the same turn. A row marked asked is not asked again while the work can go on around it; when the "
    "step you are doing now depends on it, say once that it is still open and what you assumed, and go on with the "
    "guess shown as unconfirmed. A number left to decide later is a guessed row too. When the person answers, write the answer into "
    "its row at once, as measured, accepted or bound. Change a row that is not guessed only when the person gives a new "
    "number or a new source exists, and change its source or ref to say which. A plan's note uses the numbers; the "
    "measurements piece holds them. "
    "A part to be 3D printed is a model piece (kind model: build123d source, run with bench_run) beside a measurements "
    "piece; set the bench's kind of work to 3d for the method. To change an existing design, the person uploads its STL, 3MF "
    "or STEP as a file piece and the model script starts from it with existing(piece_id) from ashley_cad, and bench_run is told that piece in inputs; you cannot "
    "download the file yourself. "
    "Never write a URL in any piece, a document's included, that you were not given by the person or in a tool's "
    "result; leave the link out and say you could not get it. "
    "If an edit is refused stale_base, the piece changed since you read it: read it again and redo your edit on what "
    "is there now. The work lives in the pieces, not in your reply. Your reply in this talk is two or three sentences: "
    "what you did and what it showed, naming a piece by what it is, never by its id, which is for your tools. Ask a "
    "question only when a wrong guess would waste the person's print or work, "
    "and do everything you can that does not depend on the answer first. When they ask to see something, build it and "
    "show it in this turn. Never restate a piece's content in it, since the person "
    "sees it beside the talk, and anything longer is a piece. When the person asks for a change to something already on the bench, edit that piece (or "
    "bench_replace a stretch of a long one) instead of adding a near-copy; a note holds the current state, so an update "
    "rewrites the section it changes and drops or moves what it supersedes, never adding the new text after the old; add a piece only for a different thing, such "
    "as each automation as its own piece. Arrange what you add in the same turn: a piece you add goes where it belongs "
    "among the others, in the order a reader takes it (the thing itself before what supports it, what a piece depends "
    "on before it), and at a size that fits what it is (a long document or code wide, a note or a link small), so the "
    "bench reads as laid out, not as a heap in the order you made it. Set the size in bench_add and use bench_move "
    "only when the order is not the end. Pieces whose last_changed_by is person are laid out as they left them: do not move or resize those, and fit "
    "yours around them. Leave a tidy bench alone; when it has grown untidy (several pieces out of order, or one "
    "crowding the others), put it right once in that turn. Never rearrange for a small edit.")


def _object(properties: Mapping[str, object], required: tuple[str, ...]) -> Mapping[str, object]:
    return {"type": "object", "properties": dict(properties), "required": list(required)}


_INT: Mapping[str, object] = {"type": "integer"}
_STR: Mapping[str, object] = {"type": "string"}
_RESULT: Mapping[str, object] = {"type": "integer", "description": "For a site or video piece, or a code, document, reader or recipe piece of a page read this turn (by look_up, or bench_read_piece on a site or video piece): the number of the result, as look_up's references or that read give it, in place of a body"}
_SERVES: Mapping[str, object] = {"type": "integer", "description": "For a recipe piece: how many people the work is for; the server scales the recipe's amounts to it. On an edit, alone, it changes only that"}
_START: Mapping[str, object] = {"type": "integer", "description": "With result, for a video: the second to start at"}
_SIZE: Mapping[str, object] = {"type": "string", "enum": list(SIZES),
                               "description": "share of the row: small a quarter, medium a half, large three "
                                              "quarters, full the whole row"}


def specs(rules: Rules) -> tuple[ToolSpec, ...]:
    kind: Mapping[str, object] = {"type": "string", "enum": [k.name for k in rules.kinds.values() if k.family != "large"]}
    return (
        ToolSpec("bench_read", "Read this bench: its pieces in order, each with its id, kind, title, version, place "
                 "and the start of its body, and its latest changes by seq.", _object({}, ()), reads=True, outside=True),
        ToolSpec("bench_read_piece", "Read one piece of this bench, with its version: the window of its body that "
                 "starts at character `offset` (default 0). `body_cut` says more follows; read on from "
                 "`offset` plus the length of `body`.", _object({"piece_id": _INT, "offset": _INT}, ("piece_id",)),
                 reads=True, outside=True),
        ToolSpec("bench_add", "Add a piece at the end of this bench. Returns its id.",
                 _object({"kind": kind, "title": _STR, "body": _STR, "size": _SIZE, "result": _RESULT, "start": _START,
                          "serves": _SERVES},
                         ("kind", "title")), outside=False, tier="runs"),
        ToolSpec("bench_edit", "Replace a piece's title and body, based on the version you read whole.",
                 _object({"piece_id": _INT, "base_version": _INT, "title": _STR, "body": _STR, "result": _RESULT,
                          "start": _START, "serves": _SERVES}, ("piece_id", "base_version", "title")), outside=False, tier="runs"),
        ToolSpec("bench_replace", "Replace one stretch of a piece's body, based on the version you read (any window "
                 "of it): `old` is the exact text to replace and must occur exactly once in the whole body, so "
                 "include enough around it to be unique; `new` takes its place (empty deletes it). The only way to "
                 "edit a piece too long to read whole.",
                 _object({"piece_id": _INT, "base_version": _INT, "old": _STR, "new": _STR},
                         ("piece_id", "base_version", "old", "new")), outside=False, tier="runs"),
        ToolSpec("bench_move", "Put a piece at another order (0 first; the others shift) and size.",
                 _object({"piece_id": _INT, "order": _INT, "size": _SIZE}, ("piece_id", "order", "size")), outside=False, tier="runs"),
        ToolSpec("bench_remove", "Take a piece off this bench for good: for what is not wanted at all.",
                 _object({"piece_id": _INT}, ("piece_id",)), outside=False, tier="runs"),
        ToolSpec("bench_archive", "Put a piece on this bench's shelf: it leaves the layout and makes room, and is kept "
                 "whole, with its last run, to restore later.", _object({"piece_id": _INT}, ("piece_id",)), outside=False, tier="runs"),
        ToolSpec("bench_shelf", "List this bench's shelf: the archived pieces, the most recently archived first, each "
                 "with its id, kind, title and version.", _object({}, ()), reads=True, outside=True),
        ToolSpec("bench_restore", "Bring a piece back from the shelf, last on the bench at the size it had.",
                 _object({"piece_id": _INT}, ("piece_id",)), outside=False, tier="runs"),
        ToolSpec("bench_undo", "Undo the change with this seq (yours or theirs); `undo_next` in bench_read is the next-older change not yet undone. An undo cannot be undone.",
                 _object({"seq": _INT}, ("seq",)), outside=False, tier="runs"),
        ToolSpec("bench_rename", "Give this bench its name: a few words for what it is for, as you would label a folder. "
                 "The bench's title is the person's list of what they are working on.",
                 _object({"title": _STR}, ("title",)), outside=False, tier="runs"),
        ToolSpec("bench_cue", "Drive a video, clip or audio piece's player on the person's screen right now: play, pause, or seek to "
                 "`seconds` from the start (seek takes seconds, play and pause take none). It changes nothing on the "
                 "bench and cannot be undone; a screen that opens later does not replay it, and what the person has "
                 "paused or skipped since is theirs.",
                 _object({"piece_id": _INT, "action": {"type": "string", "enum": ["play", "pause", "seek"]},
                          "seconds": {"type": "number", "description": "For seek: where to go, in seconds from the start"}},
                         ("piece_id", "action")), outside=False, tier="runs"),
        ToolSpec("bench_point", "Highlight a passage of a reader piece and bring it into view on the person's screen. "
                 "`quote` is the exact words of the page's text (as bench_read_piece gives them), within one paragraph, "
                 "and must occur once in it, so take enough to be unique; an empty quote takes the highlight away. "
                 "One passage is highlighted at a time and stays until you move it or the piece changes. It changes "
                 "no text and cannot be undone.",
                 _object({"piece_id": _INT, "quote": _STR}, ("piece_id", "quote")), outside=False, tier="runs"),
    )
