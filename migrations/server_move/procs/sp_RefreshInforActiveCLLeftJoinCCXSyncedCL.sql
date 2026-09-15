-- sp_RefreshInforActiveCLLeftJoinCCXSyncedCL
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Ax1, Cx3
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_RefreshInforActiveCLLeftJoinCCXSyncedCL] as

truncate table PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL];
with base as(
select [Contract.MMAHSOrganizationEID] as OrganizationEID,
org.Organization,
WorkingContractID as ContractID,
ContractName as ContractName_Infor,
inforl.[Contract.Manufacturer] as ContractManufacturer_Infor,
iif(inforl.PurchaseFromLocation <> '', concat(inforl.Vendor, '-', inforl.PurchaseFromLocation), inforl.Vendor) as ERPVendorID_Infor,
inforl.Vendor as VendorID_Infor, 
inforl.VendorItem as VendorItem_Infor,
inforl.Manufacturer as ContractLineManufacturer_Infor,
inforl.ManufacturerNumber as ManufacturerNumber_Infor,
inforl.UOM as UOM_Infor,
convert(int, inforl.DerivedUOMConversion) as QOE_Infor,
convert(decimal(18,4), inforl.BaseCost) as ContractPrice_Infor,
EffectiveDate as EffectiveDate_Infor,
ExpirationDate as ExpirationDate_Infor,
[Contract.EffectiveDate] as ContractStartDate_Infor,
[Contract.ExpirationDate] as ContractEndDate_Infor,
ItemType,
ItemNumber,
iif(ItemType = 'Itemmast', ItemNumber, '') as Item,
[Contract],
ContractLine,
concat([Contract], '-', ContractLine) as Infor_pkid,
coalesce(h.CCXCurrentSyncFlag, 'Off') as CCXCurrentSyncFlag,
ccxl.CCX_pkid,
ccxl.ManufacturerNumber_CCX,
ccxl.VendorItem_CCX,
ccxl.UOM_CCX,
ccxl.UOMtoMatchInfor_CCX,
ccxl.QOE_CCX,
ccxl.ContractPrice_CCX,
ccxl.Manufacturer,
ccxl.Vendor,
null as reduced_mfg_num_infor,
null as reduced_vendor_num_infor,
null as JoinSyncType,
ItemDescription as ItemDescription_Infor,
ItemDescription_CCX
from PLMPreprocessorShared.infor.[CONTRACTLINE] [inforl]
left join PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLine] [ccxl]
on inforl.[Contract.MMAHSOrganizationEID] = ccxl.OrganizationEID
and inforl.WorkingContractID = ccxl.ContractID
and inforl.Vendor = left(ccxl.ERPVendorID, 7)
and inforl.ManufacturerNumber = ccxl.ManufacturerNumber_CCX
and inforl.UOM = ccxl.[UOMtoMatchInfor_CCX]
left join Preprocessor.OrganizationEIDandName [org]
on inforl.[Contract.MMAHSOrganizationEID] = org.OrganizationEID
left join (
Select OrganizationEID, ContractID, ERPVendorID, 'On' as CCXCurrentSyncFlag 
from Preprocessor.CCXInforSyncedContractHeader) [h]
on inforl.[Contract.MMAHSOrganizationEID] = h.OrganizationEID
and inforl.WorkingContractID = h.ContractID
and inforl.Vendor = left(h.ERPVendorID, 7)
)

insert into PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL]
select * from base
