"""Tests for app/pipeline_state.py, the in-memory run flag behind
POST /pipeline/run.

The flag is deliberately not persisted, so a restart mid-run self-heals. The
failure mode it has to be protected against is the opposite one: a run that
never calls finish() leaves `running` True forever, and every later trigger
returns 'already_running' until the process is restarted.
"""
import threading

from app import pipeline_state


def test_first_start_claims_the_slot():
    assert pipeline_state.try_start() is True
    assert pipeline_state.snapshot()['running'] is True


def test_second_start_is_refused_while_running():
    assert pipeline_state.try_start() is True
    assert pipeline_state.try_start() is False


def test_finish_releases_the_slot():
    pipeline_state.try_start()
    pipeline_state.finish('success', details={'inserted': 1, 'updated': 2})
    snapshot = pipeline_state.snapshot()
    assert snapshot['running'] is False
    assert snapshot['last_result'] == 'success'
    assert snapshot['last_details'] == {'inserted': 1, 'updated': 2}
    assert pipeline_state.try_start() is True


def test_start_clears_the_previous_outcome():
    """Otherwise the frontend's status poll picks up the *previous* run's result
    and reports it as this run's."""
    pipeline_state.finish('error', 'something broke', details={'inserted': 9})
    pipeline_state.try_start()
    snapshot = pipeline_state.snapshot()
    assert snapshot['last_result'] is None
    assert snapshot['last_error'] is None
    assert snapshot['last_details'] is None


def test_snapshot_shape():
    """GET /pipeline/status returns this dict verbatim; RefreshDataButton reads
    `running`, `last_result`, `last_error` and `last_details`."""
    assert set(pipeline_state.snapshot()) == {
        'running', 'last_result', 'last_error', 'last_details',
    }


def test_exactly_one_of_many_concurrent_starts_wins():
    """FastAPI runs sync handlers on a thread pool, so two clicks can land in
    parallel handlers. The lock is what stops both from kicking off a run."""
    results = []
    barrier = threading.Barrier(20)

    def claim():
        barrier.wait()
        results.append(pipeline_state.try_start())

    threads = [threading.Thread(target=claim) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    assert results.count(False) == 19
