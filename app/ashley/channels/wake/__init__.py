"""Home Assistant waking her (`decisions.md`, "Home Assistant wakes her; she decides"): the wakes HA hands in through
`/api/wakes` (`ashley.senses.wakes`) are taken up by the `wakes` singleton (`runner`), which finds each event's wake
rule on a bench (`rule`) and runs her own turn on it (`wake_turn`), whose reply goes out only when `Initiative` says."""
