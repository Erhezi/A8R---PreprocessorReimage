"""Match-result filtering happens in SQL, not in the route.

Opening the review table on one contract used to hydrate every match row in the
task (one wide row per candidate pair) plus every INPUT item, then throw almost
all of it away in Python. These tests pin the replacement: each stored column is
a WHERE clause, and only the input items behind the surviving matches load.
"""

from contextlib import contextmanager
import unittest
from unittest.mock import patch

import flask_login
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from preprocessorEC.db import task_repo
from preprocessorEC.models import Base, MatchResult, TaskItem
from preprocessorEC.preprocess.routes import preprocess_bp

TASK = "3FBA"
OTHER_TASK = "9ZZZ"
CONTRACT = "L-GraceMedical-ProCem-1Sept20"


def build_engine():
    """In-memory SQLite carrying the real model tables.

    The models are schema-qualified for SQL Server; ATTACH gives SQLite a
    database of that name so the same DDL applies unchanged.
    """
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _attach(dbapi_conn, _record):  # pragma: no cover - connection hook
        dbapi_conn.execute("ATTACH DATABASE ':memory:' AS Preprocessor")

    Base.metadata.create_all(engine, tables=[MatchResult.__table__, TaskItem.__table__])
    return engine


@contextmanager
def chunk_size(size):
    """Shrink the IN()-list chunk so a handful of rows spans several chunks.

    ``_chunked`` reads the cap as a default argument, so it is bound at import
    time and patching the module constant would not reach it.
    """
    original = task_repo._chunked
    with patch.object(
        task_repo, "_chunked", lambda items, size=size: original(items, size)
    ):
        yield


def match(match_id, **overrides):
    fields = dict(
        match_id=match_id,
        task_id=TASK,
        input_item_id=1,
        matched_source="CCX",
        match_status="PENDING",
        similarity_bucket="HIGH",
        contract_number=CONTRACT,
        organization_eid_matched="105188574",
        erp_vendor_id_matched="1001649",
        uom_nuance="No",
    )
    fields.update(overrides)
    return MatchResult(**fields)


def item(item_id, file_row, **overrides):
    fields = dict(
        item_id=item_id,
        task_id=TASK,
        source_dataset="INPUT",
        file_row=file_row,
        mfg_catalog_num=f"MFG-{item_id}",
        description=f"item {item_id}",
        uom="EA",
        qoe=1,
    )
    fields.update(overrides)
    return TaskItem(**fields)


class RepoFilterTests(unittest.TestCase):
    """get_match_results / get_items_by_source against a real engine."""

    def setUp(self):
        self.engine = build_engine()
        patcher = patch.object(task_repo, "_session", lambda: Session(self.engine))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.engine.dispose)

    def seed(self, rows):
        with Session(self.engine) as s:
            s.add_all(rows)
            s.commit()

    def ids(self, results):
        return sorted(r.match_id for r in results)

    def test_no_filters_returns_only_this_task(self):
        self.seed([match(1), match(2), match(3, task_id=OTHER_TASK)])
        self.assertEqual(self.ids(task_repo.get_match_results(TASK)), [1, 2])

    def test_rows_are_readable_after_the_session_closes(self):
        self.seed([match(1)])
        (result,) = task_repo.get_match_results(TASK)
        # Would raise DetachedInstanceError if the row were not expunged.
        self.assertEqual(result.contract_number, CONTRACT)

    def test_matched_source_filter(self):
        self.seed([match(1), match(2, matched_source="INFOR_CL")])
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, matched_source="INFOR_CL")), [2]
        )

    def test_contract_filter_is_exact_on_the_stored_spelling(self):
        self.seed([match(1), match(2, contract_number="L-Other-01JAN20")])
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, contract_numbers=[CONTRACT])),
            [1],
        )

    def test_contract_filter_accepts_several_contracts(self):
        self.seed([match(1), match(2, contract_number="L-Other-01JAN20"), match(3)])
        self.assertEqual(
            self.ids(
                task_repo.get_match_results(
                    TASK, contract_numbers=[CONTRACT, "L-Other-01JAN20"]
                )
            ),
            [1, 2, 3],
        )

    def test_blank_contract_entries_are_ignored(self):
        self.seed([match(1), match(2, contract_number="L-Other-01JAN20")])
        self.assertEqual(
            self.ids(
                task_repo.get_match_results(
                    TASK, contract_numbers=["  ", "", "L-Other-01JAN20"]
                )
            ),
            [2],
        )

    def test_empty_contract_list_means_every_contract(self):
        # The UI sends no contract params at all when nothing is checked.
        self.seed([match(1), match(2, contract_number="L-Other-01JAN20")])
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, contract_numbers=[])), [1, 2]
        )

    def test_contract_list_longer_than_one_chunk_returns_the_union(self):
        contracts = [f"C-{n:04d}" for n in range(7)]
        self.seed(
            [match(n + 1, contract_number=c) for n, c in enumerate(contracts)]
            + [match(99, contract_number="C-NOT-ASKED-FOR")]
        )
        with chunk_size(3):
            results = task_repo.get_match_results(TASK, contract_numbers=contracts)
        self.assertEqual(self.ids(results), [1, 2, 3, 4, 5, 6, 7])

    def test_scope_filters_narrow_to_one_organization_and_vendor(self):
        self.seed(
            [
                match(1),
                match(2, organization_eid_matched="999"),
                match(3, erp_vendor_id_matched="999"),
            ]
        )
        self.assertEqual(
            self.ids(
                task_repo.get_match_results(
                    TASK, organization_eid="105188574", erp_vendor_id="1001649"
                )
            ),
            [1],
        )

    def test_empty_scope_value_matches_both_null_and_blank(self):
        self.seed(
            [
                match(1, organization_eid_matched=None),
                match(2, organization_eid_matched=""),
                match(3),
            ]
        )
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, organization_eid="")), [1, 2]
        )

    def test_none_scope_value_does_not_filter(self):
        self.seed([match(1, organization_eid_matched=None), match(2)])
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, organization_eid=None)), [1, 2]
        )

    def test_bucket_status_and_uom_nuance_filters(self):
        self.seed(
            [
                match(1),
                match(2, similarity_bucket="MED"),
                match(3, match_status="ACCEPTED"),
                match(4, uom_nuance="Yes"),
            ]
        )
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, similarity_bucket="MED")), [2]
        )
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, match_status="ACCEPTED")), [3]
        )
        self.assertEqual(
            self.ids(task_repo.get_match_results(TASK, uom_nuance="Yes")), [4]
        )

    def test_empty_string_filters_are_treated_as_absent(self):
        # request.args.get returns "" for a dropdown left on its "All" option.
        self.seed([match(1), match(2, similarity_bucket="MED")])
        self.assertEqual(
            self.ids(
                task_repo.get_match_results(
                    TASK, similarity_bucket="", match_status="", uom_nuance=""
                )
            ),
            [1, 2],
        )

    def test_filters_combine(self):
        self.seed(
            [
                match(1),
                match(2, similarity_bucket="MED"),
                match(3, contract_number="L-Other-01JAN20"),
                match(4, matched_source="INFOR_CL"),
            ]
        )
        results = task_repo.get_match_results(
            TASK,
            matched_source="CCX",
            contract_numbers=[CONTRACT],
            organization_eid="105188574",
            erp_vendor_id="1001649",
            similarity_bucket="HIGH",
        )
        self.assertEqual(self.ids(results), [1])

    def test_items_without_id_filter_are_ordered_by_file_row(self):
        self.seed([item(1, 3), item(2, 1), item(3, 2)])
        rows = task_repo.get_items_by_source(TASK, "INPUT")
        self.assertEqual([r.item_id for r in rows], [2, 3, 1])

    def test_items_narrow_to_the_requested_ids(self):
        self.seed([item(1, 1), item(2, 2), item(3, 3)])
        rows = task_repo.get_items_by_source(TASK, "INPUT", item_ids={1, 3})
        self.assertEqual([r.item_id for r in rows], [1, 3])

    def test_empty_item_id_set_returns_nothing(self):
        self.seed([item(1, 1)])
        self.assertEqual(task_repo.get_items_by_source(TASK, "INPUT", item_ids=set()), [])

    def test_item_ids_longer_than_one_chunk_keep_whole_query_ordering(self):
        self.seed([item(n, 10 - n) for n in range(1, 8)])
        with chunk_size(3):
            rows = task_repo.get_items_by_source(TASK, "INPUT", item_ids=set(range(1, 8)))
        self.assertEqual([r.file_row for r in rows], [3, 4, 5, 6, 7, 8, 9])


class RouteHandoffTests(unittest.TestCase):
    """The endpoint passes the UI's filters straight through to SQL."""

    def setUp(self):
        app = Flask(__name__)
        app.config["LOGIN_DISABLED"] = True
        app.secret_key = "test"
        flask_login.LoginManager().init_app(app)
        app.register_blueprint(preprocess_bp)
        self.client = app.test_client()

    @contextmanager
    def captured(self, matches=()):
        with patch.object(
            task_repo, "get_match_results", return_value=list(matches)
        ) as get_matches, patch.object(
            task_repo, "get_items_by_source", return_value=[]
        ) as get_items:
            yield get_matches, get_items

    def test_contract_click_pushes_every_scope_filter_down(self):
        with self.captured() as (get_matches, _):
            resp = self.client.get(
                f"/api/preprocess/{TASK}/matches"
                f"?contract={CONTRACT}"
                "&organization_eid=105188574&erp_vendor_id=1001649"
            )
        self.assertEqual(resp.status_code, 200)
        kwargs = get_matches.call_args.kwargs
        self.assertEqual(kwargs["contract_numbers"], [CONTRACT])
        self.assertEqual(kwargs["organization_eid"], "105188574")
        self.assertEqual(kwargs["erp_vendor_id"], "1001649")

    def test_contract_spelling_is_not_case_folded(self):
        # The value came out of this same table, so an exact compare stays
        # index-seekable without leaning on the server collation.
        with self.captured() as (get_matches, _):
            self.client.get(
                f"/api/preprocess/{TASK}/matches?contract=L-HealthCareLostics-01JAN20"
            )
        self.assertEqual(
            get_matches.call_args.kwargs["contract_numbers"],
            ["L-HealthCareLostics-01JAN20"],
        )

    def test_absent_scope_params_do_not_filter(self):
        with self.captured() as (get_matches, _):
            self.client.get(f"/api/preprocess/{TASK}/matches")
        kwargs = get_matches.call_args.kwargs
        self.assertIsNone(kwargs["organization_eid"])
        self.assertIsNone(kwargs["erp_vendor_id"])
        self.assertEqual(kwargs["contract_numbers"], [])

    def test_blank_scope_param_still_filters_to_the_empty_scope(self):
        # ?organization_eid= is how the UI asks for rows carrying no organization.
        with self.captured() as (get_matches, _):
            self.client.get(
                f"/api/preprocess/{TASK}/matches?organization_eid=&erp_vendor_id="
            )
        kwargs = get_matches.call_args.kwargs
        self.assertEqual(kwargs["organization_eid"], "")
        self.assertEqual(kwargs["erp_vendor_id"], "")

    def test_bucket_status_and_uom_nuance_reach_sql(self):
        with self.captured() as (get_matches, _):
            self.client.get(
                f"/api/preprocess/{TASK}/matches"
                "?bucket=MED&status=ACCEPTED&uom_nuance=Yes&source=CCX"
            )
        kwargs = get_matches.call_args.kwargs
        self.assertEqual(kwargs["similarity_bucket"], "MED")
        self.assertEqual(kwargs["match_status"], "ACCEPTED")
        self.assertEqual(kwargs["uom_nuance"], "Yes")
        self.assertEqual(kwargs["matched_source"], "CCX")

    def test_input_items_are_fetched_only_for_the_matches_returned(self):
        rows = [match(1, input_item_id=7), match(2, input_item_id=9)]
        with self.captured(rows) as (_, get_items):
            self.client.get(f"/api/preprocess/{TASK}/matches")
        self.assertEqual(get_items.call_args.kwargs["item_ids"], {7, 9})


if __name__ == "__main__":
    unittest.main()
