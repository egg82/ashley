from ashley import services


class Thing(services.Service):
    @classmethod
    def null(cls) -> "Thing":
        return Thing()


class Marked(Thing):
    pass


def test_a_registration_is_left_behind() -> None:
    services.register(Thing, Marked())
    assert type(services.get(Thing)) is Marked


def test_the_next_test_sees_the_default() -> None:
    """Pairs with the test above, which runs first (file order) and leaves `Thing` registered."""
    assert type(services.get(Thing)) is Thing
