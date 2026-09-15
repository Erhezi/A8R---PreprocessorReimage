-- sp_MakeInforActiveCLRefCCXSyncedCL
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Cx11
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_MakeInforActiveCLRefCCXSyncedCL] as
truncate table PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL];
-- step 1, insert type A (direct left join)
insert into PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL]
select *
from(
select 
OrganizationEID, Organization,
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
row_number() over (partition by Infor_pkid ORDER BY (select null)) as matched_ccx_line_seq,
count(1) over (partition by Infor_pkid ORDER BY (select null)) as total_matched_ccx_line,
CCXCurrentSyncFlag,
reduced_mfg_num_infor,
reduced_vendor_num_infor,
JoinSyncType,
CCX_pkid,
ManufacturerNumber_CCX,
VendorItem_CCX,
UOM_CCX,
UOMtoMatchInfor_CCX,
QOE_CCX,
ContractPrice_CCX,
ItemDescription_Infor,
ItemDescription_CCX
from PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL]
where CCX_pkid is not null -- JoinSyncTypeA
)[a];

print 'Type A inserted to PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL].';

-- step 2, insert Type B (attemp to join by vendor + vendor item + QOE previously not joinable stuff)
with a as(
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
CCXCurrentSyncFlag,
reduced_mfg_num_infor,
reduced_vendor_num_infor,
JoinSyncType,
ItemDescription_Infor
from PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL]
where CCX_pkid is null
and CCXCurrentSyncFlag = 'On' -- JoinSyncTypeB
),
b as (
select 
a.OrganizationEID, 
a.Organization,
a.ContractID,
a.ContractName_Infor,
a.ContractManufacturer_Infor,
a.ERPVendorID_Infor,
a.VendorID_Infor,
a.VendorItem_Infor,
a.ContractLineManufacturer_Infor,
a.ManufacturerNumber_Infor,
a.UOM_Infor, 
a.QOE_Infor,
a.ContractPrice_Infor,
a.EffectiveDate_Infor,
a.ExpirationDate_Infor,
a.ContractStartDate_Infor,
a.ContractEndDate_Infor,
a.ItemType,
a.ItemNumber,
a.Item,
a.[Contract],
a.[ContractLine],
a.Infor_pkid,
row_number() over (partition by a.Infor_pkid ORDER BY (select null)) as matched_ccx_line_seq,
count(1) over (partition by a.Infor_pkid ORDER BY (select null)) as total_matched_ccx_line, 
a.CCXCurrentSyncFlag,
a.reduced_mfg_num_infor,
a.reduced_vendor_num_infor,
case when ccxl.CCX_pkid is not null then 'B - Joined' else 'B - No CCX Match' end as JoinSyncType,
ccxl.CCX_pkid,
ccxl.ManufacturerNumber_CCX,
ccxl.VendorItem_CCX,
ccxl.UOM_CCX,
UOMtoMatchInfor_CCX,
ccxl.QOE_CCX,
ccxl.ContractPrice_CCX,
a.ItemDescription_Infor,
ccxl.ItemDescription_CCX
from a
left join PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLine] [ccxl]
on a.OrganizationEID = ccxl.OrganizationEID
and a.ContractID = ccxl.ContractID
and a.ERPVendorID_Infor = ccxl.ERPVendorID
and a.VendorItem_Infor = ccxl.VendorItem_CCX
and a.QOE_Infor = ccxl.QOE_CCX
)

insert into PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL]
select * from b;

print 'Type B inserted to PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL].';

-- step 3, insert Type C -- none joinable
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
row_number() over (partition by Infor_pkid ORDER BY (select null)) as matched_ccx_line_seq,
count(1) over (partition by Infor_pkid ORDER BY (select null)) as total_matched_ccx_line, 
CCXCurrentSyncFlag,
reduced_mfg_num_infor,
reduced_vendor_num_infor,
JoinSyncType,
CCX_pkid,
ManufacturerNumber_CCX,
VendorItem_CCX,
UOM_CCX,
UOMtoMatchInfor_CCX,
QOE_CCX,
ContractPrice_CCX,
ItemDescription_Infor,
ItemDescription_CCX
from PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL] [cl]
where CCX_pkid is null
and CCXCurrentSyncFlag = 'Off'
)

insert into PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL]
select * from off_ccx;

print 'Type C inserted to PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL].';
