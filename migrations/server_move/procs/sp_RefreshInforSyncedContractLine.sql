-- sp_RefreshInforSyncedContractLine
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Ax2
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_RefreshInforSyncedContractLine] as
truncate table Preprocessor.InforSyncedContractLine;
with base as(
select RN, Organization, OrganizationEID,
ContractID, sh.Manufacturer, sh.Vendor, sh.ERPVendorID,
ContractStartDate, ContractEndDate,
ContractStartDate_Infor, ContractEndDate_Infor,
Contract_Infor,
concat([Contract],'-',[ContractLine]) as Infor_pkid,
ManufacturerNumber as ManufacturerNumber_Infor,
VendorItem as VendorItem_Infor,
UOM as UOM_Infor,
convert(int, DerivedUOMConversion) as QOE_Infor,
convert(decimal(18,4), BaseCost) as ContractPrice_Infor,
EffectiveDate as EffectiveDate_Infor,
ExpirationDate as ExpirationDate_Infor,
ItemDescription as ItemDescription_Infor,
ItemType,
ItemNumber as ItemNumber,
iif(ItemType = 'Itemmast', ItemNumber, '') as Item,
ContractLine as ContractLine_Infor,
ContractManufacturer_Infor,
ManufacturerName_Infor,
infor.Manufacturer as ContractLineManufacturer_Infor,
Coalesce(m.ManufacturerName, 'UNKNOWN CODE') as ContractLineManufacturerName_Infor,
infor.Vendor as VendorID_Infor,
infor.PurchaseFromLocation as PurchaseFromLocation_Infor,
infor.VendorName as VendorName_Infor,
coalesce(pfl.PurchaseFromName, infor.VendorName) as PurchaseFromName_Infor
from Preprocessor.CCXInforSyncedContractHeader [sh]
INNER JOIN PLMPreprocessorShared.infor.[CONTRACTLINE] [infor]
on infor.[Contract.MMAHSOrganizationEID] = sh.OrganizationEID
and infor.[Contract] = sh.Contract_Infor
and infor.Vendor = left(sh.ERPVendorID, 7)
LEFT JOIN PLMPreprocessorShared.infor.[MDM_MANUFACTURER_NAME] [m]
on infor.Manufacturer = m.Manufacturer
LEFT JOIN Preprocessor.PurchaseVendorLocation [pfl]
on sh.ERPVendorID = pfl.ERPVendorID
)

insert into Preprocessor.InforSyncedContractLine
select * from base
