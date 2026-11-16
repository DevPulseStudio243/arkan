import sqlite3, json

conn = sqlite3.connect("pid_sessions.db")
c = conn.cursor()
c.execute("SELECT id, filename, elements_json, lines_json FROM pid_sessions WHERE id=73")
row = c.fetchone()
print("ID:", row[0], "Filename:", row[1])
elements = json.loads(row[2])
lines = json.loads(row[3]) if row[3] else []
print(f"Elements count: {len(elements)}")
print(f"Lines count: {len(lines)}")
for i, el in enumerate(elements):
    print(f"{i}: tag={el.get('tag')} type={el.get('type')} kind={el.get('kind')} line={el.get('line')}")
