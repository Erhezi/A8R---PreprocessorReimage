-- Migration 008: Add manufacturer and vendor fields to Task and TaskItem
-- Run once against MISCPrdAdhocDB

-- ── PreprocessorTask ─────────────────────────────────────────────────────────
IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTask'
      AND COLUMN_NAME  = 'contract_manufacturer_infor'
)
    ALTER TABLE [Preprocessor].PreprocessorTask
        ADD contract_manufacturer_infor NVARCHAR(20) NULL;

IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTask'
      AND COLUMN_NAME  = 'contract_manufacturer_name_infor'
)
    ALTER TABLE [Preprocessor].PreprocessorTask
        ADD contract_manufacturer_name_infor NVARCHAR(255) NULL;

IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTask'
      AND COLUMN_NAME  = 'erp_vendor_name'
)
    ALTER TABLE [Preprocessor].PreprocessorTask
        ADD erp_vendor_name NVARCHAR(255) NULL;

IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTask'
      AND COLUMN_NAME  = 'purchase_from_loc_name'
)
    ALTER TABLE [Preprocessor].PreprocessorTask
        ADD purchase_from_loc_name NVARCHAR(255) NULL;

-- ── PreprocessorTaskItem ──────────────────────────────────────────────────────
IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTaskItem'
      AND COLUMN_NAME  = 'manufacturer_infor'
)
    ALTER TABLE [Preprocessor].PreprocessorTaskItem
        ADD manufacturer_infor NVARCHAR(20) NULL;

IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTaskItem'
      AND COLUMN_NAME  = 'manufacturer_name_infor'
)
    ALTER TABLE [Preprocessor].PreprocessorTaskItem
        ADD manufacturer_name_infor NVARCHAR(255) NULL;
