with open('project_config.yaml', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'cable_tray: [CABLETRAY, "CHEMIN DE CABLE", "CHEMIN DE CBLE", CHEMINEMENT, CDC, "CABLE ELECT", CABLE]',
    'cable_tray: [CABLETRAY, "CHEMIN DE CABLE", "CHEMIN DE CBLE", "cheminement électrique", CHEMINEMENT, CDC]'
)

with open('project_config.yaml', 'w', encoding='utf-8') as f:
    f.write(text)

print('Cleaned cable_tray layers in project_config.yaml')
