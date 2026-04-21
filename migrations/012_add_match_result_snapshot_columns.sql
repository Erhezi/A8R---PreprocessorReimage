-- Migration 012: Persist stable matched row identifiers on match results

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [contract_id_matched] VARCHAR(100) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [organization_eid_matched] VARCHAR(10) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [organization_matched] VARCHAR(100) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [manufacturer_number_matched] VARCHAR(255) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [uom_matched] VARCHAR(10) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [erp_vendor_id_matched] VARCHAR(20) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [vendor_item_matched] VARCHAR(255) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [uom_to_match_infor_matched] VARCHAR(10) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [qoe_matched] INT NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [contract_price_matched] DECIMAL(18, 4) NULL;

ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
    ADD [item_desc_matched] VARCHAR(500) NULL;