"""A recording `Live`: `publish` keeps every event; `subscribe` hands out a real `Fanout` subscription already holding
`scripted`, so a route test reads a stream with no feed behind it."""

from ashley.live.events import Event, Watcher
from ashley.live.fanout import Fanout, Resync, Subscription
from ashley.live.live import Live


class FakeLive(Live):
    def __init__(self, scripted: tuple[Event | Resync, ...] = ()) -> None:
        self.published: list[Event] = []
        self.viewers: list[Watcher] = []
        self.scripted = scripted
        self.fanout = Fanout(8)

    def publish(self, event: Event) -> None:
        self.published.append(event)

    def subscribe(self, viewer: Watcher) -> Subscription:
        self.viewers.append(viewer)
        subscription = self.fanout.subscription(viewer)
        for item in self.scripted:
            subscription.offer(item)
        return subscription
