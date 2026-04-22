IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'infor_buy_uom_options') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
    ADD [infor_buy_uom_options] VARCHAR(500) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'active_gtin') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
    ADD [active_gtin] VARCHAR(10) NULL;
END;