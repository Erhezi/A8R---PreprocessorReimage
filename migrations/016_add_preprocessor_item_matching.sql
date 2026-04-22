IF OBJECT_ID('[Preprocessor].[PreprocessorItemMatching]', 'U') IS NULL
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorItemMatching] (
        [match_item_id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [task_id] VARCHAR(4) NOT NULL,
        [item_id] INT NOT NULL,
        [infor_item_number] VARCHAR(20) NOT NULL,
        [item_description] VARCHAR(MAX) NULL,
        [created_at] DATETIME2 NOT NULL CONSTRAINT [DF_PreprocessorItemMatching_created_at] DEFAULT SYSUTCDATETIME(),
        [updated_at] DATETIME2 NOT NULL CONSTRAINT [DF_PreprocessorItemMatching_updated_at] DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [FK_PreprocessorItemMatching_task_id]
            FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask]([task_id]),
        CONSTRAINT [FK_PreprocessorItemMatching_item_id]
            FOREIGN KEY ([item_id]) REFERENCES [Preprocessor].[PreprocessorTaskItem]([item_id])
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'ix_preprocessoritemmatching_task_id'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorItemMatching]')
)
BEGIN
    CREATE INDEX [ix_preprocessoritemmatching_task_id]
        ON [Preprocessor].[PreprocessorItemMatching] ([task_id]);
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'ix_preprocessoritemmatching_item_id'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorItemMatching]')
)
BEGIN
    CREATE INDEX [ix_preprocessoritemmatching_item_id]
        ON [Preprocessor].[PreprocessorItemMatching] ([item_id]);
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'infor_item_number') IS NOT NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem] ALTER COLUMN [infor_item_number] VARCHAR(255) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'infor_item_1') IS NOT NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem] ALTER COLUMN [infor_item_1] VARCHAR(255) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'infor_item_2') IS NOT NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem] ALTER COLUMN [infor_item_2] VARCHAR(255) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'infor_item_3') IS NOT NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem] ALTER COLUMN [infor_item_3] VARCHAR(255) NULL;
END;