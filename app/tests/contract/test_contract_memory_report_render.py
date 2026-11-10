"""`ashley.memory.report.render`: what the operator reads. Asserts on the presence of ids, texts and markers, each
marker read on the line of the fact it belongs to, never on spacing. Written blind from the contract."""

from ashley.memory.report import ReplySeen, WriteSeen, render, seen

from report_support import at, containing, done, fact, stamp, the_line

N = 7


def reply(standing: tuple[int, ...] | None = (), recalled: tuple[int, ...] | None = (), used: tuple[int, ...] = (),
          *, when: float = 0, kind: str = "chat", medium: str = "typed", speaker: str = "known",
          unrecalled: int = 0) -> ReplySeen:
    """A reply as `seen` reads it from the line the app writes; a None tier is the line's `unavailable`."""
    def listed(ids: tuple[int, ...] | None) -> str:
        return "unavailable" if ids is None else ",".join(map(str, ids))

    (found,), _ = seen([done(N, at(when), standing=listed(standing), recalled=listed(recalled),
                             used=",".join(map(str, used)), unrecalled=unrecalled, kind=kind, medium=medium,
                             speaker=speaker)], N)
    return found


def write(inserted: tuple[int, ...] = (), *, when: float = 0, add: int = 0, update: int = 0, invalidate: int = 0,
          forget: int = 0, noop: int = 0, deleted: int = 0, through: int | None = None) -> WriteSeen:
    return WriteSeen(at=stamp(at(when)), inserted=inserted, add=add, update=update, invalidate=invalidate,
                     forget=forget, noop=noop, deleted=deleted, written_through=through)


def test_a_reply_shows_its_time_kind_medium_and_speaker() -> None:
    out = render(N, (reply(when=3, kind="brainstorm", medium="spoken", speaker="unknown"),), (), {}, ())
    for token in (stamp(at(3)), "brainstorm", "spoken", "unknown"):
        assert token in out, token


def test_each_offered_fact_shows_its_id_text_kind_visibility_and_origin() -> None:
    facts = {4101: fact(4101, "likes oat milk", kind="preference", visibility="discreet", conversation=91,
                        standing=True),
             4102: fact(4102, "has a cat named Pip", kind="home", visibility="shared", conversation=92)}
    out = render(N, (reply((4101,), (4102,)),), (), facts, ())
    first, second = the_line(out, "oat milk"), the_line(out, "named Pip")
    assert "4101" in first and "preference" in first and "discreet" in first and "from conversation 91" in first
    assert "4102" in second and "home" in second and "shared" in second and "from conversation 92" in second


def test_used_is_marked_on_the_facts_the_reply_named_and_only_those() -> None:
    facts = {4101: fact(4101, "alphaT", standing=True), 4102: fact(4102, "betaT", standing=True),
             4103: fact(4103, "gammaT"), 4104: fact(4104, "deltaT")}
    out = render(N, (reply((4101, 4102), (4103, 4104), used=(4102, 4103)),), (), facts, ())
    assert "used" not in the_line(out, "alphaT") and "used" not in the_line(out, "deltaT")
    assert "used" in the_line(out, "betaT") and "used" in the_line(out, "gammaT")


def test_used_is_per_reply() -> None:
    facts = {4101: fact(4101, "alphaT"), 4102: fact(4102, "betaT")}
    out = render(N, (reply((), (4101, 4102), used=(4101,), when=1), reply((), (4101, 4102), used=(4102,), when=2)),
                 (), facts, ())
    marks = [("used" in ln) for ln in out.splitlines() if "alphaT" in ln or "betaT" in ln]
    assert marks == [True, False, False, True]


def test_a_closed_fact_says_when_and_a_superseded_one_says_by_what() -> None:
    facts = {4101: fact(4101, "oldT", valid_to=at(86400 * 3), superseded_by=4102), 4102: fact(4102, "newT"),
             4103: fact(4103, "endedT", valid_to=at(86400 * 5))}
    out = render(N, (reply((), (4101, 4102, 4103)),), (), facts, ())
    old, new, ended = the_line(out, "oldT"), the_line(out, "newT"), the_line(out, "endedT")
    assert "closed" in old and "2026-10-23" in old and "replaced by [4102]" in old
    assert "closed" not in new and "replaced" not in new
    assert "closed" in ended and "2026-10-25" in ended and "replaced" not in ended


def test_a_fact_with_no_row_is_forgotten() -> None:
    facts = {4101: fact(4101, "keptT")}
    out = render(N, (reply((4103,), (4101, 4104)),), (), facts, ())
    assert any("forgotten" in ln for ln in containing(out, "4103"))
    assert any("forgotten" in ln for ln in containing(out, "4104"))
    assert "forgotten" not in the_line(out, "keptT")


def test_an_id_used_but_offered_by_neither_tier_is_listed_as_such() -> None:
    facts = {4101: fact(4101, "seenT"), 4105: fact(4105, "strayT")}
    out = render(N, (reply((), (4101,), used=(4101, 4105), unrecalled=1),), (), facts, ())
    assert "not offered" in the_line(out, "strayT") and "used" in the_line(out, "strayT")
    assert "not offered" not in the_line(out, "seenT")


def test_a_used_id_with_no_row_and_no_offer_is_still_listed() -> None:
    out = render(N, (reply((), (), used=(4106,), unrecalled=1),), (), {}, ())
    assert any("not offered" in ln for ln in containing(out, "4106"))


def test_nothing_is_called_not_offered_when_the_reply_used_only_what_it_was_offered() -> None:
    facts = {4101: fact(4101, "aT", standing=True), 4102: fact(4102, "bT")}
    out = render(N, (reply((4101,), (4102,), used=(4101, 4102)),), (), facts, ())
    assert "not offered" not in out


def test_unreachable_memory_is_not_an_empty_list() -> None:
    out = render(N, (reply(None, None),), (), {}, ())
    assert "memory unreachable" in out and "offered facts not logged" not in out


def test_an_older_line_says_the_offer_was_not_logged() -> None:
    (old,), _ = seen([done(N, standing=None, recalled=None, used="")], N)
    out = render(N, (old,), (), {}, ())
    assert "offered facts not logged" in out and "memory unreachable" not in out


def test_a_reply_that_was_offered_nothing_says_neither() -> None:
    out = render(N, (reply((), ()),), (), {}, ())
    assert "memory unreachable" not in out and "offered facts not logged" not in out


def test_one_unreachable_reply_does_not_colour_its_neighbours() -> None:
    facts = {4101: fact(4101, "keptT")}
    out = render(N, (reply((), (4101,), when=1), reply(None, None, when=2), reply((), (), when=3)), (), facts, ())
    assert out.count("memory unreachable") == 1 and "offered facts not logged" not in out
    assert "keptT" in out


def test_replies_come_oldest_first() -> None:
    out = render(N, (reply(when=1, kind="first"), reply(when=2, kind="second"), reply(when=3, kind="third")),
                 (), {}, ())
    assert out.index("first") < out.index("second") < out.index("third")
    assert out.index(stamp(at(1))) < out.index(stamp(at(2))) < out.index(stamp(at(3)))


def test_writes_show_the_facts_they_inserted_and_the_writer_model() -> None:
    facts = {5001: fact(5001, "learnedOne"), 5002: fact(5002, "learnedTwo"), 5003: fact(5003, "unrelated")}
    writers = ((stamp(at(9)), "anthropic", "claude-writer-x", "ok"),)
    out = render(N, (reply(when=1),), (write((5001, 5002), when=8, add=2),), facts, writers)
    assert "learnedOne" in out and "learnedTwo" in out and "unrelated" not in out
    assert "5001" in out and "5002" in out
    assert "claude-writer-x" in out and "anthropic" in out


def test_a_write_inserting_nothing_still_shows() -> None:
    out = render(N, (), (write((), when=8, noop=2, through=44),), {}, ())
    assert stamp(at(8)) in out


def test_every_writer_model_is_shown() -> None:
    writers = ((stamp(at(1)), "prov-a", "model-first", "invalid_output"), (stamp(at(2)), "prov-b", "model-second", "ok"))
    out = render(N, (), (write((5001,), when=3, add=1),), {5001: fact(5001, "learnedT")}, writers)
    assert "model-first" in out and "model-second" in out and "invalid_output" in out


def test_an_inserted_fact_since_forgotten_says_so() -> None:
    out = render(N, (), (write((5001,), when=3, add=1),), {}, ())
    assert any("forgotten" in ln for ln in containing(out, "5001"))


def test_an_inserted_fact_since_closed_says_so() -> None:
    facts = {5001: fact(5001, "madeT", valid_to=at(86400), superseded_by=5002), 5002: fact(5002, "madeAgainT")}
    out = render(N, (), (write((5001, 5002), when=3, add=2),), facts, ())
    assert "closed" in the_line(out, "madeT") and "replaced by [5002]" in the_line(out, "madeT")
    assert "closed" not in the_line(out, "madeAgainT")


def test_replies_and_writes_both_appear() -> None:
    facts = {4101: fact(4101, "askedT"), 5001: fact(5001, "madeT")}
    out = render(N, (reply((), (4101,), when=1),), (write((5001,), when=2, add=1),), facts, ())
    assert "askedT" in out and "madeT" in out


def test_nothing_found_is_one_line_naming_the_conversation() -> None:
    out = render(N, (), (), {}, ())
    assert len(out.strip().splitlines()) == 1 and str(N) in out


def test_a_found_reply_is_not_the_nothing_found_line() -> None:
    out = render(N, (reply(when=1),), (), {}, ())
    assert len(containing(out, stamp(at(1)))) >= 1
    assert out != render(N, (), (), {}, ())


def test_the_conversation_id_is_shown_when_something_was_found() -> None:
    assert str(N + 1000) in render(N + 1000, (reply(when=1),), (), {}, ())


def test_render_returns_text_and_does_not_mutate_its_arguments() -> None:
    facts = {4101: fact(4101, "askedT")}
    before = dict(facts)
    assert isinstance(render(N, (reply((), (4101,)),), (), facts, ()), str)
    assert facts == before
