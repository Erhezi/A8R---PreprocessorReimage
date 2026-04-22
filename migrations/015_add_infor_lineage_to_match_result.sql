IF COL_LENGTH('Preprocessor.PreprocessorMatchResult', 'infor_pkids_matched') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
        ADD [infor_pkids_matched] VARCHAR(255) NULL;
END;