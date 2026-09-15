-- sp_RefreshCCXInforSyncedContractHeader
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Ax3, Bx1, Dx1
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_RefreshCCXInforSyncedContractHeader]
AS
BEGIN
    SET NOCOUNT ON;

    TRUNCATE TABLE [Preprocessor].[CCXInforSyncedContractHeader];

    WITH h AS (
        SELECT 
            CCX.*,
            COALESCE(co.OrganizationEID, '000000000') AS InforCompanyEID,
            ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS RN
        FROM (
            SELECT 
                Organization,
                Manufacturer,
                Vendor,
                ContractID,
                ERPVendorID,
                ContractSourceType,
                COUNT(DISTINCT ContractRefID) AS DC_contractRefID,
                [report stamp]
            FROM ghx.[CCXSyncContract]
            WHERE Sync = 1
            GROUP BY 
                Organization,
                ContractSourceType,
                Manufacturer,
                Vendor,
                ERPVendorID,
                ContractID,
                [report stamp]
        ) AS CCX
        LEFT JOIN
            [Preprocessor].[OrganizationEIDandName]
        AS co
            ON CCX.Organization = co.Organization
    ),
    cl AS (
        SELECT 
            ORGANIZATION_NAME,
            CONTRACT_NUMBER,
            MANUFACTURER_EID,
            LAST_UPDATE,
            MIN(CONTRACT_TIER_START_DATE) AS CONTRACT_START_DATE,
            MAX(CONTRACT_TIER_END_DATE) AS CONTRACT_END_DATE,
            COUNT(DISTINCT TIER_LEVEL) AS DC_TierLevel
        FROM (
            SELECT DISTINCT 
                organization_name,
                contract_number,
                tier_level,
                CONTRACT_TIER_START_DATE,
                CONTRACT_TIER_END_DATE,
                MANUFACTURER_EID,
                LAST_UPDATE
            FROM Contracts.dbo.[ZZZ_STAGING_CCX_CONTRACTS_DETAILS_GHX_PROVIDED_DAILY]
        ) AS cd
        GROUP BY 
            ORGANIZATION_NAME,
            CONTRACT_NUMBER,
            MANUFACTURER_EID,
            LAST_UPDATE
    ),
    max_contractline_stamp AS (
        SELECT MAX([update stamp]) AS LastUpdateAs
        FROM PLMPreprocessorShared.infor.[CONTRACTLINE]
    ),
    infor AS (
        SELECT 
            [Contract.MMAHSOrganizationEID],
            CCXOrganization,
            WorkingContractID,
            Vendor,
            ERPVendorID,
            i.[Contract.Manufacturer],
            ManufacturerName,
            ManufacturerEID,
            mcs.LastUpdateAs,
            [Contract],
            MIN([Contract.EffectiveDate]) AS ContractStartDate,
            MAX([Contract.ExpirationDate]) AS ContractEndDate
        FROM (
            SELECT DISTINCT 
                [Contract.MMAHSOrganizationEID],
                COALESCE(co.Organization, 'Unknown Organization Account (ERROR)') AS CCXOrganization,
                [Contract],
                WorkingContractID,
                Vendor,
                CASE 
                    WHEN PurchaseFromLocation <> '' THEN CONCAT(Vendor, '-', PurchaseFromLocation)
                    ELSE Vendor
                END AS ERPVendorID,
                [Contract.Manufacturer],
                ManufacturerName,
                ManufacturerEID,
                [Contract.EffectiveDate],
                [Contract.ExpirationDate]
            FROM PLMPreprocessorShared.infor.[CONTRACTLINE] AS icl
            LEFT JOIN
               [Preprocessor].[OrganizationEIDandName]
            AS co
                ON icl.[Contract.MMAHSOrganizationEID] = co.OrganizationEID
            LEFT JOIN PLMPreprocessorShared.infor.[MDM_MANUFACTURER_NAME] AS m
                ON icl.[Contract.Manufacturer] = m.Manufacturer
            WHERE [Contract.ContractStatus] = 'Active'
              AND [Contract.OnHold] = 'No'
              AND ContractLineState = 'Active'
              AND ActiveLine = 'Yes'
              AND OnHold = 'No'
        ) AS i
        CROSS JOIN max_contractline_stamp AS mcs
        GROUP BY 
            [Contract.MMAHSOrganizationEID],
            CCXOrganization,
            WorkingContractID,
            Vendor,
            ERPVendorID,
            i.[Contract.Manufacturer],
            ManufacturerName,
            ManufacturerEID,
            [Contract],
            mcs.LastUpdateAs
    )

    INSERT INTO [Preprocessor].[CCXInforSyncedContractHeader]
    SELECT *
    FROM (
        SELECT 
            h.RN,
            COUNT(1) OVER (PARTITION BY h.RN ORDER BY (SELECT NULL)) AS RN_check,
            h.Organization,
            h.InforCompanyEID AS OrganizationEID,
            h.Manufacturer,
            h.Vendor,
            CASE 
                WHEN h.Manufacturer <> h.Vendor
                  OR (
                      h.Vendor IN (SELECT VendorName FROM [Preprocessor].[CCXDistributor])
                      AND h.ContractSourceType LIKE 'Local%'
                  )
                THEN 'Distributor'
                ELSE 'Manufacturer'
            END AS ContractProcessType,
            h.ContractID,
            h.ERPVendorID,
            h.ContractSourceType,
            h.DC_contractRefID,
            h.InforCompanyEID,
            h.[report stamp] AS rs_CCXH,
            cl.MANUFACTURER_EID AS ManufacturerEID,
            convert(Date, cl.CONTRACT_START_DATE) AS ContractStartDate,
            convert(Date, cl.CONTRACT_END_DATE) AS ContractEndDate,
            cl.DC_TierLevel,
            cl.LAST_UPDATE AS rs_CCXL,
            infor.[Contract.MMAHSOrganizationEID] AS OrganizationEID_Infor,
            infor.WorkingContractID AS ContractID_Infor,
            infor.ERPVendorID AS ERPVendorID_Infor,
            infor.[Contract.Manufacturer] AS ContractManufacturer_Infor,
            infor.ManufacturerName AS ManufacturerName_Infor,
            infor.ManufacturerEID AS ManufacturerEID_Infor,
            infor.ContractStartDate AS ContractStartDate_Infor,
            infor.ContractEndDate AS ContractEndDate_Infor,
            infor.[Contract] AS Contract_Infor,
            infor.LastUpdateAs AS rs_Infor
        FROM h
        LEFT JOIN cl
            ON h.ContractID = cl.CONTRACT_NUMBER
           AND h.Organization = cl.ORGANIZATION_NAME
        LEFT JOIN infor
            ON h.InforCompanyEID = infor.[Contract.MMAHSOrganizationEID]
           AND h.ContractID = infor.WorkingContractID
           AND h.ERPVendorID = infor.ERPVendorID
    ) AS x;
END;
