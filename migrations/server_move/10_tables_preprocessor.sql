-- ============================================================
-- Tables (25) -> [Preprocessor] schema
-- Generated from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target database: Preprocessor
-- Idempotent: every object is guarded by an existence check.
-- ============================================================


IF OBJECT_ID(N'[Preprocessor].[CCXDistributor]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[CCXDistributor] (
    [VendorName] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [EditBy] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [EditDate] date NULL CONSTRAINT [DF__CCXDistri__EditD__6F62BD16] DEFAULT (CONVERT([date],getdate())),
    CONSTRAINT [PK_CCXDistributor] PRIMARY KEY CLUSTERED ([VendorName])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[CCXInforSyncedContractHeader]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[CCXInforSyncedContractHeader] (
    [RN] int NOT NULL,
    [RN_check] int NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Manufacturer] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Vendor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractProcessType] varchar(12) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ContractID] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ERPVendorID] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractSourceType] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [DC_contractRefID] int NULL,
    [InforCompanyEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [rs_CCXH] datetime NULL,
    [ManufacturerEID] varchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractStartDate] date NULL,
    [ContractEndDate] date NULL,
    [DC_TierLevel] int NULL,
    [rs_CCXL] date NULL,
    [OrganizationEID_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractID_Infor] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ERPVendorID_Infor] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractManufacturer_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerName_Infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ManufacturerEID_Infor] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ContractStartDate_Infor] date NULL,
    [ContractEndDate_Infor] date NULL,
    [Contract_Infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [rs_Infor] datetime NULL,
    CONSTRAINT [PK_InforSyncedContractHeader] PRIMARY KEY CLUSTERED ([RN])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[CompanyOrganization]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[CompanyOrganization] (
    [Company] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [CompanyText] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [CCXOrganization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [InforCompanyEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [loaded stamp] date NULL CONSTRAINT [DF__CompanyOr__loade__1A822545] DEFAULT (CONVERT([date],getdate())),
    CONSTRAINT [PK_CompanyOrganization] PRIMARY KEY CLUSTERED ([Company])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[DistributorGroup]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[DistributorGroup] (
    [ERPVendorID] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [VendorName] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Group] int NOT NULL,
    [EditBy] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Distribut__EditB__04E7E9E1] DEFAULT ('dli2'),
    [EditDate] date NOT NULL CONSTRAINT [DF__Distribut__EditD__05DC0E1A] DEFAULT (getdate()),
    CONSTRAINT [PK_DistributorGroup] PRIMARY KEY CLUSTERED ([ERPVendorID])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[OrganizationEIDandName]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[OrganizationEIDandName] (
    [OrganizationEID] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    CONSTRAINT [PK_OrganizationEID] PRIMARY KEY CLUSTERED ([OrganizationEID])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorContractDecision]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorContractDecision] (
    [decision_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [organization_eid] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [contract_id] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [erp_vendor_id] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [decision] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [decided_by] varchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [decided_at] datetime NOT NULL CONSTRAINT [DF__Preproces__decid__00E24ED3] DEFAULT (getdate()),
    CONSTRAINT [PK__Preproce__7F66496CD2644BB1] PRIMARY KEY CLUSTERED ([decision_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryItem]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorDiscoveryItem] (
    [discovery_item_id] int IDENTITY(1,1) NOT NULL,
    [set_id] int NOT NULL,
    [file_row] int NULL,
    [sku_raw] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [sku_input] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [reduced_sku] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [description_input] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [supplier_input] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [match_count] int NOT NULL CONSTRAINT [DF_DiscoveryItem_matches] DEFAULT ((0)),
    [created_at] datetime2(7) NOT NULL CONSTRAINT [DF_DiscoveryItem_created_at] DEFAULT (getdate()),
    CONSTRAINT [PK_PreprocessorDiscoveryItem] PRIMARY KEY CLUSTERED ([discovery_item_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryMatch]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorDiscoveryMatch] (
    [discovery_match_id] int IDENTITY(1,1) NOT NULL,
    [set_id] int NOT NULL,
    [discovery_item_id] int NOT NULL,
    [ccx_pkid] int NULL,
    [matched_on] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [sku_exact] bit NOT NULL CONSTRAINT [DF_DiscoveryMatch_exact] DEFAULT ((0)),
    [desc_similarity] float NULL,
    [rank_in_item] int NULL,
    [organization_eid_matched] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_matched] nvarchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_id_matched] nvarchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [erp_vendor_id_matched] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [mfg_catalog_num_matched] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_matched] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_to_match_infor_matched] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_catalog_num_matched] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [description_matched] nvarchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [qoe_matched] int NULL,
    [unit_price_matched] decimal(18,4) NULL,
    [contract_description] nvarchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_name_matched] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [mfg_name_matched] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_manufacturer_matched] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_status] nvarchar(15) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF_DiscoveryMatch_llm_status] DEFAULT ('NONE'),
    [llm_verdict] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_confidence] int NULL,
    [llm_reason] nvarchar(1000) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_prompt_version_id] int NULL,
    [llm_reviewed_at] datetime2(7) NULL,
    [llm_error] nvarchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_at] datetime2(7) NOT NULL CONSTRAINT [DF_DiscoveryMatch_created_at] DEFAULT (getdate()),
    [user_verdict] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [user_verdict_by] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [user_verdict_at] datetime2(7) NULL,
    [llm_same_noun] bit NULL,
    [llm_input_noun] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_matched_noun] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK_PreprocessorDiscoveryMatch] PRIMARY KEY CLUSTERED ([discovery_match_id]),
    CONSTRAINT [CK_DiscoveryMatch_on] CHECK ([matched_on]='REDUCED_VPN' OR [matched_on]='REDUCED_MFG'),
    CONSTRAINT [CK_DiscoveryMatch_llm_status] CHECK ([llm_status]='ERROR' OR [llm_status]='DONE' OR [llm_status]='IN_PROGRESS' OR [llm_status]='PENDING' OR [llm_status]='NONE'),
    CONSTRAINT [CK_DiscoveryMatch_verdict] CHECK ([llm_verdict] IS NULL OR ([llm_verdict]='UNCERTAIN' OR [llm_verdict]='DIFFERENT' OR [llm_verdict]='SAME')),
    CONSTRAINT [CK_DiscoveryMatch_user_verdict] CHECK ([user_verdict] IS NULL OR ([user_verdict]='DIFFERENT' OR [user_verdict]='SAME'))
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryPrompt]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorDiscoveryPrompt] (
    [prompt_version_id] int IDENTITY(1,1) NOT NULL,
    [prompt_key] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF_DiscoveryPrompt_key] DEFAULT ('ITEM_COMPARE'),
    [version_no] int NOT NULL,
    [system_prompt] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [user_template] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [model] nvarchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [temperature] float NULL,
    [is_active] bit NOT NULL CONSTRAINT [DF_DiscoveryPrompt_is_active] DEFAULT ((0)),
    [notes] nvarchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_by] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [created_at] datetime2(7) NOT NULL CONSTRAINT [DF_DiscoveryPrompt_created_at] DEFAULT (getdate()),
    [prompt_mode] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF_DiscoveryPrompt_mode] DEFAULT ('PAIR'),
    CONSTRAINT [PK_PreprocessorDiscoveryPrompt] PRIMARY KEY CLUSTERED ([prompt_version_id]),
    CONSTRAINT [CK_DiscoveryPrompt_mode] CHECK ([prompt_mode]='GROUP' OR [prompt_mode]='PAIR')
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoverySet]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorDiscoverySet] (
    [set_id] int IDENTITY(1,1) NOT NULL,
    [set_name] nvarchar(200) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [source_filename] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [match_mode] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF_DiscoverySet_mode] DEFAULT ('EITHER'),
    [org_eid] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF_DiscoverySet_org] DEFAULT ('105188574'),
    [row_count] int NOT NULL CONSTRAINT [DF_DiscoverySet_rows] DEFAULT ((0)),
    [match_count] int NOT NULL CONSTRAINT [DF_DiscoverySet_matches] DEFAULT ((0)),
    [has_supplier] bit NOT NULL CONSTRAINT [DF_DiscoverySet_supplier] DEFAULT ((0)),
    [status] nvarchar(30) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF_DiscoverySet_status] DEFAULT ('UPLOADED'),
    [active_prompt_version_id] int NULL,
    [created_by] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [created_at] datetime2(7) NOT NULL CONSTRAINT [DF_DiscoverySet_created_at] DEFAULT (getdate()),
    [updated_at] datetime2(7) NOT NULL CONSTRAINT [DF_DiscoverySet_updated_at] DEFAULT (getdate()),
    CONSTRAINT [PK_PreprocessorDiscoverySet] PRIMARY KEY CLUSTERED ([set_id]),
    CONSTRAINT [CK_DiscoverySet_mode] CHECK ([match_mode]='EITHER' OR [match_mode]='VENDOR' OR [match_mode]='MFG')
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorIMCheckResult]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorIMCheckResult] (
    [result_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [check_id] int NOT NULL,
    [check_code] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [dedup_id] int NULL,
    [input_item_id] int NULL,
    [severity] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__sever__55C2E6A4] DEFAULT ('WARN'),
    [subject] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [detail] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_at] datetime NOT NULL CONSTRAINT [DF__Preproces__creat__56B70ADD] DEFAULT (getdate()),
    CONSTRAINT [PK__Preproce__AFB3C316DD92BDFA] PRIMARY KEY CLUSTERED ([result_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorIntegrityIssue]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorIntegrityIssue] (
    [issue_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [check_id] int NOT NULL,
    [severity] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__sever__5503CC95] DEFAULT ('ERROR'),
    [group_keys] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [affected] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [detail] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_at] datetime NOT NULL CONSTRAINT [DF__Preproces__creat__55F7F0CE] DEFAULT (getdate()),
    CONSTRAINT [PK__Preproce__D6185C39731E3CDD] PRIMARY KEY CLUSTERED ([issue_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorItemMatching]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorItemMatching] (
    [match_item_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [item_id] int NOT NULL,
    [infor_item_number] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [item_description] varchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_at] datetime2(7) NOT NULL CONSTRAINT [DF_PreprocessorItemMatching_created_at] DEFAULT (sysutcdatetime()),
    [updated_at] datetime2(7) NOT NULL CONSTRAINT [DF_PreprocessorItemMatching_updated_at] DEFAULT (sysutcdatetime()),
    [infor_buy_uom_options] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [active_gtin] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK__Preproce__62B7D6FC51DAF016] PRIMARY KEY CLUSTERED ([match_item_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorMatchResult]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorMatchResult] (
    [match_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [input_item_id] int NOT NULL,
    [matched_source] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [matched_item_ref] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [similarity_score] float NULL,
    [bucket] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [match_status] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__match__2005F471] DEFAULT ('PENDING'),
    [reviewed_by] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reviewed_at] datetime2(7) NULL,
    [created_at] datetime2(7) NULL CONSTRAINT [DF__Preproces__creat__20FA18AA] DEFAULT (getdate()),
    [contract_number] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [match_type] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ccx_pkid] int NULL,
    [infor_pkid] varchar(31) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [similarity_bucket] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [mfn_score] float NULL,
    [mfn_complexity] float NULL,
    [uom_score] float NULL,
    [qoe_score] float NULL,
    [price_score] float NULL,
    [price_diff_pct] float NULL,
    [desc_score] float NULL,
    [weighted_score] float NULL,
    [match_ea_price] float NULL,
    [input_ea_price] float NULL,
    [pair_type] varchar(2) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_item_score] float NULL,
    [contract_id_matched] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_eid_matched] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_matched] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [manufacturer_number_matched] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_matched] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [erp_vendor_id_matched] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_item_matched] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_to_match_infor_matched] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [qoe_matched] int NULL,
    [contract_price_matched] decimal(18,4) NULL,
    [item_desc_matched] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ccx_pkids_matched] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_confidence] int NULL,
    [llm_reason] varchar(1000) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_pkids_matched] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [dedup_decision] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [dedup_decided_by] varchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [dedup_decided_at] datetime NULL,
    [uom_nuance] varchar(3) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_warning] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK__Preproce__9D7FCBA37F3477E1] PRIMARY KEY CLUSTERED ([match_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorPreCheckError]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorPreCheckError] (
    [error_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [item_id] int NULL,
    [phase] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [error_type] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [error_detail] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [resolved] bit NULL CONSTRAINT [DF__Preproces__resol__1A4D1B1B] DEFAULT ((0)),
    [resolved_by] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [resolved_at] datetime2(7) NULL,
    [created_at] datetime2(7) NULL CONSTRAINT [DF__Preproces__creat__1B413F54] DEFAULT (getdate()),
    CONSTRAINT [PK__Preproce__DA71E16C1B15500B] PRIMARY KEY CLUSTERED ([error_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorPreprocessIssue]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorPreprocessIssue] (
    [issue_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [item_id] int NOT NULL,
    [issue_type] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [severity] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [detail] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [resolved] bit NOT NULL CONSTRAINT [DF__Preproces__resol__31BA9058] DEFAULT ((0)),
    [resolved_by] varchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [resolved_at] datetime NULL,
    [resolution_action] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_at] datetime NOT NULL CONSTRAINT [DF__Preproces__creat__32AEB491] DEFAULT (getdate()),
    [updated_at] datetime NOT NULL CONSTRAINT [DF__Preproces__updat__33A2D8CA] DEFAULT (getdate()),
    CONSTRAINT [PK__Preproce__D6185C3976343596] PRIMARY KEY CLUSTERED ([issue_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorTask]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorTask] (
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [contract_number] nvarchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_id] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [purchase_from_loc] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [process_type] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [source_type] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [organization] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [oem_name] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [intention] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [mixed_intention] bit NULL CONSTRAINT [DF__Preproces__mixed__0B0AD78B] DEFAULT ((0)),
    [contract_start_date] date NULL,
    [contract_end_date] date NULL,
    [notes] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [phase] nvarchar(30) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__phase__0BFEFBC4] DEFAULT ('INTAKE'),
    [status] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__statu__0CF31FFD] DEFAULT ('DRAFT'),
    [created_by] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [created_at] datetime2(7) NULL CONSTRAINT [DF__Preproces__creat__0DE74436] DEFAULT (getdate()),
    [updated_at] datetime2(7) NULL CONSTRAINT [DF__Preproces__updat__0EDB686F] DEFAULT (getdate()),
    [intake_mode] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__intak__471FC192] DEFAULT ('SINGLE'),
    [wrike_id] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_manufacturer_name_infor] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [erp_vendor_name] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [purchase_from_loc_name] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_manufacturer_infor] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [precheck_mode] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL CONSTRAINT [DF__Preproces__prech__3A84E083] DEFAULT ('default'),
    [parent_task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [spawn_reason] varchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_description] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [threshold_config] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL CONSTRAINT [DF_PreprocessorTask_threshold_config] DEFAULT ('B'),
    [llm_prompt_version] nvarchar(60) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_review_mode] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL CONSTRAINT [DF_PreprocessorTask_llm_review_mode] DEFAULT ('GROUP'),
    CONSTRAINT [PK__Preproce__0492148D7E079532] PRIMARY KEY CLUSTERED ([task_id]),
    CONSTRAINT [CK_PreprocessorTask_threshold_config] CHECK ([threshold_config] IS NULL OR ([threshold_config]='C' OR [threshold_config]='B' OR [threshold_config]='A')),
    CONSTRAINT [CK_PreprocessorTask_llm_review_mode] CHECK ([llm_review_mode] IS NULL OR ([llm_review_mode]='GROUP' OR [llm_review_mode]='PAIR'))
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorTaskItem]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorTaskItem] (
    [item_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [vendor_catalog_num] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [mfg_catalog_num] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [description] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [standardized_description] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [unit_price] decimal(18,4) NULL,
    [qoe] int NOT NULL,
    [intention] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [status] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__statu__12ABF953] DEFAULT ('UPLOADED'),
    [error_message] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [source_dataset] nvarchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__sourc__13A01D8C] DEFAULT ('INPUT'),
    [infor_item_number] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_line_infor_item_number] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_sync_flag] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_mfg_num] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reduced_vendor_num] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_at] datetime2(7) NULL CONSTRAINT [DF__Preproces__creat__149441C5] DEFAULT (getdate()),
    [updated_at] datetime2(7) NULL CONSTRAINT [DF__Preproces__updat__158865FE] DEFAULT (getdate()),
    [tier_description] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [tier_level] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [file_row] int NULL,
    [manufacturer_name_infor] nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [manufacturer_infor] nvarchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [input_reference] int NULL,
    [vendor_id_short] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_to_match_infor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_1] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_1_active] varchar(5) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_2] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_2_active] varchar(5) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_3] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_3_active] varchar(30) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_buy_uom_options] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [ccx_pkid] int NULL,
    [infor_pkid] varchar(31) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_eid] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_type] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_manufacturer] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [mfg_name_infor_line] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [mfg_name_infor_contract] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_name_infor] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_id] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [item_price_start_date] date NULL,
    [item_price_end_date] date NULL,
    [original_mfg_catalog_num] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [original_vendor_catalog_num] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [original_description] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [original_uom] varchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [original_qoe] int NULL,
    [original_unit_price] numeric(18,4) NULL,
    [edits] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK__Preproce__52020FDD45F55AAD] PRIMARY KEY CLUSTERED ([item_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorTaskItemForDecision]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorTaskItemForDecision] (
    [dedup_id] int IDENTITY(1,1) NOT NULL,
    [match_id] int NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [input_item_id] int NOT NULL,
    [matched_source] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [match_status] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [similarity_bucket] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [similarity_score] float NULL,
    [contract_id_matched] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [erp_vendor_id_matched] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_eid_matched] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_matched] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [manufacturer_number_matched] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_item_matched] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_matched] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_to_match_infor_matched] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [qoe_matched] int NULL,
    [contract_price_matched] numeric(18,4) NULL,
    [ea_price_matched] float NULL,
    [item_desc_matched] varchar(500) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_pkids_matched] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_pkid] varchar(31) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_matched] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [match_type] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [pair_type] varchar(2) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_reason] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [llm_warning] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [task_intention] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [contract_id_input] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [erp_vendor_id_input] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_eid_input] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [organization_input] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [manufacturer_number_input] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [vendor_item_input] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_input] varchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [uom_to_match_infor_input] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [qoe_input] int NULL,
    [contract_price_input] numeric(18,4) NULL,
    [ea_price_input] float NULL,
    [item_description_input] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [infor_item_number] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__Preproces__infor__4D62AACD] DEFAULT (''),
    [matched_contract_source_type] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [matched_contract_process_type] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [input_contract_source_type] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [input_contract_process_type] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [dedup_decision] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [dedup_decided_by] varchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [created_at] datetime NOT NULL CONSTRAINT [DF__Preproces__creat__4E56CF06] DEFAULT (getdate()),
    [dedup_decided_at] datetime NULL,
    [editable] bit NOT NULL CONSTRAINT [DF__Preproces__edita__4F4AF33F] DEFAULT ((1)),
    [edits] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [resolution_grouping] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [default_action_input] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [default_action_matched] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [dedup_sort] int NULL,
    [input_decision] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [matched_decision] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK__Preproce__0D2D2DE0AA566F49] PRIMARY KEY CLUSTERED ([dedup_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PreprocessorTaskStatusLog]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PreprocessorTaskStatusLog] (
    [log_id] int IDENTITY(1,1) NOT NULL,
    [task_id] nchar(4) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [old_phase] nvarchar(30) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [new_phase] nvarchar(30) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [old_status] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [new_status] nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [changed_by] nvarchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [changed_at] datetime2(7) NULL CONSTRAINT [DF__Preproces__chang__24CAA98E] DEFAULT (getdate()),
    [notes] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    CONSTRAINT [PK__Preproce__9E2397E099E5375F] PRIMARY KEY CLUSTERED ([log_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[process_log]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[process_log] (
    [pkid] bigint IDENTITY(1,1) NOT NULL,
    [process_name] sysname COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [exec_start] datetime2(3) NOT NULL,
    [exec_end] datetime2(3) NULL,
    [status] varchar(16) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL CONSTRAINT [DF__process_l__statu__369F4106] DEFAULT ('Unknown'),
    [err_msg] nvarchar(4000) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [duration_ms] AS (case when [exec_end] IS NOT NULL then datediff_big(millisecond,[exec_start],[exec_end])  end) PERSISTED,
    CONSTRAINT [PK__process___40A64C0B3F7DB996] PRIMARY KEY CLUSTERED ([pkid])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PurchaseFromAndContractVendor]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PurchaseFromAndContractVendor] (
    [OrganizationEID] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Organization] varchar(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Location] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [LocationText] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [LocationType] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Item] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Item.Active] varchar(5) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Active] varchar(5) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Discontinued] varchar(5) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Vendor] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [PurchaseFromLocation] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [VendorName] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [PurchaseFromLocationText] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [PurchaseFromLocation_CL] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [PurchaseFromMatchFlag] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [Vendor_CL2] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [PurchaseFromLocation_CL2] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [PurchaseVendorMatchFlag] varchar(53) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [ScopeFilter] varchar(40) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[PurchaseVendorLocation]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[PurchaseVendorLocation] (
    [ERPVendorID] varchar(20) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [VendorName] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [PurchaseFromName] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [Active] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    CONSTRAINT [PK_PurchaseVendorLocation] PRIMARY KEY CLUSTERED ([ERPVendorID])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[users]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[users] (
    [user_id] int IDENTITY(1,1) NOT NULL,
    [email] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [name] varchar(120) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [user_role] varchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [pw_hash] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [is_active] bit NOT NULL,
    [created_at] datetime NOT NULL,
    [last_login_at] datetime NULL,
    [reset_code] varchar(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [reset_code_expiry] datetime NULL,
    [approved_by] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [approved_at] datetime NULL,
    [disabled_by] varchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    [disabled_at] datetime NULL,
    CONSTRAINT [PK__users__B9BE370F12E061F4] PRIMARY KEY CLUSTERED ([user_id])
);
END;
GO

IF OBJECT_ID(N'[Preprocessor].[ValidUOM]', N'U') IS NULL
BEGIN
CREATE TABLE [Preprocessor].[ValidUOM] (
    [UOM] varchar(5) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    [create stamp] datetime NULL CONSTRAINT [DF__ValidUOM__create__4AF05276] DEFAULT (getdate()),
    CONSTRAINT [PK_ValidUOM] PRIMARY KEY CLUSTERED ([UOM])
);
END;
GO
