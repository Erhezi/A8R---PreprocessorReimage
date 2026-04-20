"""Apply migration 006 — add similarity_bucket to PreprocessorMatchResult."""
import pyodbc

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=MISCPrdAdhocDB;"
    "DATABASE=PRIME;"
    "Trusted_Connection=yes;"
)
cur = conn.cursor()

cur.execute("""
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'Preprocessor'
          AND TABLE_NAME   = 'PreprocessorMatchResult'
          AND COLUMN_NAME  = 'similarity_bucket'
    )
    BEGIN
        ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
            ADD [similarity_bucket] NVARCHAR(10) NULL;
    END
""")
conn.commit()
print("similarity_bucket column added (or already existed)")

# Verify all columns
cur.execute("""
    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult'
    ORDER BY ORDINAL_POSITION
""")
cols = [r[0] for r in cur.fetchall()]
print("Current columns:", cols)
conn.close()
