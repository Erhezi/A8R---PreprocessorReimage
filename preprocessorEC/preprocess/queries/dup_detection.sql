-- name: ccx_match_manufacturer
-- CCX duplicate detection for MANUFACTURER contracts.
-- Match reduced mfg # on INPUT row → reduced_mfg_num_ccx on CCXSyncedContractLine.
-- Org-aware: MHS (105188574) sees all orgs; ENTITY sees same org + MHS.
SELECT
    ccx.CCX_pkid,
    ccx.OrganizationEID,
    ccx.Organization,
    ccx.ContractID,
    ccx.ERPVendorID,
    ccx.ManufacturerNumber_CCX       AS mfg_catalog_num_ccx,
    ccx.VendorItem_CCX               AS vendor_catalog_num_ccx,
    ccx.ItemDescription_CCX          AS description_ccx,
    ccx.UOM_CCX                      AS uom_ccx,
    ccx.QOE_CCX                      AS qoe_ccx,
    ccx.ContractPrice_CCX            AS unit_price_ccx,
    ccx.UOMtoMatchInfor_CCX          AS uom_to_match_infor_ccx,
    ccx.reduced_mfg_num_ccx,
    ccx.reduced_vendor_num_ccx,
    ccx.ContractManufacturer_Infor   AS contract_manufacturer,
    ccx.ManufacturerName_Infor       AS mfg_name_infor,
    cnt.VendorID,
    cnt.Manufacturer,
    cnt.Vendor                       AS vendor_name,
    cnt.ContractDescription,
    hdr.ContractProcessType          AS match_process_type
FROM [Preprocessor].[CCXSyncedContractLine] ccx
JOIN [Preprocessor].[CCXSyncedContractLineCnt] cnt
    ON ccx.OrganizationEID = cnt.OrganizationEID
   AND ccx.ContractID      = cnt.ContractID
   AND ccx.ERPVendorID     = cnt.ERPVendorID
LEFT JOIN [Preprocessor].[CCXInforSyncedContractHeader] hdr
    ON hdr.Organization  = ccx.Organization
   AND hdr.ContractID    = ccx.ContractID
   AND hdr.ERPVendorID   = ccx.ERPVendorID
WHERE ccx.reduced_mfg_num_ccx = :reduced_mfg_num
  AND (
      :org_eid = '105188574'
      OR ccx.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: ccx_match_manufacturer_set
-- Set-based CCX duplicate detection for MANUFACTURER contracts.
-- Match all INPUT reduced mfg numbers in one expanding-bind batch.
SELECT
    ccx.CCX_pkid,
    ccx.OrganizationEID,
    ccx.Organization,
    ccx.ContractID,
    ccx.ERPVendorID,
    ccx.ManufacturerNumber_CCX       AS mfg_catalog_num_ccx,
    ccx.VendorItem_CCX               AS vendor_catalog_num_ccx,
    ccx.ItemDescription_CCX          AS description_ccx,
    ccx.UOM_CCX                      AS uom_ccx,
    ccx.QOE_CCX                      AS qoe_ccx,
    ccx.ContractPrice_CCX            AS unit_price_ccx,
    ccx.UOMtoMatchInfor_CCX          AS uom_to_match_infor_ccx,
    ccx.reduced_mfg_num_ccx,
    ccx.reduced_vendor_num_ccx,
    ccx.ContractManufacturer_Infor   AS contract_manufacturer,
    ccx.ManufacturerName_Infor       AS mfg_name_infor,
    cnt.VendorID,
    cnt.Manufacturer,
    cnt.Vendor                       AS vendor_name,
    cnt.ContractDescription,
    hdr.ContractProcessType          AS match_process_type
FROM [Preprocessor].[CCXSyncedContractLine] ccx
JOIN [Preprocessor].[CCXSyncedContractLineCnt] cnt
    ON ccx.OrganizationEID = cnt.OrganizationEID
   AND ccx.ContractID      = cnt.ContractID
   AND ccx.ERPVendorID     = cnt.ERPVendorID
LEFT JOIN [Preprocessor].[CCXInforSyncedContractHeader] hdr
    ON hdr.Organization  = ccx.Organization
   AND hdr.ContractID    = ccx.ContractID
   AND hdr.ERPVendorID   = ccx.ERPVendorID
WHERE ccx.reduced_mfg_num_ccx IN :reduced_mfg_nums
  AND (
      :org_eid = '105188574'
      OR ccx.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: ccx_match_distributor
-- CCX duplicate detection for DISTRIBUTOR contracts.
-- Match on reduced mfg OR reduced vendor number.
SELECT
    ccx.CCX_pkid,
    ccx.OrganizationEID,
    ccx.Organization,
    ccx.ContractID,
    ccx.ERPVendorID,
    ccx.ManufacturerNumber_CCX       AS mfg_catalog_num_ccx,
    ccx.VendorItem_CCX               AS vendor_catalog_num_ccx,
    ccx.ItemDescription_CCX          AS description_ccx,
    ccx.UOM_CCX                      AS uom_ccx,
    ccx.QOE_CCX                      AS qoe_ccx,
    ccx.ContractPrice_CCX            AS unit_price_ccx,
    ccx.UOMtoMatchInfor_CCX          AS uom_to_match_infor_ccx,
    ccx.reduced_mfg_num_ccx,
    ccx.reduced_vendor_num_ccx,
    ccx.ContractManufacturer_Infor   AS contract_manufacturer,
    ccx.ManufacturerName_Infor       AS mfg_name_infor,
    cnt.VendorID,
    cnt.Manufacturer,
    cnt.Vendor                       AS vendor_name,
    cnt.ContractDescription,
    hdr.ContractProcessType          AS match_process_type,
    CASE
        WHEN ccx.reduced_mfg_num_ccx = :reduced_mfg_num THEN 'REDUCED_MFG'
        WHEN ccx.reduced_vendor_num_ccx = :reduced_vendor_num THEN 'REDUCED_VPN'
        ELSE 'CROSS_MATCH'
    END AS match_type
FROM [Preprocessor].[CCXSyncedContractLine] ccx
JOIN [Preprocessor].[CCXSyncedContractLineCnt] cnt
    ON ccx.OrganizationEID = cnt.OrganizationEID
   AND ccx.ContractID      = cnt.ContractID
   AND ccx.ERPVendorID     = cnt.ERPVendorID
LEFT JOIN [Preprocessor].[CCXInforSyncedContractHeader] hdr
    ON hdr.Organization  = ccx.Organization
   AND hdr.ContractID    = ccx.ContractID
   AND hdr.ERPVendorID   = ccx.ERPVendorID
WHERE (
        ccx.reduced_mfg_num_ccx = :reduced_mfg_num
     OR ccx.reduced_vendor_num_ccx = :reduced_vendor_num
  )
  AND (
      :org_eid = '105188574'
      OR ccx.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: ccx_match_distributor_mfg_set
-- Set-based DISTRIBUTOR match on reduced mfg numbers.
SELECT
    ccx.CCX_pkid,
    ccx.OrganizationEID,
    ccx.Organization,
    ccx.ContractID,
    ccx.ERPVendorID,
    ccx.ManufacturerNumber_CCX       AS mfg_catalog_num_ccx,
    ccx.VendorItem_CCX               AS vendor_catalog_num_ccx,
    ccx.ItemDescription_CCX          AS description_ccx,
    ccx.UOM_CCX                      AS uom_ccx,
    ccx.QOE_CCX                      AS qoe_ccx,
    ccx.ContractPrice_CCX            AS unit_price_ccx,
    ccx.UOMtoMatchInfor_CCX          AS uom_to_match_infor_ccx,
    ccx.reduced_mfg_num_ccx,
    ccx.reduced_vendor_num_ccx,
    ccx.ContractManufacturer_Infor   AS contract_manufacturer,
    ccx.ManufacturerName_Infor       AS mfg_name_infor,
    cnt.VendorID,
    cnt.Manufacturer,
    cnt.Vendor                       AS vendor_name,
    cnt.ContractDescription,
    hdr.ContractProcessType          AS match_process_type
FROM [Preprocessor].[CCXSyncedContractLine] ccx
JOIN [Preprocessor].[CCXSyncedContractLineCnt] cnt
    ON ccx.OrganizationEID = cnt.OrganizationEID
   AND ccx.ContractID      = cnt.ContractID
   AND ccx.ERPVendorID     = cnt.ERPVendorID
LEFT JOIN [Preprocessor].[CCXInforSyncedContractHeader] hdr
    ON hdr.Organization  = ccx.Organization
   AND hdr.ContractID    = ccx.ContractID
   AND hdr.ERPVendorID   = ccx.ERPVendorID
WHERE ccx.reduced_mfg_num_ccx IN :reduced_mfg_nums
  AND (
      :org_eid = '105188574'
      OR ccx.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: ccx_match_distributor_vendor_set
-- Set-based DISTRIBUTOR match on reduced vendor numbers.
SELECT
    ccx.CCX_pkid,
    ccx.OrganizationEID,
    ccx.Organization,
    ccx.ContractID,
    ccx.ERPVendorID,
    ccx.ManufacturerNumber_CCX       AS mfg_catalog_num_ccx,
    ccx.VendorItem_CCX               AS vendor_catalog_num_ccx,
    ccx.ItemDescription_CCX          AS description_ccx,
    ccx.UOM_CCX                      AS uom_ccx,
    ccx.QOE_CCX                      AS qoe_ccx,
    ccx.ContractPrice_CCX            AS unit_price_ccx,
    ccx.UOMtoMatchInfor_CCX          AS uom_to_match_infor_ccx,
    ccx.reduced_mfg_num_ccx,
    ccx.reduced_vendor_num_ccx,
    ccx.ContractManufacturer_Infor   AS contract_manufacturer,
    ccx.ManufacturerName_Infor       AS mfg_name_infor,
    cnt.VendorID,
    cnt.Manufacturer,
    cnt.Vendor                       AS vendor_name,
    cnt.ContractDescription,
    hdr.ContractProcessType          AS match_process_type
FROM [Preprocessor].[CCXSyncedContractLine] ccx
JOIN [Preprocessor].[CCXSyncedContractLineCnt] cnt
    ON ccx.OrganizationEID = cnt.OrganizationEID
   AND ccx.ContractID      = cnt.ContractID
   AND ccx.ERPVendorID     = cnt.ERPVendorID
LEFT JOIN [Preprocessor].[CCXInforSyncedContractHeader] hdr
    ON hdr.Organization  = ccx.Organization
   AND hdr.ContractID    = ccx.ContractID
   AND hdr.ERPVendorID   = ccx.ERPVendorID
WHERE ccx.reduced_vendor_num_ccx IN :reduced_vendor_nums
  AND (
      :org_eid = '105188574'
      OR ccx.OrganizationEID IN (:org_eid, '105188574')
  );

-- name: ccx_contract_summary
-- Summary of matched CCX contracts with line counts.
-- Used for the contract-level review grouping.
SELECT
    cnt.ContractID,
    cnt.OrganizationEID,
    cnt.ERPVendorID,
    cnt.VendorID,
    cnt.Manufacturer,
    cnt.Vendor,
    cnt.LineCnt_Infor,
    cnt.ContractDescription,
    cnt.ContractManufacturer_Infor
FROM [Preprocessor].[CCXSyncedContractLineCnt] cnt
WHERE cnt.ContractID = :contract_id
  AND cnt.OrganizationEID = :org_eid
  AND cnt.ERPVendorID = :erp_vendor_id;
