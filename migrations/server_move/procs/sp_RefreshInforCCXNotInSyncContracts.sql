-- sp_RefreshInforCCXNotInSyncContracts
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Cx3, Dx3
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_RefreshInforCCXNotInSyncContracts] as
truncate table PLMPreprocessorShared.Preprocessor.[InforCCXNotInSyncContracts];
with off_ccx as(
select OrganizationEID, Organization,
ContractID,
ContractName_Infor,
ContractManufacturer_Infor,
ERPVendorID_Infor,
VendorID_Infor,
VendorItem_Infor,
ContractLineManufacturer_Infor,
ManufacturerNumber_Infor,
UOM_Infor, 
QOE_Infor,
ContractPrice_Infor,
EffectiveDate_Infor,
ExpirationDate_Infor,
ContractStartDate_Infor,
ContractEndDate_Infor,
ItemType,
ItemNumber,
Item,
[Contract],
[ContractLine],
Infor_pkid,
CCXCurrentSyncFlag
from PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL]
where CCX_pkid is null
and CCXCurrentSyncFlag = 'Off'
),
h_diff as(
select distinct off_ccx.OrganizationEID, off_ccx.organization, off_ccx.ContractID, off_ccx.ERPVendorID_Infor,
ccxh.Sync, ccxhv.ERPVendorID,
case when ccxh.Sync = 0 then 'CCX marked as NOT to sync to this Infor organization account' else null end as SyncIssue
from off_ccx
left join (select sum(Sync) as Sync, Organization, ContractID 
           from ghx.[CCXSyncContract]
		   group by Organization, ContractID) [ccxh]
on off_ccx.Organization = ccxh.Organization
and off_ccx.ContractID = ccxh.ContractID
left join (select distinct Organization, ContractID, ERPVendorID 
           from ghx.[CCXSyncContract] 
		   where Sync = 1) [ccxhv]
on off_ccx.Organization = ccxhv.Organization
and off_ccx.ContractID = ccxhv.ContractID
)

insert into PLMPreprocessorShared.Preprocessor.[InforCCXNotInSyncContracts]
select *
from (
select h_diff.OrganizationEID,
h_diff.Organization,
h_diff.ContractID,
h_diff.ERPVendorID_Infor,
h_diff.ERPVendorID,
case when h_diff.SyncIssue is null and IsSync = 0 then 'CCX marked as NOT to sync to any Infor organization account'
     when h_diff.SyncIssue is null and IsSync > 0 and h_diff.ERPVendorID is null then 'Synced under an organization account that is different from current Infor organization'
	 when h_diff.SyncIssue is null and IsSync > 0 and h_diff.ERPVendorID is not null then 'Synced under an vendor account that is different from current Infor vendor'
     when h_diff.SyncIssue is null and IsSync is null then 'Contract ONLY exist on Infor but does NOT exist on CCX'
	 else h_diff.SyncIssue end SyncIssue,
	 coalesce(ccxh.IsSync, -1) as IsSync_Contract,
	 coalesce(Sync, -1) as IsSync_OrgContract
from h_diff
left join (select sum(Sync) as IsSync, ContractID from ghx.[CCXSyncContract] group by ContractID) [ccxh]
on h_diff.ContractID = ccxh.ContractID )[x]
