"""What she is told on a bench she has just opened in this turn for something the person asked to work on."""


def lead(adds: int) -> str:
    """The guidance for a fresh arrival, naming how many pieces she may add before the person has said anything
    (`bench_tools.json`, `lead_adds`); `BenchTools` refuses the next add `ask_first`."""
    return (
        "You just opened this bench for what the person asked, so lead and do the work now, in this turn. Put at most "
        f"{adds} pieces on it: a bench that opens full is more than a person can take in, and a further bench_add is "
        "refused ask_first. Choose the ones that matter most. First look at what already exists (for an automation, list "
        "the house's automations and read the ones that bear on this; for a list or a plan, what the person has told "
        "you or you know of them; for a topic the world already knows, a known problem, technique, product or place, "
        "ask look_up for the best page or video about it). Then put on the bench your draft of what they asked for and, "
        "only if it earns the place, the one best thing that already exists: an automation piece with the body the "
        "house gives, or a site or video piece put up by its result number, one specific page or video and never a "
        "search page; when no result is the thing itself, put none up. A draft that is code is one of the pieces; "
        "run it. Anything else that would help, say in a line and let the person say yes. Decide what can be decided: "
        "make the reasonable choices yourself and record each choice as a choice row, guessed, with its options. Ask "
        "only about a choice that is genuinely the person's (a preference, a trade-off with no right answer), at most one or two, once the draft is on the "
        "bench. If the bench's title is only the start of what they asked (bench_read shows it), give it a short name "
        "with bench_rename in this first turn.")
