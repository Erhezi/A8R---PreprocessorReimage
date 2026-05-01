-- name: contract_headers_by_org_contract
-- Fetch ContractSourceType + ContractProcessType for a set of
-- (Organization, ContractID) pairs from CCXInforSyncedContractHeader.
-- Returns one row per matching header; caller dedupes if needed.
SELECT
    Organization,
    ContractID,
    ContractSourceType,
    ContractProcessType
FROM [Preprocessor].[CCXInforSyncedContractHeader]
WHERE ContractID IN :contract_ids;

-- name: infor_items_by_pkid
-- Resolve the Item Master item number for a set of Infor pkids.
SELECT
    Infor_pkid,
    Item
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL]
WHERE Infor_pkid IN :infor_pkids;

-- name: workspace_exists
-- Cheap existence probe used by the idempotent populator.
SELECT TOP 1 dedup_id
FROM [Preprocessor].[PreprocessorTaskItemForDecision]
WHERE task_id = :task_id;

-- name: workspace_for_task
-- Read all dedup workspace rows for a task. CCX/INFOR_CL filter applied
-- by caller; ordering by input_item_id then dedup_sort makes the table
-- group neatly in the UI.
SELECT *
FROM [Preprocessor].[PreprocessorTaskItemForDecision]
WHERE task_id = :task_id
ORDER BY input_item_id ASC, dedup_sort ASC, dedup_id ASC;
