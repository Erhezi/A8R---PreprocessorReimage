-- sp_UpdateJoinSyncType
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Cx1
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE [Preprocessor].[sp_UpdateJoinSyncType]
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE PLMPreprocessorShared.Preprocessor.[InforActiveCLLeftJoinCCXSyncedCL]
    SET JoinSyncType = CASE 
        -- Case A: Synced and Successfully Joined
        WHEN CCX_pkid IS NOT NULL AND CCXCurrentSyncFlag = 'On' 
            THEN 'A - Joined'

        -- Case B: Synced but failed to find a match in the join
        WHEN CCX_pkid IS NULL AND CCXCurrentSyncFlag = 'On' 
            THEN 'B - Pending VI Join'

        -- Case C: Not Synced and no match
        WHEN CCX_pkid IS NULL AND CCXCurrentSyncFlag = 'Off' 
            THEN 'C - No CCX Match'

        -- Safety fallback for any unexpected data states
        ELSE 'D - Review'
    END
    WHERE JoinSyncType IS NULL; 

    PRINT 'JoinSyncType categorization complete.';
END;
