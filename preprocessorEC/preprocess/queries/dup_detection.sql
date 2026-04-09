-- name: dup_detection_manufacturer
-- SKU matching for MANUFACTURER contracts: reduced mfg # → reduced mfg # on all CCX items
SELECT
    ci.contract_number,
    ci.mfg_catalog_num,
    ci.reduced_mfg_num,
    ci.description,
    ci.uom,
    ci.unit_price,
    ci.vendor_id,
    ci.status AS ccx_status
FROM [DM_MONTYNT\dli2].CCXContractItems ci
WHERE ci.reduced_mfg_num = :reduced_mfg_num
  AND ci.status = 'ACTIVE';

-- name: dup_detection_distributor_premier
-- SKU matching for DISTRIBUTOR PREMIER: union of reduced mfg # and reduced vendor # → all CCX
SELECT
    ci.contract_number,
    ci.mfg_catalog_num,
    ci.vendor_catalog_num,
    ci.reduced_mfg_num,
    ci.description,
    ci.uom,
    ci.unit_price,
    ci.vendor_id
FROM [DM_MONTYNT\dli2].CCXContractItems ci
WHERE (ci.reduced_mfg_num = :reduced_mfg_num OR ci.reduced_vendor_num = :reduced_vendor_num)
  AND ci.status = 'ACTIVE';

-- name: dup_detection_distributor_local
-- SKU matching for DISTRIBUTOR LOCAL: mfg # + vendor # cross-match
SELECT
    ci.contract_number,
    ci.mfg_catalog_num,
    ci.vendor_catalog_num,
    ci.reduced_mfg_num,
    ci.description,
    ci.uom,
    ci.unit_price,
    ci.vendor_id
FROM [DM_MONTYNT\dli2].CCXContractItems ci
WHERE (ci.reduced_mfg_num = :reduced_mfg_num OR ci.reduced_mfg_num = :reduced_vendor_num)
  AND ci.status = 'ACTIVE';
