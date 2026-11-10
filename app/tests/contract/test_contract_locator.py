"""Service locator contract (`ashley.services`): Null Object defaults, refusal of foreign providers, unregister."""

from pathlib import Path
from typing import Any, ClassVar

import pytest
from ashley import services
from ashley.db.database import Database, NullDatabase
from ashley.services import Service
from hypothesis import given
from hypothesis import strategies as st


register_untyped: Any = services.register


class Greeter(Service):
    NULL: ClassVar["Greeter | None"] = None

    def hello(self) -> str:
        return "real"

    @classmethod
    def null(cls) -> "Greeter":
        return NullGreeter()


class NullGreeter(Greeter):
    def hello(self) -> str:
        return "null"


class Other(Service):
    @classmethod
    def null(cls) -> "Other":
        return Other()


class LoudGreeter(Greeter):
    def hello(self) -> str:
        return "LOUD"


@pytest.fixture(autouse=True)
def clean() -> Any:
    services.unregister(Greeter)
    services.unregister(Other)
    yield
    services.unregister(Greeter)
    services.unregister(Other)


def test_unregistered_interface_answers_its_null_object() -> None:
    assert isinstance(services.get(Greeter), NullGreeter)
    assert services.get(Greeter).hello() == "null"


def test_the_null_object_is_the_same_one_each_time() -> None:
    assert services.get(Greeter) is services.get(Greeter)
    assert services.get(Database) is services.get(Database)


def test_database_unwired_is_a_null_database() -> None:
    assert isinstance(services.get(Database), NullDatabase)


def test_a_registered_provider_is_what_get_answers() -> None:
    provider = Greeter()
    services.register(Greeter, provider)
    assert services.get(Greeter) is provider


def test_a_subclass_instance_is_accepted() -> None:
    provider = LoudGreeter()
    services.register(Greeter, provider)
    assert services.get(Greeter) is provider


def test_unregister_falls_back_to_a_null_object_that_then_stays_the_same() -> None:
    services.register(Greeter, Greeter())
    services.unregister(Greeter)
    assert isinstance(services.get(Greeter), NullGreeter)
    assert services.get(Greeter) is services.get(Greeter)


def test_unregister_falls_back_to_the_same_null_object_as_before() -> None:
    before = services.get(Greeter)
    services.register(Greeter, Greeter())
    services.unregister(Greeter)
    assert services.get(Greeter) is before


def test_unregister_of_an_unregistered_interface_is_harmless() -> None:
    services.unregister(Greeter)
    assert isinstance(services.get(Greeter), NullGreeter)


def test_registering_one_interface_leaves_others_on_their_null_objects() -> None:
    services.register(Greeter, Greeter())
    assert isinstance(services.get(Other), Other)
    assert services.get(Other) is services.get(Other)


def test_a_provider_of_another_interface_is_refused() -> None:
    with pytest.raises(Exception):
        register_untyped(Greeter, Other())
    assert isinstance(services.get(Greeter), NullGreeter)


@pytest.mark.parametrize("thing", [None, 0, -7, "", "greeter", [], [1, 2], Greeter, object()])
def test_anything_that_is_not_an_instance_is_refused_and_changes_nothing(thing: object) -> None:
    services.unregister(Greeter)
    with pytest.raises(Exception):
        register_untyped(Greeter, thing)
    assert isinstance(services.get(Greeter), NullGreeter)


@given(st.lists(st.sampled_from(["register", "unregister"]), min_size=1, max_size=12))
def test_get_answers_the_last_registration_else_the_null_object(ops: list[str]) -> None:
    services.unregister(Greeter)
    current: Greeter | None = None
    for op in ops:
        if op == "register":
            current = Greeter()
            services.register(Greeter, current)
        else:
            current = None
            services.unregister(Greeter)
        got = services.get(Greeter)
        assert got is current if current is not None else isinstance(got, NullGreeter)


def test_registrations_do_not_leak_between_tests(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two ordered tests in one real pytest session under the suite's own conftest: the first registers a Database,
    the second must see the Null Object. A nested in-process session, so the suite's `-n 4` cannot reorder them and
    nothing is imported twice."""
    here = Path(__file__).resolve().parent
    pytester.makeconftest((here.parent / "conftest.py").read_text())
    pytester.makepyfile(test_leak_probe=(here / "leak_probe.py").read_text())
    monkeypatch.setenv("LEAK_PROBE", "1")
    result = pytester.runpytest_inprocess("-o", "addopts=", "-p", "no:xdist", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)
