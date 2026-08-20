-- name: dedup_review_rows
-- Pull the v1.0-compatible "dedup output to review" payload for a task.
-- Filters to CCX + ACCEPTED workspace rows (matched_source='CCX' implies
-- ACCEPTED because populate_dedup_workspace only materializes ACCEPTED
-- matches, but we re-assert here for safety). EffectiveDate/ExpirationDate
-- come from the live CCXSyncedContractLine, matched on the stable business
-- key (Org, Contract, ERPVendor, MPN, UOM) -- NOT mr.ccx_pkid, which the
-- daily source sync re-issues so a snapshotted pkid drifts off its row.
SELECT
    tid.dedup_id,
    tid.input_item_id,
    tid.contract_id_matched,
    tid.erp_vendor_id_matched,
    tid.organization_eid_matched,
    tid.organization_matched,
    tid.manufacturer_number_matched,
    tid.vendor_item_matched,
    tid.item_desc_matched,
    tid.contract_price_matched,
    tid.uom_matched,
    tid.qoe_matched,
    tid.uom_to_match_infor_matched,
    tid.ea_price_matched,
    ccx.EffectiveDate_CCX            AS effective_date_matched,
    ccx.ExpirationDate_CCX           AS expiration_date_matched,
    tid.contract_id_input,
    tid.erp_vendor_id_input,
    tid.organization_eid_input,
    tid.organization_input,
    tid.manufacturer_number_input,
    tid.vendor_item_input,
    tid.item_description_input,
    tid.contract_price_input,
    tid.ea_price_input,
    tid.uom_input,
    tid.qoe_input,
    tid.uom_to_match_infor_input,
    tid.infor_item_number,
    tid.resolution_grouping,
    tid.task_intention,
    tid.matched_contract_source_type,
    tid.input_contract_source_type,
    tid.dedup_sort
FROM [Preprocessor].[PreprocessorTaskItemForDecision] tid
INNER JOIN [Preprocessor].[PreprocessorTaskItem] ti
    ON ti.item_id = tid.input_item_id
-- Live CCX dates via the stable business key. (Org, Contract, ERPVendor, MPN,
-- UOM_CCX) is globally unique in CCXSyncedContractLine, so this stays 1:1 (no
-- fan-out). Seeks the UX_CCXSyncedCL_ItemPerRN index whose leading columns are
-- exactly these five.
LEFT JOIN [Preprocessor].[CCXSyncedContractLine] ccx
    ON ccx.OrganizationEID        = tid.organization_eid_matched
   AND ccx.ContractID             = tid.contract_id_matched
   AND ccx.ERPVendorID            = tid.erp_vendor_id_matched
   AND ccx.ManufacturerNumber_CCX = tid.manufacturer_number_matched
   AND ccx.UOM_CCX                = tid.uom_matched
WHERE tid.task_id = :task_id
  AND tid.matched_source = 'CCX'
  AND tid.match_status = 'ACCEPTED'
  AND ti.status = 'ITEM_PREPROCESSED'
ORDER BY
    tid.organization_eid_matched ASC,
    tid.contract_id_matched ASC,
    tid.erp_vendor_id_matched ASC,
    tid.input_item_id ASC,
    tid.dedup_sort ASC,
    tid.dedup_id ASC;


-- name: replacement_unmatched_lines
-- For every (organization_eid, contract_id, erp_vendor_id) that the reviewer
-- marked as REPLACE, return all CCX-synced contract lines on that contract
-- *minus* the ones already ACCEPTED into the dedup workspace for this task.
-- The remainder represents "items the input file would not cover if it
-- replaces the matched contract" -- the export step appends these rows to
-- the per-contract sheet with a special Action/Notes pair.
SELECT
    ccx.OrganizationEID                  AS organization_eid_matched,
    ccx.Organization                     AS organization_matched,
    ccx.ContractID                       AS contract_id_matched,
    ccx.ERPVendorID                      AS erp_vendor_id_matched,
    ccx.ManufacturerNumber_CCX           AS manufacturer_number_matched,
    ccx.VendorItem_CCX                   AS vendor_item_matched,
    ccx.ItemDescription_CCX              AS item_desc_matched,
    ccx.ContractPrice_CCX                AS contract_price_matched,
    ccx.UOM_CCX                          AS uom_matched,
    ccx.QOE_CCX                          AS qoe_matched,
    ccx.EffectiveDate_CCX                AS effective_date_matched,
    ccx.ExpirationDate_CCX               AS expiration_date_matched
-- Lead with the (tiny) decision table and seek into CCX via direct column
-- equality. The CCX unique index UX_CCXSyncedCL_ItemPerRN leads with
-- (OrganizationEID, ContractID, ERPVendorID), so this seeks straight to the
-- one REPLACE contract's lines. DO NOT wrap the ccx columns in ISNULL(): that
-- is non-sargable and forces a full scan of the 600k+ row CCX table (observed
-- 270s vs 0.1s on a 24k-line contract). cd.* are NOT NULL with real scope
-- values, so direct equality is result-equivalent here.
FROM [Preprocessor].[PreprocessorContractDecision] cd
INNER JOIN [Preprocessor].[CCXSyncedContractLine] ccx
    ON ccx.OrganizationEID = cd.organization_eid
   AND ccx.ContractID      = cd.contract_id
   AND ccx.ERPVendorID     = cd.erp_vendor_id
-- Anti-join the accepted workspace lines off the contract's CCX lines via a
-- LEFT JOIN + "tid.dedup_id IS NULL" (left-over = CCX line with no accepted
-- match). Match on the stable business key (Org, Contract, ERPVendor, MPN,
-- UOM), NOT mr.ccx_pkid: the daily source sync re-issues CCX_pkid, so a stale
-- snapshotted pkid would fail to subtract an already-matched line and leak it
-- back as a false "only seen on to-be-replaced contract" leftover. A CCX line
-- matched by several inputs fans out here, but every such row has a non-NULL
-- dedup_id and is dropped by the IS NULL filter, leaving one row per leftover.
LEFT JOIN [Preprocessor].[PreprocessorTaskItemForDecision] tid
    ON tid.task_id          = :task_id
   AND tid.matched_source   = 'CCX'
   AND tid.match_status     = 'ACCEPTED'
   AND tid.organization_eid_matched    = ccx.OrganizationEID
   AND tid.contract_id_matched         = ccx.ContractID
   AND tid.erp_vendor_id_matched       = ccx.ERPVendorID
   AND tid.manufacturer_number_matched = ccx.ManufacturerNumber_CCX
   AND tid.uom_matched                 = ccx.UOM_CCX
WHERE cd.task_id   = :task_id
  AND cd.decision  = 'REPLACE'
  AND tid.dedup_id IS NULL
ORDER BY
    ccx.OrganizationEID ASC,
    ccx.ContractID ASC,
    ccx.ERPVendorID ASC,
    ccx.ManufacturerNumber_CCX ASC;


-- name: contract_line_counts
-- Total CCX-synced line count per matched (Org, Contract, ERPVendor)
-- key. Used to populate the "quick_line_count" sheet alongside the
-- per-key matched count computed from the workspace rows themselves.
SELECT
    cnt.OrganizationEID,
    cnt.Organization,
    cnt.ContractID,
    cnt.contractDescription,
    cnt.Vendor,
    cnt.ERPVendorID,
    cnt.LineCnt_CCX
FROM [Preprocessor].[CCXSyncedContractLineCnt] cnt
WHERE cnt.ContractID IN :contract_ids;


-- name: view_by_input_rows
-- Payload for the "view_by_input" sheet: every INPUT line on the task
-- left-joined to its CCX ACCEPTED matches in PreprocessorTaskItemForDecision
-- (with EffectiveDate/ExpirationDate from CCXSyncedContractLine, matched on
-- the stable business key, not mr.ccx_pkid). Inputs with no ACCEPTED CCX match still
-- appear once, with NULL matched columns and total_matched_lines = 0. The
-- per-input match count is computed with a window so a single pass returns
-- both the rows and the count.
SELECT
    ti.item_id                                            AS input_item_id,
    ti.file_row                                           AS file_row,
    ti.mfg_catalog_num                                    AS manufacturer_number_input,
    ti.vendor_catalog_num                                 AS vendor_item_input,
    ti.description                                        AS item_description_input,
    COALESCE(tid.contract_price_input, ti.unit_price)     AS contract_price_input,
    ti.uom                                                AS uom_input,
    ti.qoe                                                AS qoe_input,
    ti.uom_to_match_infor                                 AS uom_to_match_infor_input,
    COALESCE(tid.contract_id_input,    t.contract_number) AS contract_id_input,
    COALESCE(tid.erp_vendor_id_input,  t.vendor_id)       AS erp_vendor_id_input,
    COALESCE(tid.organization_input,   t.organization)    AS organization_input,
    t.contract_start_date                                 AS effective_date_input,
    t.contract_end_date                                   AS expiration_date_input,
    COALESCE(tid.infor_item_number,    ti.infor_item_number) AS infor_item_number,
    pim.infor_buy_uom_options                             AS infor_buy_uom_options,
    tid.dedup_id,
    tid.contract_id_matched,
    tid.erp_vendor_id_matched,
    tid.organization_eid_matched,
    tid.organization_matched,
    tid.manufacturer_number_matched,
    tid.vendor_item_matched,
    tid.item_desc_matched,
    tid.contract_price_matched,
    tid.uom_matched,
    tid.qoe_matched,
    tid.uom_to_match_infor_matched,
    ccx.EffectiveDate_CCX                                 AS effective_date_matched,
    ccx.ExpirationDate_CCX                                AS expiration_date_matched,
    tid.dedup_sort,
    COUNT(tid.dedup_id) OVER (PARTITION BY ti.item_id)    AS total_matched_lines
FROM [Preprocessor].[PreprocessorTaskItem] ti
INNER JOIN [Preprocessor].[PreprocessorTask] t
    ON t.task_id = ti.task_id
-- tid.task_id is redundant for correctness (item_id is a global identity, so
-- a workspace row can only belong to the task owning the input item) but it
-- is required for the seek: IX_TaskItemForDecision_TaskInput leads with
-- task_id, and without it the optimizer scans the whole multi-task workspace
-- table (observed 234s vs 1.1s at ~224k table rows).
LEFT JOIN [Preprocessor].[PreprocessorTaskItemForDecision] tid
    ON tid.task_id        = :task_id
    AND tid.input_item_id  = ti.item_id
    AND tid.matched_source = 'CCX'
    AND tid.match_status   = 'ACCEPTED'
-- CCX dates via the stable business key, not mr.ccx_pkid (re-issued daily by
-- the source sync). (Org, Contract, ERPVendor, MPN, UOM_CCX) is unique, so the
-- join is 1:1 and cannot fan out / inflate the total_matched_lines window.
LEFT JOIN [Preprocessor].[CCXSyncedContractLine] ccx
    ON ccx.OrganizationEID        = tid.organization_eid_matched
   AND ccx.ContractID             = tid.contract_id_matched
   AND ccx.ERPVendorID            = tid.erp_vendor_id_matched
   AND ccx.ManufacturerNumber_CCX = tid.manufacturer_number_matched
   AND ccx.UOM_CCX                = tid.uom_matched
LEFT JOIN [Preprocessor].[PreprocessorItemMatching] pim
    ON pim.task_id          = ti.task_id
    AND pim.item_id          = ti.item_id
    AND pim.infor_item_number = COALESCE(tid.infor_item_number, ti.infor_item_number)
WHERE ti.task_id        = :task_id
  AND ti.source_dataset = 'INPUT'
  AND ti.status         = 'ITEM_PREPROCESSED'
ORDER BY
    ti.file_row ASC,
    ti.item_id ASC,
    tid.organization_eid_matched ASC,
    tid.contract_id_matched ASC,
    tid.erp_vendor_id_matched ASC,
    tid.dedup_sort ASC,
    tid.dedup_id ASC;
