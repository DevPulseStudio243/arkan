with open('project_config.yaml', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'cable_tray: [CABLETRAY, "CHEMIN DE CABLE", "CHEMIN DE CBLE"]',
    'cable_tray: [CABLETRAY, "CHEMIN DE CABLE", "CHEMIN DE CBLE", CHEMINEMENT, CDC, "CABLE ELECT", CABLE]'
)
text = text.replace(
    'earthing: [MALT, TERRE, EARTH]',
    'earthing: [MALT, TERRE, EARTH, "RESEAU DE TERRE"]'
)
text = text.replace(
    'conduit: [FOURREAU, BUSE]',
    'conduit: [FOURREAU, BUSE, CONDUIT]'
)
text = text.replace(
    'pull_box_block_patterns: [CHAMBRE, PULL, REGARD]',
    'pull_box_block_patterns: [CHAMBRE, PULL, REGARD, ROGARD, "ROGARD TECH"]'
)

with open('project_config.yaml', 'w', encoding='utf-8') as f:
    f.write(text)

print('Updated project_config.yaml successfully')
