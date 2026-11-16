"""
Agent Logique 4 : Livrable & Reporting Final
Génère le livrable exploitable (Rapport d'ingénierie Markdown, Fiche Line List, MTO, Synthèse).
"""
from typing import Dict, Any, List

class DeliverableReporterAgent:
    """Génère les rapports et exports d'ingénierie pour le client ou le dossier ARH/EPC."""

    def generate_final_report(self, aggregated_data: Dict[str, Any], cross_val_data: Dict[str, Any], line_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        meta = aggregated_data.get("metadata", {})
        disc = aggregated_data.get("classification", {}).get("discipline", "pid").upper()
        eq_count = len(aggregated_data.get("equipment_and_valves", []))
        line_count = len(line_list)

        # Rapport Markdown
        md = []
        md.append(f"# 📋 RAPPORT D'AUDIT TECHNIQUE MULTI-AGENTS — PLAN {meta.get('document_number', 'SANS NUMERO')}")
        md.append(f"**Discipline Détectée :** `{disc}` | **Indice Révision :** `{meta.get('revision', '0')}` | **Client :** `{meta.get('client', 'SONATRACH')}`\n")

        md.append("## 1. Synthèse Globale des Éléments Détectés")
        md.append(f"- **Équipements & Vannes identifiés :** {eq_count}")
        md.append(f"- **Lignes de procédé tracées :** {line_count}")
        md.append(f"- **Statut Validation Croisée Inter-Disciplines :** {cross_val_data.get('status', 'OK')} (Score: {cross_val_data.get('cross_validation_score', 100)}%)\n")

        if line_list:
            md.append("## 2. Extrait de la Line List (Topologie de Tuyauterie)")
            md.append("| Ligne | Diamètre | Fluide | Classe Spec | Origine (From) | Destination (To) | Code |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for l in line_list[:10]:
                md.append(f"| `{l['line_number']}` | {l['nominal_diameter']} | {l['service_code']} | {l['piping_spec']} | {l['from_equipment']} | {l['to_equipment']} | {l['governing_code']} |")
            md.append("")

        # Quantitatifs Génie Civil / Charpente
        civ = aggregated_data.get("civil_foundations_mto", {})
        if civ.get("total_beton_m3"):
            md.append("## 3. Quantitatifs Génie Civil & Fondations (MTO)")
            md.append(f"- **Volume Béton Armé Total :** `{civ.get('total_beton_m3')} m³`")
            md.append(f"- **Surface Coffrage Banché :** `{civ.get('total_coffrage_m2')} m²`")
            md.append(f"- **Poids Ferraillage Estimé :** `{civ.get('total_acier_kg')} kg` (Norme ACI 318 / Eurocode 2)\n")

        # Quantitatifs Charpente Métallique
        stl = aggregated_data.get("structural_mto", {})
        if stl.get("total_steel_weight_kg"):
            md.append("## 4. Quantitatifs Charpente Métallique (MTO)")
            md.append(f"- **Poids Total Acier de Structure :** `{stl.get('total_steel_weight_kg')} kg` (Eurocode 3 / EN 10365)\n")

        md.append("## 5. Validation Croisée Inter-Disciplines (Cross-Check)")
        for c in cross_val_data.get("verified_concordances", [])[:5]:
            md.append(f"- [x] **{c['check_type']}** : {c['detail']}")

        markdown_report = "\n".join(md)

        return {
            "document_number": meta.get("document_number"),
            "discipline": disc,
            "markdown_report": markdown_report,
            "line_list_count": line_count,
            "equipment_count": eq_count,
            "export_ready_csv": True
        }

agent_reporter = DeliverableReporterAgent()
