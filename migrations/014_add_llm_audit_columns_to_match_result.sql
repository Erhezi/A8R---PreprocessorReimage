IF COL_LENGTH('Preprocessor.PreprocessorMatchResult', 'llm_confidence') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
        ADD [llm_confidence] INT NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorMatchResult', 'llm_reason') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
        ADD [llm_reason] VARCHAR(1000) NULL;
END;