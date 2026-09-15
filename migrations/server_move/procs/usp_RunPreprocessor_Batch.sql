-- usp_RunPreprocessor_Batch
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: none
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[usp_RunPreprocessor_Batch]
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @processes TABLE (process_name SYSNAME, exec_sql NVARCHAR(4000), ord INT);
    INSERT INTO @processes(process_name, exec_sql, ord)
    VALUES
      (N'[Preprocessor].sp_RefreshPurchaseVendorLocation',                  N'EXEC [Preprocessor].sp_RefreshPurchaseVendorLocation;',                10),
      --(N'[Preprocessor].sp_UpdateContractLineErrors',                       N'EXEC [Preprocessor].sp_UpdateContractLineErrors;',                     20), --moved out from preprocessor workflow 2026-08-10
      --(N'[Preprocessor].sp_InsertInforContractLineErrorStat',               N'EXEC [Preprocessor].sp_InsertInforContractLineErrorStat;',             21), --moved out from preprocessor workflow 2026-08-10
      (N'[Preprocessor].sp_RefreshCCXInforSyncedContractHeader',            N'EXEC [Preprocessor].sp_RefreshCCXInforSyncedContractHeader;',          30),
      (N'[Preprocessor].sp_RefreshCCXContractLineDeduped',                  N'EXEC [Preprocessor].sp_RefreshCCXContractLineDeduped;',                40),
	  (N'[Preprocessor].sp_RefreshCCXSyncedContractLine',                   N'EXEC [Preprocessor].sp_RefreshCCXSyncedContractLine;',                 50),
	  (N'[Preprocessor].sp_RefreshInforActiveCLLeftJoinCCXSyncedCL',        N'EXEC [Preprocessor].sp_RefreshInforActiveCLLeftJoinCCXSyncedCL;',      60),
	  (N'[Preprocessor].sp_UpdateReducedColumns',                           N'EXEC [Preprocessor].sp_UpdateReducedColumns;',                         61),
	  (N'[Preprocessor].sp_UpdateJoinSyncType',                             N'EXEC [Preprocessor].sp_UpdateJoinSyncType;',                           62),
	  (N'[Preprocessor].sp_MakeInforActiveCLRefCCXSyncedCL',                N'EXEC [Preprocessor].sp_MakeInforActiveCLRefCCXSyncedCL;',              70),
	  (N'[Preprocessor].sp_MakeCCXSyncedContractLineCnt',                   N'EXEC [Preprocessor].sp_MakeCCXSyncedContractLineCnt;',                 80),
	  (N'[Preprocessor].sp_MakeInforActiveContractLineCnt',                 N'EXEC [Preprocessor].sp_MakeInforActiveContractLineCnt;',               90),
	  (N'[Preprocessor].sp_ExtractCCXInforMatchedLink',                     N'EXEC [Preprocessor].sp_ExtractCCXInforMatchedLink;',                   100),
	  (N'[Preprocessor].sp_RefreshInforCCXNotInSyncContracts',              N'EXEC [Preprocessor].sp_RefreshInforCCXNotInSyncContracts;',            110),
	  (N'[Preprocessor].sp_RefreshPurchaseFromAndContractVendor',           N'EXEC [Preprocessor].sp_RefreshPurchaseFromAndContractVendor;',         120);

    DECLARE @p SYSNAME, @sql NVARCHAR(4000), @start DATETIME2(3), @end DATETIME2(3);

    DECLARE cur CURSOR LOCAL FAST_FORWARD FOR
        SELECT process_name, exec_sql FROM @processes ORDER BY ord;

    OPEN cur;
    FETCH NEXT FROM cur INTO @p, @sql;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @start = SYSDATETIME();

        BEGIN TRY
            EXEC sp_executesql @sql;
            SET @end = SYSDATETIME();

            INSERT INTO Preprocessor.process_log(process_name, exec_start, exec_end, status, err_msg)
            VALUES(@p, @start, @end, 'Success', NULL);
        END TRY
        BEGIN CATCH
            SET @end = SYSDATETIME();

            INSERT INTO Preprocessor.process_log(process_name, exec_start, exec_end, status, err_msg)
            VALUES(@p, @start, @end, 'Error', LEFT(ERROR_MESSAGE(), 4000));

            -- keep going; uncomment to fail-fast:
            -- THROW;
        END CATCH;

        FETCH NEXT FROM cur INTO @p, @sql;
    END

    CLOSE cur; DEALLOCATE cur;
END
