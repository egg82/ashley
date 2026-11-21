"""One service's to-do lists, behind the Todos port: the adapter contract. The router (`ashley.todos.routed`) chooses
which connections are asked."""

from abc import ABC, abstractmethod

from ..connections.model import Opened
from .model import Change, TodoItem, TodoList


class TodoSource(ABC):
    @abstractmethod
    async def lists(self, opened: Opened) -> tuple[TodoList, ...]:
        """The lists the connection reaches. Raises TodosFailed."""

    @abstractmethod
    async def items(self, opened: Opened, lists: tuple[TodoList, ...]) -> tuple[TodoItem, ...]:
        """Every item, done or not, of `lists` (as `lists` listed them), in the order the service keeps them. Raises
        TodosFailed."""

    @abstractmethod
    async def change(self, opened: Opened, todo_list: TodoList, change: Change) -> None:
        """Apply `change` to `todo_list`. Raises TodosFailed."""
