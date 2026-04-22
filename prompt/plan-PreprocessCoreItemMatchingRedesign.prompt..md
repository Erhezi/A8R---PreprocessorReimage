## Plan: Preprocess Core Item Matching Redesign

Replace the current item-labeling logic so all four fields, `infor_item_1`, `infor_item_2`, `infor_item_3`, and `infor_item_number`, hold only 6-digit Infor master Item values. The redesign should stop using `matched_item_ref` as the source for `infor_item_3`, use accepted `INFOR_CL` matches keyed by `infor_pkid` back to `[Item]`, allow multiple matches per source as unique comma-space values, and then explode the final `infor_item_number` list into a new `Preprocessor.PreprocessorItemMatching` table. BuyUOM should move out of item labeling and become a separate preprocess step 8, while still writing aggregated results back to `PreprocessorTaskItem.infor_buy_uom_options`.

**Steps**
1. Update the item-labeling logic in preprocess_service.py so source 1 uses the task-level `contract_manufacturer_infor` plus `TaskItem.mfg_catalog_num` against `MDM_ITEM` with `Active = 'Yes'`.
2. In the same service flow, change source 2 to use `vendor_id_short` plus `TaskItem.vendor_catalog_num` against `MDM_VENDORITEM` with `Active = 'Yes'`, collecting all unique matching `Item` values rather than taking only the first row.
3. Redefine source 3 so accepted `INFOR_CL` matches use `MatchResult.infor_pkid` to look up `[Preprocessor].[InforActiveCLRefCCXSyncedCL].[Item]`, ignoring blank `Item` values and no longer reading `matched_item_ref` as the final item source.
4. Consolidate `infor_item_1`, `infor_item_2`, and `infor_item_3` into `infor_item_number` as unique comma-space values. If there is one unique item, keep `ITEM_LABELED`; if there are multiple unique items, keep them in `infor_item_number` and preserve the multi-item status for downstream handling.
5. Split BuyUOM out of preprocess_service.py so `run_item_labeling()` only collects and persists item numbers, then add a new step 8 function that runs immediately after labeling.
6. Add a new DB table `Preprocessor.PreprocessorItemMatching` via a new migration under migrations, with surrogate `match_item_id`, `task_id`, `item_id`, single `infor_item_number`, `item_description`, `created_at`, and `updated_at`.
7. Add ORM and repository support in models.py and task_repo.py to rebuild `PreprocessorItemMatching` rows for a task and bulk insert one row per exploded item number.
8. After final `infor_item_number` is written on each input row, populate `PreprocessorItemMatching` by splitting the canonical comma-space list into distinct rows and fetch `item_description` from `MDM_ITEM.Description` by exact item number.
9. Make the new BuyUOM step consume the exploded candidate rows, query `MDM_ITEMUOM` for each item, keep `ValidForBuying = 1`, and aggregate unique `UOM*UOMConversion` strings back onto `PreprocessorTaskItem.infor_buy_uom_options`.
10. Add targeted tests for multi-match aggregation, blank Infor `Item` handling, cross-source deduplication into final `infor_item_number`, exploded row creation, rerun idempotency, and BuyUOM aggregation.

**Relevant files**
- preprocess_service.py
- item_matching.sql
- task_repo.py
- models.py
- state.py
- routes.py
- 009_add_preprocess_columns.sql

**Verification**
1. Run focused tests around item-labeling aggregation and the new `PreprocessorItemMatching` repo helpers.
2. Run an integration check with rows covering: multiple `MDM_ITEM` hits, multiple `MDM_VENDORITEM` hits, accepted `INFOR_CL` rows with blank `Item`, and cross-source multi-item consolidation.
3. Verify DB results: `TaskItem.infor_item_1/2/3` and `infor_item_number` contain only 6-digit item values; `PreprocessorItemMatching` has one row per unique candidate item; `item_description` is populated; reruns do not duplicate rows.
4. Verify orchestration: full preprocess returns separate results for item labeling and BuyUOM step 8, and `infor_buy_uom_options` is only populated by the new step.

**Scope**
- Included: item-number source correction, multi-value consolidation, new exploded item-matching table, and BuyUOM separation.
- Excluded: broader UI redesign unless a minimal API adjustment is required by the new step split.

I saved this plan to session memory at `/memories/session/plan.md`. If this matches your intent, approve it and I’ll leave it ready for implementation handoff.