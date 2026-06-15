import sqlite3
import json

db_path = "automation.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables:", tables)

# Search for jobs in the tables containing 'Cabinet'
for table in tables:
    tname = table[0]
    try:
        cursor.execute(f"PRAGMA table_info({tname});")
        cols = [col[1] for col in cursor.fetchall()]
        print(f"\nTable {tname} columns: {cols}")
        
        cursor.execute(f"SELECT * FROM {tname};")
        rows = cursor.fetchall()
        print(f"Total rows in {tname}: {len(rows)}")
        for r in rows:
            # check if 'Cabinet' is in any column
            r_str = str(r)
            if "Cabinet" in r_str:
                print(f"Found Cabinet in table {tname}!")
                # Print index and columns
                for col, val in zip(cols, r):
                    val_str = str(val)
                    if len(val_str) > 150:
                        val_str = val_str[:150] + "... [TRUNCATED]"
                    print(f"  {col}: {val_str}")
    except Exception as e:
        print(f"Error checking {tname}: {e}")

conn.close()
