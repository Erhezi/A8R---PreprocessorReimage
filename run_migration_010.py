"""Apply migration 010 — add precheck_mode to Task, scoring detail columns to MatchResult."""
import pyodbc

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=MISCPrdAdhocDB;"
    "DATABASE=PRIME;"
    "Trusted_Connection=yes;"
)
cur = conn.cursor()

with open("migrations/010_add_precheck_mode_and_scoring.sql", "r") as f:
    sql = f.read()

# SQL Server doesn't support executing multiple IF/ALTER batches in one go via pyodbc.
# Split on the IF NOT EXISTS pattern and run each block separately.
blocks = sql.split("IF NOT EXISTS")
for block in blocks:
    block = block.strip()
    if not block or block.startswith("--"):
        continue
    stmt = "IF NOT EXISTS " + block
    # Remove trailing semicolons for SQL Server
    stmt = stmt.rstrip().rstrip(";")
    try:
        cur.execute(stmt)
    except Exception as e:
        print(f"Warning: {e}")
        print(f"Statement was:\n{stmt[:200]}...")

conn.commit()
print("Migration 010 applied.")

# Verify Task columns
cur.execute("""
    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorTask'
    ORDER BY ORDINAL_POSITION
""")
print("Task columns:", [r[0] for r in cur.fetchall()])

# Verify MatchResult columns
cur.execute("""
    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult'
    ORDER BY ORDINAL_POSITION
""")
print("MatchResult columns:", [r[0] for r in cur.fetchall()])

conn.close()
