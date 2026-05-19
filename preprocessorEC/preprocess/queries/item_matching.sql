-- name: infor_cascade_by_ccx_pkids
-- Fetch Infor contract lines that reference accepted CCX pkids.
-- These are Infor-side records that map to CCX-matched items.
-- The CCX_pkid link is pre-computed in InforActiveCLRefCCXSyncedCL.
SELECT
    icl.Infor_pkid,
    icl.OrganizationEID,
    icl.Organization,
    icl.ContractID,
    icl.ERPVendorID_Infor        AS erp_vendor_id,
    icl.VendorID_Infor           AS vendor_id,
    icl.VendorItem_Infor         AS vendor_catalog_num_infor,
    icl.ManufacturerNumber_Infor AS mfg_catalog_num_infor,
    icl.UOM_Infor                AS uom_infor,
    icl.QOE_Infor                AS qoe_infor,
    icl.ContractPrice_Infor      AS unit_price_infor,
    icl.ItemType,
    icl.ItemNumber               AS infor_item_number,
    icl.Item                     AS infor_item,
    icl.reduced_mfg_num_infor,
    icl.reduced_vendor_num_infor,
    icl.CCXCurrentSyncFlag,
    icl.JoinSyncType,
    icl.CCX_pkid,
    icl.matched_ccx_line_seq,
    icl.ItemDescription_Infor,
    icl.ContractLineManufacturer_Infor AS contract_line_manufacturer
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL] icl
WHERE icl.CCX_pkid IN :ccx_pkids
  AND (
      :org_eid = '105188574'
      OR icl.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: infor_linked_pkids_by_ccx_pkids
-- Fetch all linked Infor pkids for a set of CCX pkids.
-- One CCX pkid can map to multiple Infor pkids in rare cases.
SELECT DISTINCT
    link.CCX_pkid,
    link.Infor_pkid
FROM [Preprocessor].[CCXInforMatchedLink] link
WHERE link.CCX_pkid IN :ccx_pkids
  AND link.Infor_pkid IS NOT NULL;

-- name: infor_residue_match
-- Infor residue: Infor lines with NULL CCX_pkid (no CCX match).
-- Match by reduced mfg or vendor number against INPUT items.
SELECT
    icl.Infor_pkid,
    icl.OrganizationEID,
    icl.Organization,
    icl.ContractID,
    icl.ERPVendorID_Infor        AS erp_vendor_id,
    icl.VendorID_Infor           AS vendor_id,
    icl.VendorItem_Infor         AS vendor_catalog_num_infor,
    icl.ManufacturerNumber_Infor AS mfg_catalog_num_infor,
    icl.UOM_Infor                AS uom_infor,
    icl.QOE_Infor                AS qoe_infor,
    icl.ContractPrice_Infor      AS unit_price_infor,
    icl.ItemType,
    icl.ItemNumber               AS infor_item_number,
    icl.Item                     AS infor_item,
    icl.reduced_mfg_num_infor,
    icl.reduced_vendor_num_infor,
    icl.CCXCurrentSyncFlag,
    icl.JoinSyncType,
    icl.ItemDescription_Infor,
    icl.ContractLineManufacturer_Infor AS contract_line_manufacturer,
    CASE
        WHEN icl.reduced_mfg_num_infor = :reduced_mfg_num THEN 'REDUCED_MFG'
        WHEN icl.reduced_vendor_num_infor = :reduced_vendor_num THEN 'REDUCED_VPN'
        ELSE 'CROSS_MATCH'
    END AS match_type
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL] icl
WHERE icl.CCX_pkid IS NULL
  AND (
        icl.reduced_mfg_num_infor = :reduced_mfg_num
     OR icl.reduced_vendor_num_infor = :reduced_vendor_num
  )
  AND (
      :org_eid = '105188574'
      OR icl.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: item_label_mdm_item
-- Find Infor Item# via MDM_ITEM (manufacturer + mfg catalog number).
-- Returns Item with Active status.
SELECT DISTINCT
    mi.Item,
    mi.Active,
    mi.DefaultBuyUOM,
    mi.DefaultBuyUOMMultiplier,
    mi.Description                AS mdm_description
FROM [DM_MONTYNT\dli2].[MDM_ITEM] mi
WHERE mi.Manufacturer = :manufacturer
  AND mi.ManufacturerNumber = :mfg_catalog_num
  AND mi.Active = 'Yes';

-- name: item_label_mdm_vendoritem
-- Find Infor Item# via MDM_VENDORITEM (vendor + vendor item number).
-- Returns Item with Active status.
SELECT DISTINCT
    mvi.Item,
    mvi.Active,
    mvi.Manufacturer,
    mvi.ManufacturerNumber,
    mvi.VendorBuyUOM,
  CAST(mvi.[VendorBuyUOM.UOMConversion] AS INT) AS vendor_uom_conversion
FROM [DM_MONTYNT\dli2].[MDM_VENDORITEM] mvi
WHERE mvi.Vendor = :vendor_id
  AND mvi.VendorItem = :vendor_catalog_num
  AND mvi.Active = 'Yes';

-- name: item_label_infor_item_by_pkid
-- Find Infor master Item from an accepted INFOR_CL lineage row.
SELECT DISTINCT
    icl.Item,
    icl.Infor_pkid
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL] icl
WHERE icl.Infor_pkid = :infor_pkid
  AND icl.Item IS NOT NULL
  AND LTRIM(RTRIM(CONVERT(VARCHAR(50), icl.Item))) <> '';

-- name: item_description_by_item_number
-- Find item master description for an individual Infor Item.
SELECT TOP 1
    mi.Description AS item_description
FROM [DM_MONTYNT\dli2].[MDM_ITEM] mi
WHERE mi.Item = :item_number;

-- name: item_uom_options
-- Get valid buy UOM options for an Infor Item.
SELECT
    iu.UOM,
    CAST(iu.UOMConversion AS INT) AS UOMConversion,
    iu.ValidForBuying
FROM [DM_MONTYNT\dli2].[MDM_ITEMUOM] iu
WHERE iu.Item = :item_number
  AND iu.ValidForBuying IN ('Valid', 'Default')
ORDER BY CAST(iu.UOMConversion AS INT), iu.UOMConversion;

-- name: inactive_gtin_items
-- Find item/UOM pairs that have an inactive GTIN record.
SELECT
    gtin.Item,
    gtin.UOM,
    gtin.Active AS ActiveGTIN
FROM [DM_MONTYNT\dli2].[MDM_ITEMGTIN] gtin
WHERE gtin.Active = 'No';
