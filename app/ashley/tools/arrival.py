"""Where one turn has taken the speaker's page: written by `open_bench` and `move_page` as they succeed, read by the
turn (`channels.landing`) between model steps. One per turn, gone when it ends."""


class Arrival:
    """`bench` is the bench the page is on after the turn's moves, None while it has not moved to one (or moved away
    to a room); `fresh` says that bench was opened in this same turn."""

    def __init__(self, bench: int | None = None) -> None:
        self._bench = bench
        self._opened: set[int] = set()

    @property
    def bench(self) -> int | None:
        return self._bench

    @property
    def fresh(self) -> bool:
        return self._bench is not None and self._bench in self._opened

    def opened(self, bench_id: int) -> None:
        """A bench was opened in this turn."""
        self._opened.add(bench_id)

    def moved(self, bench_id: int | None) -> None:
        """The page moved to bench `bench_id`, or to a room that is not a bench (None)."""
        self._bench = bench_id
