"""
ARQAN Plan Engine - Couche 1 : Orchestrateur & Routeur de Plans
Classifie automatiquement le document entrant parmi TOUTES les disciplines industrielles :
P&ID, Isométrique, Structure, Génie Civil, Électricité (Force & Chemins de câbles),
Instrumentation (Boucles & JB), Télécom & SCADA / F&G, CVC / HVAC, VRD et Architecture.
"""

import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("plan_engine.router")

DISCIPLINE_PATTERNS = {
    "pid": [
        r'\b(P&ID|PID|PIPING\s*&\s*INSTRUMENTATION|PROCESS\s*FLOW|PFD)\b',
        r'\b(\d+)"-[A-Z]{2,4}-\d{3,5}-[A-Z0-9]+\b',
        r'\b(VALVE|PUMP|COMPRESSOR|VESSEL|SEPARATOR|EXCHANGER|FLARE)\b',
        r'\b([0-9]{2}-[A-Z]{1,4}-[0-9]{3,4}[A-Z]?)\b'
    ],
    "isometric": [
        r'\b(ISOMETRIC|ISOMÉTRIQUE|PIPING\s*ISOMETRIC)\b',
        r'\b(SPOOL|TRONÇON|CUT\s*PIPE)\b',
        r'\b(FIELD\s*WELD|SHOP\s*WELD|FW\b|WS\b)',
        r'\b(SLOPE\s*\d|PENTE\s*\d)'
    ],
    "steel": [
        r'\b(CHARPENTE|STRUCTURE|STRUCTURAL\s*STEEL|OSSATURE)\b',
        r'\b(IPE\s*\d{3}|HEA\s*\d{3}|HEB\s*\d{3}|UPN\s*\d{3})\b',
        r'\b(RAIDISSEUR|PLATINE|GOUSSET|CONTREVENTEMENT|PORTIQUE)\b',
        r'\b(EN\s*10365|EUROCODE\s*3|AISC)\b'
    ],
    "civil": [
        r'\b(GÉNIE\s*CIVIL|GENIE\s*CIVIL|CIVIL\s*WORKS|FONDATION|FOUNDATION)\b',
        r'\b(SEMELLE|SEM\b|FND\b|RADIER|PIEU|MASSAGIER|BETON|BÉTON|COFFRAGE|FERRAILLAGE)\b',
        r'\b(ACI\s*318|EUROCODE\s*2|BAEL)\b',
        r'\b(HA\d{2}\b|FeE\s*500)'
    ],
    "electrical": [
        r'\b(SLD|UNIFILAIRE|SINGLE\s*LINE\s*DIAGRAM|SCHÉMA\s*ÉLECTRIQUE|POSTE\s*ÉLECTRIQUE)\b',
        r'\b(TGBT|MCC|TRANSFORMATEUR|TRANSFORMER|DISJONCTEUR|BREAKER|CELLULE\s*HTA)\b',
        r'\b(CBL-PWR|CHEMIN\s*DE\s*CÂBLES?|CT-PWR|CT-HTA|ÉCHELLE\s*À\s*CÂBLES)\b',
        r'\b(IEC\s*61439|IEC\s*60947|IEC\s*60076|IEC\s*60364)\b',
        r'\b(\d+\s*(?:kVA|MVA|kW|kV|A)\b)'
    ],
    "instrumentation": [
        r'\b(INSTRUMENTATION|BOUCLE\s*INSTRUMENT|LOOP\s*DIAGRAM|CARNET\s*DE\s*CÂBLES\s*INST)\b',
        r'\b(JB-INST|JB-ESD|JB-\d+|BOÎTE\s*DE\s*JONCTION|BORNIER)\b',
        r'\b(CBL-INST|MP-CBL|MULTIPAIRE|\d+\s*PAIRES?\s*x|TIERCE|1P\s*x\s*1\.5)\b',
        r'\b(4-20\s*mA|HART|SÉCURITÉ\s*INTRINSÈQUE|EX\s*IA|ZÔNE\s*ATEX)\b',
        r'\b(CT-INST|CT-IS|CHEMIN\s*INSTRUMENTATION)\b'
    ],
    "telecom": [
        r'\b(TÉLÉCOM|TELECOM|COURANTS\s*FAIBLES|SCADA|FIBRE\s*OPTIQUE|OPTICAL\s*FIBER)\b',
        r'\b(FO-CBL|ODF|TIROIR\s*OPTIQUE|CAT6A|CAT7|BAIE\s*DE\s*BRASSAGE)\b',
        r'\b(CCTV|CAMÉRA|CAMERA|SURVEILLANCE|VMS)\b',
        r'\b(F&G|FEU\s*ET\s*GAZ|FIRE\s*&\s*GAS|DÉTECTEUR\s*FLAMME|IR3|CR1-C1)\b',
        r'\b(CT-TEL|CT-FO|CHEMIN\s*TÉLÉCOM)\b'
    ],
    "hvac": [
        r'\b(CVC|HVAC|VENTILATION|CLIMATISATION|AIR\s*CONDITIONING|AÉRAULIQUE)\b',
        r'\b(CTA\b|AHU\b|CENTRALE\s*DE\s*TRAITEMENT\s*D\'AIR|GAINE\s*DE\s*VENTILATION)\b',
        r'\b(DIFFUSEUR|CLAPET\s*COUPE-FEU|VCF\b|REG-\d+|VOLET\s*DE\s*SURPRESSION)\b',
        r'\b(SURPRESSION\s*\+?50\s*PA|EN\s*1886|SMACNA|EN\s*15650)\b'
    ],
    "architectural": [
        r'\b(ARCHITECTURE|ARCHITECTURAL|PLAN\s*DE\s*MASSE|REZ-DE-CHAUSSÉE|RDC|ÉTAGE)\b',
        r'\b(CLOISON|MENUISERIE|OUVERTURE|FAÇADE|COUPE\s*AA)\b'
    ],
    "vrd": [
        r'\b(VRD|RÉSEAUX\s*DIVERS|ASSAINISSEMENT|SEWER|STORMWATER)\b',
        r'\b(CHAMBRE\s*DE\s*TIRAGE|REGARD|CANALISATION\s*ENTERRÉE|EAUX\s*PLUVIALES)\b'
    ]
}

MODEL_DISPATCH_MAP = {
    "pid": ["m01_pid_symbols", "m02_technical_ocr", "m03_line_tracer", "m04_control_loops", "m06_flow_direction", "m15_legends_standards", "m16_title_block_ocr"],
    "isometric": ["m02_technical_ocr", "m05_isometric_parser", "m06_flow_direction", "m12_dimensions_scaler", "m15_legends_standards", "m16_title_block_ocr"],
    "steel": ["m02_technical_ocr", "m08_structural_steel", "m12_dimensions_scaler", "m15_legends_standards", "m16_title_block_ocr"],
    "civil": ["m02_technical_ocr", "m09_foundations_geotech", "m12_dimensions_scaler", "m15_legends_standards", "m16_title_block_ocr"],
    "electrical": ["m02_technical_ocr", "m13_sld_unifilar", "m12_dimensions_scaler", "m15_legends_standards", "m16_title_block_ocr"],
    "instrumentation": ["m02_technical_ocr", "m04_control_loops", "m14_cabling_instrument", "m15_legends_standards", "m16_title_block_ocr"],
    "telecom": ["m02_technical_ocr", "m17_telecom_scada_cctv", "m15_legends_standards", "m16_title_block_ocr"],
    "hvac": ["m02_technical_ocr", "m18_hvac_ventilation_ducts", "m15_legends_standards", "m16_title_block_ocr"],
    "architectural": ["m10_architectural", "m12_dimensions_scaler", "m16_title_block_ocr"],
    "vrd": ["m02_technical_ocr", "m11_underground_vrd", "m12_dimensions_scaler", "m16_title_block_ocr"]
}

class PlanRouter:
    """Orchestrateur Couche 1 : Détecte le type de plan et configure les pipelines de la Couche 2 & 3."""

    def __init__(self):
        self.patterns = {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in DISCIPLINE_PATTERNS.items()}

    def route_document(self, text_content: str, filename: str = "", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        combined_text = f"{filename} {text_content}".strip()
        scores = {disc: 0 for disc in DISCIPLINE_PATTERNS}
        matched_tags = {disc: [] for disc in DISCIPLINE_PATTERNS}

        for disc, pat_list in self.patterns.items():
            for pat in pat_list:
                matches = pat.findall(combined_text)
                if matches:
                    scores[disc] += len(matches) * 2
                    matched_tags[disc].extend([m if isinstance(m, str) else m[0] for m in matches[:3]])

        # Boosters contextuels
        if re.search(r'\b(FO-CBL|ODF|CCTV|F&G|SCADA|RTU)\b', combined_text, re.I):
            scores["telecom"] += 8
        if re.search(r'\b(CTA|AHU|VCF|GAINE|DIFFUSEUR)\b', combined_text, re.I):
            scores["hvac"] += 8
        if re.search(r'\b(JB-INST|CBL-INST|MP-CBL|BOUCLE)\b', combined_text, re.I):
            scores["instrumentation"] += 8
        if re.search(r'\b(CBL-PWR|CT-PWR|TGBT|MCC|DISJONCTEUR)\b', combined_text, re.I):
            scores["electrical"] += 8

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_disc, top_score = ranked[0]

        if top_score == 0:
            top_disc = "pid"
            confidence = 0.50
        else:
            confidence = round(min(0.99, max(0.65, top_score / (top_score + 3))), 2)

        models = MODEL_DISPATCH_MAP.get(top_disc, MODEL_DISPATCH_MAP["pid"])
        agents = ["agent_aggregator", "agent_reporter", "agent_cross_validator"]
        if top_disc in ("pid", "isometric"):
            agents.insert(0, "agent_line_list")

        logger.info(f"[Router] Plan identifié : {top_disc.upper()} (Confiance: {confidence*100:.1f}%)")

        return {
            "primary_discipline": top_disc,
            "confidence": confidence,
            "scores": scores,
            "matched_indicators": matched_tags[top_disc],
            "dispatched_models": models,
            "orchestrated_agents": agents
        }

plan_router = PlanRouter()
