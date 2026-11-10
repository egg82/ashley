"""The documented upload size, through the real route with the shipped `files.json`: a body of exactly `max_bytes` is
stored whole, and one byte more is refused `too_large` with nothing stored. Nothing in front of the app is tested here;
uvicorn and Starlette set no body limit of their own."""

from files_support import PNG
from ashley.api.models import ErrorResponse
from ashley.api.workshop_models import CommandApplied
from ashley.workshop import bench_file
from respond_support import ALANA
from test_bench_files_routes import Box, box as box, db_url as db_url, detail, migrated_template as migrated_template, upload, wired as wired
from test_workshop_routes import opened


def sized(n: int) -> bytes:
    return PNG + b"\x00" * (n - len(PNG))


def test_a_body_of_exactly_the_documented_limit_is_stored_whole(box: Box) -> None:
    limit = bench_file.CONFIG.max_bytes
    assert limit == 25 * 1024 * 1024
    client = box(ALANA)
    bench = opened(client)
    status, body = upload(client, bench.id, sized(limit), "big.png", "image/png")
    assert status == 200
    piece = next(p for p in detail(client, bench.id).pieces if p.id == CommandApplied.model_validate(body).piece_id)
    assert piece.file is not None and piece.file.size_bytes == limit
    assert [len(v) for v in box.store.objects.values()] == [limit]


def test_a_body_one_byte_over_the_documented_limit_is_refused_and_nothing_is_stored(box: Box) -> None:
    limit = bench_file.CONFIG.max_bytes
    client = box(ALANA)
    bench = opened(client)
    status, body = upload(client, bench.id, sized(limit + 1), "big.png", "image/png")
    assert (status, ErrorResponse.model_validate(body).code) == (413, "too_large")
    assert box.store.objects == {} and detail(client, bench.id).pieces == []
