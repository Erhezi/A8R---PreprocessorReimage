---

## Plan: Scoring Overhaul + Precheck Modes + UI + matched_item_ref

**TL;DR**: Rework `matched_item_ref` to store MfgNum|UOM or VendorItem|UOM. Rewrite scoring with 4 pair-type weight regimes. Port the old repo's precheck duplicate modes (default/strict/explicit/distributor) to the current intake service. Rebuild preprocess UI with contract + item views.

---

### Phase A: Data Model Changes (steps 1-3, sequential)

**1. Add `precheck_mode` to Task model + migration 010**
- Add `precheck_mode VARCHAR(20) DEFAULT 'default'` to `[Preprocessor].[PreprocessorTask]`
- Add scoring detail columns to `[Preprocessor].[PreprocessorMatchResult]`: `mfn_score FLOAT`, `mfn_complexity FLOAT`, `uom_score FLOAT`, `qoe_score FLOAT`, `price_score FLOAT`, `price_diff_pct FLOAT`, `desc_score FLOAT`, `weighted_score FLOAT`, `ccx_ea_price FLOAT`, `upload_ea_price FLOAT`, `pair_type VARCHAR(1)` (A/B/C/D)
- Files: `migrations/010_add_precheck_mode_and_scoring.sql`, models.py — add fields to `Task.precheck_mode` and `MatchResult` scoring columns

**2. Add `delete_match_results(task_id)` to task_repo**
- Bulk DELETE all MatchResult rows for a task — called before re-running sku-matching
- File: task_repo.py

**3. Verify CCX/Infor SQL queries return all needed columns**
- Each CCX query must return: `mfg_catalog_num_ccx`, `vendor_catalog_num_ccx`, `uom_ccx`, `qoe_ccx`, `unit_price_ccx`, `description_ccx`, `ContractID`, `contract_manufacturer`, `ERPVendorID`, `VendorID`
- Infor residue must return: same set for comparisons
- Files: dup_detection.sql, item_matching.sql — already return most columns, verify `contract_manufacturer` and `VendorID` are present (they are)

---

### Phase B: Scoring Rewrite (steps 4-6, sequential)

**4. Rewrite scoring.py with multi-factor scoring**

Port from old repo:
- `calculate_mfn_complexity(mfn)` — length 60% + diversity 20% + char-type 20%
- `calculate_mfn_match_score(mfn_a, mfn_b)` — exact / reduced / contained / Levenshtein, adjusted by complexity
- `calculate_ea_price_match_score(price_a, price_b, qoe_a, qoe_b)` — % diff thresholds (10/20/45%)
- `calculate_description_similarity(desc_a, desc_b, model)` — transformer cosine + numerical measurement Jaccard overlay (70/30)
- `calculate_vendor_item_match(vpn_a, vpn_b)` → 1.0 if exact match, else 0.0

New: **`determine_pair_type(input_item, matched_row, task)`** → returns A/B/C/D:
- **A**: `matched_row.ContractID == task.contract_number` (same contract — item found itself)
- **B**: different contract, both MANUFACTURER type, `matched_row.contract_manufacturer == task.contract_manufacturer_infor` (same manufacturer)
- **C**: different contract, both DISTRIBUTOR type, `matched_row.ERPVendorID[:7] == task.vendor_id[:7]` (same vendor)
- **D**: everything else (including all Infor residue)

New: **`calculate_confidence_score(input_item, matched_row, pair_type, model)`** with 4 weight regimes:

| Factor | Type A | Type B | Type C (desc>0.4) | Type C (desc≤0.4) | Type D (desc>0.4) | Type D (desc≤0.4) |
|--------|--------|--------|--------------------|--------------------|--------------------|--------------------|
| MFN | 50% | 50% | 20% | 10% | 40% | 20% |
| Description | skip | skip | 30% | 40% | 30% | 50% |
| EA Price | 25% | 25% | 10% | 10% | 15% | 15% |
| UOM | 10% | 10% | 10% | 10% | 10% | 10% |
| QOE | 15% | 15% | 10% | 10% | 5% | 5% |
| VendorItem | — | — | 20% | 20% | — | — |

Buckets: HIGH ≥ 0.8, MED ≥ 0.6, LOW < 0.6

**5. Update `matched_item_ref` format in preprocess_service.py**
- Manufacturer contracts (task.process_type contains MANUFACTURER):
  - CCX: `f"{row['mfg_catalog_num_ccx']}|{row['uom_ccx']}"`
  - Infor: `f"{row['mfg_catalog_num_infor']}|{row['uom_infor']}"`
- Distributor contracts:
  - CCX: `f"{row['vendor_catalog_num_ccx']}|{row['uom_ccx']}"`
  - Infor: `f"{row['vendor_catalog_num_infor']}|{row['uom_infor']}"`

**6. Update `run_sku_matching()` and `run_infor_residue()`**
- Call `delete_match_results(task_id)` at start of `run_sku_matching()`
- Replace `_sim_score()` with `calculate_confidence_score()`, passing input item fields, matched row fields, pair_type, and model
- Store all sub-scores (`mfn_score`, `desc_score`, `price_score`, etc.) in each match dict
- Determine pair_type per match and store it
- File: preprocess_service.py

---

### Phase C: Precheck Duplicate Modes (steps 7-9, *parallel with Phase B*)

**7. Update intake duplicate detection logic**

Current behavior in intake_service.py:
- MANUFACTURER → checks `reduced_mfg|UOM` (functionally = old "explicit" mode)
- DISTRIBUTOR → checks `reduced_mfg|UOM` + `reduced_vendor`

Old repo had 4 modes with different duplicate keys:

| Mode | Old Repo Keys | Purpose |
|------|--------------|---------|
| `default` | Reduced Mfg Part Num only | Catches `aaa-bb` = `aaabb` |
| `strict` | Exact Mfg Part Num (no reduction) | `aaa-bb` ≠ `aaabb` are different items |
| `explicit` | Exact Mfg Part Num + UOM | `aaa-bb BX` ≠ `aaa-bb CA` are different |
| `distributor` | ERP VendorID + Mfg Part Num + UOM + Contract# | Old dist rule, but we should adapt to VendorID + VendorItem for new repo |

Adaptation for new repo:
- `default`: `reduced_mfg` only (no UOM) — catches `aaa-bb` = `aaabb`
- `strict`: `exact_mfg` only (no reduction, no UOM) — treats `aaa-bb` and `aaabb` as different
- `explicit`: `exact_mfg + UOM` — so `aaa-bb BX` ≠ `aaa-bb CA`
- `distributor`: `vendor_id_short + reduced_vendor_catalog_num` (since distributor items are keyed by vendor item)

Changes to intake_service.py:
- Read `task.precheck_mode` (default/strict/explicit/distributor)
- Replace current hard-coded `_check_mfg_uom_dup()` logic with mode-aware duplicate keys
- `default`: key = `reduced_mfg` (warn on dup)
- `strict`: key = `clean_mfg` (error on exact dup, warn if reduced matches)
- `explicit`: key = `clean_mfg|std_uom` (error on exact dup, warn if reduced matches)
- `distributor`: key = `vendor_id_short|reduced_vendor` (error on exact dup) + also run mfg check as warnings

**8. Add precheck_mode selector to intake UI**
- File: intake_form.html — add a dropdown/radio near the precheck button: "Duplicate Check Mode: Default / Strict / Explicit / Distributor" with a brief explanation of each
- The selected mode is POSTed with the precheck request

**9. Wire mode through intake routes**
- File: intake/routes.py — the `/api/intake/<task_id>/precheck` route reads the `precheck_mode` from request body, stores it on the Task via `task_repo.update_task(task_id, precheck_mode=mode)`, then passes to `intake_service.run_precheck()`

---

### Phase D: UI Overhaul (steps 10-13, *depends on Phase A*)

**10. Pipeline stepper** (keep current, compact at top of page)

**11. Contract-Level View section**
- After pipeline completes, show contract cards/table: contract ID, description, manufacturer, total matches, HIGH/MED/LOW counts, include/exclude toggle
- Green/red left-border styling (like old step2.html)
- Search/filter, batch include/exclude
- Click contract → expand or modal showing constituent matches

**12. Item-Level View section**
- 3 confidence cards (High green, Medium orange, Low red) with counts + false-positive sub-counts
- Clicking a card filters the detail table
- Table columns: Mfg Part Num (Match), Mfg Part Num (Input), Vendor Item (Match), Vendor Item (Input), Contract ID, Organization, Description (Match), Description (Input), UOM (Match/Input), QOE (Match/Input), Contract Price, EA Price (Match/Input), Confidence Score, Match Type, Pair Type, False Positive checkbox
- Sortable headers, search, compact 0.75rem font
- Select All / Deselect All / Save Selections buttons

**13. New API routes** in routes.py:
- `GET .../contract-summary` — grouped match counts by contract
- `GET .../matches?bucket=HIGH&contract=X` — filtered matches with full join to TaskItem fields
- `POST .../update-false-positives` — set selected match_ids to REJECTED
- `POST .../toggle-contract` — include/exclude entire contract

**File**: preprocess.html — full rewrite

---

### Phase E: Rerun + Navigation Fixes (steps 14-15, *parallel with Phase D*)

**14. Rerun button state**
- On page load, check if matches exist → "Rerun Full Preprocess" vs "Run Full Preprocess"
- Rerun calls `delete_match_results()` first (via step 2)

**15. Task page phase link**
- In the tasks list/detail page, when `task.phase == 'PREPROCESS'`, link should go to `/preprocess/<task_id>` not `/identity/<task_id>`
- File: tasks/templates/ — update the action link

---

### Phase F: Verification

16. Apply migration 010 to SQL Server
17. Run pipeline on task 7E8C — confirm matches replaced not appended on rerun
18. Verify pair-type detection: same-contract items get type A, different-contract-same-mfg get type B
19. Verify multi-factor scores produce reasonable HIGH/MED/LOW distribution
20. Test precheck with strict mode (`aaa-bb` vs `aaabb` should NOT flag as duplicate)
21. Test false-positive toggle → confirm downstream exclusion
22. Browser test: contract cards, confidence filtering, sort, search, save selections

---

**Relevant files**:
- scoring.py — full rewrite with pair-type + multi-factor
- preprocess_service.py — matched_item_ref, cleanup, new scoring
- intake_service.py — precheck_mode support
- task_repo.py — `delete_match_results()`
- models.py — `Task.precheck_mode`, MatchResult scoring columns
- routes.py — new API routes
- routes.py — wire precheck_mode
- preprocess.html — UI overhaul
- intake_form.html — mode selector
- dup_detection.sql — verify columns
- `migrations/010_add_precheck_mode_and_scoring.sql` — new migration

**Decisions**:
- `matched_item_ref` = `MfgNum|UOM` for manufacturer, `VendorItem|UOM` for distributor (original UOM, not EDI)
- Pair types A/B/C/D determine weight regime; Infor residue always type D
- Precheck modes: default (reduced_mfg), strict (exact_mfg), explicit (exact_mfg+UOM), distributor (vendor_id+vendor_item)
- False-positive = `match_status = 'REJECTED'`, cascades to all downstream steps
- `rapidfuzz` for Levenshtein in MFN scoring fallback (add to requirements.txt)
- Measurement extraction overlay for description similarity (port from old repo)

**Open question**: For the distributor precheck mode, the old repo uses `ERP VendorID + Mfg Part Num + UOM + Contract Number`. You mentioned checking `VendorID + VendorItem`. Which duplicate keys do you want for distributor mode — the old repo's combination or `vendor_id_short + vendor_catalog_num`?