-- Migration 011: Add uom_to_match_infor to TaskItem
-- Run against [PRIME] database

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME = 'PreprocessorTaskItem'
      AND COLUMN_NAME = 'uom_to_match_infor'
)
ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
    ADD uom_to_match_infor VARCHAR(10) NULL;