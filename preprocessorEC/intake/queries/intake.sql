-- name: get_valid_uoms
-- All valid UOM codes so far
SELECT DISTINCT UPPER(UOM)
FROM [Preprocessor].ValidUOM;

-- name: get_uom_to_match_infor_map
-- Translate standardized input UOM (ExternalValue) to Infor UOM (LawsonValue)
SELECT DISTINCT
    UPPER(LTRIM(RTRIM(externalValue))) AS external_value,
    UPPER(LTRIM(RTRIM(LawsonValue))) AS lawson_value
FROM [DM_MONTYNT\dli2].MDM_EDI_SUB_UOM
WHERE NULLIF(LTRIM(RTRIM(externalValue)), '') IS NOT NULL
  AND NULLIF(LTRIM(RTRIM(LawsonValue)), '') IS NOT NULL;

-- name: get_valid_vendors
-- Active vendor codes from MDM supplier master
SELECT DISTINCT LTRIM(RTRIM(Vendor))
FROM [DM_MONTYNT\dli2].MDM_SUPPLIER_NAME_INFOR
WHERE active = 'Yes'
  AND Vendor <> '';

-- name: get_valid_erp_vendor_ids
-- Active ERP vendor-location IDs (includes both 0000000 and 0000000-B000 forms)
SELECT ERPVendorID
FROM [Preprocessor].[PurchaseVendorLocation]
WHERE [Active] = 'Yes';
