-- name: get_valid_uoms
-- All valid UOM codes so far
SELECT DISTINCT UPPER(UOM)
FROM [Preprocessor].ValidUOM;

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
