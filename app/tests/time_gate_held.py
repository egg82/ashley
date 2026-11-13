"""What `time_gate.py` excuses today. Both lists may only shrink: never add an entry to let a change through.
Each group waits on real time named beside it; the fix is an injected clock or a fake that answers at once, with
one smoke test left against the real service."""

HELD: frozenset[str] = frozenset({
    # the in-flight sweep's real timing
    "tests/test_bench_replay_eval.py::test_a_turn_kept_when_its_model_call_failed_is_finished_by_the_inflight_sweep",
    # a resumed turn's real claim and resume timing
    "tests/inflight_rest_blind/test_irb_memory.py::test_a_forget_cut_off_while_it_ran_after_a_resumed_answer_is_not_made_again_nor_the_answer_queued_again",
    # a fence timed by the database's clock
    "tests/mail_bridge_blind/test_mb_job_epoch.py::test_two_bridges_never_run_from_one_vault_a_cut_off_pod_that_keeps_heartbeating_is_retired_and_its_write_back_refused",
    # the keeper's real heartbeat and fence seconds
    "tests/mail_bridge_blind/test_mb_keeper_program.py::test_no_heartbeat_answered_for_fence_s_stops_Bridge_but_not_a_moment_sooner",
    "tests/mail_bridge_blind/test_mb_keeper_program.py::test_the_keeper_heartbeats_about_every_heartbeat_s",
    # a real retry backoff the sweep waits out
    "tests/no_silent_endings/test_unreachable_kept.py::test_a_turn_unreachable_past_max_attempts_is_given_up_and_the_person_told_it_failed",
    "tests/no_silent_endings/test_unreachable_kept.py::test_the_line_is_stored_once_the_work_kept_and_the_sweep_waits_out_the_backoff",
    # the site keeper's real poll interval
    "tests/warm_look_blind/test_wl_site_keeper.py::test_the_null_lease_never_starts_the_keeper",
})
HELD_SHARED: frozenset[str] = frozenset()
