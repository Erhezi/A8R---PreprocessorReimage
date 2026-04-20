## Plan: Phase 3 v2 — Preprocess Core (Dup Detection + Item Matching + Sync)

Phase 3 takes PASSED_PC2 items, finds dups on CCX via reduced SKU matching (org-aware), scores + reviews to prune false positives, then **cascades** decisions to pre-joined Infor lines via `CCX_pkid`. Only Infor "residue" (`CCX_pkid=NULL` matches) goes through a separate item-level review. Finally, labels items with up to 3 Infor Item# sources, computes valid buyUOMs, and produces a unified preprocessed dataset (INPUT/CCX/INFOR stacked). LLM review via GPT-5-mini for MED/LOW items.

---

### Key Changes from v1

1. **New `[Preprocessor]` tables** replace old staging tables — `CCXSyncedContractLine` (~615K), `InforActiveCLRefCCXSyncedCL` (~604K, **pre-joined to CCX via `CCX_pkid`**), line count tables, `CCXInforMatchedLink`
2. **Org-aware matching** — MHS (org `105188574`) searches ALL orgs; entity-specific orgs search only same org + MHS. Applies to **both CCX and Infor**.
3. **CCX→Infor cascading** — TP/FP decisions on CCX lines automatically propagate to all Infor lines sharing the same `CCX_pkid`. Only Infor lines with `CCX_pkid IS NULL` need separate SKU matching + review.
4. **Sync check query dropped** — `InforActiveCLRefCCXSyncedCL` already has `CCXCurrentSyncFlag` and `JoinSyncType` pre-computed.
5. **3-source Item# labeling**: Item 1 (`MDM_ITEM` via Manufacturer+MfgNum), Item 2 (`MDM_VENDORITEM` via Vendor+VendorItem), Item 3 (inherited from TP Infor CL). Conflicts → show all 3 as error, user picks.
6. **Valid buyUOM** pre-computed from `MDM_ITEMUOM` as "BX\*5, PK\*10" strings.
7. **LLM integration**: GPT-5-mini via OpenAI API, key in `.env`, model configurable (future: Gemini).

---

### Task-Level Status Flow
```
PENDING_PREPROCESSOR → PREPROCESSING → REVIEW_CONTRACTS → REVIEW_ITEMS → LLM_REVIEW
  → INFOR_MATCHING → INFOR_REVIEW → ITEM_LABELING → PREPROCESSED
```

### Item-Level Status Flow
```
PASSED_PC2 → MATCHING → MATCHED / NO_MATCH → REVIEW_PENDING → MATCH_CONFIRMED
  → ITEM_LABELED / MULTI_ITEM_ERROR → PREPROCESSED
```

---

### Steps

**Phase A: Schema & Infrastructure**

1. **Migration 009** — `migrations/009_add_preprocess_columns.sql`: Add ~15 new columns to `PreprocessorTaskItem` (`input_reference`, `vendor_id`, `uom_to_match_infor`, `infor_item_1/2/3` + active flags, `infor_buy_uom_options`, `ccx_pkid`, `infor_pkid`, `organization_eid`, `organization_type`, `contract_manufacturer`, `mfg_name_infor_line/contract`, `vendor_name_infor`) and 4 to `PreprocessorMatchResult` (`contract_number`, `match_type`, `ccx_pkid`, `infor_pkid`)
2. **Update ORM models** — models.py: add all new columns
3. **Update statuses** — state.py: add task statuses (`INFOR_MATCHING`, `INFOR_REVIEW`, `ITEM_LABELING`) and item statuses (`MATCHING`, `MATCHED`, `NO_MATCH`, `REVIEW_PENDING`, `MATCH_CONFIRMED`, `ITEM_LABELED`, `MULTI_ITEM_ERROR`, `PREPROCESSED`)
4. **Update task_repo** — task_repo.py: add `add_match_results_bulk()`, `get_match_results_by_contract()`, `get_items_by_source()`, `get_accepted_ccx_pkids()`
5. **Add .env support** — config.py + new `.env.example`: `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-5-mini`)

**Phase B: SQL Queries** *(parallel with A)*

6. **Rewrite CCX queries** — dup_detection.sql: temp table management + 3 match queries (manufacturer, dist_premier, dist_local) against `[Preprocessor].[CCXSyncedContractLine]` with org filter and `CCXSyncedContractLineCnt` join. `CASE WHEN` for exact vs reduced match.
7. **Rewrite Infor queries** — item_matching.sql: `find_infor_matches_by_sku` against `InforActiveCLRefCCXSyncedCL` (residue, `CCX_pkid IS NULL`), `get_infor_lines_by_ccx_pkids` (cascade), `match_item_by_mfg` (`MDM_ITEM`), `match_item_by_vendor` (`MDM_VENDORITEM`), `get_valid_buy_uoms` (`MDM_ITEMUOM`)

**Phase C: Scoring & LLM** *(parallel with A, B)*

8. **Create scoring module** — new `preprocessorEC/services/scoring.py`: `calculate_mfn_match_score()` (complexity-weighted), `calculate_uom/qoe_score()`, `calculate_ea_price_score()`, `calculate_description_similarity()` (sentence transformer + Jaccard), `compute_weighted_score()` (MFN 40%, Desc 30%, Price 15%, UOM 10%, QOE 5%), `bucket_from_score()`, `load_sentence_model()`
9. **Create LLM module** — new `preprocessorEC/services/llm_review.py`: `get_llm_client()` (from .env), `review_item_pair()` → `{same_item, confidence, reasoning}`, `batch_review_items()`, structured prompt template. Abstract interface for future Gemini swap.

**Phase D: Core Service Logic** *(depends on A, B, C)*

10. **`run_sku_matching()`** — create temp table → execute CCX query by type → store `PreprocessorMatchResult` (source='CCX', `ccx_pkid`) + SQLite candidates → item statuses → drop temp table
11. **`compute_similarity()`** — score each (input, CCX) pair → weighted score → bucket → update both DBs
12. **`run_contract_check()`** — group by contract → join `CCXSyncedContractLineCnt` → routing heuristic → auto-include (same mfg OR max sim=100%) → queue rest for review
13. **Decision functions** — `submit_contract_decision()` marks all for a contract; `submit_item_decision()` marks individual; LLM_REVIEW triggers `llm_review.batch_review_items()` → queue for human approval; auto-transition when done
14. **CCX→Infor cascading** — collect accepted/rejected `ccx_pkid`s → query `InforActiveCLRefCCXSyncedCL` → auto-mark linked Infor lines as TP/FP
15. **Infor residue matching** — re-query `InforActiveCLRefCCXSyncedCL WHERE CCX_pkid IS NULL` with SKU join → score → bin HIGH/MED/LOW → INFOR_REVIEW
16. **Infor residue review** — simple item-only review (no contract grouping), HIGH/MED/LOW bins, MED/LOW can go to LLM
17. **Item labeling** — Item 1 (MDM_ITEM by Mfg+MfgNum), Item 2 (MDM_VENDORITEM by Vendor+VendorItem), Item 3 (TP Infor CL ItemNumber). Conflict → MULTI_ITEM_ERROR (show all 3, user picks). Compute buyUOM from MDM_ITEMUOM.
18. **`finalize_preprocess()`** — create CCX/INFOR rows in `PreprocessorTaskItem` with `input_reference` → verify no MULTI_ITEM_ERROR unresolved → all items → PREPROCESSED → advance guard

**Phase E: Routes & Templates** *(parallel with D)*

19. **Update routes** — fill stubs + add: `POST .../llm-review`, `GET .../infor-residue`, `POST .../infor-decision`, `POST .../resolve-multi-item`, `GET .../status`
20. **Templates** — preprocess.html with sections for CCX review, Infor residue review, LLM queue, Item labeling, MULTI_ITEM_ERROR resolution, preprocessed dataset preview

---

### Relevant Files
- preprocess_service.py — main logic (steps 10-18)
- `preprocessorEC/services/scoring.py` — new (step 8)
- `preprocessorEC/services/llm_review.py` — new (step 9)
- routes.py — routes (step 19)
- dup_detection.sql — CCX SQL (step 6)
- item_matching.sql — Infor SQL (step 7)
- models.py, state.py, task_repo.py — schema (steps 2-4)
- `migrations/009_add_preprocess_columns.sql` — migration (step 1)
- config.py + `.env.example` — config (step 5)

### Verification
1. Unit test scoring (MFN complexity, adaptive weights, buckets)
2. Unit test org filter (MHS→all, ENTITY→same+MHS)
3. Integration test CCX matching per contract type
4. **Integration test cascade**: accept CCX line → linked Infor lines auto-accepted
5. Integration test Infor residue (CCX_pkid=NULL only, scored separately)
6. Test Item 1/2/3: agreement, single source, conflict → MULTI_ITEM_ERROR
7. Test buyUOM computation (known items → expected strings)
8. Test LLM review round-trip (send pair → structured judgment)
9. End-to-end: intake→identity→preprocess → verify stacked dataset
10. Compare with reference repo on known contract

### Decisions
- New `[Preprocessor]` tables replace old staging tables
- CCX→Infor cascade via `CCX_pkid` avoids redundant review
- Infor residue: item-only review, still binned HIGH/MED/LOW, LLM-eligible
- Multi-item conflict: show all 3, mark error, user picks (no auto-priority)
- Sync check unnecessary — `CCXCurrentSyncFlag` pre-computed in `InforActiveCLRefCCXSyncedCL`
- LLM: GPT-5-mini via `.env`, abstract interface for future Gemini