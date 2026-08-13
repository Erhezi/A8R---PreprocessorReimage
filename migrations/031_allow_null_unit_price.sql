-- ============================================================
-- Migration 031: Allow NULL unit_price on PreprocessorTaskItem.
--
-- Intake used to coerce a blank/missing price cell to 0 at upload,
-- which made "the file gave us no price" indistinguishable from a
-- deliberate 0.00 by the time PC1 ran (so neither was ever flagged).
-- Upload now stores an empty price as NULL and a non-numeric price
-- as the sentinel -1, letting PC1 split the two cases -- both are
-- ERROR_PC1, they just name the problem differently:
--     NULL      -> BLANK_PRICE
--     <= 0      -> INVALID_PRICE
-- ============================================================

IF EXISTS (
    SELECT 1
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME = 'PreprocessorTaskItem'
      AND COLUMN_NAME = 'unit_price'
      AND IS_NULLABLE = 'NO'
)
BEGIN
    ALTER TABLE [Preprocessor].PreprocessorTaskItem
        ALTER COLUMN unit_price DECIMAL(18,4) NULL;
END;
