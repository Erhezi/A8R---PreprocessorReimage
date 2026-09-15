-- name: get_contract_header_manufacturer
-- Fetch manufacturer info from CCXInforSyncedContractHeader for UPDATE contracts
SELECT ContractManufacturer_Infor, ManufacturerName_Infor
FROM [Preprocessor].CCXInforSyncedContractHeader
WHERE Organization = :organization AND ContractID = :contract_id;

-- name: search_manufacturers
-- Search available manufacturers from MDM_MANUFACTURER_NAME_INFOR
SELECT Manufacturer, ManufacturerName, Active
FROM PLMPreprocessorShared.infor.[MDM_MANUFACTURER_NAME]
WHERE (Manufacturer LIKE :search_term OR ManufacturerName LIKE :search_term)
ORDER BY ManufacturerName;
