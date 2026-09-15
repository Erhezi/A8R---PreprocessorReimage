-- sp_MakeCCXSyncedContractLineCnt
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Cx3, Dx1
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_MakeCCXSyncedContractLineCnt] as

truncate table PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLineCnt];

with a as(
select OrganizationEID, Organization, ContractID, 
ContractManufacturer_Infor, Manufacturer,
ERPVendorID, LEFT(ERPVendorID, 7) AS VendorID, Vendor,
count(1) as LineCnt_CCX
from PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLine] [L]
group by OrganizationEID, Organization, ContractID, 
ContractManufacturer_Infor, Manufacturer, 
ERPVendorID, LEFT(ERPVendorID, 7), Vendor
),
line_cnt as(
select a.*, h.ContractDescription
from a
left join (select distinct Organization, ContractID, ContractDescription, Vendor from ghx.[CCXSyncContract]) [h]
on a.ContractID = h.ContractID
and a.Organization = h.Organization
and a.Vendor = h.Vendor
)

insert into PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLineCnt]
select * from line_cnt;
