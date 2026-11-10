"""An image or file piece's body and what `decide` allows of it: exactly a stored file's hash, size, media type and
name; an image's media type is an image's; the body is fixed once made (an Edit may retitle it, nothing else); the
piece is removed, archived, restored and undone like any other; the codec and replay keep it."""

from ashley.workshop import stored_file
from ashley.workshop.codec import decode_command, encode_command
from ashley.workshop.commands import Add, Archive, Command, Edit, Remove, Restore, Undo
from ashley.workshop.decide import EMPTY, Accepted, Decision, Refused, replay
from ashley.workshop.model import HER, By, Text
from ashley.workshop.rules import Kind, Rules, load
from ashley.workshop.stored_file import StoredFile

IMAGE = Kind("image", "large", "Image", 1000, "image")
FILE = Kind("file", "large", "File", 1000, "file")
RULES = Rules({"image": IMAGE, "file": FILE}, max_pieces=3, title_max_chars=20, recent_commands=10, undo_window=100)
SHA = "ab" * 32
PNG_BODY = stored_file.body_of(StoredFile(SHA, 20, "image/png", "cat.png"))
PDF_BODY = stored_file.body_of(StoredFile(SHA, 20, "application/pdf", "plan.pdf"))
ALANA = By(7)


def run(*commands: Command) -> list[Decision]:
    return replay(commands, RULES)


def reason(*commands: Command) -> str:
    got = run(*commands)[-1]
    assert isinstance(got, Refused)
    return got.reason


def test_the_shipped_rules_have_both_kinds_as_large() -> None:
    rules = load()
    assert (rules.kinds["image"].family, rules.kinds["image"].format) == ("large", "image")
    assert (rules.kinds["file"].family, rules.kinds["file"].format) == ("large", "file")


def test_a_body_is_exactly_a_stored_file() -> None:
    assert stored_file.file_of(PNG_BODY) == StoredFile(SHA, 20, "image/png", "cat.png")
    assert stored_file.file_of(stored_file.body_of(StoredFile(SHA, 20, "image/png", "é\"q\\.png"))) is not None
    bad = ["", "not json", "[]", "{}", PNG_BODY[:-1] + ',"extra":1}',
           PNG_BODY.replace(SHA, "AB" * 32), PNG_BODY.replace(SHA, "ab" * 31), PNG_BODY.replace('"size":20', '"size":0'),
           PNG_BODY.replace('"size":20', '"size":true'), PNG_BODY.replace('"size":20', '"size":"20"'),
           PNG_BODY.replace("image/png", "png"), PNG_BODY.replace("image/png", "Image/PNG"),
           PNG_BODY.replace("cat.png", " "), PNG_BODY.replace("cat.png", "x" * 201)]
    for body in bad:
        assert stored_file.file_of(body) is None, body
        assert reason(Add(ALANA, "file", Text("t", body), "small")) == "bad_file"


def test_an_image_piece_must_hold_an_image_and_a_file_piece_may_hold_anything() -> None:
    assert reason(Add(ALANA, "image", Text("t", PDF_BODY), "small")) == "bad_file"
    assert isinstance(run(Add(ALANA, "image", Text("t", PNG_BODY), "medium"))[-1], Accepted)
    assert isinstance(run(Add(ALANA, "file", Text("t", PDF_BODY), "small"))[-1], Accepted)
    assert isinstance(run(Add(ALANA, "file", Text("t", PNG_BODY), "small"))[-1], Accepted)


def test_a_large_piece_is_titled_and_counted_like_any_other() -> None:
    assert reason(Add(ALANA, "file", Text("", PDF_BODY), "small")) == "bad_title"
    assert reason(Add(ALANA, "file", Text("x" * 21, PDF_BODY), "small")) == "bad_title"
    full = [Add(ALANA, "file", Text(str(n), PDF_BODY), "small") for n in range(4)]
    assert reason(*full) == "full"


def test_the_body_is_fixed_but_the_title_is_not() -> None:
    made = Add(ALANA, "file", Text("old", PDF_BODY), "small")
    other = stored_file.body_of(StoredFile("cd" * 32, 20, "application/pdf", "plan.pdf"))
    assert reason(made, Edit(ALANA, 1, 1, Text("old", other))) == "bad_file"
    assert reason(made, Edit(HER, 1, 1, Text("old", ""))) == "bad_file"
    got = run(made, Edit(ALANA, 1, 1, Text("new", PDF_BODY)))[-1]
    assert isinstance(got, Accepted) and got.state.pieces[0].text == Text("new", PDF_BODY)
    assert got.state.pieces[0].version == 2


def test_a_stale_edit_is_stale_before_it_is_bad() -> None:
    made = Add(ALANA, "file", Text("old", PDF_BODY), "small")
    assert reason(made, Edit(ALANA, 1, 5, Text("old", "x"))) == "stale_base"


def test_remove_archive_restore_and_undo_work_as_for_any_piece() -> None:
    made = Add(ALANA, "file", Text("f", PDF_BODY), "small")
    gone = run(made, Remove(ALANA, 1), Undo(ALANA, 2))
    assert isinstance(gone[-1], Accepted) and gone[-1].state.pieces[0].text.body == PDF_BODY
    shelved = run(made, Archive(ALANA, 1), Restore(ALANA, 1))
    assert isinstance(shelved[-1], Accepted) and shelved[-1].state.pieces[0].kind == "file"
    undone = run(made, Undo(ALANA, 1))[-1]
    assert isinstance(undone, Accepted) and undone.state.pieces == ()


def test_the_command_survives_the_log() -> None:
    command = Add(ALANA, "image", Text("t", PNG_BODY), "medium")
    assert decode_command(encode_command(command), ALANA) == command
    assert run(command)[-1].state != EMPTY
