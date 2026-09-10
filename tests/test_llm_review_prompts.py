from contextlib import nullcontext
from decimal import Decimal
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
        system_text = " ".join(messages[0]["content"].split())
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

    def test_v2_preserves_sku_formats_for_supplier_context_review(self):
        # Verify evidence delivery only; reduced equality is not an LLM verdict.
        input_item = dict(
            self.input_item,
            vendor="Manufacturer A",
            description="ORTHO SCRW",
            mfg_catalog_num="12-34-5678",
            vendor_catalog_num="A-0012345678",
        )
        matches = [
            dict(
                self.match_item,
                vendor="Manufacturer B",
                description="Orthopedic bone screw",
                mfg_catalog_num=sku,
                vendor_catalog_num="B-" + sku,
            )
            for sku in ("123-4-5678", "12.34.5678", "0012345678")
        ]
        prompt = llm_review_prompts.load("preprocess_review_v2")
        for mode in ("PAIR", "GROUP"):
            groups = [[match] for match in matches] if mode == "PAIR" else [matches]
            for selected in groups:
                with self.subTest(mode=mode, skus=[m["mfg_catalog_num"] for m in selected]):
                    user_text = llm_review._build_messages(
                        prompt, mode, input_item, selected
                    )[1]["content"]
                    self.assertIn("Supplier: Manufacturer A", user_text)
                    self.assertIn("Mfg Catalog #: 12-34-5678", user_text)
                    self.assertIn("Supplier Catalog #: A-0012345678", user_text)
                    self.assertEqual(user_text.count("Supplier: Manufacturer B"), len(selected))
                    for match in selected:
                        self.assertIn("Mfg Catalog #: " + match["mfg_catalog_num"], user_text)
                        self.assertIn("Supplier Catalog #: " + match["vendor_catalog_num"], user_text)

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

    def test_calculated_packaging_evidence_for_reported_matches(self):
        cases = [
            # match ID, input price/QOE, match price/QOE, EA prices, price ratio
            (649412, "108.68", 100, "27.17", 25, 1.0868, 1.0868, 0.25),
            (649534, "41.95", 4, "10.49", 1, 10.4875, 10.49, 0.25005959),
            (653620, "3.59", 1, "172.21", 48, 3.59, 3.5877083, 47.969359),
            (654205, "8.66", 10, "86.64", 100, 0.866, 0.8664, 10.004619),
        ]
        for match_id, price, qoe, mprice, mqoe, ea, mea, ratio in cases:
            with self.subTest(match_id=match_id):
                context = llm_review._pair_context(
                    {"contract_price": Decimal(price), "qoe": qoe},
                    {"contract_price": Decimal(mprice), "qoe": mqoe},
                )
                self.assertAlmostEqual(float(context["input_ea_price"]), ea, places=6)
                self.assertAlmostEqual(float(context["match_ea_price"]), mea, places=6)
                self.assertAlmostEqual(float(context["contract_price_ratio"]), ratio, places=6)
                self.assertEqual(Decimal(context["qoe_ratio"]), Decimal(mqoe) / qoe)
                self.assertAlmostEqual(float(context["ea_price_ratio"]), mea / ea, places=6)

    def test_equal_raw_prices_with_conflicting_qoe_reach_v1_unchanged(self):
        # Task 3FBA, match 657083: verify evidence delivery, not an LLM verdict.
        input_item = {
            "vendor": "MEDLINE INDUSTRIES INC-PHYSICIAN OFFICE-LUM",
            "supplier_type": "DISTRIBUTOR",
            "description": "ELCTRDE,ECG,SNP,RDLCNT,MEDITRAC",
            "mfg_catalog_num": "22853",
            "vendor_catalog_num": "KDL22853",
            "uom": "CS",
            "qoe": 600,
            "contract_price": Decimal("53.00"),
        }
        match_item = dict(
            input_item,
            vendor="MEDLINE INDUSTRIES INC",
            description="ELECTRODE EKG 1 7/8INX1 3/8IN KDL TRAC RECT FM DDRGL ADH",
            uom="CA",
            qoe=200,
            matched_source="CCX",
            pair_type="C",
        )
        prompt = llm_review_prompts.load("preprocess_review_v1")
        for mode in ("PAIR", "GROUP"):
            with self.subTest(mode=mode):
                user_text = llm_review._build_messages(
                    prompt, mode, input_item, [match_item]
                )[1]["content"]
                self.assertEqual(user_text.count("Supplier Type: DISTRIBUTOR"), 2)
                self.assertEqual(user_text.count("Supplier Catalog #: KDL22853"), 2)
                self.assertEqual(user_text.count("Contract Price: 53.00"), 2)
                for evidence in (
                    "UOM: CS", "UOM: CA", "QOE: 600", "QOE: 200",
                    "Calculated Price per EA (Contract Price / QOE): 0.088333333",
                    "Calculated Price per EA (Contract Price / QOE): 0.265",
                    "QOE ratio: 0.33333333",
                    "Contract Price ratio (raw sale-unit prices): 1",
                    "Price per EA ratio: 3",
                ):
                    self.assertIn(evidence, user_text)
        self.assertEqual(input_item["qoe"], 600)
        self.assertEqual(match_item["qoe"], 200)

    def test_derived_fields_handle_invalid_values_without_inventing_equality(self):
        for bad in (None, "", "None", "invalid", "NaN", "Infinity", -1):
            with self.subTest(value=bad):
                context = llm_review._pair_context(
                    {"contract_price": bad, "qoe": bad},
                    {"contract_price": 10, "qoe": 2},
                )
                for field in ("input_ea_price", "qoe_ratio", "contract_price_ratio", "ea_price_ratio"):
                    self.assertEqual(context[field], "unavailable")
                self.assertEqual(Decimal(context["match_ea_price"]), 5)

        for invalid_side in (0, 1):
            with self.subTest(zero_qoe_side=invalid_side):
                items = [{"contract_price": 10, "qoe": 2} for _ in range(2)]
                items[invalid_side]["qoe"] = 0
                context = llm_review._pair_context(*items)
                self.assertEqual(context["qoe_ratio"], "unavailable")
                self.assertEqual(context["ea_price_ratio"], "unavailable")
                self.assertEqual(Decimal(context["contract_price_ratio"]), 1)

    def test_zero_price_is_valid_per_each_but_not_a_ratio_denominator(self):
        context = llm_review._pair_context(
            {"contract_price": 0, "qoe": 10},
            {"contract_price": 20, "qoe": 10},
        )
        self.assertEqual(Decimal(context["input_ea_price"]), 0)
        self.assertEqual(context["contract_price_ratio"], "unavailable")
        self.assertEqual(context["ea_price_ratio"], "unavailable")
        reversed_context = llm_review._pair_context(
            {"contract_price": 20, "qoe": 10},
            {"contract_price": 0, "qoe": 10},
        )
        self.assertEqual(Decimal(reversed_context["contract_price_ratio"]), 0)
        self.assertEqual(Decimal(reversed_context["ea_price_ratio"]), 0)

    def test_v1_renders_each_candidates_own_ratios_in_pair_and_group(self):
        input_item = dict(self.input_item, contract_price=108.68, qoe=100)
        matches = [
            dict(self.match_item, contract_price=27.17, qoe=25),
            dict(self.match_item, contract_price=1.0868, qoe=1),
        ]
        prompt = llm_review_prompts.load("preprocess_review_v1")
        for mode in ("PAIR", "GROUP"):
            with self.subTest(mode=mode):
                selected = matches[:1] if mode == "PAIR" else matches
                user_text = llm_review._build_messages(prompt, mode, input_item, selected)[1]["content"]
                self.assertEqual(user_text.count("Contract Price: 108.68"), 1)
                self.assertIn("Calculated Price per EA (Contract Price / QOE): 1.0868", user_text)
                self.assertIn("Calculated ratios (MATCHED / INPUT):", user_text)
                self.assertIn("QOE ratio: 0.25", user_text)
                self.assertIn("Contract Price ratio (raw sale-unit prices): 0.25", user_text)
                if mode == "GROUP":
                    second = user_text.split("[2] source:")[1]
                    self.assertIn("QOE ratio: 0.01", second)
                    self.assertIn("Contract Price ratio (raw sale-unit prices): 0.01", second)
                    self.assertNotIn("ratio: 0.25", second)

    def test_v2_never_sends_calculated_packaging_evidence(self):
        prompt = llm_review_prompts.load("preprocess_review_v2")
        for mode in ("PAIR", "GROUP"):
            with self.subTest(mode=mode):
                user_text = llm_review._build_messages(
                    prompt, mode, self.input_item, [self.match_item]
                )[1]["content"]
                for label in ("Price per EA", "ratio", "Contract Price:", "QOE:", "UOM:"):
                    self.assertNotIn(label, user_text)

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
