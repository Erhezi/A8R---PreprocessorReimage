-- ============================================================
-- Tables (8) -> [Preprocessor] schema
-- Generated from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target database: PLMPreprocessorShared
-- Idempotent: every object is guarded by an existence check.
-- ============================================================


IF OBJECT_ID(N'[Preprocessor].[CCXContractLineDeduped]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[CCXContractLineDeduped] (
    [CCX_pkid] int NOT NULL,
    [ORGANIZATION_NAME] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ORGANIZATION_EID] varchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [CONTRACT_NUMBER] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VENDOR_NAME] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [MANUFACTURER_NAME] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [TierLevel] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [TierDescription] varchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerNumber_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorItem_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOM_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [QOE_CCX] int NULL,
    [ContractPrice_CCX] decimal(18,4) NULL,
    [EffectiveDate_CCX] date NULL,
    [ExpirationDate_CCX] date NULL,
    [ItemDescription_CCX] varchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [LAST_UPDATE] date NULL,
    [CK] int NULL,
    [RK] bigint NULL,
    [UOMtoMatchInfor_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK_CCXCLDeduped] PRIMARY KEY CLUSTERED ([CCX_pkid])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[CCXInforMatchedLink]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[CCXInforMatchedLink] (
    [Infor_pkid] varchar(31) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [matched_ccx_line_seq] varchar(6) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [CCX_pkid] int NOT NULL
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[CCXSyncedContractLine]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[CCXSyncedContractLine] (
    [RN] int NOT NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractID] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Manufacturer] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Vendor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ERPVendorID] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractStartDate] date NULL,
    [ContractEndDate] date NULL,
    [ContractManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerName_Infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractStartDate_Infor] date NULL,
    [ContractEndDate_Infor] date NULL,
    [Contract_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [CCX_pkid] int NOT NULL,
    [TierLevel] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [TierDescription] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerNumber_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [VendorItem_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOM_CCX] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [QOE_CCX] int NULL,
    [ContractPrice_CCX] decimal(18,4) NULL,
    [EffectiveDate_CCX] date NULL,
    [ExpirationDate_CCX] date NULL,
    [ItemDescription_CCX] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [CK] int NULL,
    [RK] int NULL,
    [UOMtoMatchInfor_CCX] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_mfg_num_ccx] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_vendor_num_ccx] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK_CCXSyncedContractLINE] PRIMARY KEY CLUSTERED ([CCX_pkid])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[CCXSyncedContractLineCnt]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[CCXSyncedContractLineCnt] (
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractID] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Manufacturer] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ERPVendorID] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [VendorID] varchar(7) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Vendor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [LineCnt_CCX] int NULL,
    [ContractDescription] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK_CCXSyncedContractLineCnt] PRIMARY KEY CLUSTERED ([OrganizationEID], [ContractID], [ERPVendorID])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[InforActiveCLLeftJoinCCXSyncedCL]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[InforActiveCLLeftJoinCCXSyncedCL] (
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractID] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractName_Infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ERPVendorID_Infor] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorID_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorItem_Infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractLineManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerNumber_Infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOM_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [QOE_Infor] int NULL,
    [ContractPrice_Infor] decimal(18,4) NULL,
    [EffectiveDate_Infor] date NULL,
    [ExpirationDate_Infor] date NULL,
    [ContractStartDate_Infor] date NULL,
    [ContractEndDate_Infor] date NULL,
    [ItemType] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ItemNumber] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Item] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Contract] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractLine] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Infor_pkid] varchar(31) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [CCXCurrentSyncFlag] varchar(3) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [CCX_pkid] int NULL,
    [ManufacturerNumber_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorItem_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOM_CCX] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOMtoMatchInfor_CCX] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [QOE_CCX] int NULL,
    [ContractPrice_CCX] decimal(18,4) NULL,
    [Manufacturer] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Vendor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_mfg_num_infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_vendor_num_infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [JoinSyncType] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ItemDescription_Infor] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ItemDescription_CCX] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[InforActiveCLRefCCXSyncedCL]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[InforActiveCLRefCCXSyncedCL] (
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractID] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractName_Infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ERPVendorID_Infor] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorID_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorItem_Infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractLineManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerNumber_Infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOM_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [QOE_Infor] int NULL,
    [ContractPrice_Infor] decimal(18,4) NULL,
    [EffectiveDate_Infor] date NULL,
    [ExpirationDate_Infor] date NULL,
    [ContractStartDate_Infor] date NULL,
    [ContractEndDate_Infor] date NULL,
    [ItemType] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ItemNumber] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Item] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Contract] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractLine] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Infor_pkid] varchar(31) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [matched_ccx_line_seq] varchar(6) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [total_matched_ccx_line] int NULL,
    [CCXCurrentSyncFlag] varchar(3) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_mfg_num_infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_vendor_num_infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [JoinSyncType] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [CCX_pkid] int NULL,
    [ManufacturerNumber_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorItem_CCX] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOM_CCX] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [UOMtoMatchInfor_CCX] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [QOE_CCX] int NULL,
    [ContractPrice_CCX] decimal(18,4) NULL,
    [ItemDescription_Infor] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ItemDescription_CCX] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK_InforActiveCLmCCXSyncedCL] PRIMARY KEY CLUSTERED ([Infor_pkid], [matched_ccx_line_seq])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[InforActiveContractLineCnt]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[InforActiveContractLineCnt] (
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractID] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerName_Infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ERPVendorID_Infor] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [VendorID_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorName_Infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [LineCnt_Infor] int NULL,
    [ContractDescription_Infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    CONSTRAINT [PK_InforActiveContractLineCnt] PRIMARY KEY CLUSTERED ([OrganizationEID], [ContractID], [ERPVendorID_Infor])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[InforCCXNotInSyncContracts]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[InforCCXNotInSyncContracts] (
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractID] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ERPVendorID_Infor] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ERPVendorID] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [SyncIssue] varchar(86) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [IsSync_Contract] int NULL,
    [IsSync_OrgContract] int NULL,
    CONSTRAINT [PK_InforCCXNotInSyncContracts] PRIMARY KEY CLUSTERED ([OrganizationEID], [ContractID], [ERPVendorID_Infor])
);
END;
GO
