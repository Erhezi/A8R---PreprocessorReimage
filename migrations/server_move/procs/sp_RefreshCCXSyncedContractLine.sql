-- sp_RefreshCCXSyncedContractLine
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Cx3
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_RefreshCCXSyncedContractLine] as
TRUNCATE TABLE PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLine];
with base as(
select *
from Preprocessor.CCXInforSyncedContractHeader [sh]
INNER JOIN PLMPreprocessorShared.Preprocessor.[CCXContractLineDeduped] [ccx]
on ccx.ORGANIZATION_NAME = sh.Organization
and ccx.CONTRACT_NUMBER = sh.ContractID
and ccx.VENDOR_NAME = sh.Vendor
--where IS_UOM = 'f'
--and ITEM_PRICE_START_DATE < LAST_UPDATE and ITEM_PRICE_END_DATE >= LAST_UPDATE --because if last update is 4/8, data actually is 4/7 EOD
),
fb as(
select RN,
Organization,
OrganizationEID,
ContractID,
Manufacturer,
Vendor,
ERPVendorID,
ContractStartDate,
ContractEndDate,
ContractManufacturer_Infor,
ManufacturerName_Infor,
ContractStartDate_Infor,
ContractEndDate_Infor,
Contract_Infor,
CCX_pkid,
TierLevel,
TierDescription,
ManufacturerNumber_CCX,
VendorItem_CCX,
UOM_CCX,
QOE_CCX,
ContractPrice_CCX,
EffectiveDate_CCX,
ExpirationDate_CCX,
ItemDescription_CCX,
CK,
RK,
UOMtoMatchInfor_CCX,
NULL as reduced_mfg_num_ccx,
NULL AS reduced_vendor_num_ccx
from base
)

INSERT into PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLine]
SELECT * from fb;
