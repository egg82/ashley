"""Hybrid recall and `similar` on PostgresMemory over a migrated database, with the embeddings dictated by the test:
visibility never widened by vectors, text matches then vector-only ones, the fallback when the embedder is down.
Written blind from the `Memory` and `RecallPolicy` docstrings."""

import pytest
from ashley import services
from ashley.inference.inference import Inference
from ashley.memory.model import Add, Asker, Forget, Invalidate, Update
from ashley.memory.recall_policy import RecallPolicy

from conversations_support import household, person, run, scalar
from hybrid_support import AT, LATER, Dictated, conversation_of, fact, memory_with
from memory_support import conversation, say

QUERY = "bin schedule"
NEAR = {0: 1.0}


def test_vectors_never_widen_who_hears_what(db_url: str) -> None:
    """Every fact is nearest to the query and shares no word with it; only the filter decides."""
    home, other = household(db_url), household(db_url, "other")
    alana, elodie, zed = person(db_url, home, "alana"), person(db_url, home, "elodie"), person(db_url, other, "zed")
    talk, foreign = conversation(db_url, home), conversation(db_url, other)
    names = ["house", "a-shared", "a-private", "e-shared", "e-discreet", "e-private", "old", "gone", "forgotten"]
    texts = {n: f"{n} xyzzy" for n in names} | {"new": "new xyzzy", "z": "z xyzzy"}
    inference = Dictated({QUERY: NEAR} | {t: {0: 1.0, 1: 0.2} for t in texts.values()})

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 50)) as memory:
            made = await memory.apply(home, talk, [
                Add(fact(texts["house"])), Add(fact(texts["a-shared"], alana)),
                Add(fact(texts["a-private"], alana, "private")), Add(fact(texts["e-shared"], elodie)),
                Add(fact(texts["e-discreet"], elodie, "discreet")), Add(fact(texts["e-private"], elodie, "private")),
                Add(fact(texts["old"], alana)), Add(fact(texts["gone"], alana)), Add(fact(texts["forgotten"], alana))], AT)
            ids = dict(zip(names, made, strict=True))
            [new] = await memory.apply(home, talk, [Update(ids["old"], fact(texts["new"], alana))], AT.replace(day=2))
            await memory.apply(home, talk, [Invalidate(ids["gone"]), Forget(ids["forgotten"])], AT.replace(day=2))
            await memory.apply(other, foreign, [Add(fact(texts["z"], zed))], AT)
            ids["new"] = new
            everyone = {"house", "a-shared", "e-shared", "new"}
            wanted = {
                (None, False): everyone, (None, True): everyone,
                (alana, False): everyone | {"e-discreet"}, (alana, True): everyone | {"e-discreet", "a-private"},
                (elodie, False): everyone | {"e-discreet"}, (elodie, True): everyone | {"e-discreet", "e-private"},
            }
            by_id = {v: k for k, v in ids.items()}
            for (speaker, owner_only), names_wanted in wanted.items():
                got = await memory.recall(Asker(home, speaker, owner_only, LATER), QUERY)
                assert {by_id[r.fact.id] for r in got} == names_wanted, (speaker, owner_only)
                assert len(got) == len({r.fact.id for r in got})
                for r in got:
                    volunteer = not (r.fact.visibility == "discreet" and r.fact.owner_id != speaker)
                    assert r.may_volunteer is volunteer, (speaker, by_id[r.fact.id])

    run(scenario())


def _union_inference() -> tuple[Dictated, dict[str, str]]:
    texts = {"text": "Tuesday chess club", "both": "Tuesday recycling pickup", "near": "Bins out evenings",
             "mid": "Bins by the gate", "far": "Bins in winter", "junk": "Alana plays piano"}
    table = {"tuesday": NEAR, texts["text"]: {5: 1.0}, texts["both"]: {0: 1.0, 1: 5.0},
             texts["near"]: {0: 1.0, 1: 0.1}, texts["mid"]: {0: 1.0, 1: 0.5}, texts["far"]: {0: 1.0, 1: 2.0},
             texts["junk"]: {7: 1.0}}
    return Dictated(table), texts


def test_text_matches_come_first_then_the_nearest_vector_only_ones_each_once(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference, texts = _union_inference()

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 2)) as memory:
            ids = dict(zip(texts, await memory.apply(home, talk, [Add(fact(t)) for t in texts.values()], AT), strict=True))
            got = await memory.recall(Asker(home, None, False, LATER), "tuesday")
            order = [r.fact.id for r in got]
            assert set(order[:2]) == {ids["text"], ids["both"]}
            assert order[2:] == [ids["near"], ids["mid"]]

    run(scenario())


def test_with_no_text_match_the_vector_matches_alone_come_back_nearest_first(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference, texts = _union_inference()

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 3)) as memory:
            ids = dict(zip(texts, await memory.apply(home, talk, [Add(fact(t)) for t in texts.values()], AT), strict=True))
            inference.table = {**inference.table, "umbrella": NEAR}
            got = await memory.recall(Asker(home, None, False, LATER), "umbrella")
            assert [r.fact.id for r in got] == [ids["near"], ids["mid"], ids["far"]]

    run(scenario())


def test_the_policy_caps_text_matches_and_a_zero_vector_k_adds_nothing(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({"kettle": NEAR, "kettle one": {5: 1.0}, "kettle two": {5: 1.0}, "kettle three": {5: 1.0},
                          "Radio hums": NEAR})

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(2, 0)) as memory:
            ids = await memory.apply(home, talk, [Add(fact(t)) for t in
                                                  ("kettle one", "kettle two", "kettle three", "Radio hums")], AT)
            got = await memory.recall(Asker(home, None, False, LATER), "kettle")
            assert len(got) == 2 and {r.fact.id for r in got} <= set(ids[:3])

    run(scenario())


@pytest.mark.parametrize("failure", ["down", "unwired"])
def test_without_an_embedder_recall_and_similar_answer_by_full_text(db_url: str, failure: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({"tuesday": NEAR, "Tuesday chess club": {5: 1.0}, "Bins out evenings": NEAR})
    say(db_url, talk, "tuesday")

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 3)) as memory:
            first, _ = await memory.apply(home, talk, [Add(fact("Tuesday chess club")),
                                                         Add(fact("Bins out evenings"))], AT)
            seen = conversation_of(home, talk, [("person", "tuesday")])
            if failure == "down":
                inference.down = True
            else:
                services.unregister(Inference)
            got = await memory.recall(Asker(home, None, False, LATER), "tuesday")
            assert [r.fact.id for r in got] == [first]
            assert [f.id for f in await memory.similar(seen, 10)] == [first]

    run(scenario())


def _near_set() -> tuple[Dictated, dict[str, str]]:
    texts = {"both": "Tuesday recycling pickup", "v1": "Bins out evenings", "v2": "Bins by the gate",
             "v3": "Bins in winter", "t1": "Tuesday chess club", "t2": "Tuesday swim", "t3": "Tuesday choir"}
    table = {"tuesday": NEAR, texts["both"]: {0: 1.0, 1: 0.05}, texts["v1"]: {0: 1.0, 1: 0.1},
             texts["v2"]: {0: 1.0, 1: 0.5}, texts["v3"]: {0: 1.0, 1: 2.0}, texts["t1"]: {5: 1.0},
             texts["t2"]: {5: 1.0}, texts["t3"]: {5: 1.0}}
    return Dictated(table), texts


def test_a_fact_that_is_both_a_word_match_and_among_the_nearest_comes_back_once(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference, texts = _near_set()
    said = conversation_of(home, talk, [("person", "tuesday")])

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 2)) as memory:
            ids = dict(zip(texts, await memory.apply(home, talk, [Add(fact(t)) for t in texts.values()], AT), strict=True))
            recalled = [r.fact.id for r in await memory.recall(Asker(home, None, False, LATER), "tuesday")]
            similar = [f.id for f in await memory.similar(said, 10)]
            for got in (recalled, similar):
                assert len(got) == len(set(got)) and got.count(ids["both"]) == 1
                assert {ids["t1"], ids["t2"], ids["t3"], ids["both"]} <= set(got)
                assert set(got) - {ids["t1"], ids["t2"], ids["t3"], ids["both"]} <= {ids["v1"], ids["v2"]}

    run(scenario())


def test_similar_returns_up_to_limit_word_matches_plus_up_to_vector_k_nearest(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference, texts = _near_set()
    said = conversation_of(home, talk, [("person", "tuesday")])
    wanted = ["v1", "v2", "v3", "t1", "t2", "t3"]

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 2)) as memory:
            ids = dict(zip(wanted, await memory.apply(home, talk, [Add(fact(texts[n])) for n in wanted], AT), strict=True))
            got = [f.id for f in await memory.similar(said, 2)]
            assert len(got) == len(set(got)) == 4
            assert len({ids["t1"], ids["t2"], ids["t3"]} & set(got)) == 2
            assert {ids["v1"], ids["v2"]} <= set(got) and ids["v3"] not in got

    run(scenario())


def test_a_fact_embedded_by_another_model_is_never_a_vector_match(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({"tuesday": NEAR, "Control evenings": NEAR, "Stranger evenings": {5: 1.0}})
    said = conversation_of(home, talk, [("person", "tuesday")])

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 5)) as memory:
            control, stranger = await memory.apply(home, talk, [Add(fact("Control evenings")),
                                                                Add(fact("Stranger evenings"))], AT)
            literal = "[" + ",".join(repr(x) for x in inference.vector("tuesday")) + "]"
            scalar(db_url, "UPDATE facts SET embedding = %s::vector, embedding_model = 'another-model' "
                           "WHERE id = %s RETURNING id", (literal, stranger))
            got = [r.fact.id for r in await memory.recall(Asker(home, None, False, LATER), "tuesday")]
            assert control in got and stranger not in got
            assert stranger not in [f.id for f in await memory.similar(said, 10)]

    run(scenario())
