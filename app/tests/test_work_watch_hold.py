"""`POST /api/work/watches/{id}/pause` and `/resume` through the real app: a person pauses and resumes their own live watch
and the board shows it on hold; a watch that is another person's, another household's or over is 404 and stays as it was."""

from fastapi.testclient import TestClient
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, scalar
from test_work_board import ELSEWHERE, World, client as client, listed, watch, world as world


def held(w: World, watch_id: int) -> bool:
    return scalar(w.url, "SELECT held_at IS NOT NULL FROM watches WHERE id = %s", (watch_id,)) is True


def test_a_person_pauses_their_watch_the_board_shows_it_on_hold_and_resume_runs_it_again(world: World, client: TestClient) -> None:
    mine = watch(world, world.alana)
    r = client.post(f"/api/work/watches/{mine}/pause")
    assert (r.status_code, r.json()) == (200, {"id": mine, "on_hold": True})
    assert held(world, mine)
    assert [(i.id, i.state, i.lane) for i in listed(client)] == [(mine, "on_hold", "doing")]
    assert client.post(f"/api/work/watches/{mine}/pause").status_code == 200
    r = client.post(f"/api/work/watches/{mine}/resume")
    assert (r.status_code, r.json()) == (200, {"id": mine, "on_hold": False})
    assert not held(world, mine)
    assert [(i.id, i.state) for i in listed(client)] == [(mine, "running")]


def test_an_on_hold_watch_can_still_be_cancelled(world: World, client: TestClient) -> None:
    mine = watch(world, world.alana)
    assert client.post(f"/api/work/watches/{mine}/pause").status_code == 200
    assert client.delete(f"/api/work/watches/{mine}").status_code == 200
    assert listed(client) == []


def test_nobody_pauses_or_resumes_a_watch_they_could_not_cancel(world: World, client: TestClient) -> None:
    sams = watch(world, world.sam)
    strangers = watch(world, world.stranger, home=world.other_home)
    over = watch(world, world.alana, target="s9", state="ended")
    for found in (sams, strangers, over, 999999):
        for verb in ("pause", "resume"):
            assert client.post(f"/api/work/watches/{found}/{verb}").status_code == 404
    assert not any(held(world, w) for w in (sams, strangers, over))
    assert client.post(f"/api/work/watches/{sams}/pause", headers=ELSEWHERE).status_code == 403
    assert client.post("/api/work/watches/0/pause").status_code == 422
    client.cookies.clear()
    assert client.post(f"/api/work/watches/{sams}/pause").status_code == 401
