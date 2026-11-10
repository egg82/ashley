"""`checkpoint.loads` raises ValueError or KeyError for text `dumps` did not write, as its docstring says."""

import pytest
from ashley.channels import checkpoint


@pytest.mark.parametrize("text", ["[]", "null", "1", '"x"', "{}", "not json"])
def test_text_dumps_did_not_write_is_a_value_or_key_error(text: str) -> None:
    with pytest.raises((ValueError, KeyError)):
        checkpoint.loads(text)
