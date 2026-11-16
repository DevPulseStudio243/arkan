import sqlite3
import json

conn = sqlite3.connect('arh_dossiers.db')
c = conn.cursor()
c.execute("SELECT data_json FROM arh_dossiers WHERE dossier_id='DOSSIER_ARH_26307CC5'")
row = c.fetchone()
if row:
    d = json.loads(row[0])
    changed = False
    for comm in d.get('comments', []):
        if 'REM_BT_CALC' in comm.get('id', ''):
            print('D1 comment before:', comm.get('id'), comm.get('page_number'), comm.get('page'))
            comm['page_number'] = 22
            comm['page'] = 'Page 22 sur 73'
            comm['target_content'] = 'Tee Strength Calculation Sheet'
            comm['quote_snippet'] = 'Hebei Canghai Nuclear Equipment Technology Co., Ltd. - Tee Strength Calculation Sheet (8"x8" WPHY60)'
            changed = True
            print('D1 comment after:', comm.get('id'), comm.get('page_number'), comm.get('page'))
    if changed:
        c.execute("UPDATE arh_dossiers SET data_json=? WHERE dossier_id='DOSSIER_ARH_26307CC5'", (json.dumps(d, ensure_ascii=False),))
        conn.commit()
        print('D1 updated successfully!')
conn.close()
