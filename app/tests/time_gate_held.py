"""What `time_gate.py` excuses today. Both lists may only shrink: never add an entry to let a change through.
Each group waits on real time named beside it; the fix is an injected clock or a fake that answers at once, with
one smoke test left against the real service."""

HELD: frozenset[str] = frozenset({
    # the in-flight sweep's real timing
    "tests/test_bench_replay_eval.py::test_a_turn_kept_when_its_model_call_failed_is_finished_by_the_inflight_sweep",
    # a real etcd lease expiring on its TTL
    "tests/contract/test_contract_hold.py::test_a_short_hold_expires_on_its_own",
    # real etcd lease TTLs
    "tests/contract/test_contract_lease.py::test_exactly_one_of_three_holders_runs_the_body",
    "tests/contract/test_contract_lease.py::test_the_standby_takes_over_promptly_when_the_holder_is_cancelled",
    # real etcd lease TTLs and partitions
    "tests/contract/test_contract_lease_faults.py::test_a_partitioned_holder_leaves_its_body_time_to_clean_up_before_etcd_frees_the_key",
    "tests/contract/test_contract_lease_faults.py::test_a_partitioned_holder_stops_its_body_before_etcd_frees_the_key",
    "tests/contract/test_contract_lease_faults.py::test_a_revoked_lease_cancels_the_body_logs_the_loss_and_campaigns_again",
    "tests/contract/test_contract_lease_faults.py::test_a_run_cancelled_just_after_etcd_granted_it_the_key_leaves_no_key_behind",
    "tests/contract/test_contract_lease_faults.py::test_etcd_unreachable_is_logged_once_per_streak_and_carries_no_address",
    "tests/contract/test_contract_lease_faults.py::test_waiting_on_another_holder_is_logged_once_not_once_per_retry",
    # real etcd lease TTLs as leadership moves
    "tests/contract/test_contract_lease_site.py::test_a_site_that_is_not_active_logs_standby_once_per_wait",
    "tests/contract/test_contract_lease_site.py::test_the_leader_moving_away_cancels_the_body_and_frees_the_key_before_the_lease_could_expire",
    "tests/contract/test_contract_lease_site.py::test_the_standby_site_takes_over_when_leadership_moves",
    "tests/contract/test_contract_lease_site.py::test_two_sites_never_run_at_once_while_leadership_moves_back_and_forth",
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
