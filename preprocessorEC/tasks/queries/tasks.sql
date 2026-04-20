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

-- name: vendor_search
SELECT ERPVendorID, VendorName, PurchaseFromName, Active
FROM [Preprocessor].[PurchaseVendorLocation]
WHERE UPPER(ERPVendorID) LIKE :q
   OR UPPER(VendorName) LIKE :q
   OR (PurchaseFromName IS NOT NULL AND UPPER(PurchaseFromName) LIKE :q)
ORDER BY VendorName, PurchaseFromName;

