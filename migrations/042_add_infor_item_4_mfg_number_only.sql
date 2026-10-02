-- ============================================================
-- Migration 042: Source 4 of Item# labeling on PreprocessorTaskItem.
-- Run against SQL Server: YNBBSTVWP02\PROCDATASRVPROD, database Preprocessor
-- Schema: Preprocessor
--
-- Source 4 looks up MDM_ITEM by manufacturer part number alone, ignoring the
-- manufacturer. It is only consulted when Sources 1-3 (MDM_ITEM by
-- manufacturer + part number, MDM_VENDORITEM, accepted Infor contract lines)
-- all come back empty, and every label it produces is raised as a
-- MFG_ONLY_ITEM_WARN issue for a reviewer to keep (Noted) or detach.
--
-- [infor_item_4] holds the candidate Item#(s) Source 4 proposed; it stays
-- populated after a detach as the record of what was offered.
-- ============================================================

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'infor_item_4') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [infor_item_4] VARCHAR(255) NULL;
END;
GO

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'infor_item_4_active') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [infor_item_4_active] VARCHAR(5) NULL;
END;
GO
