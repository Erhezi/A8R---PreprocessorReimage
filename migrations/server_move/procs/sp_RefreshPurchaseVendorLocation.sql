-- sp_RefreshPurchaseVendorLocation
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Ax1, Ex1
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_RefreshPurchaseVendorLocation] as
truncate table Preprocessor.PurchaseVendorLocation;

with base as (
SELECT a.Vendor, a.VendorName, a.Active, b.ERPVendorID,
b.VendorLocation, b.VendorLocationText, b.LocationType,
count(1) over (partition by a.Vendor Order by a.Vendor) as c
FROM PLMPreprocessorShared.infor.[MDM_SUPPLIER_NAME] [a]
left join 
(select 
Concat(Vendor, '-', VendorLocation) as ERPVendorID, Vendor, VendorLocation, VendorLocationText, LocationType
from infor.[VendorLocation]
where status = 'Active' and LocationType <> 'Remit To' and VendorLocation like 'B0%') [b]
on a.Vendor = b.Vendor
WHERE a.vendor <> ''
),
res as (
select
case when c = 1 then Vendor
     ELSE ERPVendorID END ERPVendorID,
VendorName, VendorLocationText as PurchaseFromName,
Active
FROM base
WHERE C > 1

UNION ALL

SELECT distinct Vendor as ERPVendorID, VendorName, NULL as PurchaseFromName, Active
from base
)

insert into Preprocessor.PurchaseVendorLocation
select * from res
