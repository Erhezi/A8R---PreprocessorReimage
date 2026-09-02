from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from preprocessorEC.services import llm_review
from preprocessorEC.services import llm_review_prompts
from preprocessorEC.services import preprocess_service


class SupplierAwareReviewPromptTests(unittest.TestCase):
    def setUp(self):
        self.input_item = {
            "vendor": "Globus Medical",
            "supplier_type": "manufacturer contract",
            "description": "SPACER SPNL 22X10X21MM SUST SM PEEK",
            "mfg_catalog_num": "304.121",
            "vendor_catalog_num": "GLOBUS-304.121",
            "uom": "EA",
            "qoe": 1,
            "contract_price": 5000.0,
        }
        self.match_item = {
            "matched_source": "CCX",
            "pair_type": "B1",
            "vendor": "J&J",
            "supplier_type": "MANUFACTURER",
            "description": "SCREW LENGTH MARKER-21MM-10PK",
            "mfg_catalog_num": "304.121",
            "vendor_catalog_num": "JJ-304.121",
            "uom": "PK",
            "qoe": 10,
            "contract_price": 100.0,
        }

    def test_supplier_types_are_normalized_for_rendering(self):
        context = llm_review._pair_context(self.input_item, self.match_item)

        self.assertEqual(context["input_vendor"], "Globus Medical")
        self.assertEqual(context["match_vendor"], "J&J")
        self.assertEqual(context["input_supplier_type"], "MANUFACTURER")
        self.assertEqual(context["match_supplier_type"], "MANUFACTURER")
        self.assertEqual(llm_review._normalize_supplier_type("reseller"), "UNKNOWN")

    def test_v2_is_supplier_aware_and_still_ignores_packaging(self):
        prompt = llm_review_prompts.load("preprocess_review_v2")
        messages = llm_review._build_messages(
            prompt, "PAIR", self.input_item, [self.match_item]
        )
        system_text = messages[0]["content"]
        user_text = messages[1]["content"]

        self.assertIn("Supplier: Globus Medical", user_text)
        self.assertIn("Supplier Type: MANUFACTURER", user_text)
        self.assertIn("Supplier Catalog #: GLOBUS-304.121", user_text)
        self.assertIn("Supplier: J&J", user_text)
        self.assertNotIn("Vendor:", user_text)
        self.assertNotIn("Vendor Catalog #:", user_text)
        self.assertNotIn("UOM:", user_text)
        self.assertNotIn("QOE:", user_text)
        self.assertNotIn("Contract Price:", user_text)
        self.assertIn("raw Mfg Catalog # equality", system_text)
        self.assertIn("is NOT sufficient", system_text)
        self.assertIn("lumbar interbody spacer", system_text)
        self.assertIn("screw-length marker", system_text)

    def test_v1_is_supplier_aware_and_retains_packaging_fields(self):
        prompt = llm_review_prompts.load("preprocess_review_v1")
        messages = llm_review._build_messages(
            prompt, "GROUP", self.input_item, [self.match_item]
        )
        system_text = messages[0]["content"]
        user_text = messages[1]["content"]

        self.assertEqual(user_text.count("Supplier Type: MANUFACTURER"), 2)
        self.assertIn("Supplier Catalog #: GLOBUS-304.121", user_text)
        self.assertIn("Supplier Catalog #: JJ-304.121", user_text)
        self.assertIn("UOM: EA", user_text)
        self.assertIn("QOE: 1", user_text)
        self.assertIn("Contract Price: 5000.0", user_text)
        self.assertIn("UOM: PK", user_text)
        self.assertIn("QOE: 10", user_text)
        self.assertIn("Contract Price: 100.0", user_text)
        self.assertIn("raw Mfg Catalog # equality", system_text)
        self.assertIn("different physical item types", system_text)

    def test_both_prompts_render_supplier_fields_in_both_modes(self):
        for prompt_name in ("preprocess_review_v1", "preprocess_review_v2"):
            prompt = llm_review_prompts.load(prompt_name)
            for mode in ("PAIR", "GROUP"):
                with self.subTest(prompt=prompt_name, mode=mode):
                    user_text = llm_review._build_messages(
                        prompt, mode, self.input_item, [self.match_item]
                    )[1]["content"]
                    self.assertEqual(
                        user_text.count("Supplier Type: MANUFACTURER"), 2
                    )
                    self.assertNotIn("Vendor:", user_text)
                    self.assertNotIn("Vendor Catalog #:", user_text)

    def test_preprocess_payload_keeps_vendor_sources_and_adds_supplier_type(self):
        input_row = SimpleNamespace(
            description="Input description",
            mfg_catalog_num="MFG-1",
            vendor_catalog_num="SUP-1",
            uom="EA",
            qoe=1,
            unit_price=12.5,
        )
        match_row = SimpleNamespace(
            matched_source="CCX",
            item_desc_matched="Match description",
            manufacturer_number_matched="MFG-1",
            vendor_item_matched="SUP-2",
            uom_matched="EA",
            qoe_matched=1,
            contract_price_matched=12.5,
            similarity_score=0.8,
            pair_type="B1",
        )

        input_payload = preprocess_service._llm_input_dict(
            input_row, "Input Vendor Source", "MANUFACTURER"
        )
        match_payload = preprocess_service._llm_match_dict(
            match_row, "Match Vendor Source", "DISTRIBUTOR"
        )

        self.assertEqual(input_payload["vendor"], "Input Vendor Source")
        self.assertEqual(input_payload["supplier_type"], "MANUFACTURER")
        self.assertEqual(match_payload["vendor"], "Match Vendor Source")
        self.assertEqual(match_payload["supplier_type"], "DISTRIBUTOR")

    def test_match_supplier_types_are_resolved_by_contract_scope(self):
        class FakeStatement:
            def bindparams(self, *_args, **_kwargs):
                return self

        matches = [
            SimpleNamespace(contract_id_matched="C-100"),
            SimpleNamespace(contract_id_matched="C-200"),
        ]
        rows = [
            {
                "Organization": "MHS",
                "ContractID": "C-100",
                "ContractProcessType": "MANUFACTURER",
            },
            {
                "Organization": "MHS",
                "ContractID": "C-200",
                "ContractProcessType": "DISTRIBUTOR",
            },
        ]

        with (
            patch.object(preprocess_service, "load_query", return_value=FakeStatement()),
            patch.object(
                preprocess_service, "_sql_session", return_value=nullcontext(object())
            ),
            patch.object(
                preprocess_service, "_execute_expanding_batches", return_value=rows
            ) as execute_batches,
        ):
            result = preprocess_service._lookup_match_supplier_types(matches)

        self.assertEqual(result[("MHS", "C-100")], "MANUFACTURER")
        self.assertEqual(result[("MHS", "C-200")], "DISTRIBUTOR")
        self.assertEqual(execute_batches.call_args.args[3], ["C-100", "C-200"])


if __name__ == "__main__":
    unittest.main()
