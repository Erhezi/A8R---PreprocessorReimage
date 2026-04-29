-- Migration 020: Flag same-contract matches where Input UOM differs from
-- Matched UOM but the QOE is identical (so the item recorded against the
-- same contract is using an inconsistent UOM for the same pack size).

IF COL_LENGTH('Preprocessor.PreprocessorMatchResult', 'uom_nuance') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
        ADD [uom_nuance] VARCHAR(3) NULL;
END;
