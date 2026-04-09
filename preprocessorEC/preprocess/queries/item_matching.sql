-- name: match_infor_contract_lines
-- Match against Infor contract lines by catalog number
SELECT
    cl.contract_number,
    cl.line_number,
    cl.item_number AS infor_item_number,
    cl.mfg_catalog_num,
    cl.description,
    cl.uom,
    cl.unit_price,
    cl.buy_uom,
    cl.buy_uom_multiplier
FROM [DM_MONTYNT\dli2].InforContractLines cl
WHERE cl.reduced_mfg_num = :reduced_mfg_num
  AND cl.contract_number = :contract_number;

-- name: match_infor_item_master
-- Match against Infor item master by catalog number
SELECT
    im.item_number AS infor_item_number,
    im.description,
    im.mfg_catalog_num,
    im.uom,
    im.status AS im_status
FROM [DM_MONTYNT\dli2].InforItemMaster im
WHERE im.reduced_mfg_num = :reduced_mfg_num;
