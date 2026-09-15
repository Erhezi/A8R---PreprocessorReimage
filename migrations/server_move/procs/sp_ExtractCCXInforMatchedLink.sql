-- sp_ExtractCCXInforMatchedLink
-- Ported from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target: Preprocessor.[Preprocessor]  (run against the Preprocessor database)
-- Rewrites applied: Cx3
-- ----------------------------------------------------------
CREATE OR ALTER PROCEDURE Preprocessor.sp_ExtractCCXInforMatchedLink as
truncate table PLMPreprocessorShared.Preprocessor.[CCXInforMatchedLink];
-- many to many for some records
insert into PLMPreprocessorShared.Preprocessor.[CCXInforMatchedLink] 
select *
from(
select Infor_pkid, matched_ccx_line_seq, CCX_pkid
from PLMPreprocessorShared.Preprocessor.[InforActiveCLRefCCXSyncedCL]
where CCX_pkid is not null
)[map]
