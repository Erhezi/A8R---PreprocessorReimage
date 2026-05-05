-- name: dedup_review_rows
-- Pull the v1.0-compatible "dedup output to review" payload for a task.
-- Filters to CCX + ACCEPTED workspace rows (matched_source='CCX' implies
-- ACCEPTED because populate_dedup_workspace only materializes ACCEPTED
-- matches, but we re-assert here for safety). EffectiveDate/ExpirationDate
-- come from CCXSyncedContractLine via PreprocessorMatchResult.ccx_pkid,
-- which is not snapshotted on the workspace row.
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
    tid.infor_item_number,
    tid.resolution_grouping,
    tid.task_intention,
    tid.matched_contract_source_type,
    tid.input_contract_source_type,
    tid.dedup_sort
FROM [Preprocessor].[PreprocessorTaskItemForDecision] tid
INNER JOIN [Preprocessor].[PreprocessorMatchResult] mr
    ON tid.match_id = mr.match_id
LEFT JOIN [Preprocessor].[CCXSyncedContractLine] ccx
    ON ccx.CCX_pkid = mr.ccx_pkid
WHERE tid.task_id = :task_id
  AND tid.matched_source = 'CCX'
  AND tid.match_status = 'ACCEPTED'
ORDER BY
    tid.organization_eid_matched ASC,
    tid.contract_id_matched ASC,
    tid.erp_vendor_id_matched ASC,
    tid.input_item_id ASC,
    tid.dedup_sort ASC,
    tid.dedup_id ASC;


-- name: contract_line_counts
-- Total CCX-synced line count per matched (Org, Contract, ERPVendor)
-- key. Used to populate the "quick_line_count" sheet alongside the
-- per-key matched count computed from the workspace rows themselves.
SELECT
    cnt.OrganizationEID,
    cnt.Organization,
    cnt.ContractID,
    cnt.ERPVendorID,
    cnt.LineCnt_CCX
FROM [Preprocessor].[CCXSyncedContractLineCnt] cnt
WHERE cnt.ContractID IN :contract_ids;


-- name: view_by_input_rows
-- Payload for the "view_by_input" sheet: every INPUT line on the task
-- left-joined to its CCX ACCEPTED matches in PreprocessorTaskItemForDecision
-- (with EffectiveDate/ExpirationDate from CCXSyncedContractLine via
-- PreprocessorMatchResult.ccx_pkid). Inputs with no ACCEPTED CCX match still
-- appear once, with NULL matched columns and total_matched_lines = 0. The
-- per-input match count is computed with a window so a single pass returns
-- both the rows and the count.
SELECT
    ti.item_id                                            AS input_item_id,
    ti.file_row                                           AS file_row,
    ti.mfg_catalog_num                                    AS manufacturer_number_input,
    ti.vendor_catalog_num                                 AS vendor_item_input,
    ti.description                                        AS item_description_input,
    ti.uom                                                AS uom_input,
    ti.qoe                                                AS qoe_input,
    ti.uom_to_match_infor                                 AS uom_to_match_infor_input,
    COALESCE(tid.contract_id_input,    t.contract_number) AS contract_id_input,
    COALESCE(tid.erp_vendor_id_input,  t.vendor_id)       AS erp_vendor_id_input,
    COALESCE(tid.organization_input,   t.organization)    AS organization_input,
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
    ccx.EffectiveDate_CCX                                 AS effective_date_matched,
    ccx.ExpirationDate_CCX                                AS expiration_date_matched,
    tid.dedup_sort,
    COUNT(tid.dedup_id) OVER (PARTITION BY ti.item_id)    AS total_matched_lines
FROM [Preprocessor].[PreprocessorTaskItem] ti
INNER JOIN [Preprocessor].[PreprocessorTask] t
    ON t.task_id = ti.task_id
LEFT JOIN [Preprocessor].[PreprocessorTaskItemForDecision] tid
    ON tid.input_item_id  = ti.item_id
    AND tid.matched_source = 'CCX'
    AND tid.match_status   = 'ACCEPTED'
LEFT JOIN [Preprocessor].[PreprocessorMatchResult] mr
    ON mr.match_id = tid.match_id
LEFT JOIN [Preprocessor].[CCXSyncedContractLine] ccx
    ON ccx.CCX_pkid = mr.ccx_pkid
LEFT JOIN [Preprocessor].[PreprocessorItemMatching] pim
    ON pim.task_id          = ti.task_id
    AND pim.item_id          = ti.item_id
    AND pim.infor_item_number = COALESCE(tid.infor_item_number, ti.infor_item_number)
WHERE ti.task_id        = :task_id
  AND ti.source_dataset = 'INPUT'
ORDER BY
    ti.file_row ASC,
    ti.item_id ASC,
    tid.organization_eid_matched ASC,
    tid.contract_id_matched ASC,
    tid.erp_vendor_id_matched ASC,
    tid.dedup_sort ASC,
    tid.dedup_id ASC;
