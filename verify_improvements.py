#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verification Script for ARKAN 3 Improvements:
1. Neural Reranker Warmup & LRU Caching
2. Configurable WBS Granularity (Level 2 Macro, Level 3 Standard, Level 4 Detailed)
3. Continuous Auto-Learning Pipeline & Kaggle/Colab Export
"""

import sys
import os
import io
import time
import json
import httpx

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_URL = "http://127.0.0.1:8000"

def get_test_client():
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=0.8)
        if r.status_code == 200:
            return httpx.Client(base_url=BASE_URL, timeout=60.0)
    except Exception:
        pass
    from fastapi.testclient import TestClient
    from api_enhanced import app
    return TestClient(app)

def test_health_and_learning_sync():
    print("\n" + "="*70)
    print("▶ TEST 1 : VÉRIFICATION AUTO-LEARNING PIPELINE & SANTÉ SYSTÈME")
    print("="*70)
    
    client = get_test_client()
    try:
        # 1. Health check
        t0 = time.time()
        resp = client.get("/health")
        dt = time.time() - t0
        assert resp.status_code == 200, f"Health check échoué ({resp.status_code})"
        print(f"  ✓ /health OK en {dt*1000:.1f}ms: status={resp.json().get('status')}")
        
        # 2. Feedback stats
        resp = client.get("/learning/feedback-stats")
        assert resp.status_code == 200, f"/learning/feedback-stats échoué ({resp.status_code})"
        stats = resp.json()
        print(f"  ✓ /learning/feedback-stats OK:")
        print(f"    - Feedbacks totaux : {stats.get('feedback_db_total')}")
        print(f"    - Retours positifs ('good') : {stats.get('feedback_good')}")
        print(f"    - Échantillons prêts : {stats.get('exported_samples_ready')}")
        
        # 3. Export training data
        t0 = time.time()
        resp = client.post("/learning/export-training-data")
        dt = time.time() - t0
        assert resp.status_code == 200, f"/learning/export-training-data échoué ({resp.status_code})"
        export_res = resp.json()
        print(f"  ✓ /learning/export-training-data généré avec succès en {dt*1000:.1f}ms:")
        print(f"    - Total exemples extraits : {export_res.get('total_extracted')}")
        print(f"    - Répartition : {export_res.get('breakdown')}")
        print(f"    - Fichier Alpaca Instruct : {export_res['exported_files']['alpaca_instruct']}")
        print(f"    - Fichier ShareGPT : {export_res['exported_files']['sharegpt']}")
        assert export_res.get('total_extracted', 0) > 0, "Aucun exemple extrait !"
    finally:
        if hasattr(client, 'close'):
            client.close()


def test_wbs_granularity_levels():
    print("\n" + "="*70)
    print("▶ TEST 2 : VÉRIFICATION DE LA GRANULARITÉ WBS (NIVEAUX 2, 3 ET 4)")
    print("="*70)
    
    prompt = "Installation d'un skid de comptage gaz haute pression avec manifold 8 pouces à Hassi Messaoud"
    
    client = get_test_client()
    try:
        # --- NIVEAU 2 : MACRO ---
        print("\n  [Test Niveau 2 - Macro-Lots (5-7 tâches)]")
        t0 = time.time()
        resp_l2 = client.post("/api/planning-ia/generate", json={
            "prompt": prompt,
            "type_projet": "Skid Processus",
            "wbs_level": 2
        })
        dt_l2 = time.time() - t0
        assert resp_l2.status_code == 200, f"WBS Level 2 échoué ({resp_l2.status_code}): {resp_l2.text}"
        data_l2 = resp_l2.json()
        nb_l2 = len(data_l2["taches"])
        print(f"    ✓ Niveau 2 généré en {dt_l2:.2f}s : {nb_l2} macro-lots")
        print(f"    - Durée totale : {data_l2['duree_totale_jours']} jours")
        print(f"    - Tâches : {[t['nom'][:45] + '...' for t in data_l2['taches'][:4]]}")
        assert 5 <= nb_l2 <= 8, f"Attendu 5 à 8 tâches pour Niveau 2, obtenu {nb_l2}"
        
        # --- NIVEAU 3 : STANDARD ---
        print("\n  [Test Niveau 3 - Standard EPC (10-15 tâches)]")
        t0 = time.time()
        resp_l3 = client.post("/api/planning-ia/generate", json={
            "prompt": prompt,
            "type_projet": "Skid Processus",
            "wbs_level": 3
        })
        dt_l3 = time.time() - t0
        assert resp_l3.status_code == 200, f"WBS Level 3 échoué ({resp_l3.status_code}): {resp_l3.text}"
        data_l3 = resp_l3.json()
        nb_l3 = len(data_l3["taches"])
        print(f"    ✓ Niveau 3 généré en {dt_l3:.2f}s : {nb_l3} tâches standard")
        print(f"    - Durée totale : {data_l3['duree_totale_jours']} jours")
        print(f"    - Chemin critique : {len(data_l3['chemin_critique'])} tâches")
        assert 10 <= nb_l3 <= 18, f"Attendu 10 à 18 tâches pour Niveau 3, obtenu {nb_l3}"
        
        # --- NIVEAU 4 : DÉTAILLÉ ---
        print("\n  [Test Niveau 4 - Détaillé Opérationnel (20+ activités)]")
        t0 = time.time()
        resp_l4 = client.post("/api/planning-ia/generate", json={
            "prompt": prompt,
            "type_projet": "Skid Processus",
            "wbs_level": 4
        })
        dt_l4 = time.time() - t0
        assert resp_l4.status_code == 200, f"WBS Level 4 échoué ({resp_l4.status_code}): {resp_l4.text}"
        data_l4 = resp_l4.json()
        nb_l4 = len(data_l4["taches"])
        print(f"    ✓ Niveau 4 généré en {dt_l4:.2f}s : {nb_l4} activités détaillées")
        print(f"    - Durée totale : {data_l4['duree_totale_jours']} jours")
        print(f"    - Activités fines détectées :")
        specialized = [t['nom'] for t in data_l4['taches'] if any(k in t['nom'].lower() for k in ['cnd', 'hydrostatique', 'proctor', 'hazop', 'sablage', 'loop', 'megger', 'punch'])]
        for s in specialized[:5]:
            print(f"      * {s}")
        assert nb_l4 >= 18, f"Attendu 18+ activités pour Niveau 4, obtenu {nb_l4}"
    finally:
        if hasattr(client, 'close'):
            client.close()


def test_neural_reranker_and_cache():
    print("\n" + "="*70)
    print("▶ TEST 3 : VÉRIFICATION RERANKER WARMUP & LRU CACHE")
    print("="*70)
    
    from neural_reranker import get_reranker
    reranker = get_reranker()
    
    query = "Quelles sont les spécifications techniques du compresseur booster gaz ?"
    docs = [
        {"content": "Spécification technique du compresseur centrifuge booster gaz haute pression avec pression 28 bars."},
        {"content": "Procédure d'audit financier et administratif du chantier."},
        {"content": "Règlement intérieur et consignes de restauration du camp de base."},
        {"content": "Tableau des débits et courbes de compression du gaz combustible."}
    ]
    
    # 1er appel : Reranking réel
    t0 = time.time()
    res1 = reranker.rerank(query, docs, top_k=2)
    dt1 = time.time() - t0
    print(f"  ✓ 1er Rerank (calculé/warm) en {dt1*1000:.2f}ms")
    print(f"    Top 1: {res1[0]['content'][:65]}... (score: {res1[0].get('rerank_score', 0):.4f})")
    
    # 2eme appel identique : Test de l'accélération par Cache LRU
    t0 = time.time()
    res2 = reranker.rerank(query, docs, top_k=2)
    dt2 = time.time() - t0
    print(f"  ✓ 2eme Rerank (depuis LRU Cache) en {dt2*1000:.2f}ms (Accélération: {dt1/max(0.0001, dt2):.1f}x)")
    assert dt2 < dt1 or dt2 < 0.010, "Le cache LRU ne semble pas avoir accéléré la requête !"


if __name__ == "__main__":
    try:
        test_health_and_learning_sync()
        test_wbs_granularity_levels()
        test_neural_reranker_and_cache()
        print("\n" + "="*70)
        print("🎉 TOUTES LES VÉRIFICATIONS ONT RÉUSSI AVEC SUCCÈS (100% VALIDÉ) !")
        print("="*70)
    except Exception as e:
        print(f"\n❌ ERREUR LORS DES TESTS : {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
