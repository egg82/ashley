"""Defects found by the blind run, fixed: a site or video piece changes only through `bench_edit`, so bench_replace is
refused rather than skipping the URL check."""

from refb_support import EDITED, OTHER, error_code, rig


def test_bench_replace_cannot_swap_a_site_piece_for_a_url_she_composed() -> None:
    r = rig("site")
    assert not r.call("bench_read_piece", piece_id=EDITED).is_error
    got = r.call("bench_replace", piece_id=EDITED, base_version=1, old="https://example.org/edited", new=OTHER)
    assert error_code(got, "bad_arguments"), got.content
    assert r.shop.applied == []
