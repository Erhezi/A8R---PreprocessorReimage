-- sp_MakeInforActiveContractLineCnt
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Ax2, Cx2
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE Preprocessor.sp_MakeInforActiveContractLineCnt as

truncate table PLMPreprocessorShared.Preprocessor.[InforActiveContractLineCnt];

with a as(
select [Contract.MMAHSOrganizationEID], 
WorkingContractID as ContractID,
ContractName,
PurchaseFromLocation,
Vendor,
VendorName,
[Contract.Manufacturer],
count(1) as LineCnt_Infor
from PLMPreprocessorShared.infor.[CONTRACTLINE]
group by [Contract.MMAHSOrganizationEID],
WorkingContractID,
ContractName,
Vendor,
PurchaseFromLocation,
VendorName,
[Contract.Manufacturer]),
line_cnt as (
select a.[Contract.MMAHSOrganizationEID] as OrganizationEID,
org.Organization,
a.ContractID,
[Contract.Manufacturer] as ContractManufacturer_Infor,
mf.ManufacturerName as ManufacturerName_Infor,
case when PurchaseFromLocation = '' then Vendor else concat(Vendor,'-',PurchaseFromLocation) end as ERPVendorID_Infor,
Vendor as VendorID_Infor,
VendorName as VendorName_Infor,
LineCnt_Infor,
ContractName as ContractDescription_Infor
from a left join Preprocessor.OrganizationEIDandName [org]
on a.[Contract.MMAHSOrganizationEID] = org.OrganizationEID
left join PLMPreprocessorShared.infor.[MDM_MANUFACTURER_NAME] [mf]
on mf.Manufacturer = a.[Contract.Manufacturer]
)

insert INTO PLMPreprocessorShared.Preprocessor.[InforActiveContractLineCnt]
select * from line_cnt;
