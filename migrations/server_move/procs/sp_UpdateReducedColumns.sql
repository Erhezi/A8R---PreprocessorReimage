-- sp_UpdateReducedColumns
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Cx4
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_UpdateReducedColumns]
AS
BEGIN
    SET NOCOUNT ON;

    -- Update the table using the functions we created
    UPDATE PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL]
    SET 
        reduced_mfg_num_infor = Preprocessor.fn_ReduceCatalogNumber(ManufacturerNumber_Infor),
        reduced_vendor_num_infor = Preprocessor.fn_ReduceCatalogNumber(VendorItem_Infor)
    WHERE 
        -- Only update rows that haven't been processed yet to save time
        reduced_mfg_num_infor IS NULL 
        OR reduced_mfg_num_infor IS NULL;

    PRINT 'Reduction update complete on PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL]';

	    -- Update the table using the functions we created
    UPDATE PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLine]
    SET 
        reduced_mfg_num_ccx = Preprocessor.fn_ReduceCatalogNumber(ManufacturerNumber_CCX),
        reduced_vendor_num_ccx = Preprocessor.fn_ReduceCatalogNumber(VendorItem_CCX)
    WHERE 
        -- Only update rows that haven't been processed yet to save time
        reduced_mfg_num_ccx IS NULL 
        OR reduced_mfg_num_ccx IS NULL;

    PRINT 'Reduction update complete on PLMPreprocessorShared.Preprocessor.[CCXSyncedContractLine]';
END;
