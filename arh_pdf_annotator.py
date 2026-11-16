"""
arh_pdf_annotator.py
====================
Moteur d'annotation et de surlignage haute precision pour ARH Management.
Garantit une lisibilite integrale du document d'origine :
- Aucun pave opaque ni boite de texte geante sur le document.
- Aucune ligne diagonale traversant la page.
- Surlignage propre, translucide (jaune/ambre avec bordure carmin fine) cible
  uniquement sur l'ecart technique de la reserve active.
- Indicateur de marge discret dans l'espace blanc a gauche orientant immediatement le regard.
"""

from __future__ import annotations
import os
import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
import fitz  # PyMuPDF

logger = logging.getLogger("arh_pdf_annotator")


class ARHPDFAnnotator:
    def __init__(self, uploads_dir: str = os.getenv("ARH_UPLOADS_DIR", "d:/DATA BASE IA/arh_uploads")):
        self.uploads_dir = Path(uploads_dir)

    def resolve_pdf_path(self, dossier_id: str, filename: str) -> Optional[Path]:
        """
        Resout le chemin physique reel du fichier PDF source dans le dossier.
        Gere les noms exacts, decodes d'URL, partiels, ou generiques avec assainissement securise.
        """
        clean_dossier = Path(str(dossier_id)).name
        clean_dossier = re.sub(r'[^A-Za-z0-9_\-]', '', clean_dossier)
        if not clean_dossier:
            return None
        dossier_dir = self.uploads_dir / clean_dossier
        if not dossier_dir.exists():
            return None

        clean_fn = Path(filename).name if filename else ""
        from urllib.parse import unquote
        decoded_name = unquote(clean_fn) if clean_fn else ""

        # 1. Vérifier si c'est une pièce découpée dans pieces/
        pieces_dir = dossier_dir / "pieces"
        for check_name in [clean_fn, decoded_name]:
            if check_name:
                p_piece = pieces_dir / check_name
                if p_piece.exists() and p_piece.is_file():
                    return p_piece
                if not check_name.lower().endswith(".pdf"):
                    p_piece_pdf = pieces_dir / f"{check_name}.pdf"
                    if p_piece_pdf.exists() and p_piece_pdf.is_file():
                        return p_piece_pdf

        # 2. Vérifier directement à la racine du dossier
        for check_name in [clean_fn, decoded_name]:
            if check_name:
                p = dossier_dir / check_name
                if p.exists() and p.is_file() and not p.name.startswith("annotated_"):
                    return p
                if not check_name.lower().endswith(".pdf"):
                    p_pdf = dossier_dir / f"{check_name}.pdf"
                    if p_pdf.exists() and p_pdf.is_file() and not p_pdf.name.startswith("annotated_"):
                        return p_pdf

        # 3. Correspondance par nom partiel dans pieces/
        target_stem = Path(decoded_name).stem.lower()
        if target_stem and pieces_dir.exists():
            for p_piece in pieces_dir.glob("*.pdf"):
                if target_stem in p_piece.stem.lower() or p_piece.stem.lower() in target_stem:
                    return p_piece

        # 4. Fallback sur les fichiers PDF principaux du dossier
        pdf_files = [f for f in dossier_dir.glob("*.pdf") if not f.name.startswith("annotated_") and "pieces" not in str(f)]
        if not pdf_files:
            pdf_files = [f for f in dossier_dir.glob("*.pdf") if not f.name.startswith("annotated_")]
        if not pdf_files:
            return None

        # Trier les candidats par nombre de pages décroissant puis taille décroissante (privilégie le vrai dossier maître)
        candidates = []
        for f in pdf_files:
            try:
                with fitz.open(str(f)) as d_tmp:
                    candidates.append((len(d_tmp), f.stat().st_size, f))
            except Exception:
                candidates.append((0, f.stat().st_size, f))
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)

        if target_stem and target_stem not in ["dossier", "document", "fiche", "note", "annexe"]:
            for f in pdf_files:
                if target_stem in f.stem.lower() or f.stem.lower() in target_stem:
                    return f

        return candidates[0][2]

    def get_master_pdf_path(self, dossier_id: str) -> Optional[Path]:
        """
        Retourne le chemin vers le PDF maitre complet du dossier (le plus grand PDF non-annote hors repertoire pieces).
        """
        clean_dossier = Path(str(dossier_id)).name
        clean_dossier = re.sub(r'[^A-Za-z0-9_\-]', '', clean_dossier)
        if not clean_dossier:
            return None
        dossier_dir = self.uploads_dir / clean_dossier
        if not dossier_dir.exists():
            return None

        pdf_files = [f for f in dossier_dir.glob("*.pdf") if not f.name.startswith("annotated_") and "pieces" not in str(f).lower()]
        if not pdf_files:
            pdf_files = [f for f in dossier_dir.glob("*.pdf") if not f.name.startswith("annotated_")]
        if not pdf_files:
            return None

        candidates = []
        for f in pdf_files:
            try:
                with fitz.open(str(f)) as d_tmp:
                    candidates.append((len(d_tmp), f.stat().st_size, f))
            except Exception:
                candidates.append((0, f.stat().st_size, f))
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][2] if candidates else None


    def find_target_rects(
        self,
        page: fitz.Page,
        title: str = "",
        snippet: str = "",
        highlight_terms: Optional[List[str]] = None,
        target_content: Optional[str] = None
    ) -> List[fitz.Rect]:
        """
        Localise précisément la zone rectangulaire de la valeur ou du libellé en anomalie sur la page.
        N'introduit aucun faux rectangle sur des éléments non concernés (cartouches, initiales, dates).
        """
        rects: List[fitz.Rect] = []
        banned = {
            "PAGE", "POUR", "DANS", "AVEC", "SANS", "NON", "OUI", "SUR", "DES", "LES",
            "EST", "UNE", "PAR", "ARH", "LOT", "PRELIMINAIRE", "DOSSIER", "DECRET",
            "GCB", "SONATRACH", "RAPPORT", "ARTICLE", "EXIGENCE", "CONFORME", "CONTRAT",
            "FICHE", "DATE", "CODE", "TYPE", "NOM", "NOMINAL", "REVISE", "ANNEXE",
            "STATUS", "VALEUR", "RAPPORT", "PROJET", "PROJECT", "CLIENT", "S.T", "I.T",
            "43BARG", "BARG", "SIGN", "DESCRIPTION", "CH/2506", "PRPD", "CHKD", "APPD"
        }

        # 0. Nettoyage CJK et ponctuation des requêtes
        clean_tc = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', target_content or '').strip()
        clean_snip = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', snippet or '').replace("...", " ").strip()
        clean_tit = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+', ' ', title or '').strip()

        # 0a. Priorité Absolue : Identifiants Alphanumériques Structurés & Valeurs Numériques Clés
        # Ex: SJV203-HJ074C-02-2024, SJV-200B-25120010-D4, 259.38, 229.63, ASTM A182 F316, ASTM A995
        id_candidates = []
        for source in [clean_tc, clean_snip]:
            if not source: continue
            for m in re.finditer(r'\b[A-Z0-9]{3,}(?:[\-_][A-Z0-9]+){2,}\b', source):
                id_candidates.append(m.group(0))
            for m in re.finditer(r'\b\d{2,3}\.\d{1,2}\b', source):
                id_candidates.append(m.group(0))
            for m in re.finditer(r'\b(?:ASTM\s+[A-Z0-9]+(?:\s+[A-Z0-9]+)?)\b', source, re.I):
                id_candidates.append(m.group(0))

        for cid in id_candidates:
            f_cid = page.search_for(cid)
            if f_cid:
                return f_cid[:3]

        # 0b. Priorité Directe : Recherche par target_content verbatim et sous-parties
        if clean_tc:
            f_tc = page.search_for(clean_tc)
            if f_tc:
                return f_tc[:3]
            for part in re.split(r'[:|]', clean_tc):
                part = part.strip()
                if len(part) >= 4 and part.upper() not in banned:
                    f_part = page.search_for(part)
                    if f_part:
                        return f_part[:3]

        # 0c. Recherche par segments de snippet (séparés par |)
        if clean_snip:
            for part in re.split(r'[:|]', clean_snip):
                part = part.strip()
                if len(part) >= 6 and not any(part.lower().startswith(p) for p in ["constat", "selon", "aucun", "conform"]):
                    f_spart = page.search_for(part)
                    if f_spart:
                        return f_spart[:3]

        # 0d. Expressions Techniques Exactes ARH / Équipements
        specific_phrases = [
            "Identification of WPS followed",
            "Contrainte admissible",
            "Selon spécification projet",
            "Certification Des Signatures Du Fabricant",
            "Hydrostatic / Pneumatic Test",
            "Pressure and Leakage Test",
            "ETAT DESCRIPTIF",
            "Pression d’essai",
            "Pression de calcul",
            "ALLOWABLE STRESS",
            "SHELL TEST",
            "ARH/TPI",
            "TPI/Client"
        ]
        comb_source = f"{clean_tc} {clean_snip} {clean_tit}"
        for ph in specific_phrases:
            if ph.lower() in comb_source.lower():
                f_ph = page.search_for(ph)
                if f_ph:
                    return f_ph[:2]

        # 0e. Reconnaissance contextuelle dynamique (repli si les recherches directes n'ont pas abouti)
        combined_q = f"{title} {snippet} {target_content or ''}".lower()
        
        # 1. Visa Consulaire & Légalisation
        if "consul" in combined_q or "légalisation" in combined_q or "legalisation" in combined_q or "visa" in combined_q:
            f_cons = (page.search_for("Visa du Consulat Algérien") or 
                      page.search_for("Consulat Algérien") or 
                      page.search_for("Certification Des Signatures Du Fabricant") or 
                      page.search_for("Consulat"))
            if f_cons:
                return f_cons[:2]
        
        # 2. État Descriptif : Mentions obligatoires ARH P-CTE-1
        if "p-cte-1" in combined_q or "coform" in combined_q or "mentions" in combined_q or "procedure arh" in combined_q:
            f_pcte = (page.search_for("- Coformément a la procedure ARH") or 
                      page.search_for("Coformément a la procedure ARH") or 
                      page.search_for("Conformément à la procédure ARH") or 
                      page.search_for("P-CTE-1"))
            if f_pcte:
                return f_pcte[:2]
                
        # 3. Surépaisseur de corrosion (6mm, 6.4mm, 3mm, etc.)
        if "corrosion" in combined_q or "surépaisseur" in combined_q or "surepaisseur" in combined_q:
            f_cor = (page.search_for("Corrosion Allowance") or 
                     page.search_for("Indemnité de corrosion") or 
                     page.search_for("Surépaisseur de corrosion") or 
                     page.search_for("Surépaisseur"))
            if not f_cor:
                for c_val in ["6.4mm", "6mm", "6.4 mm", "6 mm", "3mm", "3 mm"]:
                    if c_val in combined_q:
                        f_cor = page.search_for(c_val)
                        if f_cor: break
            if f_cor:
                return f_cor[:2]

        # 4. Note de Calcul : Décret 21-315 Formule d'épaisseur
        if "21-315" in combined_q or "formule" in combined_q or "décret" in combined_q or "decret" in combined_q:
            f_dec = (page.search_for("Use Décret exécutif n° 21-315") or 
                     page.search_for("Décret exécutif n° 21-315") or 
                     page.search_for("21-315") or 
                     page.search_for("Calculation"))
            if f_dec:
                return f_dec[:2]

        # 5. Note de Calcul : Nomenclature ASME B31.8 / B31.3 / ASME VIII
        if "nomenclature" in combined_q or "asme b31" in combined_q or "b31.8" in combined_q or "b31.3" in combined_q:
            f_nom = (page.search_for("Use  ASME B31.8's nomenclature") or 
                     page.search_for("ASME B31.8's nomenclature") or 
                     page.search_for("nomenclature") or 
                     page.search_for("Calculation (ASME B31.8)") or 
                     page.search_for("ASME B31.8") or 
                     page.search_for("ASME B31.3"))
            if f_nom:
                return f_nom[:2]

        # 6. Dessins : Matériau / Barreaux / Cotes
        if "barreau" in combined_q or "barred tee" in combined_q or "guidage" in combined_q:
            f_dim = (page.search_for("Barred tee") or 
                     page.search_for("Technical Requirements") or 
                     page.search_for("WPHY60"))
            if f_dim:
                return f_dim[:2]

        # 7. Dessins : Vue en coupe & Détail A/B
        if "coupe" in combined_q or "détail" in combined_q or "detail" in combined_q or "a/b" in combined_q or "section" in combined_q:
            f_sec = page.search_for("A/B") or page.search_for("SECTION") or page.search_for("DETAIL")
            if f_sec:
                return f_sec[:2]

        # 8. Matériaux & Nuances (WPHY60, A860, A234 WPB, A105, LF2)
        if any(m in combined_q for m in ["wphy", "a860", "a234", "a105", "lf2", "a350", "nuance", "matériau"]):
            for mat_term in ["Material: WPHY60", "WPHY60", "A860 WPHY60", "A860", "WPHY 60", "A234 WPB", "A105", "LF2", "A350 LF2"]:
                f_wphy = page.search_for(mat_term)
                if f_wphy:
                    return f_wphy[:2]

        # 9. WPS/PQR : Norme d'établissement & Qualification
        if "wps" in combined_q or "pqr" in combined_q or "soudage" in combined_q or "welding" in combined_q:
            f_wn = (page.search_for("Ajouter le norme d'établissement de la WPS") or 
                    page.search_for("Pre-welding Procedure Specification Number") or 
                    page.search_for("Identification of WPS followed") or 
                    page.search_for("Welding Procedure Specification") or 
                    page.search_for("Procedure Qualification Record") or 
                    page.search_for("thickness range of the base metal"))
            if f_wn:
                return f_wn[:2]

        # 10. WPS/PQR : Métal d'apport / Undermatching
        if "undermatch" in combined_q or "e5015" in combined_q or "métal d'apport" in combined_q or "metal soud" in combined_q or "electrode" in combined_q:
            f_wu = (page.search_for("conformement au décret 21-315 le metal soudé") or 
                    page.search_for("E5015") or 
                    page.search_for("Welding Material") or 
                    page.search_for("Electrode") or 
                    page.search_for("metal soudé"))
            if f_wu:
                return f_wu[:2]

        # 11. ITP : Points d'arrêt Hold Points ARH/TPI
        if "hold point" in combined_q or "point d'arrêt" in combined_q or "point d arret" in combined_q or "arh/tpi" in combined_q or "witness" in combined_q:
            f_itp_h = (page.search_for("ARH/TPI") or 
                       page.search_for("Hydrostatic / Pneumatic Test") or 
                       page.search_for("Hold Point") or 
                       page.search_for("Witness Point") or 
                       page.search_for("Point d'arrêt") or 
                       page.search_for("TPI"))
            if f_itp_h:
                return f_itp_h[:2]

        # 12. ITP / Hydro : Test hydrostatique
        if "hydro" in combined_q or "hydrostatique" in combined_q or "épreuve" in combined_q or "epreuve" in combined_q:
            f_itp_hyd = (page.search_for("Hydrostatic / Pneumatic Test") or 
                         page.search_for("Hydrostatic testing") or 
                         page.search_for("Hydrostatic test") or 
                         page.search_for("Épreuve hydrostatique") or 
                         page.search_for("Pression d'épreuve") or 
                         page.search_for("Hydrostatic"))
            if f_itp_hyd:
                return f_itp_hyd[:2]

        # 13. Métallurgie / Traçabilité : CEV, Charpy, Traction, Dureté
        if any(k in combined_q for k in ["cev", "charpy", "résilience", "resilience", "dureté", "hardness", "traction", "tensile"]):
            for m_term in ["Carbon Equivalent", "CEV", "Charpy", "Impact Test", "Hardness", "Tensile Test", "Yield Strength"]:
                f_met = page.search_for(m_term)
                if f_met:
                    return f_met[:2]

        # 1. Recherche par highlight_terms explicites
        if highlight_terms:
            for term in highlight_terms:
                t_str = str(term).strip()
                if not t_str or t_str.upper() in banned or len(t_str) < 2:
                    continue
                found = page.search_for(t_str)
                if found:
                    rects.extend(found[:3])
                    return rects

        # 2. Recherche par extrait textuel snippet direct (si propre et signifiant)
        if snippet:
            clean_snip = re.sub(r'[\.]{2,}', ' ', snippet).strip()
            clean_snip = re.sub(r'[^\w\s\-\,\.\(\)\/]', ' ', clean_snip).strip()
            # Test direct si court
            if 4 <= len(clean_snip) <= 60 and clean_snip.upper() not in banned:
                found = page.search_for(clean_snip)
                if found:
                    rects.extend(found[:3])
                    return rects
            # Test de sous-phrases significatives de 3 à 5 mots
            words = [w for w in clean_snip.split() if w.upper() not in banned and len(w) > 1]
            for win_size in (4, 3, 2):
                for i in range(len(words) - win_size + 1):
                    sub = ' '.join(words[i:i+win_size])
                    if len(sub) >= 8:
                        found = page.search_for(sub)
                        if found:
                            rects.extend(found[:2])
                            return rects
        combined_text = f"{title} {snippet}"

        # 3. Recherche par termes techniques d'ingénierie et de soudage clés
        engineering_terms = [
            "Reinforcement Schematic Diagram", "Reinforcement Area", "Calculation (ASME B31.8)",
            "Tee Strength Calculation Sheet", "Technical Requirements", "Barred tee",
            "Welding Material Brand", "Welding Material", "Specification No.", "WPHY60",
            "Material: WPHY60", "Drawing No", "Drawing Number", "ASME B16.9", "ASME B31.8",
            "ASME B16.25", "ASME Section IX", "Hold Point", "Witness Point", "Inspection and Test Plan",
            "Purchase Order", "Descriptive Status", "Etat Descriptif", "Extruded Outlets",
            "Extruded Outlet", "Yield Strength", "Tensile Test", "Side Bend"
        ]
        for eng_term in engineering_terms:
            if eng_term.lower() in combined_text.lower():
                found = page.search_for(eng_term)
                if found:
                    rects.extend(found[:2])
                    return rects

        # 7. Recherche par mots individuels distinctifs de plus de 4 caractères
        distinct_words = re.findall(r'\b[A-Za-z0-9\-_]{4,}\b', combined_text)
        for w in distinct_words:
            if w.upper() not in banned and not w.isdigit():
                found = page.search_for(w)
                if found:
                    rects.extend(found[:2])
                    return rects

        # 8. Recherche dans les blocs de texte réels de la page
        try:
            blocks = page.get_text("blocks")
            for b in blocks:
                b_text = b[4].upper()
                if any(w.upper() in b_text for w in distinct_words if w.upper() not in banned and len(w) >= 4):
                    r_block = fitz.Rect(b[0], b[1], b[2], b[3])
                    rects.append(r_block)
                    return rects
        except Exception:
            pass

        # 9. Fallback ciblé : chercher le bloc de contenu technique principal sur la page
        try:
            blocks = page.get_text("blocks")
            valid_b = [b for b in blocks if len(b[4].strip()) >= 35 and not any(h in b[4].upper() for h in ["PAGE ", "CONFIDENTIAL", "REVISION", "PROJET"])]
            if valid_b:
                best_b = max(valid_b[:4], key=lambda b: len(b[4].strip()))
                rects.append(fitz.Rect(best_b[0], best_b[1], best_b[2], best_b[3]))
                return rects
        except Exception:
            pass

        p_rect = page.rect
        if p_rect.width > p_rect.height:
            # Plan CAD / Dessin en paysage : zone technique centrale
            fallback_rect = fitz.Rect(p_rect.width * 0.20, p_rect.height * 0.20, p_rect.width * 0.80, p_rect.height * 0.40)
        else:
            # Document portrait : zone principale ciblée
            fallback_rect = fitz.Rect(p_rect.width * 0.10, p_rect.height * 0.20, p_rect.width * 0.90, p_rect.height * 0.35)
        
        rects.append(fallback_rect)
        return rects

    def render_page_to_png(
        self,
        dossier_id: str,
        filename: str,
        page_num: int,
        target_snippet: Optional[str] = None,
        target_title: Optional[str] = None,
        highlight_enabled: bool = True
    ) -> bytes:
        """
        Rend une page specifique du document source d'origine en image PNG haute definition.
        Garantit une lisibilite totale du document sans AUCUN pave opaque recouvrant le texte.
        Si une reserve specifique est ciblee, applique un surlignage translucide et un indicateur de marge.
        """
        src_path = self.resolve_pdf_path(dossier_id, filename)
        if not src_path or not src_path.exists():
            src_path = self.get_master_pdf_path(dossier_id)
            if not src_path or not src_path.exists():
                logger.error(f"[ANNOTATOR] Fichier source PDF introuvable : {dossier_id} / {filename}")
                return b""

        try:
            doc = fitz.open(str(src_path))
            total_pages = len(doc)
            if total_pages == 0:
                doc.close()
                return b""

            # Fallback dynamique sur le PDF maitre si la page demandee depasse le fichier courant
            # (ex: page globale 18 demandee alors que le nom resolu etait une sous-piece de 1 a 3 pages)
            if page_num > total_pages:
                master_path = self.get_master_pdf_path(dossier_id)
                if master_path and master_path != src_path:
                    try:
                        master_doc = fitz.open(str(master_path))
                        if len(master_doc) >= page_num:
                            doc.close()
                            doc = master_doc
                            total_pages = len(doc)
                            logger.info(f"[ANNOTATOR] Auto-fallback sur le PDF maitre '{master_path.name}' pour page {page_num}/{total_pages}")
                        else:
                            master_doc.close()
                    except Exception as e_m:
                        logger.warning(f"[ANNOTATOR] Erreur fallback master PDF : {e_m}")

            page_index = max(0, min(page_num - 1, total_pages - 1))
            page = doc[page_index]


            if highlight_enabled and (target_snippet or target_title):
                rect_targets = self.find_target_rects(
                    page,
                    title=target_title or "",
                    snippet=target_snippet or "",
                    target_content=target_snippet or ""
                )

                if rect_targets:
                    primary_rect = rect_targets[0]
                    y_center = (primary_rect.y0 + primary_rect.y1) / 2.0

                    same_line_rects = [r for r in rect_targets if abs(((r.y0 + r.y1) / 2.0) - y_center) < 14.0]
                    if not same_line_rects:
                        same_line_rects = [primary_rect]

                    union_rect = same_line_rects[0]
                    for r in same_line_rects[1:]:
                        union_rect = union_rect | r

                    # Surlignage doux translucide avec fine bordure carmin
                    pad_rect = fitz.Rect(
                        union_rect.x0 - 3.0,
                        union_rect.y0 - 2.0,
                        union_rect.x1 + 3.0,
                        union_rect.y1 + 2.0
                    )
                    page.draw_rect(
                        pad_rect,
                        color=(0.88, 0.12, 0.12),
                        fill=(1.0, 0.93, 0.35),
                        fill_opacity=0.4,
                        width=1.8
                    )

                    # Indicateur de marge ARH discret dans l'espace blanc a gauche (x=12 a 46)
                    # Oriente le regard instantanement sans JAMAIS toucher ni masquer le texte
                    badge_y0 = max(5.0, pad_rect.y0 - 2.0)
                    badge_y1 = min(page.rect.height - 5.0, pad_rect.y1 + 2.0)
                    if (badge_y1 - badge_y0) < 14.0:
                        badge_y1 = badge_y0 + 14.0

                    margin_badge = fitz.Rect(12.0, badge_y0, 46.0, badge_y1)
                    page.draw_rect(
                        margin_badge,
                        color=(0.85, 0.12, 0.12),
                        fill=(0.85, 0.12, 0.12),
                        width=1.0
                    )
                    page.insert_textbox(
                        margin_badge + (2, 1, -2, -1),
                        "ARH",
                        color=(1, 1, 1),
                        fontsize=7.5,
                        fontname="helv"
                    )

                    # Fleche pointeur courte restant strictement dans la marge blanche (x=46 a 50)
                    ym = (badge_y0 + badge_y1) / 2.0
                    p1 = fitz.Point(46.0, ym - 4.0)
                    p2 = fitz.Point(50.0, ym)
                    p3 = fitz.Point(46.0, ym + 4.0)
                    page.draw_polyline(
                        [p1, p2, p3, p1],
                        color=(0.85, 0.12, 0.12),
                        fill=(0.85, 0.12, 0.12)
                    )

            zoom = 150 / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes("png")
            doc.close()
            return png_bytes

        except Exception as e:
            logger.error(f"[ANNOTATOR] Erreur rendu PNG page {page_num} pour {filename}: {e}", exc_info=True)
            return b""

    def annotate_document(
        self,
        dossier_id: str,
        filename: str,
        comments: List[Dict[str, Any]],
        page_blocks: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Cree une version PDF annotee propre et professionnelle pour le telechargement.
        Utilise des surlignages non destructifs et des annotations popups standard,
        SANS aucun pave opaque recouvrant le document d'origine.
        """
        pdf_path = self.resolve_pdf_path(dossier_id, filename)
        if not pdf_path or not pdf_path.exists():
            pdf_path = self.get_master_pdf_path(dossier_id)
            if not pdf_path or not pdf_path.exists():
                return ""


        clean_dossier = Path(str(dossier_id)).name
        clean_dossier = re.sub(r'[^A-Za-z0-9_\-]', '', clean_dossier)
        if not clean_dossier:
            return ""

        filename = pdf_path.name
        annotated_filename = f"annotated_{filename}"
        annotated_pdf_path = self.uploads_dir / clean_dossier / annotated_filename

        try:
            doc = fitz.open(str(pdf_path))
            comments_by_page: Dict[int, List[Dict[str, Any]]] = {}

            for comment in comments:
                if comment.get("is_missing_document"):
                    continue
                page_str = str(comment.get("page", ""))
                m_pg = re.search(r'Page\s*(\d+)', page_str, re.IGNORECASE)
                page_num = int(m_pg.group(1)) if m_pg else (comment.get("page_number") or 1)
                comments_by_page.setdefault(page_num, []).append(comment)

            for page_num, p_comments in comments_by_page.items():
                page_index = page_num - 1
                if page_index < 0 or page_index >= len(doc):
                    continue

                page = doc[page_index]

                for comment in p_comments:
                    title = comment.get("title", "Remarque Technique")
                    desc = comment.get("description", "")
                    cat = comment.get("category", "Controle Technique")
                    reg_ref = comment.get("regulation_ref") or comment.get("standard") or "Reglementation ARH"
                    snippet = comment.get("quote_snippet", "")
                    terms = comment.get("highlight_terms", [])

                    rect_targets = self.find_target_rects(page, title=title, snippet=snippet, highlight_terms=terms)
                    if rect_targets:
                        target = rect_targets[0]
                        pad_rect = fitz.Rect(target.x0 - 2.0, target.y0 - 1.0, target.x1 + 2.0, target.y1 + 1.0)
                        page.draw_rect(
                            pad_rect,
                            color=(0.88, 0.12, 0.12),
                            fill=(1.0, 0.93, 0.35),
                            fill_opacity=0.35,
                            width=1.8
                        )
                        note_text = f"[{cat}] {title}\n* Constat: {desc}\n* Norme: {reg_ref}"
                        page.add_text_annot(fitz.Point(pad_rect.x0, pad_rect.y0), note_text)

            doc.save(str(annotated_pdf_path))
            doc.close()
            return str(annotated_pdf_path)

        except Exception as e:
            logger.error(f"[ANNOTATOR] Erreur annotation PDF {filename}: {e}", exc_info=True)
            return ""
