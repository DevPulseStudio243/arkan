import sqlite3

conn = sqlite3.connect('arh_dossiers.db')
c = conn.cursor()
c.execute('SELECT piece_code, piece_name, page_start, page_end, page_count, file_name FROM arh_sliced_pieces WHERE dossier_id="DOSSIER_ARH_A034FE30"')
for r in c.fetchall():
    print(r)
conn.close()
