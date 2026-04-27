ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
ADD [dedup_decision] VARCHAR(20) NULL,
    [dedup_decided_by] VARCHAR(120) NULL,
    [dedup_decided_at] DATETIME NULL;