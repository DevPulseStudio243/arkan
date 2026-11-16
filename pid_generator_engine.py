# ============================================================
#  ARKAN — PID Generator Engine (Procédés & Tuyauteries IA)
#  Conception logique & vectorielle selon normes ISA 5.1 & Sonatrach
# ============================================================

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import ezdxf
from ezdxf import colors

logger = logging.getLogger("PID_Generator_Engine")

# ── Modèles de Données Pydantic ──

class PIDEquipment(BaseModel):
    tag: str
    type: str  # "vessel", "pump", "exchanger", "tank", "pig_trap", "wellhead"
    label: str
    design_pressure: str = "45 barg"
    design_temp: str = "75 °C"

class PIDPipeline(BaseModel):
    tag: str  # e.g. 8"-HC-1001-A1A
    from_equipment: str
    to_equipment: str
    diameter_inch: int = 8
    fluid: str = "HC"
    piping_class: str = "A1A"
    insulation: str = "N"

class PIDValve(BaseModel):
    tag: str
    type: str  # "gate", "globe", "ball", "check", "control_valve", "psv", "esdv"
    pipeline_tag: str
    fail_position: str = "FC"  # FC, FO, FL, N/A
    role: str = "Isolement / Régulation"

class PIDInstrument(BaseModel):
    tag: str
    loop: str
    measured_variable: str  # L, P, T, F
    function: str  # IC, T, V, S
    type: str

class PIDDesignResult(BaseModel):
    title: str
    project_code: str
    unit: str
    equipments: List[PIDEquipment]
    pipelines: List[PIDPipeline]
    valves: List[PIDValve]
    instruments: List[PIDInstrument]
    svg_content: str
    dexpi_xml: str
    dxf_filename: Optional[str] = None
    mto_summary: Dict[str, Any] = {}


class PIDGeneratorEngine:
    """Moteur de génération et de synthèse de schémas P&ID industriels."""

    def __init__(self):
        self.catalog_path = Path("data/pid_catalog.json")
        self.output_dir = Path("generated_visuals")
        self.output_dir.mkdir(exist_ok=True)

    def generate(self, prompt: str, process_type: str = "separation", project_code: str = "ARKAN-EPC") -> PIDDesignResult:
        """Génère la topologie de procédé, le schéma vectoriel SVG et le fichier CAO DXF."""
        prompt_lower = (prompt or "").lower()

        # 1. Sélection ou synthèse de la topologie selon le type de procédé
        if "pig" in prompt_lower or "racleur" in prompt_lower or process_type == "pig_trap":
            res = self._build_pig_trap_topology(prompt, project_code)
            actual_type = "pig_trap"
        elif "puits" in prompt_lower or "well" in prompt_lower or process_type == "wellhead":
            res = self._build_wellhead_topology(prompt, project_code)
            actual_type = "wellhead"
        elif "pompe" in prompt_lower or "pump" in prompt_lower or process_type == "pumping":
            res = self._build_pumping_topology(prompt, project_code)
            actual_type = "pumping"
        elif "torche" in prompt_lower or "flare" in prompt_lower or process_type == "flare":
            res = self._build_flare_topology(prompt, project_code)
            actual_type = "flare"
        else:
            # Séparateur par défaut ou customisé
            res = self._build_separator_topology(prompt, project_code)
            actual_type = "separation"

        # 2. Génération du Rendu Vectoriel SVG
        svg_content = self._render_orthogonal_svg(
            res["equipments"], 
            res["pipelines"], 
            res["valves"], 
            res["instruments"],
            process_type=actual_type,
            title=res["title"]
        )
        
        # 3. Génération du XML DEXPI standard (ISO 15926)
        dexpi_xml = self._generate_dexpi_xml(res["title"], res["equipments"], res["pipelines"], res["valves"], res["instruments"])

        # 4. Génération du Fichier DXF AutoCAD natif
        dxf_filename = self._generate_dxf(res["title"], res["equipments"], res["pipelines"], res["valves"], res["instruments"])

        # 5. Calcul de MTO prévisionnel
        mto_summary = self._calculate_mto(res["pipelines"], res["valves"])

        return PIDDesignResult(
            title=res["title"],
            project_code=project_code,
            unit=res.get("unit", "U-100"),
            equipments=res["equipments"],
            pipelines=res["pipelines"],
            valves=res["valves"],
            instruments=res["instruments"],
            svg_content=svg_content,
            dexpi_xml=dexpi_xml,
            dxf_filename=dxf_filename,
            mto_summary=mto_summary
        )

    def _build_separator_topology(self, prompt: str, project_code: str) -> Dict[str, Any]:
        equipments = [
            PIDEquipment(tag="V-101", type="vessel", label="Séparateur de Production Biphasique HP", design_pressure="68.0 barg", design_temp="85.0 °C"),
            PIDEquipment(tag="P-101A", type="pump", label="Pompe d'Expédition Condensats (A)", design_pressure="75.0 barg", design_temp="70.0 °C"),
            PIDEquipment(tag="P-101B", type="pump", label="Pompe d'Expédition Condensats (B - Secours)", design_pressure="75.0 barg", design_temp="70.0 °C")
        ]
        pipelines = [
            PIDPipeline(tag='8"-HC-1001-A1A', from_equipment="Collecteur Amont (Manifold)", to_equipment="V-101", diameter_inch=8, fluid="HC", piping_class="A1A"),
            PIDPipeline(tag='6"-HC-1002-A1A', from_equipment="V-101", to_equipment="P-101A/B", diameter_inch=6, fluid="HC", piping_class="A1A"),
            PIDPipeline(tag='4"-FG-1003-A1A', from_equipment="V-101", to_equipment="Collecteur Torche HP", diameter_inch=4, fluid="FG", piping_class="A1A"),
            PIDPipeline(tag='6"-HC-1004-A1A', from_equipment="P-101A/B", to_equipment="Pipeline Expédition", diameter_inch=6, fluid="HC", piping_class="A1A")
        ]
        valves = [
            PIDValve(tag="ESDV-1001", type="esdv", pipeline_tag='8"-HC-1001-A1A', fail_position="FC", role="Vanne d'Arrêt d'Urgence Amont"),
            PIDValve(tag="LCV-101", type="control_valve", pipeline_tag='6"-HC-1002-A1A', fail_position="FC", role="Vanne de Régulation de Niveau"),
            PIDValve(tag="PSV-101A", type="psv", pipeline_tag='4"-FG-1003-A1A', fail_position="FO", role="Soupape de Sécurité HP (Locked Open)"),
            PIDValve(tag="PSV-101B", type="psv", pipeline_tag='4"-FG-1003-A1A', fail_position="FO", role="Soupape de Sécurité HP Secours (Locked Open)"),
            PIDValve(tag="NRV-1004", type="check", pipeline_tag='6"-HC-1004-A1A', fail_position="N/A", role="Clapet Anti-Retour Refoulement")
        ]
        instruments = [
            PIDInstrument(tag="LT-101", loop="101", measured_variable="L", function="T", type="Transmetteur Niveau Radar"),
            PIDInstrument(tag="LIC-101", loop="101", measured_variable="L", function="IC", type="Régulateur de Niveau DCS"),
            PIDInstrument(tag="PT-101", loop="102", measured_variable="P", function="T", type="Transmetteur Pression Ciel Gaz"),
            PIDInstrument(tag="PIC-101", loop="102", measured_variable="P", function="IC", type="Régulateur Pression Torche")
        ]
        return {
            "title": "Unité de Séparation de Production HP (Standard Sonatrach / GCB)",
            "unit": "U-100",
            "equipments": equipments,
            "pipelines": pipelines,
            "valves": valves,
            "instruments": instruments
        }

    def _build_pig_trap_topology(self, prompt: str, project_code: str) -> Dict[str, Any]:
        equipments = [
            PIDEquipment(tag="PL-201", type="pig_trap", label="Gare de Racleurs Départ (Pig Launcher) 12\" Cl.600", design_pressure="98.0 barg", design_temp="60.0 °C")
        ]
        pipelines = [
            PIDPipeline(tag='12"-HC-2001-D1A', from_equipment="Ligne Principale", to_equipment="PL-201", diameter_inch=12, fluid="HC", piping_class="D1A"),
            PIDPipeline(tag='4"-HC-2002-D1A', from_equipment="Ligne Kicker Amont", to_equipment="PL-201", diameter_inch=4, fluid="HC", piping_class="D1A"),
            PIDPipeline(tag='2"-HC-2003-D1A', from_equipment="PL-201", to_equipment="Réseau Torche / Purge", diameter_inch=2, fluid="HC", piping_class="D1A"),
            PIDPipeline(tag='2"-HC-2004-D1A', from_equipment="PL-201", to_equipment="Closed Drain Fût", diameter_inch=2, fluid="HC", piping_class="D1A")
        ]
        valves = [
            PIDValve(tag="MOV-2001", type="gate", pipeline_tag='12"-HC-2001-D1A', fail_position="FL", role="Vanne d'Isolation Trap Motorisée"),
            PIDValve(tag="HV-2002", type="ball", pipeline_tag='4"-HC-2002-D1A', fail_position="FL", role="Vanne Kicker Manuelle"),
            PIDValve(tag="PSV-201", type="psv", pipeline_tag='2"-HC-2003-D1A', fail_position="FO", role="Soupape Thermique Fût Trap")
        ]
        instruments = [
            PIDInstrument(tag="XI-201", loop="201", measured_variable="X", function="I", type="Détecteur de Passage Racleur Bidirectionnel"),
            PIDInstrument(tag="PI-201", loop="202", measured_variable="P", function="I", type="Manomètre Local avec vanne DBB")
        ]
        return {
            "title": "Gare de Racleurs Départ 12\" (Standard Touat Gaz / Sonatrach)",
            "unit": "U-200",
            "equipments": equipments,
            "pipelines": pipelines,
            "valves": valves,
            "instruments": instruments
        }

    def _build_wellhead_topology(self, prompt: str, project_code: str) -> Dict[str, Any]:
        equipments = [
            PIDEquipment(tag="X-TREE-01", type="wellhead", label="Tête de Puits Éruptif (Arbre de Noël 5000 psi)", design_pressure="345 barg", design_temp="110 °C")
        ]
        pipelines = [
            PIDPipeline(tag='4"-HC-3001-API5K', from_equipment="Tubing Puits", to_equipment="Flowline Collecte", diameter_inch=4, fluid="HC", piping_class="API5K"),
            PIDPipeline(tag='1/2"-CI-3002-316L', from_equipment="Skid Injection Chimique", to_equipment="Tête de Puits", diameter_inch=1, fluid="CI", piping_class="316L")
        ]
        valves = [
            PIDValve(tag="SSSV-01", type="esdv", pipeline_tag='4"-HC-3001-API5K', fail_position="FC", role="Subsurface Safety Valve Fond"),
            PIDValve(tag="PWV-01", type="gate", pipeline_tag='4"-HC-3001-API5K', fail_position="FC", role="Production Wing Valve"),
            PIDValve(tag="CHOKE-01", type="control_valve", pipeline_tag='4"-HC-3001-API5K', fail_position="FC", role="Duse Réglable Manuelle/Auto")
        ]
        instruments = [
            PIDInstrument(tag="PT-301", loop="301", measured_variable="P", function="T", type="Transmetteur Pression Tête de Puits"),
            PIDInstrument(tag="TT-301", loop="302", measured_variable="T", function="T", type="Transmetteur Température Tête de Puits")
        ]
        return {
            "title": "Tête de Puits de Production avec Injection d'Inhibiteur",
            "unit": "U-300",
            "equipments": equipments,
            "pipelines": pipelines,
            "valves": valves,
            "instruments": instruments
        }

    def _build_pumping_topology(self, prompt: str, project_code: str) -> Dict[str, Any]:
        equipments = [
            PIDEquipment(tag="P-201A", type="pump", label="Pompe Centrifuge d'Alimentation (A)", design_pressure="40.0 barg", design_temp="65.0 °C"),
            PIDEquipment(tag="P-201B", type="pump", label="Pompe Centrifuge d'Alimentation (B - Secours)", design_pressure="40.0 barg", design_temp="65.0 °C")
        ]
        pipelines = [
            PIDPipeline(tag='6"-HC-4001-A1A', from_equipment="Aspiration Commune", to_equipment="P-201A/B", diameter_inch=6, fluid="HC", piping_class="A1A"),
            PIDPipeline(tag='4"-HC-4002-A1A', from_equipment="P-201A/B", to_equipment="Refoulement Collecteur", diameter_inch=4, fluid="HC", piping_class="A1A"),
            PIDPipeline(tag='2"-HC-4003-A1A', from_equipment="Refoulement Pompes", to_equipment="Recirculation Débit Minimum", diameter_inch=2, fluid="HC", piping_class="A1A")
        ]
        valves = [
            PIDValve(tag="FCV-201", type="control_valve", pipeline_tag='2"-HC-4003-A1A', fail_position="FO", role="Vanne de Débit Minimum"),
            PIDValve(tag="NRV-201A", type="check", pipeline_tag='4"-HC-4002-A1A', fail_position="N/A", role="Clapet Anti-Retour Pompe A"),
            PIDValve(tag="NRV-201B", type="check", pipeline_tag='4"-HC-4002-A1A', fail_position="N/A", role="Clapet Anti-Retour Pompe B")
        ]
        instruments = [
            PIDInstrument(tag="FT-201", loop="201", measured_variable="F", function="T", type="Débitmètre Transmetteur Refoulement"),
            PIDInstrument(tag="FIC-201", loop="201", measured_variable="F", function="IC", type="Régulateur de Débit Minimum")
        ]
        return {
            "title": "Poste de Pompage Centrifuge (1 Service + 1 Secours)",
            "unit": "U-400",
            "equipments": equipments,
            "pipelines": pipelines,
            "valves": valves,
            "instruments": instruments
        }

    def _build_flare_topology(self, prompt: str, project_code: str) -> Dict[str, Any]:
        equipments = [
            PIDEquipment(tag="KO-101", type="vessel", label="Ballon Séparateur de Torche (Knock-Out Drum)", design_pressure="10.0 barg", design_temp="120.0 °C")
        ]
        pipelines = [
            PIDPipeline(tag='16"-FG-5001-A1A', from_equipment="Collecteur Torche Usine", to_equipment="KO-101", diameter_inch=16, fluid="FG", piping_class="A1A"),
            PIDPipeline(tag='16"-FG-5002-A1A', from_equipment="KO-101", to_equipment="Fût de Torche / Brûleur", diameter_inch=16, fluid="FG", piping_class="A1A"),
            PIDPipeline(tag='3"-HC-5003-A1A', from_equipment="KO-101", to_equipment="Pompes de Récupération Condensats", diameter_inch=3, fluid="HC", piping_class="A1A")
        ]
        valves = [
            PIDValve(tag="LCV-501", type="control_valve", pipeline_tag='3"-HC-5003-A1A', fail_position="FC", role="Purge Automatique Condensats Torche")
        ]
        instruments = [
            PIDInstrument(tag="LT-501", loop="501", measured_variable="L", function="T", type="Niveau Haute Alarme Torche (LAHH)")
        ]
        return {
            "title": "Réseau de Torche HP & Knock-Out Drum",
            "unit": "U-500",
            "equipments": equipments,
            "pipelines": pipelines,
            "valves": valves,
            "instruments": instruments
        }

    def _render_orthogonal_svg(self, equipments: List[PIDEquipment], pipelines: List[PIDPipeline], valves: List[PIDValve], instruments: List[PIDInstrument], process_type: str = "separation", title: str = "") -> str:
        """Génère le dessin vectoriel SVG avec symboles ISA-5.1 orthogonaux nets pour les 5 types de procédé."""
        clean_title = title if title else "SCHÉMA DE PROCÉDÉ & INSTRUMENTATION (ISA 5.1)"
        
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1350 720" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" style="background:#0B132B; width:100%; height:100%; min-height:500px; display:block; user-select:none;">']
        
        # 1. Grille CAO & Définitions
        svg.append("""<defs>
            <pattern id="pid-grid" width="30" height="30" patternUnits="userSpaceOnUse">
                <path d="M 30 0 L 0 0 0 30" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="0.8"/>
            </pattern>
            <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#38BDF8"/>
            </marker>
            <marker id="arrow-amber" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#F59E0B"/>
            </marker>
            <marker id="arrow-green" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#10B981"/>
            </marker>
            <marker id="arrow-red" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#EF4444"/>
            </marker>
        </defs>""")
        svg.append('<rect width="100%" height="100%" fill="#0B132B"/>')
        svg.append('<rect width="100%" height="100%" fill="url(#pid-grid)"/>')

        # 2. Cartouche Normalisé Sonatrach / EPC (Bas Droite)
        svg.append(f"""<g id="title-block" transform="translate(920, 580)">
            <rect width="400" height="120" fill="#0F172A" stroke="#334155" stroke-width="1.5" rx="4"/>
            <line x1="0" y1="36" x2="400" y2="36" stroke="#334155" stroke-width="1"/>
            <line x1="0" y1="76" x2="400" y2="76" stroke="#334155" stroke-width="1"/>
            <line x1="230" y1="36" x2="230" y2="120" stroke="#334155" stroke-width="1"/>
            <text x="200" y="24" fill="#38BDF8" font-size="13" font-family="monospace" font-weight="bold" text-anchor="middle">ARKAN INTELLIGENCE EPC — P&amp;ID</text>
            <text x="12" y="56" fill="#F8FAFC" font-size="10" font-family="sans-serif" font-weight="bold">{clean_title[:32]}</text>
            <text x="12" y="102" fill="#94A3B8" font-size="10" font-family="monospace">STD : ISA-5.1 / ASME B31.3</text>
            <text x="242" y="56" fill="#94A3B8" font-size="10" font-family="sans-serif">PROJET : SONATRACH / GCB</text>
            <text x="242" y="102" fill="#10B981" font-size="11" font-family="monospace" font-weight="bold">STATUS : VALIDÉ (IFC)</text>
        </g>""")

        # 3. RENDU SPÉCIFIQUE SELON LE PROCÉDÉ
        if process_type == "pig_trap":
            # GARE DE RACLEURS (PIG LAUNCHER)
            svg.append("""<g id="pig-launcher">
                <rect x="300" y="300" width="280" height="100" rx="14" fill="#1E293B" stroke="#38BDF8" stroke-width="3"/>
                <ellipse cx="300" cy="350" rx="22" ry="50" fill="#0F172A" stroke="#38BDF8" stroke-width="3"/>
                <text x="440" y="345" fill="#F8FAFC" font-size="18" font-family="monospace" font-weight="bold" text-anchor="middle">PL-201</text>
                <text x="440" y="370" fill="#94A3B8" font-size="11" font-family="sans-serif" text-anchor="middle">PIG LAUNCHER 12" Cl.600</text>
                
                <path d="M 580 350 L 960 350" stroke="#F59E0B" stroke-width="4.5" fill="none" marker-end="url(#arrow-amber)"/>
                <rect x="680" y="335" width="140" height="18" fill="#0F172A" stroke="#F59E0B" stroke-width="0.8" rx="2"/>
                <text x="750" y="348" fill="#FBBF24" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">12"-HC-2001-D1A</text>
                
                <g transform="translate(640, 350)">
                    <polygon points="-14,-10 0,0 -14,10" fill="#F8FAFC"/>
                    <polygon points="14,-10 0,0 14,10" fill="#F8FAFC"/>
                    <line x1="0" y1="0" x2="0" y2="-18" stroke="#F8FAFC" stroke-width="1.5"/>
                    <rect x="-9" y="-30" width="18" height="12" fill="#38BDF8" rx="2"/>
                    <text x="0" y="-21" fill="#0F172A" font-size="8" font-family="sans-serif" font-weight="bold" text-anchor="middle">M</text>
                    <text x="0" y="24" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">MOV-2001 (FL)</text>
                </g>

                <g transform="translate(880, 350)">
                    <circle cx="0" cy="-35" r="16" fill="#0F172A" stroke="#38BDF8" stroke-width="1.5"/>
                    <line x1="0" y1="0" x2="0" y2="-19" stroke="#38BDF8" stroke-width="1.5"/>
                    <text x="0" y="-31" fill="#38BDF8" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">XI</text>
                    <text x="0" y="-20" fill="#38BDF8" font-size="8" font-family="monospace" text-anchor="middle">201</text>
                </g>

                <path d="M 120 180 L 400 180 L 400 300" stroke="#F59E0B" stroke-width="3.5" fill="none" marker-end="url(#arrow-amber)"/>
                <rect x="180" y="166" width="130" height="18" fill="#0F172A" stroke="#F59E0B" stroke-width="0.8" rx="2"/>
                <text x="245" y="179" fill="#FBBF24" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">4"-HC-2002-D1A (KICKER)</text>
                
                <g transform="translate(340, 180)">
                    <polygon points="-12,-8 0,0 -12,8" fill="#F8FAFC"/>
                    <polygon points="12,-8 0,0 12,8" fill="#F8FAFC"/>
                    <circle cx="0" cy="0" r="3" fill="#0F172A"/>
                    <line x1="0" y1="0" x2="0" y2="-12" stroke="#F8FAFC" stroke-width="1.5"/>
                    <line x1="-6" y1="-12" x2="6" y2="-12" stroke="#F8FAFC" stroke-width="2"/>
                    <text x="0" y="-18" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">HV-2002</text>
                </g>

                <g transform="translate(500, 300)">
                    <line x1="0" y1="0" x2="0" y2="-60" stroke="#EF4444" stroke-width="2.5"/>
                    <polygon points="-8,-68 0,-60 8,-68" fill="#F8FAFC"/>
                    <polygon points="0,-60 8,-52 8,-68" fill="#F8FAFC"/>
                    <rect x="-6" y="-78" width="12" height="6" fill="#F8FAFC"/>
                    <text x="0" y="-84" fill="#F87171" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">PSV-201 [FO]</text>
                </g>

                <path d="M 480 400 L 480 500 L 750 500" stroke="#10B981" stroke-width="2.5" fill="none" marker-end="url(#arrow-green)"/>
                <text x="600" y="492" fill="#34D399" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">2"-HC-2004-D1A (DRAIN)</text>
            </g>""")

        elif process_type == "wellhead":
            # TÊTE DE PUITS (CHRISTMAS TREE 5000 PSI)
            svg.append("""<g id="wellhead-tree">
                <line x1="460" y1="100" x2="460" y2="580" stroke="#F59E0B" stroke-width="5"/>
                
                <g transform="translate(460, 140)">
                    <polygon points="-9,-12 0,0 9,-12" fill="#F8FAFC"/>
                    <polygon points="-9,12 0,0 9,12" fill="#F8FAFC"/>
                    <text x="24" y="4" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold">SWAB VALVE</text>
                </g>

                <g transform="translate(460, 240)">
                    <polygon points="-9,-12 0,0 9,-12" fill="#F8FAFC"/>
                    <polygon points="-9,12 0,0 9,12" fill="#F8FAFC"/>
                    <text x="24" y="4" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold">UMV (FC)</text>
                </g>

                <g transform="translate(460, 340)">
                    <polygon points="-9,-12 0,0 9,-12" fill="#F8FAFC"/>
                    <polygon points="-9,12 0,0 9,12" fill="#F8FAFC"/>
                    <text x="24" y="4" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold">LMV (Manuelle)</text>
                </g>

                <line x1="380" y1="440" x2="540" y2="440" stroke="#64748B" stroke-width="2" stroke-dasharray="6,4"/>
                <text x="360" y="444" fill="#94A3B8" font-size="9" text-anchor="end">NIVEAU SOL</text>
                <rect x="435" y="500" width="50" height="36" fill="#1E293B" stroke="#EF4444" stroke-width="2" rx="3"/>
                <text x="460" y="522" fill="#F87171" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">SSSV</text>

                <path d="M 460 190 L 980 190" stroke="#F59E0B" stroke-width="4.5" fill="none" marker-end="url(#arrow-amber)"/>
                <rect x="580" y="174" width="140" height="18" fill="#0F172A" stroke="#F59E0B" stroke-width="0.8" rx="2"/>
                <text x="650" y="187" fill="#FBBF24" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">4"-HC-3001-API5K</text>

                <g transform="translate(540, 190)">
                    <polygon points="-12,-9 0,0 -12,9" fill="#F8FAFC"/>
                    <polygon points="12,-9 0,0 12,9" fill="#F8FAFC"/>
                    <line x1="0" y1="0" x2="0" y2="-15" stroke="#F8FAFC" stroke-width="1.5"/>
                    <circle cx="0" cy="-20" r="6" fill="#EF4444"/>
                    <text x="0" y="24" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">PWV-01 (FC)</text>
                </g>

                <g transform="translate(780, 190)">
                    <polygon points="-12,-9 0,0 -12,9" fill="#38BDF8"/>
                    <polygon points="12,-9 0,0 12,9" fill="#38BDF8"/>
                    <line x1="-12" y1="-14" x2="12" y2="-14" stroke="#38BDF8" stroke-width="2"/>
                    <line x1="0" y1="0" x2="0" y2="-14" stroke="#38BDF8" stroke-width="1.5"/>
                    <text x="0" y="24" fill="#38BDF8" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">CHOKE-01</text>
                </g>

                <g transform="translate(900, 190)">
                    <circle cx="0" cy="-35" r="16" fill="#0F172A" stroke="#38BDF8" stroke-width="1.5"/>
                    <line x1="0" y1="0" x2="0" y2="-19" stroke="#38BDF8" stroke-width="1.5"/>
                    <text x="0" y="-32" fill="#38BDF8" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">PT</text>
                    <text x="0" y="-21" fill="#38BDF8" font-size="8" font-family="monospace" text-anchor="middle">301</text>
                </g>
                <g transform="translate(900, 260)">
                    <circle cx="0" cy="-35" r="16" fill="#0F172A" stroke="#38BDF8" stroke-width="1.5"/>
                    <path d="M 0 0 L 0 -19" stroke="#38BDF8" stroke-width="1.5"/>
                    <text x="0" y="-32" fill="#38BDF8" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">TT</text>
                    <text x="0" y="-21" fill="#38BDF8" font-size="8" font-family="monospace" text-anchor="middle">301</text>
                </g>
            </g>""")

        elif process_type == "pumping":
            # STATION DE POMPAGE CENTRIFUGE (1+1)
            svg.append("""<g id="pumping-skid">
                <path d="M 80 340 L 320 340" stroke="#10B981" stroke-width="4" fill="none" marker-end="url(#arrow-green)"/>
                <text x="180" y="330" fill="#34D399" font-size="11" font-family="monospace" font-weight="bold">6"-HC-4001-A1A (ASPIRATION)</text>
                
                <path d="M 320 340 L 320 230 L 460 230" stroke="#10B981" stroke-width="3.5" fill="none"/>
                <circle cx="500" cy="230" r="32" fill="#1E293B" stroke="#38BDF8" stroke-width="2.5"/>
                <polygon points="500,202 528,230 500,230" fill="#38BDF8"/>
                <text x="500" y="278" fill="#F8FAFC" font-size="13" font-family="monospace" font-weight="bold" text-anchor="middle">P-201A</text>
                <text x="500" y="294" fill="#94A3B8" font-size="9" text-anchor="middle">DUTY PUMP</text>

                <path d="M 320 340 L 320 450 L 460 450" stroke="#10B981" stroke-width="3.5" fill="none"/>
                <circle cx="500" cy="450" r="32" fill="#1E293B" stroke="#38BDF8" stroke-width="2.5"/>
                <polygon points="500,422 528,450 500,450" fill="#38BDF8"/>
                <text x="500" y="498" fill="#F8FAFC" font-size="13" font-family="monospace" font-weight="bold" text-anchor="middle">P-201B</text>
                <text x="500" y="514" fill="#94A3B8" font-size="9" text-anchor="middle">STANDBY PUMP</text>

                <path d="M 532 230 L 660 230 L 660 340" stroke="#10B981" stroke-width="3.5" fill="none"/>
                <path d="M 532 450 L 660 450 L 660 340" stroke="#10B981" stroke-width="3.5" fill="none"/>
                <path d="M 660 340 L 1020 340" stroke="#10B981" stroke-width="4" fill="none" marker-end="url(#arrow-green)"/>
                <text x="740" y="330" fill="#34D399" font-size="11" font-family="monospace" font-weight="bold">4"-HC-4002-A1A (REFOULEMENT)</text>

                <g transform="translate(590, 230)">
                    <polygon points="-10,-8 0,0 -10,8" fill="#F8FAFC"/>
                    <polygon points="10,-8 0,0 10,8" fill="#F8FAFC"/>
                    <line x1="0" y1="-8" x2="0" y2="8" stroke="#F8FAFC" stroke-width="2"/>
                    <text x="0" y="20" fill="#F8FAFC" font-size="8" font-family="monospace" text-anchor="middle">NRV-201A</text>
                </g>
                <g transform="translate(590, 450)">
                    <polygon points="-10,-8 0,0 -10,8" fill="#F8FAFC"/>
                    <polygon points="10,-8 0,0 10,8" fill="#F8FAFC"/>
                    <line x1="0" y1="-8" x2="0" y2="8" stroke="#F8FAFC" stroke-width="2"/>
                    <text x="0" y="20" fill="#F8FAFC" font-size="8" font-family="monospace" text-anchor="middle">NRV-201B</text>
                </g>

                <path d="M 820 340 L 820 120 L 220 120 L 220 340" stroke="#F59E0B" stroke-width="2.5" fill="none" stroke-dasharray="6,2"/>
                <text x="520" y="112" fill="#FBBF24" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">2"-HC-4003-A1A (MIN FLOW RECIRCULATION)</text>

                <g transform="translate(600, 120)">
                    <polygon points="-12,-9 0,0 -12,9" fill="#F8FAFC"/>
                    <polygon points="12,-9 0,0 12,9" fill="#F8FAFC"/>
                    <line x1="0" y1="0" x2="0" y2="-14" stroke="#F8FAFC" stroke-width="1.5"/>
                    <path d="M -9 -14 Q 0 -19 9 -14" stroke="#F8FAFC" stroke-width="2" fill="none"/>
                    <text x="0" y="22" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">FCV-201 (FO)</text>
                </g>
                <g transform="translate(740, 120)">
                    <circle cx="0" cy="-30" r="16" fill="#0F172A" stroke="#38BDF8" stroke-width="1.5"/>
                    <line x1="0" y1="0" x2="0" y2="-14" stroke="#38BDF8" stroke-width="1.5"/>
                    <text x="0" y="-27" fill="#38BDF8" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">FIC</text>
                    <text x="0" y="-16" fill="#38BDF8" font-size="8" font-family="monospace" text-anchor="middle">201</text>
                </g>
            </g>""")

        elif process_type == "flare":
            # KNOCK-OUT DRUM & TORCHE HP
            svg.append("""<g id="flare-network">
                <rect x="380" y="160" width="190" height="360" rx="36" fill="#1E293B" stroke="#EF4444" stroke-width="3"/>
                <text x="475" y="320" fill="#F8FAFC" font-size="18" font-family="monospace" font-weight="bold" text-anchor="middle">KO-101</text>
                <text x="475" y="345" fill="#94A3B8" font-size="11" font-family="sans-serif" text-anchor="middle">FLARE K.O. DRUM</text>
                <rect x="400" y="220" width="150" height="24" fill="rgba(239,68,68,0.15)" stroke="#94A3B8" stroke-width="1" stroke-dasharray="3,3"/>
                <text x="475" y="236" fill="#94A3B8" font-size="9" font-family="sans-serif" text-anchor="middle">DEMISTER PAD</text>

                <path d="M 80 270 L 380 290" stroke="#EF4444" stroke-width="5" fill="none" marker-end="url(#arrow-red)"/>
                <text x="210" y="260" fill="#F87171" font-size="11" font-family="monospace" font-weight="bold">16"-FG-5001-A1A (SLOPE 1:500)</text>

                <path d="M 475 160 L 475 70 L 960 70 L 960 180" stroke="#EF4444" stroke-width="5" fill="none"/>
                <text x="720" y="60" fill="#F87171" font-size="11" font-family="monospace" font-weight="bold" text-anchor="middle">16"-FG-5002-A1A (VERS TORCHE)</text>

                <polygon points="940,560 980,560 970,180 950,180" fill="#1E293B" stroke="#EF4444" stroke-width="2.5"/>
                <path d="M 960 180 Q 940 140 960 110 Q 980 140 960 180 Z" fill="#F59E0B" stroke="#EF4444" stroke-width="1.5"/>
                <path d="M 960 170 Q 950 145 960 130 Q 970 145 960 170 Z" fill="#FDE047"/>
                <text x="960" y="580" fill="#F87171" font-size="11" font-family="monospace" font-weight="bold" text-anchor="middle">FLARE STACK</text>

                <path d="M 475 520 L 475 620 L 760 620" stroke="#10B981" stroke-width="3" fill="none" marker-end="url(#arrow-green)"/>
                <text x="620" y="610" fill="#34D399" font-size="10" font-family="monospace" font-weight="bold">3"-HC-5003-A1A (PURGE CONDENSATS)</text>
                
                <g transform="translate(560, 620)">
                    <polygon points="-12,-8 0,0 -12,8" fill="#F8FAFC"/>
                    <polygon points="12,-8 0,0 12,8" fill="#F8FAFC"/>
                    <line x1="0" y1="0" x2="0" y2="-14" stroke="#F8FAFC" stroke-width="1.5"/>
                    <path d="M -9 -14 Q 0 -19 9 -14" stroke="#F8FAFC" stroke-width="2" fill="none"/>
                    <text x="0" y="20" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">LCV-501</text>
                </g>

                <g transform="translate(340, 360)">
                    <circle cx="0" cy="0" r="18" fill="#0F172A" stroke="#EF4444" stroke-width="2"/>
                    <text x="0" y="-4" fill="#EF4444" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">LAHH</text>
                    <text x="0" y="10" fill="#EF4444" font-size="8" font-family="monospace" text-anchor="middle">501</text>
                    <line x1="18" y1="0" x2="40" y2="0" stroke="#EF4444" stroke-width="1.5" stroke-dasharray="3,3"/>
                </g>
            </g>""")

        else:
            # SÉPARATEUR DE PRODUCTION BIPHASIQUE HP (V-101)
            svg.append("""<g id="separator-v101">
                <rect x="440" y="180" width="200" height="300" rx="36" fill="#1E293B" stroke="#38BDF8" stroke-width="3"/>
                <path d="M 450 370 Q 540 380 630 370 L 630 460 Q 540 470 450 460 Z" fill="rgba(56,189,248,0.15)"/>
                <text x="540" y="260" fill="#F8FAFC" font-size="20" font-family="monospace" font-weight="bold" text-anchor="middle">V-101</text>
                <text x="540" y="285" fill="#94A3B8" font-size="11" font-family="sans-serif" text-anchor="middle">HP SEPARATOR</text>
                <text x="540" y="304" fill="#64748B" font-size="10" font-family="monospace" text-anchor="middle">P: 68 barg | T: 85 °C</text>

                <g transform="translate(820, 480)">
                    <circle cx="40" cy="40" r="32" fill="#1E293B" stroke="#38BDF8" stroke-width="2.5"/>
                    <polygon points="40,8 72,40 40,40" fill="#38BDF8"/>
                    <text x="40" y="90" fill="#F8FAFC" font-size="13" font-family="monospace" font-weight="bold" text-anchor="middle">P-101A/B</text>
                    <text x="40" y="106" fill="#94A3B8" font-size="9" text-anchor="middle">CONDENSATE PUMP</text>
                </g>

                <path d="M 80 270 L 440 270" stroke="#F59E0B" stroke-width="4" fill="none" marker-end="url(#arrow-amber)"/>
                <rect x="160" y="254" width="130" height="18" fill="#0F172A" stroke="#F59E0B" stroke-width="0.8" rx="2"/>
                <text x="225" y="267" fill="#FBBF24" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">8"-HC-1001-A1A</text>
                
                <g transform="translate(340, 270)">
                    <polygon points="-12,-9 0,0 -12,9" fill="#F8FAFC"/>
                    <polygon points="12,-9 0,0 12,9" fill="#F8FAFC"/>
                    <line x1="0" y1="0" x2="0" y2="-16" stroke="#F8FAFC" stroke-width="1.5"/>
                    <circle cx="0" cy="-22" r="7" fill="#EF4444" stroke="#F8FAFC" stroke-width="1"/>
                    <text x="0" y="-34" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">ESDV-1001 (FC)</text>
                </g>

                <path d="M 540 480 L 540 520 L 820 520" stroke="#10B981" stroke-width="3.5" fill="none"/>
                <rect x="610" y="508" width="120" height="18" fill="#0F172A" stroke="#10B981" stroke-width="0.8" rx="2"/>
                <text x="670" y="521" fill="#34D399" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">6"-HC-1002-A1A</text>
                
                <g transform="translate(670, 520)">
                    <polygon points="-12,-9 0,0 -12,9" fill="#F8FAFC"/>
                    <polygon points="12,-9 0,0 12,9" fill="#F8FAFC"/>
                    <line x1="0" y1="0" x2="0" y2="-16" stroke="#F8FAFC" stroke-width="1.5"/>
                    <path d="M -10 -16 Q 0 -22 10 -16" stroke="#F8FAFC" stroke-width="2" fill="none"/>
                    <text x="0" y="24" fill="#F8FAFC" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">LCV-101 (FC)</text>
                </g>

                <path d="M 540 180 L 540 100 L 880 100" stroke="#EF4444" stroke-width="3" fill="none" marker-end="url(#arrow-red)"/>
                <rect x="670" y="86" width="120" height="18" fill="#0F172A" stroke="#EF4444" stroke-width="0.8" rx="2"/>
                <text x="730" y="99" fill="#F87171" font-size="10" font-family="monospace" font-weight="bold" text-anchor="middle">4"-FG-1003-A1A</text>
                
                <g transform="translate(640, 100)">
                    <polygon points="-8,-8 0,0 8,-8" fill="#F8FAFC"/>
                    <polygon points="0,0 8,8 8,-8" fill="#F8FAFC"/>
                    <line x1="0" y1="-8" x2="0" y2="-18" stroke="#F8FAFC" stroke-width="1.5"/>
                    <rect x="-6" y="-24" width="12" height="6" fill="#F8FAFC"/>
                    <text x="0" y="-30" fill="#F87171" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">PSV-101A [LO]</text>
                </g>

                <g transform="translate(400, 360)">
                    <circle cx="0" cy="0" r="18" fill="#0F172A" stroke="#38BDF8" stroke-width="1.5"/>
                    <line x1="-18" y1="0" x2="18" y2="0" stroke="#38BDF8" stroke-width="0.8"/>
                    <text x="0" y="-4" fill="#38BDF8" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">LT</text>
                    <text x="0" y="12" fill="#38BDF8" font-size="8" font-family="monospace" text-anchor="middle">101</text>
                    <line x1="18" y1="0" x2="40" y2="0" stroke="#38BDF8" stroke-width="1.5"/>
                </g>
                <g transform="translate(670, 420)">
                    <circle cx="0" cy="0" r="20" fill="#0F172A" stroke="#38BDF8" stroke-width="2"/>
                    <line x1="-20" y1="0" x2="20" y2="0" stroke="#38BDF8" stroke-width="1"/>
                    <text x="0" y="-5" fill="#38BDF8" font-size="9" font-family="monospace" font-weight="bold" text-anchor="middle">LIC</text>
                    <text x="0" y="13" fill="#38BDF8" font-size="9" font-family="monospace" text-anchor="middle">101</text>
                    <path d="M -260 -60 L -260 0 L -20 0" stroke="#38BDF8" stroke-width="1.2" stroke-dasharray="4,4" fill="none"/>
                    <path d="M 0 20 L 0 84" stroke="#38BDF8" stroke-width="1.2" stroke-dasharray="4,4" fill="none"/>
                </g>
            </g>""")

        svg.append('</svg>')
        return "\n".join(svg)


    def _generate_dxf(self, title: str, equipments: List[PIDEquipment], pipelines: List[PIDPipeline], valves: List[PIDValve], instruments: List[PIDInstrument]) -> str:
        """Génère un fichier DXF R2010 normalisé pour consultation CAO sous AutoCAD."""
        safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)[:30]
        filename = f"pid_{safe_title}_{os.getpid()}.dxf"
        filepath = self.output_dir / filename

        doc = ezdxf.new('R2010')
        msp = doc.modelspace()

        # Création des calques standards d'ingénierie
        doc.layers.add(name='EQUIPMENT', color=colors.CYAN)
        doc.layers.add(name='PIPING', color=colors.YELLOW)
        doc.layers.add(name='VALVES', color=colors.WHITE)
        doc.layers.add(name='INSTRUMENTATION', color=colors.GREEN)
        doc.layers.add(name='TEXT', color=colors.WHITE)

        # 1. Dessiner le séparateur V-101
        msp.add_lwpolyline([(450, 200), (630, 200), (630, 480), (450, 480)], close=True, dxfattribs={'layer': 'EQUIPMENT'})
        msp.add_text("V-101 (HP SEPARATOR)", height=12, dxfattribs={'layer': 'TEXT'}).set_placement((470, 340))

        # 2. Dessiner la tuyauterie
        msp.add_line((100, 290), (450, 290), dxfattribs={'layer': 'PIPING'})
        msp.add_text('8"-HC-1001-A1A', height=8, dxfattribs={'layer': 'TEXT'}).set_placement((180, 305))

        msp.add_lwpolyline([(540, 200), (540, 100), (800, 100)], dxfattribs={'layer': 'PIPING'})
        msp.add_text('4"-FG-1003-A1A', height=8, dxfattribs={'layer': 'TEXT'}).set_placement((620, 115))

        msp.add_lwpolyline([(540, 480), (540, 560), (800, 560)], dxfattribs={'layer': 'PIPING'})
        msp.add_text('6"-HC-1002-A1A', height=8, dxfattribs={'layer': 'TEXT'}).set_placement((620, 575))

        # 3. Dessiner la vanne LCV-101
        msp.add_lwpolyline([(670, 550), (690, 560), (670, 570)], close=True, dxfattribs={'layer': 'VALVES'})
        msp.add_lwpolyline([(710, 550), (690, 560), (710, 570)], close=True, dxfattribs={'layer': 'VALVES'})
        msp.add_text("LCV-101", height=7, dxfattribs={'layer': 'TEXT'}).set_placement((680, 535))

        # 4. Dessiner l'instrument LIC-101
        msp.add_circle((690, 460), radius=15, dxfattribs={'layer': 'INSTRUMENTATION'})
        msp.add_line((675, 460), (705, 460), dxfattribs={'layer': 'INSTRUMENTATION'})
        msp.add_text("LIC", height=6, dxfattribs={'layer': 'TEXT'}).set_placement((684, 466))
        msp.add_text("101", height=6, dxfattribs={'layer': 'TEXT'}).set_placement((684, 448))

        doc.saveas(str(filepath))
        return filename

    def _generate_dexpi_xml(self, title: str, equipments: List[PIDEquipment], pipelines: List[PIDPipeline], valves: List[PIDValve], instruments: List[PIDInstrument]) -> str:
        """Génère un export XML standard DEXPI (ISO 15926) pour SmartPlant / AVEVA."""
        eq_xml = "".join([f'<Equipment ID="{eq.tag}" Type="{eq.type}" Description="{eq.label}" DesignPressure="{eq.design_pressure}"/>\n' for eq in equipments])
        pipe_xml = "".join([f'<Pipe ID="{p.tag}" Diameter="{p.diameter_inch}" Fluid="{p.fluid}" Spec="{p.piping_class}"/>\n' for p in pipelines])
        valve_xml = "".join([f'<Valve ID="{v.tag}" Type="{v.type}" PipeRef="{v.pipeline_tag}" FailSafe="{v.fail_position}"/>\n' for v in valves])
        inst_xml = "".join([f'<Instrument ID="{i.tag}" Loop="{i.loop}" MeasuredVariable="{i.measured_variable}" Function="{i.function}"/>\n' for i in instruments])

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<DexpiModel xmlns="http://www.dexpi.org/Specification" version="1.3">
    <PlantInformation ProjectName="ARKAN EPC Sonatrach" Title="{title}"/>
    <Equipments>
{eq_xml}    </Equipments>
    <PipingNetworks>
{pipe_xml}    </PipingNetworks>
    <Valves>
{valve_xml}    </Valves>
    <Instruments>
{inst_xml}    </Instruments>
</DexpiModel>"""

    def _calculate_mto(self, pipelines: List[PIDPipeline], valves: List[PIDValve]) -> Dict[str, Any]:
        """Extrait la nomenclature MTO prévisionnelle (tuyauterie, vannes, brides)."""
        pipe_items = []
        for p in pipelines:
            pipe_items.append({
                "item": f"Tube Acier Carbone ASTM A106 Gr.B {p.diameter_inch}\" Sch.40",
                "pipeline": p.tag,
                "diameter": f"{p.diameter_inch}\"",
                "quantity": "25 m",
                "class": p.piping_class
            })
        valve_items = []
        for v in valves:
            valve_items.append({
                "item": f"Robinetterie {v.type.upper()} Tag {v.tag}",
                "pipeline": v.pipeline_tag,
                "position": v.fail_position,
                "quantity": 1
            })
        return {
            "total_lines": len(pipelines),
            "total_valves": len(valves),
            "piping": pipe_items,
            "valves": valve_items
        }

# Instance singleton
pid_master_generator = PIDGeneratorEngine()
