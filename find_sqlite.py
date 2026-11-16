import sqlite3, glob, os

for db in glob.glob("*.db") + glob.glob("*/*.db"):
    print("DB:", db)
    try:
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in c.fetchall()]
        print("  Tables:", tables)
        for t in tables:
            try:
                c.execute(f"SELECT count(*) FROM {t}")
                cnt = c.fetchone()[0]
                print(f"    {t}: {cnt} rows")
            except:
                pass
    except Exception as e:
        print("  Error:", e)
