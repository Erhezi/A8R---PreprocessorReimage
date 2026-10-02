"""Relabeling items whose accepted Infor CL lineage changed after labeling.

The pipeline labels items before the reviewer decides MED/LOW matches, so an
Infor line accepted afterwards never reached Source 3. Finalize now relabels
exactly the items whose stored ``infor_item_3`` no longer matches their
accepted lineage, and leaves every other item's label and resolutions alone.
"""

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from preprocessorEC.services import preprocess_service


def input_item(item_id, infor_item_3=None):
    return SimpleNamespace(item_id=item_id, infor_item_3=infor_item_3, status="ITEM_PREPROCESSED")


class RefreshStaleItemLabelsTest(unittest.TestCase):
    def _run(self, items, accepted, items_by_pkid):
        repo = MagicMock()
        repo.get_item_matches.return_value = [
            SimpleNamespace(item_id=2, match_item_id=10, infor_item_number="112204"),
            SimpleNamespace(item_id=1, match_item_id=11, infor_item_number="102713"),
        ]
        label_items = MagicMock(return_value=([{"item_id": 2}], [], [{"item_id": 2}]))
        check_buy_uom = MagicMock(return_value=([{"item_id": 2}], [], [], 0))

        def live_items(task_id, item_ids=None):
            return [i for i in items if item_ids is None or i.item_id in item_ids]

        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "_live_input_items", side_effect=live_items), \
             patch.object(preprocess_service, "_accepted_infor_pkids_by_input", return_value=accepted), \
             patch.object(preprocess_service, "_sql_session", return_value=nullcontext()), \
             patch.object(preprocess_service, "_infor_items_by_pkid", return_value=items_by_pkid), \
             patch.object(preprocess_service, "_label_items", label_items), \
             patch.object(preprocess_service, "_check_buy_uom", check_buy_uom):
            result = preprocess_service.refresh_stale_item_labels("9B25")
        return result, repo, label_items, check_buy_uom

    def test_relabels_only_the_item_accepted_after_labeling(self):
        items = [
            input_item(1, infor_item_3="102713"),  # labeled, lineage unchanged
            input_item(2),                          # accepted after labeling
            input_item(3),                          # no Infor lineage at all
        ]
        accepted = {1: {"284-248"}, 2: {"1876-354"}}
        items_by_pkid = {"284-248": {"102713"}, "1876-354": {"112204"}}

        result, repo, label_items, check_buy_uom = self._run(items, accepted, items_by_pkid)

        self.assertEqual(result, {"relabeled": 1})
        self.assertEqual([i.item_id for i in label_items.call_args.args[2]], [2])
        repo.delete_unresolved_preprocess_issues.assert_called_once_with(
            "9B25", ["MULTI_ITEM_ERROR", "MFG_ONLY_ITEM_WARN", "BUY_UOM_ERROR"], item_ids=[2],
        )
        repo.delete_item_matches_for_items.assert_called_once_with("9B25", [2])
        # Buy-UOM only sees the relabeled item and its own candidates.
        self.assertEqual([i.item_id for i in check_buy_uom.call_args.args[2]], [2])
        self.assertEqual([c.match_item_id for c in check_buy_uom.call_args.args[3]], [10])

    def test_rejected_after_labeling_clears_the_label(self):
        items = [input_item(1, infor_item_3="102713")]

        result, _repo, label_items, _check = self._run(items, {}, {})

        self.assertEqual(result, {"relabeled": 1})
        self.assertEqual([i.item_id for i in label_items.call_args.args[2]], [1])

    def test_nothing_written_when_labels_are_current(self):
        items = [input_item(1, infor_item_3="102713"), input_item(3)]
        accepted = {1: {"284-248"}}

        result, repo, label_items, check_buy_uom = self._run(items, accepted, {"284-248": {"102713"}})

        self.assertEqual(result, {"relabeled": 0})
        label_items.assert_not_called()
        check_buy_uom.assert_not_called()
        repo.delete_unresolved_preprocess_issues.assert_not_called()
        repo.update_items_bulk.assert_not_called()


class RefreshAfterDecisionsTest(unittest.TestCase):
    """Accept/reject on the review screen relabels the items it touched."""

    def _state_machine(self, labeled=True):
        sm = MagicMock()
        sm.get_state.return_value = {"item_labeling_done": labeled}
        return sm

    def test_decided_matches_scope_the_refresh_to_their_items(self):
        repo = MagicMock()
        repo.get_input_item_ids_for_matches.return_value = {2, 5}
        refresh = MagicMock(return_value={"relabeled": 1})
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "refresh_stale_item_labels", refresh):
            result = preprocess_service.refresh_item_labels_after_decisions(
                "9B25", self._state_machine(), match_ids=[697918, 697931],
            )

        repo.get_input_item_ids_for_matches.assert_called_once_with([697918, 697931])
        refresh.assert_called_once_with("9B25", {2, 5})
        self.assertEqual(result, {"relabeled": 1})

    def test_nothing_runs_before_labeling_has(self):
        repo = MagicMock()
        refresh = MagicMock()
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "refresh_stale_item_labels", refresh):
            result = preprocess_service.refresh_item_labels_after_decisions(
                "9B25", self._state_machine(labeled=False), match_ids=[1],
            )

        self.assertEqual(result, {"relabeled": 0})
        repo.get_input_item_ids_for_matches.assert_not_called()
        refresh.assert_not_called()

    def test_no_items_touched_means_no_refresh(self):
        refresh = MagicMock()
        with patch.object(preprocess_service, "refresh_stale_item_labels", refresh):
            result = preprocess_service.refresh_item_labels_after_decisions(
                "9B25", self._state_machine(), item_ids=set(),
            )

        self.assertEqual(result, {"relabeled": 0})
        refresh.assert_not_called()

    def test_a_failed_refresh_does_not_fail_the_saved_decision(self):
        refresh = MagicMock(side_effect=RuntimeError("db busy"))
        with patch.object(preprocess_service, "refresh_stale_item_labels", refresh), \
             self.assertLogs(preprocess_service.logger, level="ERROR"):
            result = preprocess_service.refresh_item_labels_after_decisions(
                "9B25", self._state_machine(), item_ids={2},
            )

        self.assertEqual(result, {"relabeled": 0, "refresh_failed": True})


if __name__ == "__main__":
    unittest.main()
