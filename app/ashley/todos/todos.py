"""The Todos service (`ashley.services`): a household's to-do lists and their items as neutral records (`model`), from
every connection that serves the `todo` port and that the household has not switched off, labelled with its source; and
changes to an item, sent to the connection that holds the list. Callers import this module and `model`; adapters
implement `source.TodoSource`."""

from abc import abstractmethod

from ..services import Service
from .model import Board, Change, NotConnected


class Todos(Service):
    @classmethod
    def null(cls) -> "Todos":
        return NullTodos()

    @abstractmethod
    async def connected(self, household_id: int) -> bool:
        """Whether any of the household's connections serves to-do lists now. Raises TodosUnavailable."""

    @abstractmethod
    async def board(self, household_id: int, only: tuple[str, ...] | None = None) -> Board:
        """The lists of every serving connection (those whose id is in `only` when given) and their items. A source
        that fails is named in `Board.unread`, not raised. Raises NotConnected, TodosUnavailable. Logs `todo.read`
        with counts and duration_ms, never an item."""

    @abstractmethod
    async def change(self, household_id: int, list_id: str, change: Change) -> None:
        """Apply `change` to the list `list_id` of the connection that holds it. Raises NoSuchList, NotConnected,
        TodosUnavailable, TodosFailed. Logs `todo.change` with the op, source and duration_ms, never an item."""


class NullTodos(Todos):
    """No household has a to-do source."""

    async def connected(self, household_id: int) -> bool:
        return False

    async def board(self, household_id: int, only: tuple[str, ...] | None = None) -> Board:
        raise NotConnected

    async def change(self, household_id: int, list_id: str, change: Change) -> None:
        raise NotConnected

