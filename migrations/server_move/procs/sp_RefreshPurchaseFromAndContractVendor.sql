-- sp_RefreshPurchaseFromAndContractVendor
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Ax3, Ex1
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_RefreshPurchaseFromAndContractVendor] as

Truncate Table Preprocessor.PurchaseFromAndContractVendor;

with cl_vendor as(
select distinct [Contract.MMAHSOrganizationEID] as OrganizationEID,
org.Organization,
Vendor, PurchaseFromLocation, 
ItemNumber as Item
from PLMPreprocessorShared.infor.[CONTRACTLINE] [cl]
left join Preprocessor.OrganizationEIDandName [org]
on cl.[Contract.MMAHSOrganizationEID] = org.OrganizationEID
where ItemType = 'itemmast'
),
vloc as (
SELECT *
FROM(
SELECT Item, [Location], Active, Discontinued,
row_number() over (partition by Item, [Location] order by [report stamp] desc) as rk
FROM PLMPreprocessorShared.infor.[ITEM_LOCATION]
WHERE [report stamp] >= GETDATE() - 7)[X]
WHERE RK = 1
),
repl_vendor as(
select distinct a.OrganizationEID, org.Organization,
a.[Location], LocationText, LocationType,
a.Item, i.Active as [Item.Active], vloc.Active, vloc.Discontinued,
Vendor, PurchaseFromLocation, VendorName, PurchaseFromLocationText
from(
select distinct repl.company, COALESCE(InforCompanyEID, '105188574') as OrganizationEID,
[Location], LocationText, LocationType,
Item, vendor, VendorName, PurchaseFromLocation, PurchaseFromLocationText
from infor.[ItemReplenishFrom] [repl]
left join Preprocessor.CompanyOrganization [co]
on repl.Company = co.Company
where UseVendorOrReplenishFrom = 'Vendor')[a]
left join Preprocessor.OrganizationEIDandName [org]
on a.OrganizationEID = org.OrganizationEID
left join (SELECT DISTINCT Item, Active from PLMPreprocessorShared.infor.[MDM_ITEM]) [i]
on a.Item = i.Item
left join vloc
on a.[Location] = vloc.[Location]
and a.Item = vloc.Item
),
final as (
select * 
from(
select repl_vendor.*, 
cl_vendor.PurchaseFromLocation as PurchaseFromLocation_CL,
case when repl_vendor.PurchaseFromLocation = cl_vendor.PurchaseFromLocation then 'PurchaseFrom Matched on ContractLine'
     else 'PurchaseFrom NOT Matched on ContractLine' end as [PurchaseFromMatchFlag],
[clv2].Vendor AS Vendor_CL2, clv2.PurchaseFromLocation AS PurchaseFromLocation_CL2,
case when clv2.Vendor is not null and clv2.Vendor <> repl_vendor.Vendor then 'Different Vendor on ContractLine'
     when clv2.Vendor is not null and clv2.Vendor = repl_vendor.Vendor then 'Same Vendor on ContractLine'
     else 'Replenish vendor does NOT have an active ContractLine' end as [PurchaseVendorMatchFlag],
case when cl_vendor.PurchaseFromLocation is not null and clv2.vendor <> repl_vendor.Vendor then 'Drop - Additional Vendor on ContractLine'
     else 'Keep' end as [ScopeFilter]
from repl_vendor
left join cl_vendor
ON repl_vendor.Item = cl_vendor.Item
and repl_vendor.OrganizationEID = cl_vendor.OrganizationEID
and repl_vendor.Vendor = cl_vendor.Vendor
--and repl_vendor.PurchaseFromLocation = cl_vendor.PurchaseFromLocation
left join cl_vendor [clv2]
ON repl_vendor.Item = [clv2].Item
and repl_vendor.OrganizationEID = [clv2].OrganizationEID
where [Item.Active] = 'Yes' and Active = 'Yes' and Discontinued = 'No'
)[x]
--where ScopeFilter = 'Keep'
)

insert into Preprocessor.PurchaseFromAndContractVendor
select * from final
