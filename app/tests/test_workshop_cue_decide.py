"""A Cue on a bench from `decide`'s contract: accepted for a video piece, refused in its stated order, changing no
piece, never undone, never in the way of undoing a change around it, and kept by the codec."""

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import Add, Command, Cue, Cued, Edit, Undo, type_of
from ashley.workshop.decide import Accepted, Decision, Refused, decide, replay
from ashley.workshop.embed import MAX_START
from ashley.workshop.model import HER, By, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.undo_walk import Step, next_undo

VIDEO = Kind("video", "live", "Video", 100, "video")
NOTE = Kind("note", "stored", "Note", 100)
RULES = Rules({"video": VIDEO, "note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
ALANA = By(7)
URL = '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'


def run(*commands: Command) -> list[Decision]:
    return replay(commands, RULES)


def video() -> Add:
    return Add(ALANA, "video", Text("v", URL), "small")


def test_a_cue_of_a_video_piece_is_accepted_and_changes_no_piece() -> None:
    added, seek, play = run(video(), Cue(HER, 1, "seek", 90.5), Cue(HER, 1, "play", None))
    assert isinstance(seek, Accepted) and seek.effect == Cued(1, "seek", 90.5)
    assert isinstance(play, Accepted) and play.effect == Cued(1, "play", None)
    assert seek.state.pieces == added.state.pieces == play.state.pieces


def test_a_cue_of_a_video_file_or_an_audio_file_is_accepted_like_an_embedded_video() -> None:
    body = '{"sha256":"' + "a" * 64 + '","size":9,"media_type":"%s","name":"f"}'
    rules = Rules({"clip": Kind("clip", "large", "Clip", 1000, "clip"), "audio": Kind("audio", "large", "Audio", 1000, "audio")},
                  max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
    added = replay([Add(ALANA, "clip", Text("c", body % "video/mp4"), "medium"),
                    Add(ALANA, "audio", Text("a", body % "audio/mpeg"), "small"), Cue(HER, 1, "seek", 4.0),
                    Cue(HER, 2, "play", None)], rules)
    assert [type(d) for d in added] == [Accepted] * 4
    assert isinstance(added[2], Accepted) and added[2].effect == Cued(1, "seek", 4.0)


def test_cue_refusals_in_their_stated_order() -> None:
    gone = run(video(), Cue(HER, 9, "play", None))[-1]
    assert isinstance(gone, Refused) and gone.reason == "no_such_piece"
    note = run(Add(ALANA, "note", Text("n", "x"), "small"), Cue(HER, 1, "play", None))[-1]
    assert isinstance(note, Refused) and note.reason == "not_video"
    added = run(video())[-1]
    without = Rules({"note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
    unknown = decide(added.state, Cue(HER, 1, "play", None), without)
    assert isinstance(unknown, Refused) and unknown.reason == "unknown_kind"


def test_a_cue_with_the_wrong_seconds_is_refused_bad_cue() -> None:
    for cue in (Cue(HER, 1, "seek", None), Cue(HER, 1, "seek", -1.0), Cue(HER, 1, "seek", MAX_START + 1.0),
                Cue(HER, 1, "seek", float("nan")), Cue(HER, 1, "play", 3.0), Cue(HER, 1, "pause", 0.0)):
        got = run(video(), cue)[-1]
        assert isinstance(got, Refused) and got.reason == "bad_cue", cue
    assert isinstance(run(video(), Cue(HER, 1, "seek", 0.0))[-1], Accepted)
    assert isinstance(run(video(), Cue(HER, 1, "seek", float(MAX_START)))[-1], Accepted)


def test_a_cue_is_never_undone() -> None:
    got = run(video(), Cue(HER, 1, "play", None), Undo(ALANA, 2))[-1]
    assert isinstance(got, Refused) and got.reason == "nothing_to_undo"


def test_a_cue_does_not_stand_in_the_way_of_undoing_the_edit_before_it() -> None:
    other = '{"url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"}'
    got = run(video(), Edit(ALANA, 1, 1, Text("v", other)), Cue(HER, 1, "pause", None), Undo(ALANA, 2))[-1]
    assert isinstance(got, Accepted) and got.state.pieces[0].text.body == URL


def test_undo_walks_past_a_cue() -> None:
    assert next_undo([Step(1, True), Step(2, True, run=True)]) == 1


def test_a_cue_and_its_effect_survive_the_codec() -> None:
    for cue, effect in ((Cue(ALANA, 3, "seek", 12.5), Cued(3, "seek", 12.5)), (Cue(ALANA, 3, "pause", None),
                                                                              Cued(3, "pause", None))):
        assert type_of(cue) == "cue"
        assert decode_command(encode_command(cue), ALANA) == cue
        assert decode_effect(encode_effect(effect)) == effect
