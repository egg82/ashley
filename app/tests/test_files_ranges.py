"""A `Range` header over a file of known size: one range is clipped to the file, anything else is served whole, and a
range that cannot be met is said to be."""

import pytest
from ashley.files import ranges


@pytest.mark.parametrize("header,size,expected", [
    ("bytes=0-9", 100, (0, 9)), ("bytes=10-", 100, (10, 99)), ("bytes=-10", 100, (90, 99)),
    ("bytes=90-500", 100, (90, 99)), ("bytes=-500", 100, (0, 99)), ("bytes=99-99", 100, (99, 99)),
    ("bytes=0-", 1, (0, 0))])
def test_one_range_is_the_bytes_asked_clipped_to_the_file(header: str, size: int, expected: tuple[int, int]) -> None:
    assert ranges.parse(header, size) == expected


@pytest.mark.parametrize("header", [None, "", "bytes=", "bytes=-", "items=0-9", "bytes=0-9,20-29", "bytes=a-b", "0-9"])
def test_no_header_or_not_one_range_serves_the_whole_file(header: str | None) -> None:
    assert ranges.parse(header, 100) is None


@pytest.mark.parametrize("header", ["bytes=100-", "bytes=100-200", "bytes=50-40", "bytes=-0"])
def test_a_range_outside_the_file_is_unsatisfiable(header: str) -> None:
    assert ranges.parse(header, 100) == "unsatisfiable"
