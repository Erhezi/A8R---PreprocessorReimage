-- sp_RefreshCCXContractLineDeduped
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Ax1, Bx1, Cx2
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE Preprocessor.sp_RefreshCCXContractLineDeduped as

truncate table PLMPreprocessorShared.Preprocessor.[CCXContractLineDeduped];

with base as(
select * from(
select 
PK_ID AS CCX_pkid,
ORGANIZATION_NAME,
ORGANIZATION_EID,
CONTRACT_NUMBER,
VENDOR_NAME,
MANUFACTURER_NAME,
TIER_LEVEL as TierLevel,
TIER_DESCRIPTION AS TierDescription,
MANUFACTURER_PART_NUMBER as ManufacturerNumber_CCX,
VENDOR_PART_NUMBER AS VendorItem_CCX,
UOM AS UOM_CCX,
convert(int, QOE) AS QOE_CCX,
convert(decimal(18, 4), PRICE) AS ContractPrice_CCX,
convert(date, ITEM_PRICE_START_DATE) AS EffectiveDate_CCX,
convert(date, ITEM_PRICE_END_DATE) AS ExpirationDate_CCX,
PART_DESCRIPTION AS ItemDescription_CCX,
LAST_UPDATE,
COUNT(1) OVER (PARTITION BY Organization_EID, CONTRACT_NUMBER, VENDOR_NAME, MANUFACTURER_PART_NUMBER, UOM ORDER BY CONTRACT_NUMBER) AS CK,
ROW_NUMBER() OVER (PARTITION BY Organization_EID, CONTRACT_NUMBER, VENDOR_NAME, MANUFACTURER_PART_NUMBER, UOM 
ORDER BY ITEM_PRICE_END_DATE DESC, ITEM_PRICE_START_DATE DESC, PK_ID DESC) AS RK
from Contracts.dbo.[ZZZ_STAGING_CCX_CONTRACTS_DETAILS_GHX_PROVIDED_DAILY]
where IS_UOM = 'f'
and ITEM_PRICE_START_DATE < LAST_UPDATE and ITEM_PRICE_END_DATE >= LAST_UPDATE
) [x]
where RK = 1
)

insert into PLMPreprocessorShared.Preprocessor.[CCXContractLineDeduped]
select *
from(
select base.*, coalesce(ediuom.LawsonValue, base.UOM_CCX) as UOMtoMatchInfor_CCX
from base left join PLMPreprocessorShared.infor.[MDM_EDI_SUB_UOM] [ediuom]
on base.UOM_CCX = EDIUOM.ExternalValue
)[c]
