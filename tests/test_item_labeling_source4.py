"""Source 4 of Item# labeling: MDM_ITEM by manufacturer part number alone.

Source 4 is a fallback, consulted only for items Sources 1-3 left empty, and
every label it proposes is held as a MFG_ONLY_ITEM_WARN issue until a reviewer
keeps it (Noted) or detaches it.
"""

from contextlib import nullcontext
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from preprocessorEC.services import preprocess_service
from preprocessorEC.state import Status


class FakeStmt:
    def __init__(self, name):
        self.name = name

    def bindparams(self, *args, **kwargs):
        return self


def fake_load_query(blueprint, file, query=None):
    return FakeStmt(query)


def input_item(item_id, mfg, vpn=None):
    return SimpleNamespace(
        item_id=item_id,
        mfg_catalog_num=mfg,
        vendor_catalog_num=vpn,
        vendor_id_short=None,
    )


class LabelItemsSource4Test(unittest.TestCase):
    def _label(self, items, source_1_rows=(), source_3_by_pkid=None, accepted=None, source_4_rows=()):
        source_4_asked = []

        def expanding(sess, stmt, bind_name, values, extra=None):
            if stmt.name == "item_label_mdm_item_set":
                return list(source_1_rows)
            if stmt.name == "item_label_mdm_item_by_mfg_num_set":
                source_4_asked.extend(values)
                return [row for row in source_4_rows if row["ManufacturerNumber"] in values]
            if stmt.name == "item_descriptions_by_item_numbers":
                return []
            raise AssertionError(f"unexpected query {stmt.name}")

        task = SimpleNamespace(contract_manufacturer_infor="1297", vendor_id="1000931")
        with patch.object(preprocess_service, "_sql_session", return_value=nullcontext(MagicMock())), \
             patch.object(preprocess_service, "load_query", fake_load_query), \
             patch.object(preprocess_service, "_execute_expanding_batches", side_effect=expanding), \
             patch.object(preprocess_service, "_execute_two_expanding_batches", return_value=[]), \
             patch.object(preprocess_service, "_infor_items_by_pkid", return_value=source_3_by_pkid or {}):
            updates, issues, match_rows = preprocess_service._label_items(
                "9B25", task, items, accepted or {},
            )
        return {u["item_id"]: u for u in updates}, issues, match_rows, source_4_asked

    def test_only_items_with_sources_1_to_3_empty_ask_source_4(self):
        items = [input_item(1, "M00509911"), input_item(2, "CH40NBF"), input_item(3, "ACTC1525")]
        by_id, issues, match_rows, asked = self._label(
            items,
            source_3_by_pkid={"1361-322": {"102989"}},
            accepted={2: {"1361-322"}},
            source_4_rows=[
                {"Manufacturer": "1100", "ManufacturerName": "AVANOS", "ManufacturerNumber": "M00509911",
                 "Item": "112204", "mdm_description": "TUBE 18FR"},
                {"Manufacturer": "1111", "ManufacturerName": "X", "ManufacturerNumber": "CH40NBF",
                 "Item": "102989", "mdm_description": "CONTAINER"},
            ],
        )

        self.assertEqual(sorted(asked), ["ACTC1525", "M00509911"])  # item 2 has a contract-line Item#

        self.assertEqual(by_id[1]["infor_item_4"], "112204")
        self.assertEqual(by_id[1]["infor_item_number"], "112204")
        self.assertEqual(by_id[1]["status"], Status.MFG_ONLY_ITEM_WARN)

        self.assertEqual(by_id[2]["infor_item_3"], "102989")
        self.assertIsNone(by_id[2]["infor_item_4"])
        self.assertEqual(by_id[2]["status"], Status.ITEM_LABELED)

        self.assertIsNone(by_id[3]["infor_item_number"])
        self.assertEqual(by_id[3]["status"], Status.ITEM_FETCHED)

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual((issue["item_id"], issue["issue_type"], issue["severity"]), (1, "MFG_ONLY_ITEM_WARN", "WARN"))
        detail = json.loads(issue["detail"])
        self.assertEqual(detail["candidates"], ["112204"])
        self.assertEqual(detail["candidate_details"][0]["manufacturer_name"], "AVANOS")
        self.assertEqual(
            sorted((row["item_id"], row["infor_item_number"]) for row in match_rows),
            [(1, "112204"), (2, "102989")],
        )

    def test_source_1_hit_blocks_source_4(self):
        items = [input_item(1, "49-1500-5")]
        by_id, issues, _rows, asked = self._label(
            items,
            source_1_rows=[{"ManufacturerNumber": "49-1500-5", "Item": "102713"}],
            source_4_rows=[{"Manufacturer": "1189", "ManufacturerName": None, "ManufacturerNumber": "49-1500-5",
                            "Item": "999999", "mdm_description": "OTHER"}],
        )

        self.assertEqual(asked, [])
        self.assertEqual(by_id[1]["infor_item_number"], "102713")
        self.assertEqual(issues, [])

    def test_several_source_4_candidates_are_one_review(self):
        items = [input_item(1, "29624")]
        by_id, issues, _rows, _asked = self._label(
            items,
            source_4_rows=[
                {"Manufacturer": "1498", "ManufacturerName": "A", "ManufacturerNumber": "29624",
                 "Item": "200002", "mdm_description": "B"},
                {"Manufacturer": "1062", "ManufacturerName": "C", "ManufacturerNumber": "29624",
                 "Item": "200001", "mdm_description": "D"},
            ],
        )

        self.assertEqual(by_id[1]["infor_item_number"], "200001, 200002")
        self.assertEqual(by_id[1]["status"], Status.MFG_ONLY_ITEM_WARN)
        self.assertEqual([i["issue_type"] for i in issues], ["MFG_ONLY_ITEM_WARN"])
        self.assertEqual(json.loads(issues[0]["detail"])["candidates"], ["200001", "200002"])


def open_mfg_only_issue(issue_id=7, item_id=1, candidates=("112204",)):
    return SimpleNamespace(
        issue_id=issue_id,
        task_id="9B25",
        item_id=item_id,
        issue_type="MFG_ONLY_ITEM_WARN",
        resolved=False,
        detail=json.dumps({"candidates": list(candidates)}),
    )


class ResolveMfgOnlyTest(unittest.TestCase):
    def test_noted_keeps_a_candidate_and_runs_buy_uom(self):
        repo = MagicMock()
        repo.get_preprocess_issue.return_value = open_mfg_only_issue()
        settle = MagicMock(return_value=(Status.ITEM_PREPROCESSED, None))
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "_settle_item_number", settle):
            result = preprocess_service.resolve_mfg_only_keep("9B25", 7, "112204", "reviewer")

        settle.assert_called_once_with("9B25", 1, "112204", "KEEP_MFG_ONLY")
        self.assertEqual(repo.resolve_preprocess_issue.call_args.kwargs["resolution_action"], "NOTED")
        self.assertEqual(result["kept"], "112204")

    def test_noted_refuses_an_item_that_was_not_proposed(self):
        repo = MagicMock()
        repo.get_preprocess_issue.return_value = open_mfg_only_issue()
        with patch.object(preprocess_service, "task_repo", repo):
            with self.assertRaises(ValueError):
                preprocess_service.resolve_mfg_only_keep("9B25", 7, "123456", "reviewer")
        repo.resolve_preprocess_issue.assert_not_called()

    def test_detach_leaves_the_item_unlabeled(self):
        repo = MagicMock()
        repo.get_preprocess_issue.return_value = open_mfg_only_issue()
        buy_uom = SimpleNamespace(issue_id=8, item_id=1, issue_type="BUY_UOM_ERROR", resolved=False)
        other_item = SimpleNamespace(issue_id=9, item_id=2, issue_type="MULTI_ITEM_ERROR", resolved=False)
        repo.get_preprocess_issues.return_value = [open_mfg_only_issue(), buy_uom, other_item]
        with patch.object(preprocess_service, "task_repo", repo):
            result = preprocess_service.resolve_mfg_only_detach("9B25", 7, "reviewer")

        repo.delete_item_matches_for_items.assert_called_once_with("9B25", [1])
        repo.update_items_bulk.assert_called_once_with([{
            "item_id": 1,
            "infor_item_number": None,
            "infor_buy_uom_options": None,
            "status": Status.ITEM_PREPROCESSED,
        }])
        resolved = {c.kwargs["issue_id"]: c.kwargs["resolution_action"] for c in repo.resolve_preprocess_issue.call_args_list}
        self.assertEqual(resolved, {8: "ITEM_DETACHED", 7: "DETACHED"})
        self.assertEqual(result["item_status"], Status.ITEM_PREPROCESSED)

    def test_other_issue_types_are_refused(self):
        repo = MagicMock()
        issue = open_mfg_only_issue()
        issue.issue_type = "MULTI_ITEM_ERROR"
        repo.get_preprocess_issue.return_value = issue
        with patch.object(preprocess_service, "task_repo", repo):
            with self.assertRaises(ValueError):
                preprocess_service.resolve_mfg_only_detach("9B25", 7, "reviewer")


class BuyUomHoldsBackSource4Test(unittest.TestCase):
    def test_no_buy_uom_issue_until_the_label_is_kept(self):
        item = SimpleNamespace(
            item_id=1, infor_item_number="112204", status=Status.MFG_ONLY_ITEM_WARN,
            uom_to_match_infor="CA", qoe=10, intention=None,
        )
        candidate = SimpleNamespace(match_item_id=5, item_id=1, infor_item_number="112204")
        sess = MagicMock()
        sess.execute.return_value.mappings.return_value.all.side_effect = [
            [],                                           # inactive GTINs
            [{"UOM": "BX", "UOMConversion": 5}],          # buy UOM options for 112204
        ]
        with patch.object(preprocess_service, "_sql_session", return_value=nullcontext(sess)), \
             patch.object(preprocess_service, "load_query", fake_load_query):
            updates, _cands, issues, _n = preprocess_service._check_buy_uom(
                "9B25", SimpleNamespace(intention="ADD"), [item], [candidate],
            )

        self.assertEqual(issues, [])
        self.assertEqual(updates, [{"item_id": 1, "infor_buy_uom_options": "BX*5"}])


if __name__ == "__main__":
    unittest.main()
