"""Batched match decisions + scoped cascade re-aggregation.

Covers the behaviour that replaced the per-match transaction: one transaction
for the whole batch, and a cascade re-aggregation scoped to the input items
actually touched instead of a full-task rescan per match.
"""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from preprocessorEC.db import task_repo


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class FakeSession:
    """Serves canned result sets in the order the repo asks for them."""

    def __init__(self, result_sets):
        self._result_sets = list(result_sets)
        self.commits = 0

    def query(self, *entities):
        rows = self._result_sets.pop(0) if self._result_sets else []
        return FakeQuery(rows)

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def cascade_row(match_id, input_item_id, lineage, status="PENDING", bucket="HIGH"):
    return SimpleNamespace(
        match_id=match_id,
        task_id="3FBA",
        input_item_id=input_item_id,
        matched_source="INFOR_CL",
        match_type="CASCADE",
        ccx_pkid=None,
        ccx_pkids_matched=lineage,
        match_status=status,
        similarity_bucket=bucket,
        reviewed_by=None,
        reviewed_at=None,
    )


def ccx_row(match_id, input_item_id, pkid, status="PENDING", bucket="HIGH"):
    return SimpleNamespace(
        match_id=match_id,
        task_id="3FBA",
        input_item_id=input_item_id,
        matched_source="CCX",
        match_type="DIRECT",
        ccx_pkid=pkid,
        ccx_pkids_matched=None,
        match_status=status,
        similarity_bucket=bucket,
        reviewed_by=None,
        reviewed_at=None,
    )


class CascadeReaggregationTests(unittest.TestCase):
    """_reaggregate_cascade_for_input_items: aggregate + who gets stamped."""

    def _run(self, cascade_rows, ccx_rows, **kwargs):
        session = FakeSession([cascade_rows, ccx_rows])
        return task_repo._reaggregate_cascade_for_input_items(
            session,
            task_id="3FBA",
            input_item_ids={88},
            reviewed_by="tester",
            reviewed_at="NOW",
            **kwargs,
        )

    def test_all_sources_rejected_rejects_the_cascade(self):
        cascade = cascade_row(9100, 88, "41001, 41002")
        sources = [
            ccx_row(5002, 88, 41001, status="REJECTED"),
            ccx_row(5003, 88, 41002, status="REJECTED"),
        ]

        changed = self._run([cascade], sources)

        self.assertEqual(changed, 1)
        self.assertEqual(cascade.match_status, "REJECTED")
        self.assertEqual(cascade.reviewed_by, "tester")

    def test_one_accepted_source_keeps_the_link(self):
        cascade = cascade_row(9100, 88, "41001, 41002")
        sources = [
            ccx_row(5002, 88, 41001, status="REJECTED"),
            ccx_row(5003, 88, 41002, status="ACCEPTED"),
        ]

        changed = self._run([cascade], sources)

        self.assertEqual(changed, 1)
        self.assertEqual(cascade.match_status, "ACCEPTED")

    def test_unchanged_row_in_the_stamp_set_is_still_reviewed(self):
        # Deciding one source of a still-PENDING cascade counts as reviewing
        # that cascade row, which is what the per-match version did and what
        # keeps the row out of the next LLM batch.
        cascade = cascade_row(9100, 88, "41001, 41002", status="PENDING")
        sources = [
            ccx_row(5002, 88, 41001, status="REJECTED"),
            ccx_row(5003, 88, 41002, status="PENDING"),
        ]

        changed = self._run([cascade], sources, stamp_pkids_by_item={88: {41001}})

        self.assertEqual(changed, 0)                     # aggregate did not move
        self.assertEqual(cascade.match_status, "PENDING")
        self.assertEqual(cascade.reviewed_by, "tester")  # but it was reviewed
        self.assertEqual(cascade.reviewed_at, "NOW")

    def test_unchanged_row_outside_the_stamp_set_is_left_alone(self):
        cascade = cascade_row(9100, 88, "41001", status="PENDING")
        sources = [ccx_row(5002, 88, 41001, status="PENDING")]

        changed = self._run([cascade], sources, stamp_pkids_by_item={88: {49999}})

        self.assertEqual(changed, 0)
        self.assertIsNone(cascade.reviewed_by)

    def test_no_stamp_set_means_only_changed_rows_are_stamped(self):
        # The contract-decision path passes no stamp set; unchanged rows must
        # keep the reviewer they already had.
        cascade = cascade_row(9100, 88, "41001", status="PENDING")
        sources = [ccx_row(5002, 88, 41001, status="PENDING")]

        changed = self._run([cascade], sources)

        self.assertEqual(changed, 0)
        self.assertIsNone(cascade.reviewed_by)


class UpdateMatchDecisionsTests(unittest.TestCase):
    """update_match_decisions: one transaction, scoped re-aggregation."""

    def _apply(self, rows, match_ids, status="REJECTED"):
        session = FakeSession([rows])
        with patch.object(task_repo, "_session", return_value=session), \
             patch.object(task_repo, "_reaggregate_cascade_for_input_items") as reagg:
            updated = task_repo.update_match_decisions(match_ids, status, "tester")
        return updated, session, reagg

    def test_whole_batch_is_one_transaction(self):
        rows = [ccx_row(5002, 88, 41001), ccx_row(5003, 91, 41055)]

        updated, session, reagg = self._apply(rows, [5002, 5003])

        self.assertEqual(updated, 2)
        self.assertEqual(session.commits, 1)      # not one commit per match
        self.assertEqual(reagg.call_count, 1)     # not one rescan per match
        for row in rows:
            self.assertEqual(row.match_status, "REJECTED")
            self.assertEqual(row.reviewed_by, "tester")

    def test_reaggregation_is_scoped_to_the_touched_input_items(self):
        rows = [ccx_row(5002, 88, 41001), ccx_row(5003, 91, 41055)]

        _, _, reagg = self._apply(rows, [5002, 5003])

        kwargs = reagg.call_args.kwargs
        self.assertEqual(kwargs["task_id"], "3FBA")
        self.assertEqual(kwargs["input_item_ids"], {88, 91})
        self.assertEqual(kwargs["stamp_pkids_by_item"], {88: {41001}, 91: {41055}})

    def test_non_ccx_rows_do_not_trigger_re_aggregation(self):
        rows = [cascade_row(9100, 88, "41001")]

        updated, session, reagg = self._apply(rows, [9100])

        self.assertEqual(updated, 1)
        self.assertEqual(session.commits, 1)
        reagg.assert_not_called()

    def test_ids_are_deduped_and_ordered(self):
        # Ascending order so two concurrent batches queue rather than deadlock.
        seen = {}

        def fake_chunked(items, size=1000):
            seen["ids"] = list(items)
            yield items

        with patch.object(task_repo, "_chunked", fake_chunked):
            self._apply([], [5031, 5002, 5031, 5010])

        self.assertEqual(seen["ids"], [5002, 5010, 5031])

    def test_missing_rows_are_skipped_not_an_error(self):
        updated, session, reagg = self._apply([], [999999])

        self.assertEqual(updated, 0)
        self.assertEqual(session.commits, 0)
        reagg.assert_not_called()

    def test_empty_batch_short_circuits(self):
        with patch.object(task_repo, "_session") as session:
            self.assertEqual(
                task_repo.update_match_decisions([], "REJECTED", "tester"), 0
            )
        session.assert_not_called()


class DeadlockRetryTests(unittest.TestCase):
    """_with_deadlock_retry: rerun the victim, but only for real deadlocks."""

    def setUp(self):
        import pyodbc
        from sqlalchemy.exc import DBAPIError

        self.DBAPIError = DBAPIError
        self.deadlock = DBAPIError.instance(
            "SELECT 1",
            {},
            pyodbc.Error(
                "40001",
                "[40001] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]"
                "Transaction (Process ID 80) was deadlocked on lock resources "
                "with another process and has been chosen as the deadlock "
                "victim. Rerun the transaction. (1205) (SQLExecDirectW)",
            ),
            pyodbc.Error,
        )
        self.other = DBAPIError.instance(
            "SELECT 1",
            {},
            pyodbc.Error("42S02", "[42S02] Invalid object name 'nope'."),
            pyodbc.Error,
        )
        self._backoff = task_repo._DEADLOCK_BACKOFF_SECONDS
        task_repo._DEADLOCK_BACKOFF_SECONDS = 0

    def tearDown(self):
        task_repo._DEADLOCK_BACKOFF_SECONDS = self._backoff

    def test_recognises_the_victim_error(self):
        self.assertTrue(task_repo._is_deadlock(self.deadlock))
        self.assertFalse(task_repo._is_deadlock(self.other))

    def test_retries_until_it_succeeds(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 2:
                raise self.deadlock
            return "committed"

        self.assertEqual(task_repo._with_deadlock_retry(flaky), "committed")
        self.assertEqual(len(calls), 2)

    def test_gives_up_rather_than_looping_forever(self):
        calls = []

        def always():
            calls.append(1)
            raise self.deadlock

        with self.assertRaises(self.DBAPIError):
            task_repo._with_deadlock_retry(always)
        self.assertEqual(len(calls), task_repo._DEADLOCK_ATTEMPTS)

    def test_other_database_errors_are_not_retried(self):
        calls = []

        def broken():
            calls.append(1)
            raise self.other

        with self.assertRaises(self.DBAPIError):
            task_repo._with_deadlock_retry(broken)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
