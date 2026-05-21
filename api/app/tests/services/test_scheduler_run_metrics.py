"""Tests for the track_scheduler_run context manager.

Pins ok/error outcome handling and re-raise semantics so a buggy
instrumentation can't silently swallow scheduler exceptions.
"""

from __future__ import annotations

import pytest

from app.core.metrics import (
    SCHEDULER_OUTCOME_ERROR,
    SCHEDULER_OUTCOME_OK,
    SCHEDULER_RUN_DURATION,
    SCHEDULER_RUNS,
    track_scheduler_run,
)


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def _histogram_count(histogram, **labels) -> float:
    suffix = f"{histogram._name}_count"
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name == suffix and sample.labels == labels:
                return sample.value
    return 0.0


def test_records_ok_on_clean_exit():
    task = "_test_track_ok"
    before_counter = _counter_value(
        SCHEDULER_RUNS, task=task, outcome=SCHEDULER_OUTCOME_OK
    )
    before_hist = _histogram_count(SCHEDULER_RUN_DURATION, task=task)

    with track_scheduler_run(task):
        pass

    assert (
        _counter_value(SCHEDULER_RUNS, task=task, outcome=SCHEDULER_OUTCOME_OK)
        == before_counter + 1
    )
    assert _histogram_count(SCHEDULER_RUN_DURATION, task=task) == before_hist + 1


def test_records_error_and_reraises():
    task = "_test_track_error"
    before_ok = _counter_value(SCHEDULER_RUNS, task=task, outcome=SCHEDULER_OUTCOME_OK)
    before_err = _counter_value(
        SCHEDULER_RUNS, task=task, outcome=SCHEDULER_OUTCOME_ERROR
    )

    with pytest.raises(ValueError, match="boom"):
        with track_scheduler_run(task):
            raise ValueError("boom")

    # error path must record once on the error label and not touch the ok label
    assert (
        _counter_value(SCHEDULER_RUNS, task=task, outcome=SCHEDULER_OUTCOME_OK)
        == before_ok
    )
    assert (
        _counter_value(SCHEDULER_RUNS, task=task, outcome=SCHEDULER_OUTCOME_ERROR)
        == before_err + 1
    )
