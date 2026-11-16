# fix_chromadb.py

- find_sqlite_db · function · L18-L29 — def find_sqlite_db()
- backup_db · function · L32-L38 — def backup_db(db_path)
- get_table_columns · function · L41-L44 — def get_table_columns(cursor, table_name)
- get_all_tables · function · L47-L50 — def get_all_tables(cursor)
- diagnose · function · L53-L95 — def diagnose(db_path)
- fix_schema · function · L98-L126 — def fix_schema(db_path, issues)
- verify_fix · function · L129-L174 — def verify_fix(db_path)
- option_rebuild · function · L177-L188 — def option_rebuild()
- main · function · L191-L248 — def main()
