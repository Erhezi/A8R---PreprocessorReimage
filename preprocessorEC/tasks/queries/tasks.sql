-- name: contract_lookup
SELECT TOP 1
    ContractID,
    ERPVendorID,
    ContractProcessType,
    ContractSourceType,
    Organization,
    Manufacturer,
    ContractStartDate,
    ContractEndDate,
    Vendor
FROM [Preprocessor].[CCXInforSyncedContractHeader]
WHERE ContractID = :cid;

-- name: contract_tier_count
SELECT COUNT(DISTINCT DC_ContractRefID) AS cnt
FROM [Preprocessor].[CCXInforSyncedContractHeader]
WHERE ContractID = :cid;

-- name: contract_validate_by_org
SELECT TOP 1
    ContractID,
    ERPVendorID,
    ContractProcessType,
    ContractSourceType,
    Organization,
    Manufacturer,
    ContractStartDate,
    ContractEndDate,
    Vendor
FROM [Preprocessor].[CCXInforSyncedContractHeader]
WHERE ContractID = :cid
  AND Organization = :org;

-- name: contract_validate_any
SELECT TOP 1
    ContractID,
    ERPVendorID,
    ContractProcessType,
    ContractSourceType,
    Organization,
    Manufacturer,
    ContractStartDate,
    ContractEndDate,
    Vendor
FROM [Preprocessor].[CCXInforSyncedContractHeader]
WHERE ContractID = :cid;

-- name: contract_rows_by_id
-- All CCX synced header rows for a contract id (a contract can span multiple
-- organizations / tiers). Used to register/verify a CCX contract number on a task.
SELECT
    ContractID,
    ERPVendorID,
    Organization,
    ContractEndDate,
    Vendor
FROM [Preprocessor].[CCXInforSyncedContractHeader]
WHERE ContractID = :cid;

-- name: contract_description_by_id
-- The CCX contract description for a contract id, sourced from the CCX synced
-- contract line-count table (one description per contract, keyed by
-- OrganizationEID + ContractID + ERPVendorID). Descriptions are contract-level,
-- so any non-null row for the contract id serves; TOP 1 keeps it deterministic.
SELECT TOP 1 ContractDescription
FROM [Preprocessor].[CCXSyncedContractLineCnt]
WHERE ContractID = :cid
  AND ContractDescription IS NOT NULL
ORDER BY ContractDescription;

-- name: vendor_search
SELECT ERPVendorID, VendorName, PurchaseFromName, Active
FROM [Preprocessor].[PurchaseVendorLocation]
WHERE UPPER(ERPVendorID) LIKE :q
   OR UPPER(VendorName) LIKE :q
   OR (PurchaseFromName IS NOT NULL AND UPPER(PurchaseFromName) LIKE :q)
ORDER BY VendorName, PurchaseFromName;

