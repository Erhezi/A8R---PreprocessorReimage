"""Source 4 of Item# labeling: MDM_ITEM by manufacturer part number alone.

Source 4 is a fallback, consulted only for items Sources 1-3 left empty. Its
candidates are proposals: each becomes an item-match row with a decision. An
LLM compares the two descriptions (SAME -> ACCEPTED, DIFFERENT -> REJECTED), a
reviewer can flip either on the Item Matching Results table, and only ACCEPTED
candidates label the input item. PENDING ones block finalize.
"""

from contextlib import nullcontext
from datetime import datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from preprocessorEC.services import llm_review, llm_review_prompts, preprocess_service
from preprocessorEC.state import Status


class FakeStmt:
    def __init__(self, name):
        self.name = name

    def bindparams(self, *args, **kwargs):
        return self


def fake_load_query(blueprint, file, query=None):
    return FakeStmt(query)


def input_item(item_id, mfg, vpn=None, description=None):
    return SimpleNamespace(
        item_id=item_id,
        mfg_catalog_num=mfg,
        vendor_catalog_num=vpn,
        vendor_id_short=None,
        description=description,
    )


def mdm_row(mfg_num, item, description, manufacturer="1100", name="AVANOS"):
    return {"Manufacturer": manufacturer, "ManufacturerName": name, "ManufacturerNumber": mfg_num,
            "Item": item, "mdm_description": description}


def item_match(match_item_id, item_id, item, *, mfg_only=True, status="PENDING", verdict=None,
               description="ITEM MASTER DESC", task_id="9B25"):
    return SimpleNamespace(
        match_item_id=match_item_id, task_id=task_id, item_id=item_id, infor_item_number=item,
        item_description=description, mfg_only=mfg_only, match_status=status if mfg_only else None,
        llm_verdict=verdict, llm_reason=None, reviewed_by=None, reviewed_at=None,
    )


class LabelItemsSource4Test(unittest.TestCase):
    def _label(self, items, source_1_rows=(), source_3_by_pkid=None, accepted=None, source_4_rows=(),
               prior_reviews=None):
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
                "9B25", task, items, accepted or {}, prior_reviews,
            )
        return {u["item_id"]: u for u in updates}, issues, match_rows, source_4_asked

    def test_source_4_proposes_pending_rows_without_labeling(self):
        items = [input_item(1, "M00509911"), input_item(2, "CH40NBF"), input_item(3, "ACTC1525")]
        by_id, issues, match_rows, asked = self._label(
            items,
            source_3_by_pkid={"1361-322": {"102989"}},
            accepted={2: {"1361-322"}},
            source_4_rows=[
                mdm_row("M00509911", "112204", "TUBE 18FR"),
                mdm_row("CH40NBF", "102989", "CONTAINER", manufacturer="1111", name="X"),
            ],
        )

        self.assertEqual(sorted(asked), ["ACTC1525", "M00509911"])  # item 2 has a contract-line Item#

        # Proposed, recorded, but not linked until accepted.
        self.assertEqual(by_id[1]["infor_item_4"], "112204")
        self.assertIsNone(by_id[1]["infor_item_number"])
        self.assertEqual(by_id[1]["status"], Status.ITEM_FETCHED)

        self.assertEqual(by_id[2]["infor_item_3"], "102989")
        self.assertIsNone(by_id[2]["infor_item_4"])
        self.assertEqual(by_id[2]["status"], Status.ITEM_LABELED)

        self.assertIsNone(by_id[3]["infor_item_number"])
        self.assertEqual(by_id[3]["status"], Status.ITEM_FETCHED)

        self.assertEqual(issues, [])  # no MFG_ONLY_ITEM_WARN any more
        by_item = {(row["item_id"], row["infor_item_number"]): row for row in match_rows}
        self.assertEqual(sorted(by_item), [(1, "112204"), (2, "102989")])
        self.assertTrue(by_item[(1, "112204")]["mfg_only"])
        self.assertEqual(by_item[(1, "112204")]["match_status"], "PENDING")
        self.assertEqual(by_item[(1, "112204")]["item_description"], "TUBE 18FR")
        self.assertFalse(by_item[(2, "102989")].get("mfg_only", False))

    def test_source_1_hit_blocks_source_4(self):
        items = [input_item(1, "49-1500-5")]
        by_id, issues, rows, asked = self._label(
            items,
            source_1_rows=[{"ManufacturerNumber": "49-1500-5", "Item": "102713"}],
            source_4_rows=[mdm_row("49-1500-5", "999999", "OTHER", manufacturer="1189", name=None)],
        )

        self.assertEqual(asked, [])
        self.assertEqual(by_id[1]["infor_item_number"], "102713")
        self.assertEqual(issues, [])
        self.assertEqual([r["infor_item_number"] for r in rows], ["102713"])

    def test_only_accepted_candidates_label_the_item(self):
        items = [input_item(1, "29624")]
        source_4_rows = [mdm_row("29624", "200002", "B", "1498", "A"), mdm_row("29624", "200001", "D", "1062", "C")]
        reviewed = datetime(2026, 10, 6, 9, 30)

        by_id, issues, rows, _ = self._label(items, source_4_rows=source_4_rows, prior_reviews={
            (1, "200001"): {"match_status": "ACCEPTED", "llm_verdict": "SAME", "llm_reason": "same tube",
                            "reviewed_by": "LLM", "reviewed_at": reviewed},
            (1, "200002"): {"match_status": "REJECTED", "llm_verdict": "DIFFERENT", "llm_reason": "a drape",
                            "reviewed_by": "LLM", "reviewed_at": reviewed},
        })

        self.assertEqual(by_id[1]["infor_item_number"], "200001")
        self.assertEqual(by_id[1]["status"], Status.ITEM_LABELED)
        self.assertEqual(by_id[1]["infor_item_4"], "200001, 200002")
        self.assertEqual(issues, [])
        # The rejected candidate stays as a row — the record of what was proposed.
        decisions = {r["infor_item_number"]: (r["match_status"], r["llm_verdict"], r["reviewed_at"]) for r in rows}
        self.assertEqual(decisions, {
            "200001": ("ACCEPTED", "SAME", reviewed),
            "200002": ("REJECTED", "DIFFERENT", reviewed),
        })

    def test_two_accepted_candidates_are_a_multi_item_error(self):
        items = [input_item(1, "29624")]
        source_4_rows = [mdm_row("29624", "200002", "B"), mdm_row("29624", "200001", "D")]
        accepted = {"match_status": "ACCEPTED"}

        by_id, issues, _rows, _ = self._label(items, source_4_rows=source_4_rows, prior_reviews={
            (1, "200001"): accepted, (1, "200002"): accepted,
        })

        self.assertEqual(by_id[1]["infor_item_number"], "200001, 200002")
        self.assertEqual(by_id[1]["status"], Status.MULTI_ITEM_ERROR)
        self.assertEqual([i["issue_type"] for i in issues], ["MULTI_ITEM_ERROR"])
        detail = json.loads(issues[0]["detail"])
        self.assertEqual(detail["candidates"], ["200001", "200002"])
        self.assertEqual(detail["sources"]["mfg_number_only"], "200001, 200002")


class MfgOnlyLlmReviewTest(unittest.TestCase):
    def _run(self, rows, items, verdicts):
        repo = MagicMock()
        repo.get_item_matches.return_value = rows
        repo.count_pending_mfg_only_item_matches.return_value = 0
        review = MagicMock(side_effect=lambda input_desc, item_desc: verdicts[item_desc])
        relabel = MagicMock()

        def live_items(task_id, item_ids=None):
            return [i for i in items if item_ids is None or i.item_id in item_ids]

        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "_live_input_items", side_effect=live_items), \
             patch.object(preprocess_service, "review_description_pair", review), \
             patch.object(preprocess_service, "_relabel_items", relabel):
            result = preprocess_service.run_mfg_only_llm_review("9B25")
        updates = {u["match_item_id"]: u for u in repo.update_item_matches_bulk.call_args.args[0]}
        return result, updates, review, relabel

    def test_same_accepts_and_relabels_different_rejects_no_verdict_stays_pending(self):
        items = [input_item(1, "A", description="TUBE FEEDING 18FR"),
                 input_item(2, "B", description="GLOVE EXAM NITRILE M")]
        rows = [
            item_match(10, 1, "112204", description="FEEDING TUBE 18 FR"),
            item_match(11, 2, "300001", description="DRAPE SURGICAL"),
            item_match(12, 2, "300002", description="UNREADABLE"),
            item_match(13, 1, "102713", mfg_only=False),                       # Sources 1-3: never asked
            item_match(14, 2, "300003", status="REJECTED", verdict="DIFFERENT"),  # already decided
        ]
        verdicts = {
            "FEEDING TUBE 18 FR": {"verdict": "SAME", "reason": "same feeding tube"},
            "DRAPE SURGICAL": {"verdict": "DIFFERENT", "reason": "glove vs drape"},
            "UNREADABLE": {"verdict": None, "reason": "LLM request timed out."},
        }

        result, updates, review, relabel = self._run(rows, items, verdicts)

        self.assertEqual(review.call_count, 3)
        self.assertEqual(sorted(updates), [10, 11, 12])
        self.assertEqual((updates[10]["match_status"], updates[10]["llm_verdict"], updates[10]["reviewed_by"]),
                         ("ACCEPTED", "SAME", "LLM"))
        self.assertEqual((updates[11]["match_status"], updates[11]["llm_verdict"]), ("REJECTED", "DIFFERENT"))
        # No verdict: keep the reason, leave the decision alone so it is asked again.
        self.assertEqual(updates[12], {"match_item_id": 12, "llm_reason": "LLM request timed out."})
        # Only the item that gained a linked Item# is relabeled.
        self.assertEqual([i.item_id for i in relabel.call_args.args[2]], [1])
        self.assertEqual(
            {k: result[k] for k in ("reviewed", "same", "different", "undecided")},
            {"reviewed": 2, "same": 1, "different": 1, "undecided": 1},
        )

    def test_awaiting_means_pending_without_a_verdict(self):
        awaiting = preprocess_service.awaiting_mfg_only_llm_review
        self.assertTrue(awaiting(item_match(1, 1, "1")))
        self.assertFalse(awaiting(item_match(1, 1, "1", verdict="SAME", status="ACCEPTED")))
        self.assertFalse(awaiting(item_match(1, 1, "1", status="REJECTED")))  # a reviewer decided
        self.assertFalse(awaiting(item_match(1, 1, "1", mfg_only=False)))


class SubmitMfgOnlyDecisionTest(unittest.TestCase):
    def _submit(self, row, decision):
        repo = MagicMock()
        repo.get_item_match.return_value = row
        repo.count_pending_mfg_only_item_matches.return_value = 0
        relabel = MagicMock()
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "_live_input_items", return_value=[input_item(1, "A")]), \
             patch.object(preprocess_service, "_relabel_items", relabel):
            result = preprocess_service.submit_mfg_only_decision("9B25", 10, decision, "reviewer")
        return result, repo, relabel

    def test_rejecting_an_accepted_match_unlinks_it(self):
        result, repo, relabel = self._submit(item_match(10, 1, "112204", status="ACCEPTED", verdict="SAME"), "rejected")

        update = repo.update_item_matches_bulk.call_args.args[0][0]
        self.assertEqual((update["match_status"], update["reviewed_by"]), ("REJECTED", "reviewer"))
        relabel.assert_called_once()
        self.assertEqual(result["relabeled"], 1)

    def test_accepting_an_llm_different_links_it(self):
        _result, _repo, relabel = self._submit(item_match(10, 1, "112204", status="REJECTED", verdict="DIFFERENT"), "ACCEPTED")
        relabel.assert_called_once()

    def test_rejecting_a_pending_match_changes_no_label(self):
        result, repo, relabel = self._submit(item_match(10, 1, "112204"), "REJECTED")
        repo.update_item_matches_bulk.assert_called_once()
        relabel.assert_not_called()
        self.assertEqual(result["relabeled"], 0)

    def test_refuses_bad_input(self):
        cases = [
            (item_match(10, 1, "112204"), "PENDING"),                 # not a decision
            (item_match(10, 1, "112204", mfg_only=False), "REJECTED"),  # Sources 1-3 rows have none
            (item_match(10, 1, "112204", task_id="OTHER"), "REJECTED"),
            (None, "REJECTED"),
        ]
        for row, decision in cases:
            with self.subTest(row=row, decision=decision):
                repo = MagicMock()
                repo.get_item_match.return_value = row
                with patch.object(preprocess_service, "task_repo", repo):
                    with self.assertRaises(ValueError):
                        preprocess_service.submit_mfg_only_decision("9B25", 10, decision, "reviewer")
                repo.update_item_matches_bulk.assert_not_called()


class RelabelKeepsSource4DecisionsTest(unittest.TestCase):
    def test_prior_decisions_reach_label_items(self):
        repo = MagicMock()
        repo.get_item_matches.return_value = [
            item_match(10, 1, "112204", status="REJECTED", verdict="DIFFERENT"),
            item_match(11, 1, "102713", mfg_only=False),
            item_match(12, 2, "300001", status="ACCEPTED"),  # another item, not relabeled
        ]
        label_items = MagicMock(return_value=([], [], []))
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "_live_input_items", return_value=[]), \
             patch.object(preprocess_service, "_label_items", label_items), \
             patch.object(preprocess_service, "_check_buy_uom", return_value=([], [], [], 0)):
            preprocess_service._relabel_items("9B25", SimpleNamespace(), [input_item(1, "A")], {})

        prior = label_items.call_args.args[4]
        self.assertEqual(list(prior), [(1, "112204")])
        self.assertEqual(prior[(1, "112204")]["match_status"], "REJECTED")
        self.assertEqual(prior[(1, "112204")]["llm_verdict"], "DIFFERENT")


class PickKeepsSource4RowsTest(unittest.TestCase):
    def test_unpicked_accepted_source_4_row_is_rejected_not_deleted(self):
        repo = MagicMock()
        repo.get_item_matches.return_value = [
            item_match(10, 1, "200001", status="ACCEPTED"),
            item_match(11, 1, "200002", status="ACCEPTED"),
            item_match(12, 1, "200003", status="REJECTED"),
        ]
        repo.get_task_item.return_value = SimpleNamespace(uom_to_match_infor=None, qoe=None, intention=None)
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "_sql_session", return_value=nullcontext(MagicMock())), \
             patch.object(preprocess_service, "_query_buy_uom_options", return_value=[]):
            preprocess_service._settle_item_number("9B25", 1, "200001", "PICK_ITEM", decided_by="reviewer")

        repo.delete_item_matches_by_ids.assert_not_called()
        updates = repo.update_item_matches_bulk.call_args.args[0]
        self.assertEqual([(u["match_item_id"], u["match_status"], u["reviewed_by"]) for u in updates],
                         [(11, "REJECTED", "reviewer")])


class FinalizeGateTest(unittest.TestCase):
    def test_pending_source_4_matches_block_finalize(self):
        repo = MagicMock()
        repo.count_live_input_items.return_value = 3
        repo.count_pending_matches.return_value = 0
        repo.count_pending_mfg_only_item_matches.return_value = 2
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "refresh_stale_item_labels", return_value={"relabeled": 0}):
            with self.assertRaisesRegex(ValueError, "2 manufacturer-part-number-only"):
                preprocess_service.finalize_preprocess("9B25", MagicMock(), "reviewer")
        repo.mark_input_items_preprocessed.assert_not_called()


class BuyUomTest(unittest.TestCase):
    def _check(self, item, candidates, option_rows):
        sess = MagicMock()
        sess.execute.return_value.mappings.return_value.all.side_effect = [[]] + option_rows
        with patch.object(preprocess_service, "_sql_session", return_value=nullcontext(sess)), \
             patch.object(preprocess_service, "load_query", fake_load_query):
            return preprocess_service._check_buy_uom(
                "9B25", SimpleNamespace(intention="ADD"), [item], candidates,
            )

    def test_unlinked_source_4_rows_get_options_but_do_not_count(self):
        item = SimpleNamespace(item_id=1, infor_item_number="112204", status=Status.ITEM_LABELED,
                               uom_to_match_infor="BX", qoe=5, intention=None)
        candidates = [item_match(5, 1, "112204", status="ACCEPTED"), item_match(6, 1, "300001", status="REJECTED")]
        updates, cand_updates, issues, matched = self._check(item, candidates, [
            [{"UOM": "BX", "UOMConversion": 5}],   # 112204
            [{"UOM": "CS", "UOMConversion": 50}],  # 300001
        ])

        self.assertEqual(updates, [{"item_id": 1, "infor_buy_uom_options": "BX*5"}])
        self.assertEqual({c["match_item_id"]: c["infor_buy_uom_options"] for c in cand_updates},
                         {5: "BX*5", 6: "CS*50"})
        self.assertEqual((issues, matched), ([], 1))

    def test_legacy_mfg_only_warn_item_gets_no_buy_uom_issue(self):
        # MFG_ONLY_ITEM_WARN is no longer raised, but items already holding it
        # keep their buy-UOM check deferred until the old issue is resolved.
        item = SimpleNamespace(item_id=1, infor_item_number="112204", status=Status.MFG_ONLY_ITEM_WARN,
                               uom_to_match_infor="CA", qoe=10, intention=None)
        updates, _c, issues, _n = self._check(
            item, [SimpleNamespace(match_item_id=5, item_id=1, infor_item_number="112204")],
            [[{"UOM": "BX", "UOMConversion": 5}]],
        )
        self.assertEqual(issues, [])
        self.assertEqual(updates, [{"item_id": 1, "infor_buy_uom_options": "BX*5"}])


def open_mfg_only_issue(issue_id=7, item_id=1, candidates=("112204",)):
    return SimpleNamespace(
        issue_id=issue_id,
        task_id="9B25",
        item_id=item_id,
        issue_type="MFG_ONLY_ITEM_WARN",
        resolved=False,
        detail=json.dumps({"candidates": list(candidates)}),
    )


class ResolveLegacyMfgOnlyIssueTest(unittest.TestCase):
    """Issues raised before Source 4 moved to the Item Matching Results table."""

    def test_noted_keeps_a_candidate_and_runs_buy_uom(self):
        repo = MagicMock()
        repo.get_preprocess_issue.return_value = open_mfg_only_issue()
        settle = MagicMock(return_value=(Status.ITEM_PREPROCESSED, None))
        with patch.object(preprocess_service, "task_repo", repo), \
             patch.object(preprocess_service, "_settle_item_number", settle):
            result = preprocess_service.resolve_mfg_only_keep("9B25", 7, "112204", "reviewer")

        settle.assert_called_once_with("9B25", 1, "112204", "KEEP_MFG_ONLY", decided_by="reviewer")
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


class DescriptionCheckPromptTest(unittest.TestCase):
    def test_prompt_is_its_own_family_and_stays_out_of_the_picker(self):
        prompt = llm_review_prompts.latest(llm_review_prompts.MFG_ONLY_DESC_REVIEW)
        self.assertEqual(prompt.name, "mfg_only_desc_review_v1")
        self.assertNotIn(prompt.name, llm_review_prompts.names())
        user_text = prompt.render_user("PAIR", input_desc="TUBE FEEDING 18FR", match_desc="FEEDING TUBE 18 FR")
        self.assertIn("INPUT description: TUBE FEEDING 18FR", user_text)
        self.assertIn("ITEM MASTER description: FEEDING TUBE 18 FR", user_text)
        self.assertIn('"verdict": "same" or "different"', prompt.render_system("PAIR"))

    def test_verdict_parsing(self):
        parse = llm_review._parse_verdict
        self.assertEqual(parse('{"verdict": "same", "reason": "r"}'), {"verdict": "SAME", "reason": "r"})
        self.assertEqual(parse('{"verdict": " Different ", "reason": "r"}')["verdict"], "DIFFERENT")
        for bad in ('{"verdict": "maybe"}', "not json", "[]", '{"reason": "no verdict"}'):
            with self.subTest(reply=bad):
                self.assertIsNone(parse(bad)["verdict"])

    def test_blank_description_is_never_sent(self):
        with patch.object(llm_review, "_chat") as chat:
            result = llm_review.review_description_pair("TUBE", "  ")
        chat.assert_not_called()
        self.assertIsNone(result["verdict"])


if __name__ == "__main__":
    unittest.main()
