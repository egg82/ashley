"""Body and argument limits hold for Proton as for Gmail (design: "`max_body_chars` for a draft must fit
`max_argument_chars` in `app/ashley/tools/outside.json`", `max_recipients`, `max_change_ids`), and a call refused for its
arguments reaches neither Bridge socket."""

from mail_proton_blind_support import ALANA_ADDRESS, CONFIG, DRAFT, LABEL, M1, SEARCH, SEND, SUBJECTS, Box, World, data, failed, rows, snapshot, stock, target


def mine(**over: object) -> dict[str, object]:
    base: dict[str, object] = {"mailbox": ALANA_ADDRESS, "to": ["dana@club.test"], "subject": "Saturday", "body": "See you."}
    return {**base, **over}


def untouched(world: World, box: Box) -> None:
    assert world.bridge.smtp.attempts == 0 and box.account.present("Drafts") == [] and box.account.commands == []


def test_a_body_of_exactly_the_limit_is_sent_and_one_character_more_is_refused(world: World, alana: Box) -> None:
    data(world.turn().call(SEND, **mine(body="a" * CONFIG.max_body_chars)))
    assert len(world.bridge.smtp.delivered) == 1
    failed(world.turn().call(SEND, **mine(body="a" * (CONFIG.max_body_chars + 1))))
    assert world.bridge.smtp.attempts == 1


def test_a_draft_body_over_the_limit_is_refused_and_nothing_is_appended(world: World, alana: Box) -> None:
    failed(world.turn().call(DRAFT, **mine(body="a" * (CONFIG.max_body_chars + 1))))
    data(world.turn().call(DRAFT, **mine(body="a" * CONFIG.max_body_chars)))
    assert len(alana.account.present("Drafts")) == 1


def test_more_recipients_than_the_limit_are_refused_to_and_cc_together(world: World, alana: Box) -> None:
    many = [f"r{n}@club.test" for n in range(CONFIG.max_recipients + 1)]
    failed(world.turn().call(SEND, **mine(to=many)))
    failed(world.turn().call(SEND, **mine(to=many[:2], cc=many[2:])))
    untouched(world, alana)
    data(world.turn().call(SEND, **mine(to=many[:2], cc=many[2:CONFIG.max_recipients])))
    assert len(world.bridge.smtp.delivered[0].rcpts) == CONFIG.max_recipients


def test_a_label_call_over_the_id_limit_is_refused_and_changes_nothing(world: World, alana: Box) -> None:
    stock(alana)
    before = snapshot(alana)
    row = next(r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS)) if r["subject"] == SUBJECTS[M1])
    failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row)] * (CONFIG.max_change_ids + 1), add=["Receipts"]))
    assert snapshot(alana) == before
