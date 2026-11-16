import sqlite3, json

conn = sqlite3.connect("pid_sessions.db")
c = conn.cursor()
c.execute("SELECT id, filename, saved_at, length(elements_json), length(lines_json) FROM pid_sessions WHERE filename LIKE '%300002%'")
rows = c.fetchall()
for r in rows:
    print(r)

if rows:
    last_id = rows[-1][0]
    c.execute("SELECT filename, elements_json FROM pid_sessions WHERE id=?", (last_id,))
    fname, el_raw = c.fetchone()
    el_json = json.loads(el_raw)
    print(f"\nIn last session {last_id} ({fname}), elements count: {len(el_json)}")
    for i, el in enumerate(el_json):
        print(f"{i}: tag={el.get('tag')} type={el.get('type')} kind={el.get('kind')} line={el.get('line')}")
