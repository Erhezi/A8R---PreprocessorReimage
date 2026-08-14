-- CCX duplicate detection.
--
-- Both blocks share one projection and differ only in which reduced part-number
-- column they match on. Callers pass an expanding bind list, chunked to
-- SQLSERVER_IN_CHUNK because SQL Server caps a statement at 2100 parameters.
--
-- Org-awareness: MHS (105188574) sees every organization; a member entity sees
-- its own org plus MHS.
--
-- Consumers: preprocess_service._load_ccx_candidate_rows (MANUFACTURER contracts
-- use the mfg block only; DISTRIBUTOR uses both) and discovery_service, whose
-- match modes map MFG -> mfg block, VENDOR -> vendor block, EITHER -> both.

-- name: ccx_match_mfg_set
-- Set-based CCX match on reduced MANUFACTURER part numbers.
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

-- name: ccx_match_vendor_set
-- Set-based CCX match on reduced VENDOR part numbers.
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
