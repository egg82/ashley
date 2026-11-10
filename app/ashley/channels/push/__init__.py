"""The web push channel (`decisions.md`, "Web push"): replies queued in the `Outbox` for a thread `push:<person id>` are
sent by one singleton under the lease `push` (`later`) to every browser that person subscribed (`subscriptions`), through
`sender`, the only module touching the Web Push library. Her VAPID identity comes from the settings (`config.vapid`);
tunables are data, `push.json`."""
