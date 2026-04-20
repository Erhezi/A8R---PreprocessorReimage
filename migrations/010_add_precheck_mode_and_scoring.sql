-- Migration 010: Add precheck_mode to Task, scoring detail columns to MatchResult
-- Run against [PRIME] database

-- Task: precheck_mode
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorTask' AND COLUMN_NAME = 'precheck_mode'
)
ALTER TABLE [Preprocessor].[PreprocessorTask]
    ADD precheck_mode VARCHAR(20) NULL DEFAULT 'default';

-- MatchResult: scoring detail columns
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'mfn_score'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD mfn_score FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'mfn_complexity'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD mfn_complexity FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'uom_score'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD uom_score FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'qoe_score'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD qoe_score FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'price_score'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD price_score FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'price_diff_pct'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD price_diff_pct FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'desc_score'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD desc_score FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'weighted_score'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD weighted_score FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'match_ea_price'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD match_ea_price FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'input_ea_price'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD input_ea_price FLOAT NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'pair_type'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD pair_type VARCHAR(1) NULL;

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult' AND COLUMN_NAME = 'vendor_item_score'
)
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] ADD vendor_item_score FLOAT NULL;
