-- name: get_nuvia_descriptions
-- Placeholder for Nuvia lookup
SELECT item_id, standardized_description
FROM [DM_MONTYNT\dli2].PreprocessorTaskItem
WHERE task_id = :task_id AND standardized_description IS NOT NULL;

-- name: get_contract_header_manufacturer
-- Fetch manufacturer info from CCXInforSyncedContractHeader for UPDATE contracts
SELECT ContractManufacturer_Infor, ManufacturerName_Infor
FROM [Preprocessor].CCXInforSyncedContractHeader
WHERE Organization = :organization AND ContractID = :contract_id;

-- name: search_manufacturers
-- Search available manufacturers from MDM_MANUFACTURER_NAME_INFOR
SELECT Manufacturer, ManufacturerName, Active
FROM [DM_MONTYNT\dli2].MDM_MANUFACTURER_NAME_INFOR
WHERE (Manufacturer LIKE :search_term OR ManufacturerName LIKE :search_term)
ORDER BY ManufacturerName;
