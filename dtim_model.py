"""
Arkan V6 — Digital Twin Intermediate Model (DTIM)
Ce module contient les structures de données unifiées pour la représentation
topologique et sémantique des procédés industriels (Oil & Gas).
"""

import uuid
from typing import List, Dict, Any, Tuple, Optional

class NormalizedEntity:
    """Classe de base représentant toute entité graphique ou textuelle normalisée."""
    def __init__(
        self,
        entity_type: str,
        geometry: Any = None,
        rotation: float = 0.0,
        scale: float = 1.0,
        layer: str = "0",
        source: str = "unknown",
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.id = str(uuid.uuid4())
        self.entity_type = entity_type
        self.geometry = geometry
        self.rotation = rotation
        self.scale = scale
        self.layer = layer
        self.source = source  # Ex: "PDF", "DWG", "DEXPI"
        self.confidence = confidence
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "geometry": self.geometry,
            "rotation": self.rotation,
            "scale": self.scale,
            "layer": self.layer,
            "source": self.source,
            "confidence": self.confidence,
            "metadata": self.metadata
        }


class PipeEntity(NormalizedEntity):
    """Représentation intermédiaire d'un tuyau (Pipe run)."""
    def __init__(
        self,
        start_point: Tuple[float, float],
        end_point: Tuple[float, float],
        polyline: List[Tuple[float, float]],
        diameter: str = "",
        spec: str = "",
        line_number: str = "",
        service: str = "",
        fluid: str = "",
        pressure: float = 0.0,
        temperature: float = 0.0,
        material: str = "",
        insulation: str = "",
        **kwargs
    ):
        super().__init__(entity_type="Pipe", **kwargs)
        self.start_point = start_point
        self.end_point = end_point
        self.polyline = polyline
        self.diameter = diameter
        self.spec = spec
        self.line_number = line_number
        self.service = service
        self.fluid = fluid
        self.pressure = pressure
        self.temperature = temperature
        self.material = material
        self.insulation = insulation

    def to_dict(self) -> Dict[str, Any]:
        res = super().to_dict()
        res.update({
            "start_point": self.start_point,
            "end_point": self.end_point,
            "polyline": self.polyline,
            "diameter": self.diameter,
            "spec": self.spec,
            "line_number": self.line_number,
            "service": self.service,
            "fluid": self.fluid,
            "pressure": self.pressure,
            "temperature": self.temperature,
            "material": self.material,
            "insulation": self.insulation
        })
        return res


class Port:
    """Représente un point de raccordement physique ou logique sur un équipement."""
    def __init__(
        self,
        name: str,
        port_type: str,  # "IN", "OUT", "generic"
        position: Tuple[float, float],
        component_id: str
    ):
        self.id = f"{component_id}.{name}"
        self.name = name
        self.port_type = port_type
        self.position = position
        self.component_id = component_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "port_type": self.port_type,
            "position": self.position,
            "component_id": self.component_id
        }


class EquipmentEntity(NormalizedEntity):
    """Représentation d'un équipement majeur de procédé (pompe, séparateur, réservoir, etc.)."""
    def __init__(
        self,
        tag: str,
        equipment_type: str,
        bbox: List[float],
        ports: Optional[List[Port]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(entity_type="Equipment", **kwargs)
        self.tag = tag
        self.equipment_type = equipment_type
        self.bbox = bbox
        self.ports = ports or []
        self.attributes = attributes or {}

    def to_dict(self) -> Dict[str, Any]:
        res = super().to_dict()
        res.update({
            "tag": self.tag,
            "equipment_type": self.equipment_type,
            "bbox": self.bbox,
            "ports": [p.to_dict() for p in self.ports],
            "attributes": self.attributes
        })
        return res


class InstrumentEntity(NormalizedEntity):
    """Représentation d'un composant d'instrumentation (PIT, FIT, transmetteurs, etc.)."""
    def __init__(
        self,
        tag: str,
        loop: str,
        isa_symbol: str,
        bbox: List[float],
        thresholds: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        super().__init__(entity_type="Instrument", **kwargs)
        self.tag = tag
        self.loop = loop
        self.isa_symbol = isa_symbol
        self.bbox = bbox
        self.thresholds = thresholds or {}

    def to_dict(self) -> Dict[str, Any]:
        res = super().to_dict()
        res.update({
            "tag": self.tag,
            "loop": self.loop,
            "isa_symbol": self.isa_symbol,
            "bbox": self.bbox,
            "thresholds": self.thresholds
        })
        return res


class TextEntity(NormalizedEntity):
    """Représente un texte brut géolocalisé extrait du plan."""
    def __init__(
        self,
        text: str,
        font: str,
        height: float,
        bbox: List[float],
        **kwargs
    ):
        super().__init__(entity_type="Text", **kwargs)
        self.text = text
        self.font = font
        self.height = height
        self.bbox = bbox

    def to_dict(self) -> Dict[str, Any]:
        res = super().to_dict()
        res.update({
            "text": self.text,
            "font": self.font,
            "height": self.height,
            "bbox": self.bbox
        })
        return res


class DTIMNode:
    """Représente un nœud logique de connexion ou de jonction dans le réseau topologique."""
    def __init__(
        self,
        position: Tuple[float, float],
        node_type: str,  # "TEE", "CROSS", "REDUCER", "NOZZLE", "PIPE_END", "EQUIPMENT"
        connected_edges: Optional[List[str]] = None,
        confidence: float = 1.0
    ):
        self.id = str(uuid.uuid4())
        self.position = position
        self.node_type = node_type
        self.connected_edges = connected_edges or []
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "position": self.position,
            "node_type": self.node_type,
            "connected_edges": self.connected_edges,
            "confidence": self.confidence
        }


class DTIMEdge:
    """Représente une liaison ou arête du réseau reliant deux nœuds logiques."""
    def __init__(
        self,
        start_node_id: str,
        end_node_id: str,
        geometry: List[Tuple[float, float]],
        length: float = 0.0,
        diameter: str = "",
        spec: str = "",
        confidence: float = 1.0
    ):
        self.id = str(uuid.uuid4())
        self.start_node_id = start_node_id
        self.end_node_id = end_node_id
        self.geometry = geometry
        self.length = length
        self.diameter = diameter
        self.spec = spec
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "start_node_id": self.start_node_id,
            "end_node_id": self.end_node_id,
            "geometry": self.geometry,
            "length": self.length,
            "diameter": self.diameter,
            "spec": self.spec,
            "confidence": self.confidence
        }


class DTIMProject:
    """Conteneur global en mémoire pour un jumeau numérique topologique de procédé (DTIM)."""
    def __init__(self, project_name: str):
        self.project_name = project_name
        self.drawings: List[Dict[str, Any]] = []
        self.components: List[NormalizedEntity] = []
        self.pipes: List[PipeEntity] = []
        self.nodes: List[DTIMNode] = []
        self.edges: List[DTIMEdge] = []
        self.metadata: Dict[str, Any] = {}

    def add_component(self, comp: NormalizedEntity):
        self.components.append(comp)

    def add_pipe(self, pipe: PipeEntity):
        self.pipes.append(pipe)

    def add_node(self, node: DTIMNode):
        self.nodes.append(node)

    def add_edge(self, edge: DTIMEdge):
        self.edges.append(edge)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "drawings": self.drawings,
            "components": [c.to_dict() for c in self.components],
            "pipes": [p.to_dict() for p in self.pipes],
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "metadata": self.metadata
        }
