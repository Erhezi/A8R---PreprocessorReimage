"""Connection-drop retry for read-only SQL Server work.

ODBC reports a reset link as 08S01 and can raise it mid-fetch, after the
statement has already started streaming rows. ``pool_pre_ping`` cannot help
there — it only validates at checkout — so reads that must survive a flaky
link wrap themselves in ``with_disconnect_retry``.
"""

import unittest
from unittest.mock import patch

from sqlalchemy.exc import OperationalError, ProgrammingError

from preprocessorEC.db.engine import with_disconnect_retry


def _disconnect_error():
    """An 08S01 the way SQLAlchemy hands it up after invalidating the pool."""
    err = OperationalError(
        "SELECT 1",
        {},
        Exception(
            "('08S01', '[08S01] [Microsoft][ODBC Driver 17 for SQL Server]"
            "TCP Provider: An existing connection was forcibly closed by the "
            "remote host. (10054) (SQLGetData)')"
        ),
    )
    err.connection_invalidated = True
    return err


class DisconnectRetryTests(unittest.TestCase):
    def setUp(self):
        # Keep the backoff from actually sleeping through the suite.
        patcher = patch("preprocessorEC.db.engine.time.sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_value_without_retrying_when_nothing_drops(self):
        calls = []

        def op():
            calls.append(1)
            return "rows"

        self.assertEqual(with_disconnect_retry(op), "rows")
        self.assertEqual(len(calls), 1)
        self.sleep.assert_not_called()

    def test_reruns_the_whole_operation_after_a_drop(self):
        calls = []

        def op():
            calls.append(1)
            if len(calls) == 1:
                raise _disconnect_error()
            return "rows"

        self.assertEqual(with_disconnect_retry(op), "rows")
        self.assertEqual(len(calls), 2)

    def test_gives_up_after_the_attempt_budget(self):
        calls = []

        def op():
            calls.append(1)
            raise _disconnect_error()

        with self.assertRaises(OperationalError):
            with_disconnect_retry(op, attempts=3)
        self.assertEqual(len(calls), 3)

    def test_backs_off_exponentially_between_attempts(self):
        def op():
            raise _disconnect_error()

        with self.assertRaises(OperationalError):
            with_disconnect_retry(op, attempts=3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [0.5, 1.0])

    def test_does_not_retry_a_live_connection_error(self):
        """A syntax/permission error is not a disconnect — fail fast."""
        calls = []

        def op():
            calls.append(1)
            raise ProgrammingError("SELECT bogus", {}, Exception("Invalid column name"))

        with self.assertRaises(ProgrammingError):
            with_disconnect_retry(op)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
