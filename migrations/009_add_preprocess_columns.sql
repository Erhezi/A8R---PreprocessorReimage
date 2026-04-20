-- Migration 009: Add Phase 3 (Preprocess Core) columns
-- PreprocessorTaskItem: linkage, Infor item labeling, org/sync fields
-- PreprocessorMatchResult: contract grouping, match type, PK references

-- ============================================================================
-- PreprocessorTaskItem — new columns for Phase 3
-- ============================================================================

-- Links CCX/INFOR rows back to the originating INPUT item
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [input_reference] INT NULL;

-- Vendor ID (left 7 of ERPVendorID for CCX/INPUT, or VendorID for Infor)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [vendor_id_short] VARCHAR(10) NULL;

-- EDI-translated UOM (via MDM_EDI_SUB_UOM)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [uom_to_match_infor] VARCHAR(10) NULL;

-- Infor Item labeling (3 sources)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_item_1] VARCHAR(20) NULL;          -- from MDM_ITEM (Manufacturer+MfgNum)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_item_1_active] VARCHAR(5) NULL;
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_item_2] VARCHAR(20) NULL;          -- from MDM_VENDORITEM (Vendor+VendorItem)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_item_2_active] VARCHAR(5) NULL;
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_item_3] VARCHAR(100) NULL;         -- from TP Infor CL match (may list multiple)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_item_3_active] VARCHAR(30) NULL;

-- Valid buy UOM options (e.g. "BX*5, PK*10")
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_buy_uom_options] VARCHAR(500) NULL;

-- PK references to source system rows
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [ccx_pkid] INT NULL;
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [infor_pkid] VARCHAR(31) NULL;

-- Organization entity fields
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [organization_eid] VARCHAR(10) NULL;
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [organization_type] VARCHAR(10) NULL;     -- MHS | ENTITY

-- Manufacturer codes (4-digit, contract and line level)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [contract_manufacturer] VARCHAR(10) NULL;

-- Infor standard names
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [mfg_name_infor_line] VARCHAR(255) NULL;
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [mfg_name_infor_contract] VARCHAR(255) NULL;
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [vendor_name_infor] VARCHAR(255) NULL;

-- Contract ID on the item row (for CCX/INFOR sourced rows)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [contract_id] VARCHAR(100) NULL;

-- Price start/end dates (for CCX/INFOR sourced rows)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [item_price_start_date] DATE NULL;
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD [item_price_end_date] DATE NULL;


-- ============================================================================
-- PreprocessorMatchResult — new columns for Phase 3
-- ============================================================================

-- Contract number for contract-level grouping
ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [contract_number] VARCHAR(100) NULL;

-- How the match was found
ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [match_type] VARCHAR(20) NULL;            -- EXACT_MFG | REDUCED_MFG | REDUCED_VPN | CROSS_MATCH

-- PK references to source rows
ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [ccx_pkid] INT NULL;
ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [infor_pkid] VARCHAR(31) NULL;
