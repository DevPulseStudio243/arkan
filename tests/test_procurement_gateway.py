# -*- coding: utf-8 -*-
"""
tests/test_procurement_gateway.py
Vérifie la passerelle MTO vers Achats / Procurement :
  - Injection des articles validés dans un contrat de fourniture (BoQ)
  - Prise en compte de la marge d'approvisionnement (Quantité à commander)
  - Comparaison théorique plan vs contractuel / réceptions
"""

import os
import sys
sys.path.insert(0, os.path.abspath('.'))
import procurement_db
from routes.procurement_router import inject_mto_to_procurement, compare_mto_with_procurement, MtoInjectionRequest

def test_procurement_gateway():
    procurement_db.init_procurement_db()

    # Création d'un contrat de test
    import time
    ctr_num = f"CTR-TEST-ELEC-{int(time.time())}"
    contract_id = procurement_db.create_contract(
        numero_contrat=ctr_num,
        fournisseur="ELSEWEDY ELECTRIC ALGERIE",
        objet="Fourniture de Câbles de Puissance et Mise à la Terre",
        date_signature="2026-01-15",
        date_debut="2026-02-01",
        date_fin_prevue="2026-12-31",
        montant=15000000.0,
        devise="DZD",
        statut="signé",
        project_id="C3421-ROK1-SP1-OK1"
    )
    assert contract_id, "Échec création contrat de test."

    # Injection d'articles MTO avec quantités nettes et commandées (marge 8%)
    mto_items = [
        {
            "tag": "C-300-P-101A",
            "description": "CÂBLE CU/XLPE/PVC 3X120+70 mm²",
            "quantity_net": 100.0,
            "quantity_ordered": 108.0, # 8% marge
            "unit": "m",
            "unit_price": 4500.0,
            "source_drawing": "DW-300010.dwg"
        },
        {
            "tag": "CUIVRE-NU-50",
            "description": "Câble cuivre nu 50 mm² pour terre",
            "quantity_net": 200.0,
            "quantity_ordered": 220.0, # 10% marge
            "unit": "m",
            "unit_price": 1200.0,
            "source_drawing": "ELE-DW-300001.dwg"
        }
    ]

    req = MtoInjectionRequest(
        contract_id=contract_id,
        items=mto_items,
        source_project="C3421-ROK1-SP1-OK1"
    )

    res_inject = inject_mto_to_procurement(req)
    assert res_inject["status"] == "success"
    assert res_inject["injected_count"] == 2, f"Attendu 2 articles injectés, obtenu {res_inject['injected_count']}"

    # Vérification dans procurement_db
    items = procurement_db.get_contract_items(contract_id)
    assert len(items) >= 2, "Les articles doivent figurer dans le contrat."
    item_cable = [it for it in items if "3X120" in it["designation"]][0]
    assert float(item_cable["quantite_contractuelle"]) == 108.0, "La quantité injectée doit être la quantité à commander avec marge (108.0 m)."

    # Comparaison MTO vs Achats
    res_comp = compare_mto_with_procurement(project_id="C3421-ROK1-SP1-OK1")
    assert res_comp["status"] == "success"
    assert res_comp["total_items_compared"] >= 2

    print("TEST TEST_PROCUREMENT_GATEWAY RÉUSSI AVEC SUCCÈS !")

if __name__ == "__main__":
    test_procurement_gateway()
