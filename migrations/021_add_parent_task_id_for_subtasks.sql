-- ============================================================
-- Migration 021: Sub-task lineage support on PreprocessorTask.
-- Adds parent_task_id + spawn_reason so that error rows split
-- off during PC1 advance can be linked back to their ancestor.
-- ============================================================

IF COL_LENGTH('Preprocessor.PreprocessorTask', 'parent_task_id') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD [parent_task_id] NCHAR(4) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTask', 'spawn_reason') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD [spawn_reason] VARCHAR(50) NULL;
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = 'FK_PreprocessorTask_parent_task'
      AND parent_object_id = OBJECT_ID('[Preprocessor].[PreprocessorTask]')
)
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD CONSTRAINT [FK_PreprocessorTask_parent_task]
            FOREIGN KEY ([parent_task_id])
            REFERENCES [Preprocessor].[PreprocessorTask]([task_id]);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'ix_preprocessor_task_parent_task_id'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorTask]')
)
BEGIN
    CREATE INDEX [ix_preprocessor_task_parent_task_id]
        ON [Preprocessor].[PreprocessorTask] ([parent_task_id]);
END;
