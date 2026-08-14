-- name: ccx_lines_by_contract_scope
-- Current CCX_pkid for every line of the given contracts, keyed by the stable
-- business key (the UX_CCXSyncedCL_ItemPerRN unique index).
--
-- CCX_pkid is a surrogate that the daily archive-and-reload re-issues, so a
-- pkid snapshotted onto PreprocessorMatchResult during SKU matching cannot be
-- trusted on a later request. _refresh_ccx_pkids() uses this to re-resolve the
-- snapshotted business key back to the current pkid before any pkid-keyed join.
--
-- Filtering on the three contract-scope columns hits the unique index; the
-- caller narrows to the exact 6-part key in Python. All three lists are small
-- (a task spans a handful of contracts), and the caller chunks contract_ids.
SELECT
    ccx.CCX_pkid,
    ccx.OrganizationEID,
    ccx.ContractID,
    ccx.ERPVendorID,
    ccx.ManufacturerNumber_CCX,
    ccx.UOM_CCX,
    ccx.UOMtoMatchInfor_CCX
FROM [Preprocessor].[CCXSyncedContractLine] ccx
WHERE ccx.ContractID      IN :contract_ids
  AND ccx.OrganizationEID IN :org_eids
  AND ccx.ERPVendorID     IN :erp_vendor_ids;

-- name: infor_cascade_by_infor_pkids
-- Infor contract lines for a set of Infor_pkid values.
--
-- This is the cascade's entry point. Infor_pkid is a business key
-- (Contract + '-' + ContractLine, e.g. '1001-1'), so it survives the nightly
-- TRUNCATE/INSERT of the source tables. CCX_pkid does not: every reload
-- re-issues it, so a pkid snapshotted during SKU matching points at an
-- unrelated line by the next morning.
--
-- run_sku_matching already records the linked Infor pkids on each CCX match row
-- (PreprocessorMatchResult.infor_pkids_matched), so the cascade reads them from
-- there rather than re-deriving the linkage from a pkid that has since moved.
--
-- Only Infor-side columns are selected, so DISTINCT collapses the
-- (Infor_pkid, matched_ccx_line_seq) rows to one row per Infor line.
SELECT DISTINCT
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
    icl.ItemDescription_Infor,
    icl.ContractLineManufacturer_Infor AS contract_line_manufacturer
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL] icl
WHERE icl.Infor_pkid IN :infor_pkids
  AND (
      :org_eid = '105188574'
      OR icl.OrganizationEID IN (:org_eid, '105188574')
  );

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

-- name: infor_residue_match_mfg_set
-- Set-based Infor residue match on reduced manufacturer numbers.
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
    icl.ContractLineManufacturer_Infor AS contract_line_manufacturer
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL] icl
WHERE icl.CCX_pkid IS NULL
  AND icl.reduced_mfg_num_infor IN :reduced_mfg_nums
  AND (
      :org_eid = '105188574'
      OR icl.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: infor_residue_match_vendor_set
-- Set-based Infor residue match on reduced vendor numbers.
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
    icl.ContractLineManufacturer_Infor AS contract_line_manufacturer
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL] icl
WHERE icl.CCX_pkid IS NULL
  AND icl.reduced_vendor_num_infor IN :reduced_vendor_nums
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

-- name: item_label_mdm_item_set
-- Set-based MDM_ITEM lookup for a single manufacturer and many mfg numbers.
SELECT DISTINCT
    mi.Manufacturer,
    mi.ManufacturerNumber,
    mi.Item,
    mi.Active,
    mi.DefaultBuyUOM,
    mi.DefaultBuyUOMMultiplier,
    mi.Description                AS mdm_description
FROM [DM_MONTYNT\dli2].[MDM_ITEM] mi
WHERE mi.Manufacturer = :manufacturer
  AND mi.ManufacturerNumber IN :mfg_catalog_nums
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

-- name: item_label_mdm_vendoritem_set
-- Set-based MDM_VENDORITEM lookup. The IN predicates intentionally return a
-- superset; callers pair Vendor + VendorItem exactly in Python.
SELECT DISTINCT
    mvi.Vendor,
    mvi.VendorItem,
    mvi.Item,
    mvi.Active,
    mvi.Manufacturer,
    mvi.ManufacturerNumber,
    mvi.VendorBuyUOM,
    CAST(mvi.[VendorBuyUOM.UOMConversion] AS INT) AS vendor_uom_conversion
FROM [DM_MONTYNT\dli2].[MDM_VENDORITEM] mvi
WHERE mvi.Vendor IN :vendor_ids
  AND mvi.VendorItem IN :vendor_catalog_nums
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

-- name: item_label_infor_item_by_pkids_set
-- Set-based Infor master Item lookup from accepted INFOR_CL lineage rows.
SELECT DISTINCT
    icl.Infor_pkid,
    icl.Item
FROM [Preprocessor].[InforActiveCLRefCCXSyncedCL] icl
WHERE icl.Infor_pkid IN :infor_pkids
  AND icl.Item IS NOT NULL
  AND LTRIM(RTRIM(CONVERT(VARCHAR(50), icl.Item))) <> '';

-- name: item_description_by_item_number
-- Find item master description for an individual Infor Item.
SELECT TOP 1
    mi.Description AS item_description
FROM [DM_MONTYNT\dli2].[MDM_ITEM] mi
WHERE mi.Item = :item_number;

-- name: item_descriptions_by_item_numbers
-- Set-based item master descriptions.
SELECT
    mi.Item,
    mi.Description AS item_description
FROM [DM_MONTYNT\dli2].[MDM_ITEM] mi
WHERE mi.Item IN :item_numbers;

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
