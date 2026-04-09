-- name: check_ccx_infor_sync
-- Compare CCX items to Infor contract lines for sync status
SELECT
    ci.mfg_catalog_num,
    ci.vendor_id,
    ci.contract_number,
    ci.uom AS ccx_uom,
    cl.uom AS infor_uom,
    CASE
        WHEN cl.line_number IS NOT NULL THEN 'SYNCED'
        ELSE 'UNSYNCED'
    END AS sync_status
FROM [DM_MONTYNT\dli2].CCXContractItems ci
LEFT JOIN [DM_MONTYNT\dli2].InforContractLines cl
    ON ci.contract_number = cl.contract_number
    AND ci.reduced_mfg_num = cl.reduced_mfg_num
WHERE ci.vendor_id = :vendor_id
  AND ci.contract_number = :contract_number;
