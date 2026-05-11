-- common.sql: Shared queries used across modules
-- All queries use :param named parameter style for SQLAlchemy text()

-- name: get_valid_vendor_ids
-- Get distinct active vendor IDs from MDM supplier table
SELECT DISTINCT Vendor
FROM [DM_MONTYNT\dli2].MDM_SUPPLIER_NAME_INFOR
WHERE active = 'Yes' AND VENDOR <> '';

-- name: get_vendor_supplier_mapping
-- Full vendor-supplier mapping with names
SELECT Supplier, Vendor, VendorName
FROM [DM_MONTYNT\dli2].MDM_SUPPLIER_NAME_INFOR
WHERE active = 'Yes' AND VENDOR <> '';

-- name: get_vendor_names_by_erp_ids
-- Batch lookup of VendorName by ERPVendorID. Used for LLM review prompts so
-- the model sees vendor *names* on both sides of a match pair instead of bare
-- IDs. Returns one row per distinct ERPVendorID found in PurchaseVendorLocation.
SELECT ERPVendorID, MAX(VendorName) AS VendorName
FROM [Preprocessor].[PurchaseVendorLocation]
WHERE ERPVendorID IN :erp_vendor_ids
GROUP BY ERPVendorID;

-- name: get_uom_mapping
-- UOM standard substitution lookup
SELECT UOM_Input, UOM_Standard
FROM [DM_MONTYNT\dli2].PreprocessorUOMMapping;

-- name: get_edi_sub_uom
-- EDI UOM translation table
SELECT OriginalUOM, TranslatedUOM
FROM [DM_MONTYNT\dli2].PreprocessorEDIUOM;
