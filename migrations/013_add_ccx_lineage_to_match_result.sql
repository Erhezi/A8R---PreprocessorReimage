IF COL_LENGTH('Preprocessor.PreprocessorMatchResult', 'ccx_pkids_matched') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
        ADD [ccx_pkids_matched] VARCHAR(255) NULL;
END;