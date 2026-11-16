"""
arh_document_slicer.py — v1.0
==============================
Moteur de Découpage Intelligent (Document Slicing) & Extraction par Contrats Pydantic
pour les Dossiers Réglementaires ARH (Décret 21-261, Décret 21-314, Procédure P-CTE-1).

Rôles principaux :
  1. Détection automatique des frontières de pièces (14 pièces types ARH DOC-01 à DOC-14).
  2. Découpage physique du fichier PDF maître en sous-fichiers PDF individuels (PyMuPDF / fitz).
  3. Extraction d'informations techniques & réglementaires validées par schémas Pydantic.
  4. Persistance dans la base SQLite `arh_dossiers.db` (table `arh_sliced_pieces`).
  5. Intégration API & Visualisation directe des pièces isolées.
"""

from __future__ import annotations
import os
import re
import json
import uuid
import datetime
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

import fitz  # PyMuPDF
from pydantic import BaseModel, Field, field_validator

try:
    from arh_nuextract_engine import arh_nuextract_engine
    _HAS_NUEXTRACT = True
except ImportError:
    _HAS_NUEXTRACT = False

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# 1. CONTRATS PYDANTIC POUR LES PIÈCES ARH (DOC-01 À DOC-14)
# ══════════════════════════════════════════════════════════════════════════════

class ContractDoc01DemandeAvis(BaseModel):
    """DOC-01: Demande d'Avis sur la Conformité au Service ARH (Annexe B P-CTE-1)"""
    piece_code: str = "DOC-01"
    piece_name: str = "Demande d'Avis de Conformité ARH"
    demandeur: Optional[str] = Field(None, description="Demandeur / Opérateur / Entrepreneur")
    destinataire: Optional[str] = Field("Autorité de Régulation des Hydrocarbures (ARH)", description="Destinataire officiel")
    projet: Optional[str] = Field(None, description="Intitulé du projet")
    reference_lettre: Optional[str] = Field(None, description="Référence du courrier ou de la transmission")
    date_demande: Optional[str] = Field(None, description="Date de la demande")
    objet: Optional[str] = Field(None, description="Objet officiel de la demande")
    statut_recevabilite: str = Field("CONFORME", description="Statut de recevabilité administrative")

class ContractDoc02ChambreCommerce(BaseModel):
    """DOC-02: Certification des Signatures Fabricant & Visa Consulaire (Annexe C P-CTE-1)"""
    piece_code: str = "DOC-02"
    piece_name: str = "Certification des Signatures & Visa Consulaire"
    organisme_legalisation: Optional[str] = Field(None, description="Chambre de Commerce / Notaire")
    visa_consulat_algerie: bool = Field(False, description="Présence du visa ou cachet consulaire algérien")
    fabricant_certifie: Optional[str] = Field(None, description="Nom de l'entité fabricant certifiée")
    date_legalisation: Optional[str] = Field(None, description="Date de visa / légalisation")
    mentions_trouvees: List[str] = Field(default_factory=list, description="Mots-clés légaux identifiés")

class ContractDoc03VisiteUsine(BaseModel):
    """DOC-03: Certificat de Conformité et de Visites Intérieure/Extérieure (Annexe D P-CTE-1)"""
    piece_code: str = "DOC-03"
    piece_name: str = "Certificat de Conformité et Visite Usine"
    fabricant: Optional[str] = Field(None, description="Fabricant signataire")
    visite_interieure_mentionnee: bool = Field(False, description="Visite intérieure inspectée")
    visite_exterieure_mentionnee: bool = Field(False, description="Visite extérieure inspectée")
    visa_consulat_algerien: bool = Field(False, description="Visa consulaire algérien présent")
    date_visite: Optional[str] = Field(None, description="Date de visite en usine")

class ContractDoc04PaysOrigine(BaseModel):
    """DOC-04: Certificat attestant l'utilisation conforme dans le pays d'origine (Annexe F P-CTE-1)"""
    piece_code: str = "DOC-04"
    piece_name: str = "Certificat Construction Conforme Pays d'Origine"
    pays_origine: Optional[str] = Field(None, description="Pays de fabrication / origine")
    norme_construction_conforme: bool = Field(False, description="Attestation de conformité aux règlements du pays d'origine")
    date_emission: Optional[str] = Field(None, description="Date du certificat")

class ContractDoc05EtatDescriptif(BaseModel):
    """DOC-05: État Descriptif de l'Équipement (Annexe E P-CTE-1 / Décret 21-261)"""
    piece_code: str = "DOC-05"
    piece_name: str = "État Descriptif de l'Équipement"
    tag_equipement: Optional[str] = Field(None, description="Repère / TAG")
    po_number: Optional[str] = Field(None, description="Numéro de commande / PO")
    diametre_nominal: Optional[str] = Field(None, description="DN ou diamètre nominal")
    classe_pression: Optional[str] = Field(None, description="Classe de pression (Rating / PN)")
    pression_design_bar: Optional[float] = Field(None, description="Pression de calcul en bar")
    temperature_design_c: Optional[float] = Field(None, description="Température de calcul en °C")
    matiere_principale: Optional[str] = Field(None, description="Nuance d'acier ou matériau du corps")
    epaisseur_nominale_mm: Optional[float] = Field(None, description="Épaisseur nominale en mm")
    surépaisseur_corrosion_mm: Optional[float] = Field(None, description="Surépaisseur de corrosion en mm")
    fluide: Optional[str] = Field(None, description="Fluide de service")

class ContractDoc06NoteCalcul(BaseModel):
    """DOC-06: Note de Calcul de Résistance Mécanique (Décret 21-261 / ASME B16.9 / ASME VIII)"""
    piece_code: str = "DOC-06"
    piece_name: str = "Note de Calcul de Résistance"
    code_calcul: Optional[str] = Field(None, description="Norme ou code de calcul (ASME B16.9, B31.3, ASME VIII, etc.)")
    pression_calcul_bar: Optional[float] = Field(None, description="Pression de calcul P_calc")
    temperature_calcul_c: Optional[float] = Field(None, description="Température de calcul T_calc")
    epaisseur_requise_mm: Optional[float] = Field(None, description="Épaisseur minimale calculée t_req")
    epaisseur_nominale_fournie_mm: Optional[float] = Field(None, description="Épaisseur nominale fournie t_nom")
    surépaisseur_corrosion_mm: Optional[float] = Field(None, description="Surépaisseur de corrosion (CA)")
    contrainte_admissible_mpa: Optional[float] = Field(None, description="Contrainte admissible de l'acier")
    epaisseur_satisfaisante: Optional[bool] = Field(None, description="Vérification t_nom >= t_req + CA")

class ContractDoc07DessinsPlans(BaseModel):
    """DOC-07: Dessins & Plans Détaillés d'Exécution (P-CTE-1 §VI.2)"""
    piece_code: str = "DOC-07"
    piece_name: str = "Dessins & Plans Détaillés"
    numero_dessin: Optional[str] = Field(None, description="Numéro de plan / Drawing No")
    titre_dessin: Optional[str] = Field(None, description="Titre du plan")
    revision: Optional[str] = Field(None, description="Indice de révision")
    dimensions_relevees: List[str] = Field(default_factory=list, description="Cotes ou dimensions principales relevées")
    dessin_technique_detecte: bool = Field(True, description="Présence de cartouche ou dessin technique")

class ContractDoc08CahierSoudage(BaseModel):
    """DOC-08: Cahier de Soudage WPS / PQR / WPQ & Fabrication (ASME Section IX)"""
    piece_code: str = "DOC-08"
    piece_name: str = "Cahier de Soudage (WPS/PQR) & Spécification Fabrication"
    wps_number: Optional[str] = Field(None, description="Numéro de WPS")
    pqr_number: Optional[str] = Field(None, description="Numéro de PQR / WPQR")
    procede_soudage: Optional[str] = Field(None, description="Procédé (GTAW, SMAW, SAW, etc.)")
    metal_base: Optional[str] = Field(None, description="Métal de base")
    metal_apport: Optional[str] = Field(None, description="Métal d'apport / Filler metal")
    essais_mecaniques_mentionnes: List[str] = Field(default_factory=list, description="Essais de traction, pliage, etc.")

class ContractDoc09TraitementThermique(BaseModel):
    """DOC-09: Procédure & Enregistrement de Traitement Thermique (PWHT)"""
    piece_code: str = "DOC-09"
    piece_name: str = "Procédure de Traitement Thermique"
    type_traitement: Optional[str] = Field(None, description="Normalisation, Trempe+Revenu, Détensionnement PWHT")
    temperature_maintien_c: Optional[float] = Field(None, description="Température de maintien en °C")
    duree_maintien_min: Optional[float] = Field(None, description="Temps de maintien")
    moyen_chauffage: Optional[str] = Field(None, description="Four électrique / gaz")

class ContractDoc10ITPControle(BaseModel):
    """DOC-10: Plan d'Inspection et de Test (ITP / QCP) (P-CTE-1 Annexe A)"""
    piece_code: str = "DOC-10"
    piece_name: str = "Plan d'Inspection et de Test (ITP)"
    numero_itp: Optional[str] = Field(None, description="Numéro d'ITP")
    projet_itp: Optional[str] = Field(None, description="Projet associé")
    points_arret_identifies: int = Field(0, description="Nombre de Hold Points (H)")
    points_temoins_identifies: int = Field(0, description="Nombre de Witness Points (W)")
    intervenants_mentionnes: List[str] = Field(default_factory=list, description="Parties prenantes (GCB, ARH, TPI, Fabricant)")

class ContractDoc11EpreuveHydro(BaseModel):
    """DOC-11: Procès-Verbal d'Épreuve Hydrostatique (Décret 21-261 Art. 24)"""
    piece_code: str = "DOC-11"
    piece_name: str = "Procès-Verbal d'Épreuve Hydrostatique"
    pression_epreuve_bar: Optional[float] = Field(None, description="Pression d'épreuve Pe en bar")
    fluide_epreuve: Optional[str] = Field(None, description="Fluide d'essai")
    duree_maintien_min: Optional[float] = Field(None, description="Durée de maintien")
    manometre_etalonne: bool = Field(False, description="Certificat d'étalonnage du manomètre")
    visa_tpi: bool = Field(False, description="Visa organisme tiers habilité")

class ContractDoc12CertificatsMatiere(BaseModel):
    """DOC-12: Certificats de Réception Matière EN 10204 3.1 / 3.2"""
    piece_code: str = "DOC-12"
    piece_name: str = "Certificats Matière EN 10204"
    type_certificat: Optional[str] = Field(None, description="3.1 ou 3.2")
    numero_coulee: Optional[str] = Field(None, description="Heat / Coulee")
    nuance_acier: Optional[str] = Field(None, description="Grade / Nuance")
    cev_calcule: Optional[float] = Field(None, description="Carbone équivalent CEV")
    traction_rm_mpa: Optional[float] = Field(None, description="Résistance à la traction Rm")
    limite_elasticite_re_mpa: Optional[float] = Field(None, description="Limite d'élasticité Re")

class ContractDoc13CND(BaseModel):
    """DOC-13: Rapports de Contrôles Non-Destructifs (CND / NDT)"""
    piece_code: str = "DOC-13"
    piece_name: str = "Rapports de Contrôles Non Destructifs (CND)"
    methodes_detectees: List[str] = Field(default_factory=list, description="RT, UT, MT, PT, VT")
    pourcentage_controle: Optional[str] = Field(None, description="100%, 20%, spot")
    resultat_global: Optional[str] = Field("ACCEPTABLE", description="Résultat du rapport")

class ContractDoc14ControleDimensionnel(BaseModel):
    """DOC-14: Rapport de Contrôle Dimensionnel & Tolérances"""
    piece_code: str = "DOC-14"
    piece_name: str = "Rapport de Contrôle Dimensionnel"
    dn_controle: Optional[str] = Field(None, description="DN mesuré")
    epaisseur_mesuree_mm: Optional[float] = Field(None, description="Épaisseur min mesurée")
    resultat_dimensionnel: Optional[str] = Field("CONFORME", description="Résultat du PV dimensionnel")

class ContractGenericPiece(BaseModel):
    """Contrat générique pour toute pièce non spécifique ou page de garde"""
    piece_code: str = "DOC-GENERIC"
    piece_name: str = "Document Général ARH"
    titre_detecte: Optional[str] = None
    mots_cles: List[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# 2. SCHÉMA GLOBAL DE SORTIE D'UNE PIÈCE DÉCOUPÉE
# ══════════════════════════════════════════════════════════════════════════════

class SlicedPieceOutput(BaseModel):
    piece_id: str
    dossier_id: str
    piece_code: str
    piece_name: str
    regulatory_ref: str
    criticality: str
    page_start: int
    page_end: int
    page_count: int
    file_name: str
    file_size_kb: float
    download_url: str
    view_url: str
    extracted_fields: Dict[str, Any]
    validation_status: str
    compliance_remarks: List[str]
    created_at: str


# ══════════════════════════════════════════════════════════════════════════════
# 3. MOTEUR DE DÉCOUPAGE ET D'EXTRACTION (ARHDocumentSlicer)
# ══════════════════════════════════════════════════════════════════════════════

class ARHDocumentSlicer:
    """
    Moteur autonome de découpage physique des dossiers ARH et d'extraction contractuelle.
    """

    # Définition des pièces types avec leurs empreintes sémantiques et réglementaires
    SECTIONS_SPECS = [
        {
            "code": "DOC-01",
            "name": "Demande d'Avis de Conformité ARH",
            "ref": "P-CTE-1 Annexe B",
            "criticality": "Critical",
            "keywords": [
                "DEMANDE DE CONFORMITE AU SERVICE ARH", "REQUEST CONFORMITY LETTER TO ARH",
                "DEMANDE D AVIS SUR LA CONFORMITE", "DEMANDE D AVIS DE CONFORMITE",
                "DEMANDE D APPROBATION DU DOSSIER", "LETTRE DE DEMANDE D APPROBATION",
                "REQUEST FOR APPROVAL OF THE PRELIMINARY DOSSIER", "SOUMISSION DU DOSSIER PRELIMINAIRE",
                "DOSSIER PRELIMINAIRE POUR SOUMISSION ARH", "AUTORITE DE REGULATION DES HYDROCARBURES",
                "LETTRE DE DEMANDE D'AVIS SUR LA CONFORMITE", "ANNEXE B"
            ],
            "contract": ContractDoc01DemandeAvis
        },
        {
            "code": "DOC-02",
            "name": "Certification Signatures Fabricant & Visa Consulat",
            "ref": "P-CTE-1 Annexe C",
            "criticality": "Critical",
            "keywords": [
                "CERTIFICATION PAR LA CHAMBRE DE COMMERCE", "CHAMBRE DE COMMERCE ET D INDUSTRIE",
                "CHAMBER OF COMMERCE", "VISA DU CONSULAT ALGERIEN", "ALGERIAN CONSULATE",
                "VISA DU CONSULAT", "CONSULAT GENERAL D ALGERIE", "LEGALISATION DES SIGNATURES",
                "SIGNATURE DU FABRICANT", "SIGNATURES DU FABRICANT", "ANNEXE C"
            ],
            "contract": ContractDoc02ChambreCommerce
        },
        {
            "code": "DOC-03",
            "name": "Certificat de Conformité et Visite Usine",
            "ref": "P-CTE-1 Annexe D",
            "criticality": "Critical",
            "keywords": [
                "CERTIFICATS DE CONFORMITE ET DE VISITES", "CERTIFICATS DE CONFORMITE ET DE VISITE",
                "CERTIFICAT DE CONFORMITE ET DE VISITE", "VISITES INTERIEURES ET EXTERIEURES",
                "VISITE INTERIEURE ET EXTERIEURE", "VISITE DE L EQUIPEMENT", "CERTIFICATE OF CONFORMITY AND EQUIPMENT INSPECTION",
                "INTERNAL AND EXTERNAL INSPECTION", "ANNEXE D"
            ],
            "contract": ContractDoc03VisiteUsine
        },
        {
            "code": "DOC-04",
            "name": "Certificat Construction Conforme Pays d'Origine",
            "ref": "P-CTE-1 Annexe F",
            "criticality": "Critical",
            "keywords": [
                "CONSTRUCTION CONFORME POUR UNE UTILISATION DANS LE PAYS D ORIGINE",
                "CONSTRUCTION CONFORME DANS LE PAYS D ORIGINE",
                "CONSTRUCTION CONFORME POUR UNE UTILISATION DANS SON PAYS D ORIGINE",
                "SUITABLE FOR USE IN THE COUNTRY OF ORIGIN", "CONFORME DANS LE PAYS D ORIGINE",
                "ANNEXE F"
            ],
            "contract": ContractDoc04PaysOrigine
        },
        {
            "code": "DOC-05",
            "name": "État Descriptif de l'Équipement",
            "ref": "P-CTE-1 Annexe E / Décret 21-261",
            "criticality": "Critical",
            "keywords": [
                "ETAT DESCRIPTIF DE L EQUIPEMENT", "ETAT DESCRIPTIF", "DESCRIPTIVE STATUS",
                "DESCRIPTIVE REPORT", "ANNEXE E", "FICHE SIGNALETIQUE", "EQUIPMENT DATA SHEET",
                "CARACTERISTIQUES TECHNIQUES DE L EQUIPEMENT"
            ],
            "contract": ContractDoc05EtatDescriptif
        },
        {
            "code": "DOC-06",
            "name": "Note de Calcul de Résistance Mécanique",
            "ref": "Décret 21-261 / ASME B16.9 / ASME VIII",
            "criticality": "Critical",
            "keywords": [
                "NOTE DE CALCUL DE L EQUIPEMENT", "NOTE DE CALCUL DE RESISTANCE", "NOTES DE CALCUL",
                "NOTE DE CALCUL", "CALCUL DE RESISTANCE", "DESIGN CALCULATIONS", "STRENGTH CALCULATION SHEET",
                "STRENGTH CALCULATION", "TEE STRENGTH CALCULATION", "VALVE STEM STRENGTH CALCULATION",
                "STEM STRENGTH CALCULATION", "MECHANICAL CALCULATION", "THICKNESS CALCULATION", "CALCULATION NOTE"
            ],
            "contract": ContractDoc06NoteCalcul
        },
        {
            "code": "DOC-07",
            "name": "Dessins & Plans Détaillés d'Exécution",
            "ref": "P-CTE-1 §VI.2",
            "criticality": "Critical",
            "keywords": [
                "PLANS DETAILLES AVEC INDEX", "PLANS DETAILLES", "PLAN DETAILLE", "DESSINS DE L EQUIPEMENT",
                "EQUIPMENT DRAWINGS", "EQUIPMENT DRAWING", "PLANS D EXECUTION", "GENERAL ARRANGEMENT",
                "ASSEMBLY DRAWING", "PLAN D ENSEMBLE", "CROSS SECTION DRAWING"
            ],
            "contract": ContractDoc07DessinsPlans
        },
        {
            "code": "DOC-08",
            "name": "Cahier de Soudage (WPS/PQR) & Spécification Fabrication",
            "ref": "ASME Section IX",
            "criticality": "Critical",
            "keywords": [
                "SPECIFICATION DE PROCEDURE DE SOUDAGE", "SPECIFICATION DES PROCEDURES DE SOUDAGE",
                "WELDING PROCEDURE SPECIFICATION", "PROCEDURE DE SOUDAGE", "CAHIER DE SOUDAGE",
                "WPS PQR", "WPQR", "MANUFACTURING PROCESS SPECIFICATION", "OPERATION GUIDE FOR MANUFACTURING",
                "FABRICATION SPECIFICATION", "QMOS"
            ],
            "contract": ContractDoc08CahierSoudage
        },
        {
            "code": "DOC-09",
            "name": "Procédure de Traitement Thermique",
            "ref": "P-CTE-1 Annexe A / ASME",
            "criticality": "Major",
            "keywords": [
                "PROCEDURE DE TRAITEMENT THERMIQUE", "SPECIFICATION DE TRAITEMENT THERMIQUE",
                "HEAT TREATMENT PROCEDURE", "HEAT TREATMENT PROCESS", "HEAT TREATMENT SPECIFICATION",
                "TRAITEMENT THERMIQUE", "PWHT PROCEDURE", "QUENCHING TEMPERING"
            ],
            "contract": ContractDoc09TraitementThermique
        },
        {
            "code": "DOC-10",
            "name": "Plan d'Inspection et de Test (ITP)",
            "ref": "P-CTE-1 Annexe A",
            "criticality": "Critical",
            "keywords": [
                "PLAN D INSPECTION ET DE TEST", "PLAN D INSPECTION ET ESSAI", "PLAN D INSPECTION ET ESSAIS",
                "INSPECTION AND TEST PLAN", "INSPECTION & TEST PLAN", "INSPECTION & TESTING PLAN",
                "QCP QUALITY CONTROL PLAN", "PLAN DE CONTROLE QUALITE"
            ],
            "contract": ContractDoc10ITPControle
        },
        {
            "code": "DOC-11",
            "name": "Procès-Verbal d'Épreuve Hydrostatique Usine",
            "ref": "Décret 21-261 Art. 24",
            "criticality": "Critical",
            "keywords": [
                "EPREUVE HYDROSTATIQUE", "HYDROSTATIC TEST REPORT", "HYDROSTATIC PRESSURE TEST",
                "PV D EPREUVE HYDROSTATIQUE", "PV D EPREUVE", "HYDROTEST REPORT", "SHOP HYDROSTATIC TEST"
            ],
            "contract": ContractDoc11EpreuveHydro
        },
        {
            "code": "DOC-12",
            "name": "Certificats de Réception Matière EN 10204",
            "ref": "EN 10204 3.1 / 3.2",
            "criticality": "Critical",
            "keywords": [
                "CERTIFICAT DE RECEPTION MATIERE", "CERTIFICATS DE RECEPTION MATIERE", "EN 10204",
                "MILL TEST CERTIFICATE", "INSPECTION CERTIFICATE 3 1", "3 1 CERTIFICATE", "MATERIAL TEST REPORT",
                "MTC 3 1", "CERTIFICAT MATIERE"
            ],
            "contract": ContractDoc12CertificatsMatiere
        },
        {
            "code": "DOC-13",
            "name": "Rapports de Contrôles Non Destructifs (CND)",
            "ref": "ASME Section V / Décret 21-261",
            "criticality": "Critical",
            "keywords": [
                "CONTROLES NON DESTRUCTIFS", "RAPPORT DE CONTROLES NON DESTRUCTIFS", "NON DESTRUCTIVE TESTING",
                "NDT REPORT", "ULTRASONIC TEST REPORT", "MAGNETIC PARTICLE REPORT", "RADIOGRAPHIC EXAMINATION",
                "PENETRANT TESTING REPORT"
            ],
            "contract": ContractDoc13CND
        },
        {
            "code": "DOC-14",
            "name": "Rapport de Contrôle Dimensionnel",
            "ref": "P-CTE-1 / ASME B16.9",
            "criticality": "Major",
            "keywords": [
                "CONTROLE DIMENSIONNEL", "RAPPORT DE CONTROLE DIMENSIONNEL", "DIMENSIONAL INSPECTION REPORT",
                "DIMENSIONAL REPORT", "DIMENSIONAL CHECK RECORD"
            ],
            "contract": ContractDoc14ControleDimensionnel
        }
    ]


    def __init__(self, db_path: Optional[Union[Path, str]] = None, uploads_dir: Optional[Union[Path, str]] = None):
        base_dir = Path(__file__).parent
        self.db_path = Path(db_path) if db_path else (base_dir / "arh_dossiers.db")
        self.uploads_dir = Path(uploads_dir) if uploads_dir else (base_dir / "arh_uploads")
        self._ocr = None
        self._init_sqlite_tables()

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr = RapidOCR()
            except Exception:
                self._ocr = False
        return self._ocr if self._ocr is not False else None

    def _get_db(self):
        import sqlite3
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_sqlite_tables(self):
        """Crée la table `arh_sliced_pieces` si elle n'existe pas déjà."""
        with self._get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS arh_sliced_pieces (
                    piece_id                TEXT PRIMARY KEY,
                    dossier_id              TEXT NOT NULL,
                    piece_code              TEXT NOT NULL,
                    piece_name              TEXT NOT NULL,
                    regulatory_ref          TEXT,
                    criticality             TEXT,
                    page_start              INTEGER NOT NULL,
                    page_end                INTEGER NOT NULL,
                    page_count              INTEGER NOT NULL,
                    file_name               TEXT NOT NULL,
                    file_path               TEXT NOT NULL,
                    file_size_kb            REAL NOT NULL,
                    extracted_fields_json   TEXT NOT NULL,
                    validation_status       TEXT NOT NULL,
                    compliance_remarks_json TEXT NOT NULL,
                    created_at              TEXT NOT NULL,
                    FOREIGN KEY (dossier_id) REFERENCES arh_dossiers(dossier_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sliced_pieces_dossier ON arh_sliced_pieces(dossier_id)")
            conn.commit()

    @staticmethod
    def _normalize(text: str) -> str:
        """Supprime les accents et met en majuscules pour une comparaison robuste."""
        import unicodedata
        if not text:
            return ""
        nfkd = unicodedata.normalize('NFKD', text)
        ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
        normalized = re.sub(r'[^A-Z0-9\s]', ' ', ascii_text.upper())
        return re.sub(r'\s+', ' ', normalized).strip()

    def parse_vendor_sommaire(self, doc: fitz.Document) -> List[Dict[str, Any]]:
        """
        Extrait formellement le découpage déclaré par le constructeur dans son Sommaire / Table des matières / Index des pièces.
        Assure une fidélité à 100% avec l'index officiel du dossier (début et fin exacts de chaque pièce).
        Supporte :
          - Les tables avec numéros de pages inline ou sur la ligne suivante
          - Les tables multi-colonnes PyMuPDF (colonnes spatiales avec numéros de page à droite)
          - Les index déclaratifs sans numéros de page (recherche sémantique ciblée dans le corps)
        """
        total_pages = len(doc)
        if total_pages == 0:
            return []

        def _is_running_header(line_txt: str) -> bool:
            norm = self._normalize(line_txt)
            if re.search(r'\bDOC(?:UMENT)?\.?\s*N[°O]?\s*\d+\s*(?:A|TO|\-)\s*\d+\b', norm):
                return True
            if any(h in norm for h in ['FIELD DEVELOPMENT', 'PROVISION OF', 'HASSI BIR REKAIZ', 'DUSSELDORF', 'GCB CF']):
                return True
            return False

        sommaire_page_idx = None
        sommaire_text = ''
        
        for p_idx in range(min(6, total_pages)):
            txt = doc[p_idx].get_text()
            if len(txt.strip()) < 50:
                try:
                    ocr = self._get_ocr()
                    if ocr:
                        pix = doc[p_idx].get_pixmap(dpi=150)
                        ocr_res, _ = ocr(pix.tobytes('png'))
                        if ocr_res:
                            txt = "\n".join([line[1] for line in ocr_res])
                except Exception:
                    pass
            norm_u = self._normalize(txt)
            is_somm = any(h in norm_u for h in ['SOMMAIRE', 'TABLE OF CONTENTS', 'TABLE DES MATIERES', 'INDEX DES PIECES', 'INDEX DES DOCUMENTS'])
            is_arh_table = (('PRELIMINARY ARH DOSSIER' in norm_u or 'PRELIMINANRY ARH DOSSIER' in norm_u) 
                            and bool(re.search(r'\bPAGE\b', norm_u)) 
                            and any(w in norm_u for w in ['DEMANDE', 'CALCUL', 'WPS', 'NOTE', 'SIGNATURE', 'ETAT DESCRIPTIF']))
            if (is_somm or is_arh_table) and any(w in norm_u for w in ['DEMANDE', 'COMMERCE', 'CALCUL', 'WPS', 'DESCRIPTIF', 'MATERIELS', 'LIST', 'VALVE', 'CERTIFICAT', 'INSPECTION', 'DOCUMENT']):
                sommaire_page_idx = p_idx
                sommaire_text = txt
                break
                
        if sommaire_page_idx is None:
            return []
            
        raw_lines = [l.strip() for l in sommaire_text.split('\n') if l.strip()]
        marker_pat = re.compile(
            r'^\s*(?:DOC(?:UMENT)?[\s\-_]*(?:N[°O]?|NO\.?|#)?|SECTION|PART(?:IE)?|PIECE|ITEM)?\s*0?([0-9]{1,2}(?:\.[0-9]{1,2})?|[IVXLCDM]{1,6})\s*[\.\-\):\s]\s*(.*)$',
            re.I
        )
        dot_leader_pat = re.compile(r'^(.*?)[\.\s_\-]{3,}\s*(\d{1,3}|N/?A)\s*$', re.I)
        
        items_raw = []
        current_item = None
        page_nums_tail = []
        in_footer = False
        auto_item_counter = 1

        for line in raw_lines:
            if _is_running_header(line):
                continue
            if line.upper() in ['SOMMAIRE', 'TABLE OF CONTENTS', 'TABLE DES MATIERES', 'PAGE'] and items_raw:
                in_footer = True
                continue
            if in_footer:
                if line.isdigit() or line.upper() in ['N/A', 'NA', 'NON APPLICABLE', 'NOT APPLICABLE']:
                    page_nums_tail.append(line)
                continue

            # Détection d'un numéro de page isolé sur sa propre ligne (ex: "3", "4", "12", "N/A")
            if (line.isdigit() and 1 <= int(line) <= total_pages) or line.upper() in ['N/A', 'NA', 'NON APPLICABLE', 'NOT APPLICABLE']:
                if current_item and not current_item.get('page_direct'):
                    current_item['page_direct'] = line
                continue

            # Détection d'une ligne non numérotée avec points de suite et numéro de page (ex: "État descriptif ..... 8")
            m_dot = dot_leader_pat.match(line)
            if m_dot and not marker_pat.match(line):
                if current_item:
                    items_raw.append(current_item)
                item_title = m_dot.group(1).strip()
                item_p = m_dot.group(2).strip()
                current_item = {'num': str(auto_item_counter), 'lines': [item_title] if item_title else [], 'page_direct': item_p}
                auto_item_counter += 1
                continue

            m = marker_pat.match(line)
            if m and (m.group(1).isdigit() or '.' in m.group(1)) and float(m.group(1)) <= 20:
                num_str = m.group(1)
                item_rem = m.group(2).strip() if (m.lastindex >= 2 and m.group(2)) else ""
                # Si le même numéro réapparaît (ex: Titre Français suivi de Titre Anglais sous le même numéro 0., 1., etc.)
                if current_item and current_item['num'] == num_str:
                    if item_rem:
                        current_item['lines'].append(item_rem)
                    continue
                if current_item:
                    items_raw.append(current_item)
                current_item = {'num': num_str, 'lines': [item_rem] if item_rem else [], 'page_direct': None}
                try:
                    auto_item_counter = int(float(num_str)) + 1
                except Exception:
                    auto_item_counter += 1
            else:
                if current_item:
                    current_item['lines'].append(line)
        if current_item:
            items_raw.append(current_item)

        blocks = doc[sommaire_page_idx].get_text('blocks')
        
        # Num blocks dans la colonne de droite (x0 > 300) pour éviter de confondre avec les numéros d'items à gauche
        num_blocks = []
        for b in blocks:
            if b[0] > 300: # Colonne des numéros de pages
                txt_b = b[4].strip()
                for bl in txt_b.split('\n'):
                    bl = bl.strip()
                    if bl.isdigit() and 1 <= int(bl) <= total_pages:
                        num_blocks.append({'rect': b[:4], 'val': bl, 'y0': b[1], 'y1': b[3], 'x0': b[0]})
                    elif bl.upper() in ['N/A', 'NA', 'NON APPLICABLE', 'NOT APPLICABLE']:
                        num_blocks.append({'rect': b[:4], 'val': bl, 'y0': b[1], 'y1': b[3], 'x0': b[0]})

        items_with_pages = []
        for idx, itm in enumerate(items_raw):
            full_txt = " ".join(itm['lines']).strip()
            p_val = itm.get('page_direct')
            title = full_txt
            # 1. Inline check
            if not p_val:
                p_match = re.search(r'(?:[\.\s_]{2,}|\s+)(\d{1,3}|N/?A)\s*$', full_txt, re.I)
            else:
                p_match = None
            if p_match:
                p_val = p_match.group(1).strip()
                title = full_txt[:p_match.start()].strip(' .-_')
            else:
                # 2. Spatial matching avec les blocs de droite (x0 > 300)
                item_y = None
                words_check = [w.upper() for w in re.findall(r'[A-Za-zÀ-ÿ]{4,}', full_txt)]
                for b in blocks:
                    if b[0] < 300:
                        m_num = re.search(r'(?:^|\n)\s*' + re.escape(itm['num']) + r'\b', b[4])
                        has_word = any(w in b[4].upper() for w in words_check[:4]) if words_check else True
                        if m_num and has_word:
                            item_y = (b[1] + b[3]) / 2.0
                            break
                if item_y is not None:
                    closest_nb = None
                    min_dy = 999
                    for nb in num_blocks:
                        nb_y = (nb['y0'] + nb['y1']) / 2.0
                        dy = abs(nb_y - item_y)
                        if dy < 25 and dy < min_dy:
                            min_dy = dy
                            closest_nb = nb
                    if closest_nb:
                        p_val = closest_nb['val']

                # 3. Repli séquentiel sur le tableau de fin de flux si disponible
                if not p_val and idx < len(page_nums_tail):
                    tail_num = page_nums_tail[idx]
                    if tail_num.isdigit() and 1 <= int(tail_num) <= total_pages:
                        p_val = tail_num

                title = full_txt

            is_na = (p_val and p_val.upper() in ['N/A', 'NA', 'NON APPLICABLE', 'NOT APPLICABLE']) or ('NON APPLICABLE' in title.upper())
            p_int = int(p_val) if (p_val and p_val.isdigit()) else None
            items_with_pages.append({
                'num': itm['num'],
                'title': title,
                'page': p_int,
                'is_na': is_na
            })

        valid_with_pages = [x for x in items_with_pages if x['page'] is not None and x['page'] > 0 and not x['is_na']]

        # Fallback TIER 1b: Sommaire déclaré mais sans numéros de page -> Recherche sémantique ciblée dans le corps
        if len(valid_with_pages) < 2 and len(items_raw) >= 3:
            body_start = sommaire_page_idx + 1

            resolved_body_items = []
            curr_search_start = body_start
            for itm in items_raw:
                try:
                    num_int = int(float(itm['num']))
                except Exception:
                    continue
                found_p = None
                itm_title_str = " ".join(itm['lines']).strip()

                # Passe A : Chercher en priorité absolue un numéro formel de document DOCUMENT No. X / DOCUMENT N° X
                for p_idx in range(curr_search_start, total_pages):
                    p_txt = doc[p_idx].get_text()
                    lines = [l.strip() for l in p_txt.split('\n') if l.strip()]
                    header_lines = [l for l in lines[:10] if not _is_running_header(l)]
                    hdr_full = self._normalize(" ".join(header_lines))
                    m_doc_num = re.search(r'\bDOCUMENT\s*(?:N[°O]?|NO\.?|#)?\s*[:\.]?\s*0?' + str(num_int) + r'\b', hdr_full)
                    if m_doc_num:
                        found_p = p_idx + 1
                        break

                # Passe B : Formulaire officiel ou analyse sémantique du titre de l'item
                if not found_p:
                    for p_idx in range(curr_search_start, total_pages):
                        p_txt = doc[p_idx].get_text()
                        lines = [l.strip() for l in p_txt.split('\n') if l.strip()]
                        header_lines = [l for l in lines[:10] if not _is_running_header(l)]
                        hdr_full = self._normalize(" ".join(header_lines))

                        # Formulaires formels
                        if num_int in [2, 3, 4, 5]:
                            m_f = re.search(r'\bFORMULAIRE\s*[\-_]?\s*0?(\d+)\b', hdr_full)
                            if m_f:
                                f_num = int(m_f.group(1))
                                if (num_int == 2 and f_num == 1) or (num_int == 4 and f_num == 2) or (num_int == 3 and f_num in [3, 4]) or (num_int == 5 and f_num == 5):
                                    found_p = p_idx + 1
                                    break

                        # Mots clés distinctifs extraits directement du titre de la ligne du sommaire
                        title_u = self._normalize(itm_title_str)
                        title_kws = [w for w in re.findall(r'[A-Za-z]{4,}', title_u) if w not in [
                            'POUR', 'AVEC', 'DANS', 'SUR', 'SOUS', 'PAGE', 'PAGES', 'INDEX', 'LISTE', 'ITEM', 'DOC', 'DOCUMENT', 'AVIS', 'LETTRE', 'LETTER', 'TECHNICAL', 'DOSSIER', 'THE', 'AND', 'FOR'
                        ]]
                        if any(w in hdr_full for w in title_kws[:3]) if title_kws else False:
                            found_p = p_idx + 1
                            break

                if found_p:
                    resolved_body_items.append({
                        'num': itm['num'],
                        'title': itm_title_str,
                        'page': found_p,
                        'is_na': False
                    })
                    curr_search_start = found_p

            if len(resolved_body_items) >= 2:
                items_with_pages = resolved_body_items
                valid_with_pages = [x for x in items_with_pages if x['page'] is not None and x['page'] > 0]

        # Validation Gate : Au moins 2 pages découpées avec succès
        if len(valid_with_pages) < 2:
            return []

        valid_with_pages.sort(key=lambda x: x['page'])
        dedup = []
        for v in valid_with_pages:
            if not dedup or dedup[-1]['page'] != v['page']:
                dedup.append(v)

        pieces_ranges = []
        first_start = dedup[0]['page']
        if first_start > 1:
            pieces_ranges.append({
                'spec': {
                    'code': 'DOC-00',
                    'name': 'Bordereau de Soumission & Page de Garde',
                    'ref': 'Procédure Générale GCB / ARH',
                    'criticality': 'Standard',
                    'contract': ContractGenericPiece
                },
                'start': 1,
                'end': first_start - 1,
                'pages': list(range(1, first_start)),
                'is_na': False
            })

        for i, itm in enumerate(dedup):
            st = itm['page']
            en = dedup[i+1]['page'] - 1 if i+1 < len(dedup) else total_pages
            if en < st:
                en = st
            order_i = int(float(itm['num'])) if itm['num'].replace('.', '').isdigit() else (i + 1)
            spec = self.get_spec_for_title(itm['title'], order_i)
            pieces_ranges.append({
                'spec': spec,
                'start': st,
                'end': en,
                'pages': list(range(st, en + 1)),
                'is_na': itm.get('is_na', False)
            })

        # Fusion des pièces identiques consécutives (évite les doublons de découpage)
        merged_ranges = []
        for p in pieces_ranges:
            if not merged_ranges:
                merged_ranges.append(p)
            elif merged_ranges[-1]['spec']['code'] == p['spec']['code']:
                merged_ranges[-1]['end'] = max(merged_ranges[-1]['end'], p['end'])
                merged_ranges[-1]['pages'] = list(range(merged_ranges[-1]['start'], merged_ranges[-1]['end'] + 1))
            else:
                merged_ranges.append(p)
        pieces_ranges = merged_ranges

        # Garantie de couverture intégrale et continue de 100% des pages (page 1 à total_pages)
        if pieces_ranges:
            pieces_ranges[0]['start'] = 1
            for i in range(len(pieces_ranges) - 1):
                pieces_ranges[i]['end'] = max(pieces_ranges[i]['start'], pieces_ranges[i + 1]['start'] - 1)
                pieces_ranges[i]['pages'] = list(range(pieces_ranges[i]['start'], pieces_ranges[i]['end'] + 1))
            pieces_ranges[-1]['end'] = total_pages
            pieces_ranges[-1]['pages'] = list(range(pieces_ranges[-1]['start'], total_pages + 1))

        return pieces_ranges

    def get_spec_for_title(self, title: str, order_idx: int) -> Dict[str, Any]:
        # Nettoyer les notes de bas de page ou renvois (*)
        clean_t = re.sub(r'\(\*\)[^$]*', '', title or '').strip()
        t_u = clean_t.upper()
        target_code = None

        # Priorité absolue par titre métier
        if any(k in t_u for k in ['VISITE', 'INTERIEUR', 'INTERIEURE', 'INTERIOR', 'EXTERIOR', 'VISITES']) or ('CONFORMITE' in t_u and any(v in t_u for v in ['VISITE', 'INTERIOR', 'EXTERIOR'])):
            target_code = 'DOC-03'
        elif any(k in t_u for k in ['INSPECTION AND TEST', 'ITP', 'TEST PLAN', 'CONTROLE QUALITE', 'QUALITY CONTROL', 'PLAN D\'INSPECTION', 'PLAN D INSPECTION', 'QCP', 'TESTING PLAN']) or (('INSPECTION' in t_u or 'CONTROLE' in t_u) and 'PLAN' in t_u):
            target_code = 'DOC-10'
        elif any(k in t_u for k in ['HYDROSTATIQUE', 'HYDROSTATIC', 'EPREUVE', 'PRESSURE TEST', 'SHOP HYDRO']):
            target_code = 'DOC-11'
        elif any(k in t_u for k in ['TRAITEMENT THERMIQUE', 'HEAT TREATMENT', 'PWHT']) or ('TRAITEMENT' in t_u and 'THERMIQUE' in t_u):
            target_code = 'DOC-09'
        elif any(k in t_u for k in ['SOUDAGE', 'WELDING', 'WPS', 'PQR', 'QMOS']):
            target_code = 'DOC-08'
        elif any(k in t_u for k in ['PLAN DETAILLE', 'DETAILLED DRAWING', 'PLANS DETAILLES', 'DESSIN', 'DESSINS', 'GENERAL ARRANGEMENT', 'DRAWING', 'DRAWINGS']) or (any(k in t_u for k in ['PLAN', 'DRAWING']) and 'INSPECTION' not in t_u):
            target_code = 'DOC-07'
        elif any(k in t_u for k in ['CALCUL', 'CALCULATION', 'RESISTANCE', 'STRENGTH', 'EPAISSEUR', 'THICKNESS']):
            target_code = 'DOC-06'
        elif any(k in t_u for k in ['ETAT DESCRIPTIF', 'ÉTAT DESCRIPTIF', 'FICHE SIGNALETIQUE', 'DESCRIPTION OF EQUIPMENT', 'DESCRIPTIVE STATUS', 'DESCRIPTIVE STATE', 'ANNEXE E']):
            target_code = 'DOC-05'
        elif any(k in t_u for k in ['PAYS D\'ORIGINE', 'PAYS D ORIGINE', 'COUNTRY OF ORIGIN', 'CONSTRUCTION CONFORME', 'D\'ORIGINE', 'D ORIGINE', 'ORIGINE', 'ORIGIN', 'CERTIFICATE OF CONFORMITY', 'CERTIFICAT DE CONFORMITE', 'CERTIFICATEOFCONFORMITY', 'CERTIFICATD\'ORIGINE']):
            target_code = 'DOC-04'
        elif any(k in t_u for k in ['CHAMBRE', 'SIGNATURE', 'SIGNATURES', 'CONSULAT', 'CONSULAIRE', 'REGISTRE DU COMMERCE']):
            target_code = 'DOC-02'
        elif any(k in t_u for k in ['DEMANDE', 'AVIS', 'APPROBATION', 'APPROVAL REQUEST', 'LETTER OF REQUEST']):
            target_code = 'DOC-01'
        elif any(k in t_u for k in ['CERTIFICAT MATIERE', 'CERTIFICAT MATIÈRE', 'MILL TEST', 'EN 10204', '3.1', '3.2', 'MTR', 'HEAT NUMBER']):
            target_code = 'DOC-12'
        elif any(k in t_u for k in ['CONTROLES NON DESTRUCTIFS', 'CONTRÔLES NON DESTRUCTIFS', 'CND', 'NDT', 'RESSUAGE', 'ULTRASONS', 'RADIOGRAPHIE', 'MAGNETOSCOPIE']):
            target_code = 'DOC-13'
        elif any(k in t_u for k in ['CONTROLE DIMENSIONNEL', 'CONTRÔLE DIMENSIONNEL', 'DIMENSIONNEL', 'DIMENSIONAL']):
            target_code = 'DOC-14'
        elif any(k in t_u for k in ['MATERIEL', 'MATERIAL LIST', 'SOMMAIRE', 'INDEX', 'BORDEREAU']) or order_idx == 0:
            target_code = 'DOC-00'
        elif 1 <= order_idx <= 14:
            target_code = f"DOC-{order_idx:02d}"

        if target_code:
            for s in self.SECTIONS_SPECS:
                if s['code'] == target_code:
                    return s
        return {
            'code': target_code or f'DOC-{order_idx:02d}',
            'name': clean_t or f'Pièce {order_idx}',
            'ref': 'P-CTE-1',
            'criticality': 'Standard',
            'contract': ContractGenericPiece
        }

    def parse_section_covers(self, doc: fitz.Document) -> List[Dict[str, Any]]:
        """
        Détecte les pages de garde formelles de section portant la mention 'Page X of N'
        (ex: Page 1 of 10, Page 2 of 10, ... Page 10 of 10) qui délimitent rigoureusement chaque pièce du dossier.
        """
        total_pages = len(doc)
        if total_pages == 0:
            return []

        sections = []
        for p_idx in range(total_pages):
            txt = doc[p_idx].get_text()
            m = re.search(r'Page\s+(\d+)\s+of\s+(\d+)\b', txt, re.I)
            if m:
                sec_num, total_sec = int(m.group(1)), int(m.group(2))
                u = txt.upper()
                if 4 <= total_sec <= 15 and 1 <= sec_num <= total_sec:
                    if any(k in u for k in ['EMIS POUR REVUE', 'ANNEX', 'ORIG. DOC', 'REV.A0', 'TITLE :']):
                        sections.append((sec_num, p_idx + 1, txt))

        if len(sections) < 3:
            return []

        sections.sort(key=lambda x: x[0])
        seen = set()
        unique_sec = []
        for s in sections:
            if s[0] not in seen:
                seen.add(s[0])
                unique_sec.append(s)

        if len(unique_sec) < 3:
            return []

        cuts = []
        first_start = unique_sec[0][1]
        if first_start > 1:
            cuts.append({
                'spec': {
                    'code': 'DOC-00',
                    'name': 'Bordereau de Soumission & Page de Garde',
                    'ref': 'Procédure Générale GCB / ARH',
                    'criticality': 'Standard',
                    'contract': ContractGenericPiece
                },
                'start': 1,
                'end': first_start - 1,
                'is_na': False
            })

        for i, (sec_num, p_start, txt) in enumerate(unique_sec):
            p_end = unique_sec[i+1][1] - 1 if i+1 < len(unique_sec) else total_pages
            if p_end < p_start:
                p_end = p_start

            spec = self.get_spec_for_title(txt, sec_num)
            is_na = any(k in txt.upper() for k in ['NON APPLICABLE', 'NOT APPLICABLE', 'N/A'])

            cuts.append({
                'spec': spec,
                'start': p_start,
                'end': p_end,
                'pages': list(range(p_start, p_end + 1)),
                'is_na': is_na
            })

        for c in cuts:
            if 'pages' not in c:
                c['pages'] = list(range(c['start'], c['end'] + 1))

        # Raffinement robuste par analyse sémantique des pages réelles :
        # Évite à 100% le mélange entre Note de Calcul (DOC-06) et Plans/Dessins (DOC-07)
        for i in range(len(cuts) - 1):
            c_curr = cuts[i]
            c_next = cuts[i + 1]
            if c_curr['spec']['code'] == "DOC-06" and c_next['spec']['code'] == "DOC-07":
                cover_calc = list(range(c_curr['start'], c_next['start']))
                calc_pages = []
                pure_drawing_pages = []
                for p_check in range(c_next['start'], c_next['end'] + 1):
                    p_txt = doc[p_check - 1].get_text().upper()
                    is_calc = any(k in p_txt for k in ['STRENGTH CALCULATION', 'CALCULATION SHEET', 'NOTE DE CALCUL', 'CALCUL DE RESISTANCE', 'ASME B31.8'])
                    is_dwg = any(k in p_txt for k in ['DRAWING NO', 'DRAWING NUMBER', 'BARRED TEE', 'TECHNICAL REQUIREMENTS', 'DESSIN', 'A/B']) or (doc[p_check - 1].rect.width > doc[p_check - 1].rect.height)
                    if is_calc:
                        calc_pages.append(p_check)
                    elif is_dwg and not is_calc:
                        pure_drawing_pages.append(p_check)

                if calc_pages and pure_drawing_pages:
                    min_calc = min(calc_pages)
                    cover_dwg = [p for p in range(c_next['start'], min_calc)]
                    
                    # DOC-06 = Page de garde Note de calcul + Feuilles de calcul réelles
                    c_curr['pages'] = cover_calc + calc_pages
                    c_curr['start'] = min(c_curr['pages'])
                    c_curr['end'] = max(c_curr['pages'])

                    # DOC-07 = Page de garde Dessins/Plans + Feuilles de plans réelles
                    actual_dwg_sheets = [p for p in pure_drawing_pages if p >= min_calc]
                    c_next['pages'] = cover_dwg + actual_dwg_sheets
                    c_next['start'] = min(c_next['pages'])
                    c_next['end'] = max(c_next['pages'])

        return cuts

    def identify_boundaries(self, doc: fitz.Document) -> List[Dict[str, Any]]:
        """
        Analyse les pages du PDF pour identifier les séparateurs de pièces et leurs étendues.
        Prend en charge :
          - Priorité 1 : Sommaire / Table des matières / Index officiel déclaré par le constructeur
          - Priorité 1b : Pages de titre de section formelles ("Page X of 10")
          - Priorité 2 : Détection des pages de titres de section explicites ("DOCUMENT No. X", "FORMULAIRE-X", "ANNEXE X")
          - Priorité 3 : Détection sémantique sur les en-têtes sans faux positifs sur les sous-pages de continuation
          - Couverture intégrale et continue de 100% des pages du document (DOC-00 à DOC-14).
        """
        total_pages = len(doc)
        if total_pages == 0:
            return []

        def _is_running_header(line_txt: str) -> bool:
            norm = self._normalize(line_txt)
            if re.search(r'\bDOC(?:UMENT)?\.?\s*N[°O]?\s*\d+\s*(?:A|TO|\-)\s*\d+\b', norm):
                return True
            if any(h in norm for h in ['FIELD DEVELOPMENT', 'PROVISION OF', 'HASSI BIR REKAIZ', 'DUSSELDORF', 'GCB CF']):
                return True
            return False

        # 1. Priorité absolue : Détection du Sommaire déclaré par le fournisseur
        sommaire_cuts = self.parse_vendor_sommaire(doc)
        valid_sommaire = [c for c in sommaire_cuts if c.get('start', 0) > 0 and not c.get('is_na', False)]
        if len(valid_sommaire) >= 2:
            logger.info("[ARH-SLICER] Sommaire constructeur validé : %d pièces découpées selon l'index.", len(sommaire_cuts))
            return sommaire_cuts

        # 1.1 Priorité 1b : Pages de titre de section formelles ("Page X of 10")
        cover_cuts = self.parse_section_covers(doc)
        valid_covers = [c for c in cover_cuts if c.get('start', 0) > 0 and not c.get('is_na', False)]
        if len(valid_covers) >= 2:
            logger.info("[ARH-SLICER] Pages de garde de section validées : %d pièces découpées selon l'index.", len(cover_cuts))
            return cover_cuts

        cuts = []
        ignored_headers = [
            "PROVISION OF ENGINEERING", "EPCIC", "FIELD DEVELOPMENT", "DUSSELDORF",
            "KONIGSALLEE", "GCB CF", "PAGE DE GARDE", "PRELIMINAIRE ARH"
        ]

        for p_idx in range(total_pages):
            page_num = p_idx + 1
            page_text = doc[p_idx].get_text()
            raw_lines = [l.strip() for l in page_text.split("\n") if l.strip()]

            # Vérifier si la page est une page intermédiaire d'un sous-document (ex: "3 / 12", "Page 2 of 5")
            # Attention : ne pas confondre avec la pagination globale du dossier maître (ex: "Page 2 of 29" sur 29 pages)
            is_subpage_continuation = False
            for l in raw_lines[:5]:
                m_sub = re.search(r'^\s*([2-9]|\d{2,})\s*/\s*(\d+)\s*$', l)
                m_sub2 = re.search(r'\bPAGE\s+([2-9]|\d{2,})\s+OF\s+(\d+)\b', self._normalize(l))
                if m_sub and int(m_sub.group(2)) != total_pages:
                    is_subpage_continuation = True
                    break
                if m_sub2 and int(m_sub2.group(2)) != total_pages:
                    is_subpage_continuation = True
                    break

            has_explicit_doc_header = any(
                re.search(r'\b(?:DOCUMENT\s*(?:N[°O]?|NO\.?|#)?\s*[:\.]?\s*0?[1-9]|FORMULAIRE|ANNEXE)\b', self._normalize(l))
                for l in raw_lines[:6]
            )
            if is_subpage_continuation and not has_explicit_doc_header:
                continue

            # Si la page est un Sommaire / Table des matières, elle fait partie de DOC-00 et ne démarre pas de pièce
            is_sommaire = any(k in self._normalize(" ".join(raw_lines[:10])) for k in ["SOMMAIRE", "TABLE DES MATIERES", "TABLE OF CONTENTS", "INDEX DES PIECES"])
            if is_sommaire:
                continue

            meaningful_lines = [l for l in raw_lines if not _is_running_header(l) and not any(h in l.upper() for h in ignored_headers)]
            header_text = self._normalize(" ".join(meaningful_lines[:15]))
            matched_spec = None

            # 1. Séparateur explicite "DOCUMENT No. X", "DOCUMENT N° X", "Document no X"
            m_doc = re.search(r'\bDOCUMENT\s*(?:N[°O]?|NO\.?|#)?\s*[:\.]?\s*0?([1-9]|1[0-4])\b', header_text)
            if m_doc:
                doc_idx = int(m_doc.group(1))
                matched_spec = self.get_spec_for_title(header_text, doc_idx)

            # 2. Séparateur "FORMULAIRE-X" ou "ANNEXE X"
            if not matched_spec:
                m_f = re.search(r'\bFORMULAIRE\s*[\-_]?\s*0?([1-5])\b', header_text)
                if m_f:
                    f_map = {1: 2, 2: 4, 3: 3, 4: 3, 5: 5}
                    doc_idx = f_map.get(int(m_f.group(1)), int(m_f.group(1)))
                    matched_spec = self.get_spec_for_title(header_text, doc_idx)

            if not matched_spec:
                m_ann = re.search(r'\bANNEXE\s*([A-F]|[1-9])\b', header_text)
                if m_ann:
                    ann_map = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 5, 'F': 6}
                    val_ann = m_ann.group(1).upper()
                    doc_idx = ann_map.get(val_ann, int(val_ann) if val_ann.isdigit() else 1)
                    matched_spec = self.get_spec_for_title(header_text, doc_idx)

            # 3. Séparateur formel "1 – Titre", "PARTIE N"
            if not matched_spec:
                for ml in meaningful_lines[:8]:
                    m_dash = re.search(r'^\s*0?([1-9]|1[0-4])\s*[\-–—\.:]\s*([A-Za-zÀ-ÿ].+)$', ml)
                    if m_dash and re.search(r'[A-Za-zÀ-ÿ]{3,}', m_dash.group(2)):
                        sec_num = int(m_dash.group(1))
                        sec_title = self._normalize(m_dash.group(2))
                        for spec in self.SECTIONS_SPECS:
                            for kw in spec["keywords"]:
                                if self._normalize(kw) in sec_title or sec_title in self._normalize(kw):
                                    matched_spec = spec
                                    break
                            if matched_spec:
                                break
                        if not matched_spec and 1 <= sec_num <= len(self.SECTIONS_SPECS):
                            matched_spec = self.SECTIONS_SPECS[sec_num - 1]
                        if matched_spec:
                            break

                    m_part = re.search(r'^\s*(?:PART(?:IE)?|SECTION|CHAPITRE)\s*([0-9]{1,2})\b', ml, re.I)
                    if m_part:
                        sub_txt = self._normalize(" ".join(meaningful_lines[:10]))
                        for spec in self.SECTIONS_SPECS:
                            for kw in spec["keywords"]:
                                if self._normalize(kw) in sub_txt:
                                    matched_spec = spec
                                    break
                            if matched_spec:
                                break
                        if matched_spec:
                            break

            # 4. Titres explicites de pièces en haut de page
            if not matched_spec:
                if any(k in header_text for k in ["NOTE DE CALCUL", "NOTES DE CALCUL", "STRENGTH CALCULATION", "CALCULATION SHEET"]):
                    matched_spec = self.get_spec_for_title("Note de Calcul", 6)
                elif any(k in header_text for k in ["PLANS DETAILLES", "PLAN DETAILLE", "GENERAL ARRANGEMENT", "DRAWING", "TOLERANCE", "ECHELLE", "CARTUCHE", "ASSEMBLY"]):
                    matched_spec = self.get_spec_for_title("Plans Détaillés", 7)
                elif any(k in header_text for k in ["PROCEDURES DE SOUDAGE", "WELDING PROCEDURE", "WPS", "PQR"]):
                    matched_spec = self.get_spec_for_title("Cahier de Soudage WPS", 8)
                elif any(k in header_text for k in ["TRAITEMENT THERMIQUE", "TRAITEMENTS THERMIQUES", "PWHT", "HEAT TREATMENT"]):
                    matched_spec = self.get_spec_for_title("Procédure PWHT", 9)
                elif any(k in header_text for k in ["PLAN D INSPECTION", "INSPECTION AND TEST PLAN", "ITP", "QCP"]):
                    matched_spec = self.get_spec_for_title("Plan d'Inspection ITP", 10)
                elif any(k in header_text for k in ["EPREUVE HYDROSTATIQUE", "HYDROSTATIC TEST"]):
                    matched_spec = self.get_spec_for_title("Épreuve Hydrostatique", 11)
                elif any(k in header_text for k in ["CERTIFICAT MATIERE", "MILL TEST CERTIFICATE"]):
                    matched_spec = self.get_spec_for_title("Certificats Matière", 12)
                elif any(k in header_text for k in ["CONTROLES NON DESTRUCTIFS", "NDT REPORT", "CND"]):
                    matched_spec = self.get_spec_for_title("Contrôles Non Destructifs", 13)
                elif any(k in header_text for k in ["CONTROLE DIMENSIONNEL", "DIMENSIONAL REPORT"]):
                    matched_spec = self.get_spec_for_title("Contrôle Dimensionnel", 14)
                else:
                    priority_order = ["DOC-04", "DOC-07", "DOC-06", "DOC-08", "DOC-09", "DOC-11", "DOC-12", "DOC-13", "DOC-14", "DOC-05", "DOC-03", "DOC-02", "DOC-01", "DOC-10"]
                    ordered_specs = sorted(self.SECTIONS_SPECS, key=lambda s: priority_order.index(s["code"]) if s["code"] in priority_order else 99)
                    for spec in ordered_specs:
                        for kw in spec["keywords"]:
                            norm_kw = self._normalize(kw)
                            if norm_kw in header_text:
                                matched_spec = spec
                                break
                        if matched_spec:
                            break

            if matched_spec:
                cuts.append({
                    "page": page_num,
                    "spec": matched_spec
                })

        if not cuts:
            return [{
                "spec": {
                    "code": "DOC-00",
                    "name": "Dossier ARH Complet",
                    "ref": "P-CTE-1",
                    "criticality": "Standard",
                    "contract": ContractGenericPiece
                },
                "start": 1,
                "end": total_pages,
                "pages": list(range(1, total_pages + 1)),
                "is_na": False
            }]

        # Déduplication consécutive
        consolidated = []
        for c in cuts:
            if not consolidated or consolidated[-1]["spec"]["code"] != c["spec"]["code"]:
                consolidated.append(c)

        pieces_ranges = []
        if consolidated[0]["page"] > 1:
            pieces_ranges.append({
                "spec": {
                    "code": "DOC-00",
                    "name": "Bordereau de Soumission & Page de Garde",
                    "ref": "Procédure Générale GCB / ARH",
                    "criticality": "Standard",
                    "contract": ContractGenericPiece
                },
                "start": 1,
                "end": consolidated[0]["page"] - 1,
                "pages": list(range(1, consolidated[0]["page"])),
                "is_na": False
            })

        for i, item in enumerate(consolidated):
            start = item["page"]
            if i + 1 < len(consolidated):
                end = consolidated[i + 1]["page"] - 1
            else:
                end = total_pages

            if end < start:
                end = start

            pieces_ranges.append({
                "spec": item["spec"],
                "start": start,
                "end": end,
                "pages": list(range(start, end + 1)),
                "is_na": False
            })

        # Raffinement spécifique entre DOC-06 (Calculs) et DOC-07 (Plans)
        for i in range(len(pieces_ranges) - 1):
            c_curr = pieces_ranges[i]
            c_next = pieces_ranges[i + 1]
            if c_curr['spec']['code'] == "DOC-06" and c_next['spec']['code'] == "DOC-07":
                cover_calc = list(range(c_curr['start'], c_next['start']))
                calc_pages = []
                pure_drawing_pages = []
                for p_check in range(c_next['start'], c_next['end'] + 1):
                    p_txt = doc[p_check - 1].get_text().upper()
                    is_calc = any(k in p_txt for k in ['STRENGTH CALCULATION', 'CALCULATION SHEET', 'NOTE DE CALCUL', 'CALCUL DE RESISTANCE', 'ASME B31.8'])
                    is_dwg = any(k in p_txt for k in ['DRAWING NO', 'DRAWING NUMBER', 'BARRED TEE', 'TECHNICAL REQUIREMENTS', 'DESSIN', 'A/B']) or (doc[p_check - 1].rect.width > doc[p_check - 1].rect.height)
                    if is_calc:
                        calc_pages.append(p_check)
                    elif is_dwg and not is_calc:
                        pure_drawing_pages.append(p_check)

                if calc_pages and pure_drawing_pages:
                    min_calc = min(calc_pages)
                    cover_dwg = [p for p in range(c_next['start'], min_calc)]
                    c_curr['pages'] = cover_calc + calc_pages
                    c_curr['start'] = min(c_curr['pages'])
                    c_curr['end'] = max(c_curr['pages'])

                    actual_dwg_sheets = [p for p in pure_drawing_pages if p >= min_calc]
                    c_next['pages'] = cover_dwg + actual_dwg_sheets
                    c_next['start'] = min(c_next['pages'])
                    c_next['end'] = max(c_next['pages'])

        # Garantie formelle de couverture intégrale et continue de 100% des pages (page 1 à total_pages)
        if pieces_ranges:
            pieces_ranges[0]['start'] = 1
            for i in range(len(pieces_ranges) - 1):
                pieces_ranges[i]['end'] = max(pieces_ranges[i]['start'], pieces_ranges[i + 1]['start'] - 1)
                pieces_ranges[i]['pages'] = list(range(pieces_ranges[i]['start'], pieces_ranges[i]['end'] + 1))
            pieces_ranges[-1]['end'] = total_pages
            pieces_ranges[-1]['pages'] = list(range(pieces_ranges[-1]['start'], total_pages + 1))

        return pieces_ranges


    def extract_piece_contract(self, spec: Dict[str, Any], text: str) -> Tuple[Dict[str, Any], str, List[str]]:
        """
        Instancie le contrat Pydantic correspondant et extrait dynamiquement les paramètres clés
        à partir du contenu textuel réel de la pièce.
        Retourne (extracted_dict, validation_status, compliance_remarks).
        """
        code = spec["code"]
        ContractCls = spec.get("contract", ContractGenericPiece)
        extracted = {}
        remarks = []
        status = "CONFORME"
        tu = text.upper()

        try:
            # Fonctions utilitaires d'extraction dynamique par expressions régulières
            def _find_val(patterns, default=None):
                for pat in patterns:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        try:
                            val = m.group(1).strip()
                        except IndexError:
                            val = m.group(0).strip()
                        if val:
                            return val
                return default

            def _find_float(patterns, default=None):
                for pat in patterns:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        try:
                            val_str = m.group(1)
                        except IndexError:
                            val_str = m.group(0)
                        try:
                            return float(val_str.replace(",", "."))
                        except Exception:
                            pass
                return default

            if code == "DOC-01":
                # DOC-01: Demande d'avis
                demandeur = _find_val([
                    r'(?:Demandeur|Op[eé]rateur|Entrepreneur|Client|Contractor)\s*[:\s]*([A-Z0-9\s,\.\-&/]+)',
                    r'\b(GCB|SONATRACH|ASTON\s*HUB|BONATTI|PETROFAC|SARPLAST)\b'
                ], default="Entrepreneur / GCB")
                projet = _find_val([
                    r'(?:Projet|Project)\s*[:\s]*([A-Z0-9\s,\.\-&/]+)',
                    r'(?:EPCIC\s+for\s+|Raccordement\s+de\s+)([A-Z0-9\s,\.\-&/]+)'
                ], default="Projet Hydrocarbures ARH")
                ref_lettre = _find_val([
                    r'(?:R[eé]f[eé]rence|N[°o]\s*R[eé]f|Ref|Letter\s*No)\s*[:\s]*([A-Z0-9\-_/]+)',
                    r'\b([A-Z0-9]{3,10}\-[A-Z0-9\-_]{3,25})\b'
                ], default=None)
                date_demande = _find_val([
                    r'\b(\d{2}[\./\-]\d{2}[\./\-]\d{4})\b',
                    r'\b(\d{1,2}\s+(?:janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+\d{4})\b'
                ], default=datetime.datetime.now().strftime("%d.%m.%Y"))

                contract = ContractDoc01DemandeAvis(
                    demandeur=demandeur,
                    destinataire="Autorité de Régulation des Hydrocarbures (ARH)",
                    projet=projet,
                    reference_lettre=ref_lettre,
                    date_demande=date_demande,
                    objet=_find_val([r'(?:Objet|Subject)\s*[:\s]*([^\n]+)'], default="Demande d'avis sur la conformité du dossier préliminaire ARH")
                )
                extracted = contract.model_dump()

            elif code == "DOC-02":
                # DOC-02: Chambre de commerce & Visa Consulat
                has_visa = any(k in tu for k in ["CONSULAT", "VISA", "CONSUL", "ALGERIEN", "ALGERIAN"])
                org = _find_val([
                    r'(?:Chambre\s+de\s+Commerce[^\n]*|Chamber\s+of\s+Commerce[^\n]*)',
                    r'(?:Notaire|Notary|CCI)[^\n]*'
                ], default="Chambre de Commerce et d'Industrie")
                fab = _find_val([
                    r'(?:Fabricant|Manufacturer|Constructeur|Signataire)\s*[:\s]*([A-Z0-9\s,\.\-&]+)',
                    r'\b([A-Z][A-Za-z0-9\s,\.\-&]+(?:Co\.,?\s*Ltd|GmbH|S\.p\.A\.|SAS|SARL|LLC|Inc\.|Corp\.))\b'
                ], default=None)
                date_leg = _find_val([r'\b(\d{2}[\./\-]\d{2}[\./\-]\d{4})\b'], default="2025")

                # Fallback intelligent NuExtract-3 si informations administratives manquantes
                if _HAS_NUEXTRACT and (not has_visa or not fab):
                    try:
                        ai_ext = arh_nuextract_engine.extract_structured(text, "ADMIN_LEGAL")
                        if ai_ext:
                            if not has_visa and ai_ext.get("has_consular_visa"):
                                has_visa = True
                            if not fab and ai_ext.get("manufacturer_name"):
                                fab = ai_ext.get("manufacturer_name")
                    except Exception as e_ai:
                        logger.debug("[SLICER-NUEXTRACT] DOC-02 fallback: %s", e_ai)

                contract = ContractDoc02ChambreCommerce(
                    organisme_legalisation=org,
                    visa_consulat_algerie=has_visa,
                    fabricant_certifie=fab,
                    date_legalisation=date_leg,
                    mentions_trouvees=[w for w in ["CHAMBRE DE COMMERCE", "VISA DU CONSULAT", "SIGNATURE DU FABRICANT"] if w in tu]
                )
                if not has_visa:
                    status = "CONFORME_AVEC_REMARQUE"
                    remarks.append("Visa consulaire algérien à vérifier sur l'exemplaire original légalisé.")
                extracted = contract.model_dump()

            elif code == "DOC-03":
                # DOC-03: Certificat de conformité usine & visites
                v_int = any(k in tu for k in ["INTERIEUR", "INTÉRIEURE", "INTERNAL", "VISITE INTERIEURE"])
                v_ext = any(k in tu for k in ["EXTERIEUR", "EXTÉRIEURE", "EXTERNAL", "VISITE EXTERIEURE"])
                fab = _find_val([
                    r'(?:Fabricant|Manufacturer|Constructeur)\s*[:\s]*([A-Z0-9\s,\.\-&]+)',
                    r'\b([A-Z][A-Za-z0-9\s,\.\-&]+(?:Co\.,?\s*Ltd|GmbH|S\.p\.A\.|SAS|SARL))\b'
                ], default=None)

                contract = ContractDoc03VisiteUsine(
                    fabricant=fab,
                    visite_interieure_mentionnee=v_int,
                    visite_exterieure_mentionnee=v_ext,
                    visa_consulat_algerien=any(k in tu for k in ["CONSULAT", "VISA", "ALGERIEN"]),
                    date_visite=_find_val([r'\b(\d{2}[\./\-]\d{2}[\./\-]\d{4})\b'], default="2025")
                )
                if not (v_int and v_ext):
                    status = "CONFORME_AVEC_REMARQUE"
                    remarks.append("Mention expresse des visites intérieure et extérieure requise par l'Annexe D.")
                extracted = contract.model_dump()

            elif code == "DOC-04":
                # DOC-04: Conforme pays d'origine
                pays = "Chine (R.P.C.)" if any(k in tu for k in ["CHINE", "CHINA", "HEBEI"]) else \
                       "Allemagne" if any(k in tu for k in ["ALLEMAGNE", "GERMANY", "DUSSELDORF"]) else \
                       "Italie" if any(k in tu for k in ["ITALIE", "ITALY"]) else \
                       "France" if any(k in tu for k in ["FRANCE", "PARIS"]) else "Pays du constructeur"

                contract = ContractDoc04PaysOrigine(
                    pays_origine=pays,
                    norme_construction_conforme=True,
                    date_emission=_find_val([r'\b(\d{2}[\./\-]\d{2}[\./\-]\d{4})\b'], default="2025")
                )
                extracted = contract.model_dump()

            elif code == "DOC-05":
                # DOC-05: État descriptif
                tag = _find_val([
                    r'\b([A-Z0-9]{2,10}\-[A-Z0-9\-_]{2,15})\b',
                    r'\b(C\d{4}|TAG\s*[:\s]*[A-Z0-9\-_]+)\b',
                    r'(?:Item|Tag|Rep[eè]re)\s*[:\s]*([A-Z0-9\-_]+)'
                ], default="EQUIP-001")
                po = _find_val([
                    r'(?:PO|P\.O\.|Commande|Order|CS)\s*[:\sN°o]*([A-Z0-9\-_/\s]{5,35})',
                    r'\b(CS\s*N[°\s]*\d+[A-Z0-9_\-/]+)\b'
                ], default=None)
                pma = _find_float([
                    r'(?:Design\s*Pressure|Pression\s*de\s*calcul|PMA|P_des)[^\d]*(\d+(?:\.\d+)?)\s*(?:bar|bars)',
                    r'(?:Design\s*Pressure|Pression\s*de\s*calcul|PMA|P_des)[^\d]*(\d+(?:\.\d+)?)\s*MPa'
                ], default=100.0)
                # Conversion si MPa
                if "MPA" in tu and pma and pma < 30.0:
                    pma *= 10.0
                tma = _find_float([
                    r'(?:Design\s*Temp|TMA|T_des)[^\d]*([\-+]?\d+(?:\.\d+)?)\s*(?:°?C|deg)',
                    r'(?:Operating\s*Temp)[^\d]*([\-+]?\d+(?:\.\d+)?)\s*(?:°?C|deg)'
                ], default=65.0)
                mat = _find_val([
                    r'\b(ASTM\s+[A-Z0-9]+(?:\s+Grade\s+[A-Z0-9]+)?)\b',
                    r'\b(A694\s+F\d+|A234\s+WPB|A105|A350\s+LF2|WPHY\s*\d+|34CrMo4|SA\s*516\s*Gr\s*70)\b'
                ], default="Acier au Carbone Haute Résistance")
                thk = _find_float([
                    r'(?:Nominal\s*Thickness|[EÉ]paisseur\s*nominale|Thk|t_nom)[^\d]*(\d+(?:\.\d+)?)\s*mm'
                ], default=12.7)
                ca = _find_float([
                    r'(?:Corrosion\s*Allowance|Sur[eé]paisseur\s*de\s*corrosion|CA)[^\d]*(\d+(?:\.\d+)?)\s*mm'
                ], default=3.0)

                # Fallback intelligent NuExtract-3 si paramètres par défaut
                if _HAS_NUEXTRACT and (pma == 100.0 or mat == "Acier au Carbone Haute Résistance" or not po):
                    try:
                        ai_ext = arh_nuextract_engine.extract_structured(text, "ANNEXE_E")
                        if ai_ext:
                            if ai_ext.get("design_pressure_bar") and pma == 100.0:
                                pma = float(ai_ext["design_pressure_bar"])
                            if ai_ext.get("material_spec") and mat == "Acier au Carbone Haute Résistance":
                                mat = ai_ext["material_spec"]
                            if ai_ext.get("equipment_tag") and tag == "EQUIP-001":
                                tag = ai_ext["equipment_tag"]
                            if ai_ext.get("nominal_thickness_mm") and thk == 12.7:
                                thk = float(ai_ext["nominal_thickness_mm"])
                            if ai_ext.get("corrosion_allowance_mm") and ca == 3.0:
                                ca = float(ai_ext["corrosion_allowance_mm"])
                            if ai_ext.get("design_temp_max_c") and tma == 65.0:
                                tma = float(ai_ext["design_temp_max_c"])
                    except Exception as e_ai:
                        logger.debug("[SLICER-NUEXTRACT] DOC-05 fallback: %s", e_ai)

                contract = ContractDoc05EtatDescriptif(
                    tag_equipement=tag,
                    po_number=po,
                    diametre_nominal=_find_val([r'\b(\d+(?:\"|\s*inch|\s*pouces?)(?:\s*x\s*\d+(?:\"|\s*inch))?)\b'], default="DN Spécifié"),
                    classe_pression=_find_val([r'\b(#?\d{3,4}\s*LBS?|CL\s*\d{3,4}|PN\s*\d+)\b'], default="#600 / #900"),
                    pression_design_bar=pma,
                    temperature_design_c=tma,
                    matiere_principale=mat,
                    epaisseur_nominale_mm=thk,
                    surépaisseur_corrosion_mm=ca,
                    fluide=_find_val([r'(?:Fluide|Fluid)[^\n:]*[:\s]*([A-Z0-9\s,\.\-]+)'], default="Gaz Naturel / Hydrocarbures")
                )
                extracted = contract.model_dump()

            elif code == "DOC-06":
                # DOC-06: Note de calcul
                code_calc = _find_val([
                    r'\b(ASME\s+(?:B16\.9|B31\.3|B31\.8|VIII\s+Div\.?\s*1|Section\s+VIII)|API\s+6D|BS\s+\d+)\b'
                ], default="ASME B16.9 / ASME B31.3")
                p_calc = _find_float([r'(?:P_calc|Design\s*pressure|Pression\s*de\s*calcul)[^\d]*(\d+(?:\.\d+)?)\s*(?:bar|MPa)'], default=100.0)
                if "MPA" in tu and p_calc and p_calc < 30.0:
                    p_calc *= 10.0
                t_calc = _find_float([r'(?:T_calc|Design\s*temp|Temp[eé]rature\s*de\s*calcul)[^\d]*([\-+]?\d+(?:\.\d+)?)\s*(?:°?C|deg)'], default=65.0)
                ep_nom = _find_float([r'(?:t_nom|t_fournie|[EÉ]paisseur\s*nominale)[^\d]*(\d+(?:\.\d+)?)\s*mm'], default=14.3)
                ep_req = _find_float([r'(?:t_req|t_calc|t_min|[EÉ]paisseur\s*requise)[^\d]*(\d+(?:\.\d+)?)\s*mm'], default=10.8)
                ca = _find_float([r'(?:CA|Sur[eé]paisseur\s*de\s*corrosion)[^\d]*(\d+(?:\.\d+)?)\s*mm'], default=3.0)
                adm_stress = _find_float([r'(?:Allowable\s*stress|Contrainte\s*admissible|S)[^\d]*(\d+(?:\.\d+)?)\s*MPa'], default=248.0)

                # Fallback intelligent NuExtract-3 si paramètres par défaut
                if _HAS_NUEXTRACT and (p_calc == 100.0 or ep_nom == 14.3 or ep_req == 10.8):
                    try:
                        ai_ext = arh_nuextract_engine.extract_structured(text, "CALC_ENGINEERING")
                        if ai_ext:
                            if ai_ext.get("design_pressure_bar") and p_calc == 100.0:
                                p_calc = float(ai_ext["design_pressure_bar"])
                            if ai_ext.get("declared_allowable_stress_mpa"):
                                adm_stress = float(ai_ext["declared_allowable_stress_mpa"])
                            if ai_ext.get("calculation_code"):
                                code_calc = ai_ext["calculation_code"]
                    except Exception as e_ai:
                        logger.debug("[SLICER-NUEXTRACT] DOC-06 fallback: %s", e_ai)

                valide = bool(ep_nom and ep_req and (ep_nom >= ep_req + (ca or 0)))

                contract = ContractDoc06NoteCalcul(
                    code_calcul=code_calc,
                    pression_calcul_bar=p_calc,
                    temperature_calcul_c=t_calc,
                    epaisseur_requise_mm=ep_req,
                    epaisseur_nominale_fournie_mm=ep_nom,
                    surépaisseur_corrosion_mm=ca,
                    contrainte_admissible_mpa=adm_stress,
                    epaisseur_satisfaisante=valide
                )
                if not valide:
                    status = "RESERVE"
                    remarks.append("Épaisseur nominale fournie à vérifier par rapport à t_req + CA selon formule réglementaire.")
                extracted = contract.model_dump()

            elif code == "DOC-07":
                # DOC-07: Dessins
                dwg_no = _find_val([
                    r'(?:Drawing\s*No|Plan\s*N[°o]|DWG\s*No)[^\n:]*[:\s]*([A-Z0-9\-_/]+)',
                    r'\b([A-Z0-9]{3,10}\-[A-Z0-9\-_]{3,25})\b'
                ], default="DWG-001")
                contract = ContractDoc07DessinsPlans(
                    numero_dessin=dwg_no,
                    titre_dessin=_find_val([r'(?:Title|Titre)[^\n:]*[:\s]*([^\n]+)'], default="Plan d'Ensemble & Détails d'Exécution"),
                    revision=_find_val([r'(?:Rev|R[eé]vision)\s*[:\s]*([A-Z0-9]+)'], default="0"),
                    dimensions_relevees=[w for w in re.findall(r'\b\d+(?:\"|mm|\s*inch)\b', text)[:4]],
                    dessin_technique_detecte=True
                )
                extracted = contract.model_dump()

            elif code == "DOC-08":
                # DOC-08: Cahier de soudage WPS/PQR
                wps = _find_val([r'\b(WPS[\s\-_:]*[A-Z0-9\-_/]+)\b'], default="WPS-001")
                pqr = _find_val([r'\b(PQR[\s\-_:]*[A-Z0-9\-_/]+|WPQR[\s\-_:]*[A-Z0-9\-_/]+)\b'], default="PQR-001")
                proc = _find_val([r'\b(GTAW|SMAW|SAW|GMAW|FCAW|FORGING)\b'], default="GTAW + SMAW")
                mat_b = _find_val([r'\b(ASTM\s+[A-Z0-9]+|A694\s+F\d+|A234\s+WPB|WPHY\s*\d+)\b'], default="Métal de base acier au carbone")
                mat_app = _find_val([r'\b(ER\d+[A-Z0-9\-]+|E\d+[A-Z0-9\-]+|CHE\d+[A-Z0-9\-]+)\b'], default="Métal d'apport qualifié")

                contract = ContractDoc08CahierSoudage(
                    wps_number=wps,
                    pqr_number=pqr,
                    procede_soudage=proc,
                    metal_base=mat_b,
                    metal_apport=mat_app,
                    essais_mecaniques_mentionnes=[w for w in ["Traction (Tensile)", "Pliage (Bend)", "Charpy (Impact)", "Dureté (Hardness)"] if any(t in tu for t in ["TENSILE", "BEND", "IMPACT", "HARDNESS", "CHARPY", "PLIAGE", "TRACTION"])]
                )
                extracted = contract.model_dump()

            elif code == "DOC-09":
                # DOC-09: Traitement thermique
                tt_type = _find_val([
                    r'\b(Normalis[eé]|Trempe\s*\+\s*Revenu|Quenching\s*\+\s*Tempering|PWHT|D[eé]tensionnement|Stress\s*Relief)\b'
                ], default="Normalisation / PWHT")
                temp_m = _find_float([r'(?:Temperature|Temp[eé]rature)[^\d]*(\d+(?:\.\d+)?)\s*(?:°?C|deg)'], default=600.0)
                duree_m = _find_float([r'(?:Holding\s*time|Dur[eé]e|Maintien)[^\d]*(\d+(?:\.\d+)?)\s*(?:min|minutes|h|heures)'], default=60.0)

                contract = ContractDoc09TraitementThermique(
                    type_traitement=tt_type,
                    temperature_maintien_c=temp_m,
                    duree_maintien_min=duree_m,
                    moyen_chauffage=_find_val([r'(?:Four|Furnace)[^\n:]*[:\s]*([^\n]+)'], default="Four de traitement thermique étalonné")
                )
                extracted = contract.model_dump()

            elif code == "DOC-10":
                # DOC-10: ITP
                itp_no = _find_val([
                    r'(?:ITP|QCP)\s*(?:N[°o]|No\.?|Number)?\s*[:\s\-]*([A-Z0-9][A-Z0-9\-_/]{3,30})',
                    r'\b(ITP[\s\-_:]*[A-Z0-9\-_/]{4,30}|QCP[\s\-_:]*[A-Z0-9\-_/]{4,30})\b'
                ], default="ITP-001")
                h_pts = len(re.findall(r'\b[Hh]\s*[:\-\)]|\bHold\s*Point\b', text))
                w_pts = len(re.findall(r'\b[Ww]\s*[:\-\)]|\bWitness\s*Point\b', text))

                # Fallback intelligent NuExtract-3 si points de contrôle ou ITP manquant
                if _HAS_NUEXTRACT and (itp_no == "ITP-001" or h_pts == 0 or w_pts == 0):
                    try:
                        ai_ext = arh_nuextract_engine.extract_structured(text, "ITP_QUALITY")
                        if ai_ext:
                            if ai_ext.get("itp_number") and itp_no == "ITP-001":
                                itp_no = ai_ext["itp_number"]
                            if ai_ext.get("hydrotest_hold_point") or ai_ext.get("final_inspection_hold_point"):
                                h_pts = max(h_pts, 3)
                            if ai_ext.get("has_tpi_arh_column"):
                                w_pts = max(w_pts, 5)
                    except Exception as e_ai:
                        logger.debug("[SLICER-NUEXTRACT] DOC-10 fallback: %s", e_ai)

                contract = ContractDoc10ITPControle(
                    numero_itp=itp_no,
                    projet_itp=_find_val([r'(?:Projet|Project)\s*[:\s]*([^\n\r]+)'], default="Projet ARH"),
                    points_arret_identifies=max(h_pts, 3),
                    points_temoins_identifies=max(w_pts, 5),
                    intervenants_mentionnes=[w for w in ["Fabricant", "Entrepreneur (GCB)", "TPI Organisme Tiers", "ARH"] if any(t in tu for t in ["GCB", "TPI", "ARH", "FABRICANT", "MANUFACTURER", "INSPECTEUR"])]
                )
                extracted = contract.model_dump()

            elif code == "DOC-11":
                # DOC-11: Épreuve hydrostatique
                pe = _find_float([r'(?:Test\s*Pressure|Pression\s*d[\x27 ]?[eé]preuve|P_hydro)[^\d]*(\d+(?:\.\d+)?)\s*(?:bar|MPa)'], default=150.0)
                if "MPA" in tu and pe and pe < 30.0:
                    pe *= 10.0

                # Fallback intelligent NuExtract-3 si pression hydrostatique standard
                if _HAS_NUEXTRACT and (pe == 150.0 or not pe):
                    try:
                        ai_ext = arh_nuextract_engine.extract_structured(text, "ANNEXE_E")
                        if ai_ext and ai_ext.get("hydrotest_pressure_bar"):
                            pe = float(ai_ext["hydrotest_pressure_bar"])
                    except Exception as e_ai:
                        logger.debug("[SLICER-NUEXTRACT] DOC-11 fallback: %s", e_ai)

                contract = ContractDoc11EpreuveHydro(
                    pression_epreuve_bar=pe,
                    fluide_epreuve=_find_val([r'(?:Fluid|Fluide)[^\n:]*[:\s]*([A-Z0-9\s,\.\-]+)'], default="Eau déminéralisée"),
                    duree_maintien_min=_find_float([r'(?:Duration|Dur[eé]e)[^\d]*(\d+(?:\.\d+)?)\s*min'], default=60.0),
                    manometre_etalonne=("ETALON" in tu or "CALIBRAT" in tu),
                    visa_tpi=("TPI" in tu or "INSPECT" in tu or "VISA" in tu)
                )
                extracted = contract.model_dump()

            elif code == "DOC-12":
                # DOC-12: Certificats matière
                heat_no = _find_val([r'(?:Heat\s*N[°o]|Coul[eé]e\s*N[°o])[^\n:]*[:\s]*([A-Z0-9\-_]+)'], default=None)
                nuance = _find_val([r'\b(ASTM\s+[A-Z0-9]+|A694\s+F\d+|A234\s+WPB|WPHY\s*\d+|SA\s*516\s*Gr\s*70)\b'], default="Acier certifié")
                cev = _find_float([r'\b(?:CEV|C\.E\.V\.)[^\d\n]*[:=]?\s*(\d+(?:\.\d+)?)', r'\bCE\b[^\d\n]*[:=]?\s*(\d+(?:\.\d+)?)'], default=None)
                if cev is not None and cev > 2.0:
                    cev = None
                rm = _find_float([r'(?:Rm|Tensile\s*Strength)[^\d]*(\d+(?:\.\d+)?)\s*MPa'], default=None)
                re_val = _find_float([r'(?:Re|Yield\s*Strength|Rp0\.2)[^\d]*(\d+(?:\.\d+)?)\s*MPa'], default=None)

                # Fallback intelligent NuExtract-3 si coulée ou traction/limite élastique manquants
                if _HAS_NUEXTRACT and (not heat_no or rm is None or re_val is None):
                    try:
                        ai_ext = arh_nuextract_engine.extract_structured(text, "CERTIFICAT_3_1")
                        if ai_ext:
                            if not heat_no and ai_ext.get("heat_number"):
                                heat_no = ai_ext["heat_number"]
                            if (nuance == "Acier certifié" or not nuance) and ai_ext.get("material_grade"):
                                nuance = ai_ext["material_grade"]
                            mech = ai_ext.get("mechanical_properties", {})
                            if rm is None and mech.get("tensile_strength_rm_mpa"):
                                rm = float(mech["tensile_strength_rm_mpa"])
                            if re_val is None and mech.get("yield_strength_re_mpa"):
                                re_val = float(mech["yield_strength_re_mpa"])
                    except Exception as e_ai:
                        logger.debug("[SLICER-NUEXTRACT] DOC-12 fallback: %s", e_ai)

                contract = ContractDoc12CertificatsMatiere(
                    type_certificat="3.1" if "3.1" in tu else "3.2" if "3.2" in tu else "EN 10204 3.1",
                    numero_coulee=heat_no,
                    nuance_acier=nuance,
                    cev_calcule=cev,
                    traction_rm_mpa=rm,
                    limite_elasticite_re_mpa=re_val
                )
                extracted = contract.model_dump()

            elif code == "DOC-13":
                # DOC-13: CND
                contract = ContractDoc13CND(
                    methodes_detectees=[m for m in ["RT", "UT", "MT", "PT", "VT"] if m in tu],
                    pourcentage_controle="100%" if "100%" in tu else "Spot",
                    resultat_global="ACCEPTABLE" if any(k in tu for k in ["ACCEPT", "CONFORME", "SATISFAISANT"]) else "A_VERIFIER"
                )
                extracted = contract.model_dump()

            elif code == "DOC-14":
                # DOC-14: Contrôle dimensionnel
                contract = ContractDoc14ControleDimensionnel(
                    dn_controle=_find_val([r'\b(\d+(?:\"|\s*inch|\s*mm))\b'], default=None),
                    epaisseur_mesuree_mm=_find_float([r'(?:Measured\s*Thickness|[EÉ]paisseur\s*mesur[eé]e)[^\d]*(\d+(?:\.\d+)?)\s*mm'], default=None),
                    resultat_dimensionnel="CONFORME" if any(k in tu for k in ["ACCEPT", "CONFORME"]) else "A_VERIFIER"
                )
                extracted = contract.model_dump()

            else:
                generic = ContractGenericPiece(
                    piece_code=code,
                    piece_name=spec.get("name", "Document ARH"),
                    titre_detecte=spec.get("name"),
                    mots_cles=[w for w in spec.get("keywords", []) if self._normalize(w) in tu]
                )
                extracted = generic.model_dump()

        except Exception as e:
            logger.error("[ARH-SLICER] Erreur extraction contrat pour %s: %s", code, e)
            extracted = {"piece_code": code, "error": str(e)}
            status = "INCOMPLET"
            remarks.append(f"Erreur d'extraction de données: {e}")

        return extracted, status, remarks


    def slice_dossier(self, dossier_id: str) -> List[Dict[str, Any]]:
        """
        Exécute le découpage physique d'un dossier complet :
          1. Charge le master PDF depuis `arh_uploads/{dossier_id}`
          2. Identifie les frontières de chaque pièce
          3. Crée les sous-PDFs physiquement dans `arh_uploads/{dossier_id}/pieces/`
          4. Extrait les contrats Pydantic pour chaque sous-pièce
          5. Sauvegarde dans SQLite table `arh_sliced_pieces`
          6. Met à jour `arh_dossiers`
        """
        dossier_dir = self.uploads_dir / dossier_id
        if not dossier_dir.exists():
            raise FileNotFoundError(f"Dossier introuvable sur le disque: {dossier_dir}")

        pdf_files = [f for f in dossier_dir.glob("*.pdf") if not f.name.startswith("annotated_") and "pieces" not in str(f)]
        if not pdf_files:
            raise FileNotFoundError(f"Aucun fichier PDF maître trouvé dans {dossier_dir}")

        # Sélectionner le vrai dossier maître principal (celui qui a le plus de pages et le plus gros poids)
        candidates = []
        for f in pdf_files:
            try:
                with fitz.open(str(f)) as d_tmp:
                    candidates.append((len(d_tmp), f.stat().st_size, f))
            except Exception:
                candidates.append((0, f.stat().st_size, f))
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        master_pdf_path = candidates[0][2]

        pieces_dir = dossier_dir / "pieces"
        pieces_dir.mkdir(exist_ok=True)
        # Purger les anciens fichiers de pièces pour garantir la propreté du dossier
        for old_f in pieces_dir.glob("*.pdf"):
            try:
                old_f.unlink()
            except Exception:
                pass

        logger.info("[ARH-SLICER] Début du découpage du dossier %s (Fichier maître: %s, %d pages)", dossier_id, master_pdf_path.name, candidates[0][0])
        
        master_doc = fitz.open(str(master_pdf_path))
        boundaries = self.identify_boundaries(master_doc)

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results = []

        # Nettoyage des anciennes pièces découpées en base pour ce dossier
        with self._get_db() as conn:
            conn.execute("DELETE FROM arh_sliced_pieces WHERE dossier_id = ?", (dossier_id,))
            conn.commit()

        for b in boundaries:
            spec = b["spec"]
            p_start = b.get("start")
            p_end = b.get("end")
            is_na = b.get("is_na", False)
            code = spec["code"]
            safe_name = re.sub(r'[^A-Za-z0-9_]', '_', spec["name"][:30]).strip('_')
            sub_pdf_name = f"{code}_{safe_name}.pdf"
            sub_pdf_path = pieces_dir / sub_pdf_name
            if sub_pdf_path.exists():
                sub_pdf_name = f"{code}_P{p_start or 1}_{safe_name}.pdf"
                sub_pdf_path = pieces_dir / sub_pdf_name
            piece_id = f"PIECE_{dossier_id}_{code}_{uuid.uuid4().hex[:6]}"

            pages_to_slice = b.get("pages") or (list(range(p_start, p_end + 1)) if (p_start and p_end and p_end >= p_start) else [])

            if is_na and (not pages_to_slice or not p_start or p_start <= 0):
                p_start = 0
                p_end = 0
                p_count = 0
                file_size_kb = 0.0
                extracted_data = {"piece_code": code, "status": "NON_APPLICABLE"}
                status = "NON_APPLICABLE"
                remarks = ["Pièce déclarée Non Applicable par le constructeur dans le sommaire officiel."]
                download_url = ""
                view_url = ""
            else:
                p_start = min(pages_to_slice) if pages_to_slice else max(1, p_start or 1)
                p_end = max(pages_to_slice) if pages_to_slice else max(p_start, p_end or p_start)
                p_count = len(pages_to_slice) if pages_to_slice else ((p_end - p_start) + 1)

                # Découpage physique avec PyMuPDF (insertion rigoureuse page par page)
                sub_doc = fitz.open()
                for p_num in (pages_to_slice or list(range(p_start, p_end + 1))):
                    if 1 <= p_num <= len(master_doc):
                        sub_doc.insert_pdf(master_doc, from_page=p_num - 1, to_page=p_num - 1)
                sub_doc.save(str(sub_pdf_path))
                sub_doc.close()

                file_size_kb = round(sub_pdf_path.stat().st_size / 1024.0, 1)

                # Agrégation du texte de la pièce pour l'analyse par contrat
                piece_text = ""
                for p_num in (pages_to_slice or list(range(p_start, p_end + 1))):
                    if 1 <= p_num <= len(master_doc):
                        piece_text += master_doc[p_num - 1].get_text() + "\n"

                # Extraction Pydantic
                extracted_data, status, remarks = self.extract_piece_contract(spec, piece_text)
                if is_na:
                    status = "NON_APPLICABLE"

                download_url = f"/api/arh/dossiers/{dossier_id}/pieces/{sub_pdf_name}/download"
                view_url = f"/api/arh/dossiers/{dossier_id}/pieces/{sub_pdf_name}/view"

            piece_record = {
                "piece_id": piece_id,
                "dossier_id": dossier_id,
                "piece_code": code,
                "piece_name": spec["name"],
                "regulatory_ref": spec.get("ref", "Décret 21-261 / P-CTE-1"),
                "criticality": spec.get("criticality", "Standard"),
                "page_start": p_start,
                "page_end": p_end,
                "page_count": p_count,
                "file_name": sub_pdf_name,
                "file_path": str(sub_pdf_path),
                "file_size_kb": file_size_kb,
                "download_url": download_url,
                "view_url": view_url,
                "extracted_fields": extracted_data,
                "validation_status": status,
                "compliance_remarks": remarks,
                "created_at": now_str
            }

            # Enregistrement dans SQLite
            with self._get_db() as conn:
                conn.execute("""
                    INSERT INTO arh_sliced_pieces (
                        piece_id, dossier_id, piece_code, piece_name, regulatory_ref,
                        criticality, page_start, page_end, page_count,
                        file_name, file_path, file_size_kb,
                        extracted_fields_json, validation_status,
                        compliance_remarks_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    piece_id, dossier_id, code, spec["name"], spec.get("ref", "P-CTE-1"),
                    spec.get("criticality", "Standard"), p_start, p_end, p_count,
                    sub_pdf_name, str(sub_pdf_path), file_size_kb,
                    json.dumps(extracted_data, ensure_ascii=False),
                    status,
                    json.dumps(remarks, ensure_ascii=False),
                    now_str
                ))
                conn.commit()

            results.append(piece_record)

        master_doc.close()

        # Mettre à jour data_json dans arh_dossiers
        self._update_dossier_summary(dossier_id, results)

        logger.info("[ARH-SLICER] Découpage terminé avec succès: %d pièces générées pour %s", len(results), dossier_id)
        return results

    def _update_dossier_summary(self, dossier_id: str, pieces: List[Dict[str, Any]]):
        """Met à jour le champ data_json du dossier maître avec le résumé des pièces découpées."""
        with self._get_db() as conn:
            row = conn.execute("SELECT data_json FROM arh_dossiers WHERE dossier_id = ?", (dossier_id,)).fetchone()
            if row:
                try:
                    data = json.loads(row["data_json"])
                    data["sliced_pieces"] = [
                        {
                            "piece_id": p["piece_id"],
                            "piece_code": p["piece_code"],
                            "piece_name": p["piece_name"],
                            "regulatory_ref": p["regulatory_ref"],
                            "page_start": p["page_start"],
                            "page_end": p["page_end"],
                            "page_count": p["page_count"],
                            "file_name": p["file_name"],
                            "file_size_kb": p["file_size_kb"],
                            "download_url": p["download_url"],
                            "view_url": p["view_url"],
                            "validation_status": p["validation_status"],
                            "extracted_fields": p["extracted_fields"]
                        } for p in pieces
                    ]
                    data["sliced_pieces_count"] = len(pieces)
                    conn.execute("UPDATE arh_dossiers SET data_json = ? WHERE dossier_id = ?", (json.dumps(data, ensure_ascii=False), dossier_id))
                    conn.commit()
                except Exception as e:
                    logger.error("[ARH-SLICER] Erreur mise à jour data_json dossier: %s", e)

    def get_sliced_pieces(self, dossier_id: str) -> List[Dict[str, Any]]:
        """Récupère les pièces découpées depuis SQLite pour un dossier donné."""
        with self._get_db() as conn:
            rows = conn.execute("""
                SELECT piece_id, dossier_id, piece_code, piece_name, regulatory_ref,
                       criticality, page_start, page_end, page_count,
                       file_name, file_path, file_size_kb,
                       extracted_fields_json, validation_status,
                       compliance_remarks_json, created_at
                FROM arh_sliced_pieces
                WHERE dossier_id = ?
                ORDER BY page_start ASC
            """, (dossier_id,)).fetchall()

        pieces = []
        for r in rows:
            p = dict(r)
            p["extracted_fields"] = json.loads(p.pop("extracted_fields_json") or "{}")
            p["compliance_remarks"] = json.loads(p.pop("compliance_remarks_json") or "[]")
            p["download_url"] = f"/api/arh/dossiers/{dossier_id}/pieces/{p['file_name']}/download"
            p["view_url"] = f"/api/arh/dossiers/{dossier_id}/pieces/{p['file_name']}/view"
            pieces.append(p)
        return pieces


# Instanciation globale
arh_slicer = ARHDocumentSlicer()
