# iso_multi_agent_ensemble.py

- AgentMetadataOutput · class · L21-L32 — class AgentMetadataOutput
- AgentBOMItem · class · L35-L49 — class AgentBOMItem
- AgentSpoolOutput · class · L52-L58 — class AgentSpoolOutput
- EnsembleAnalysisResult · class · L61-L74 — class EnsembleAnalysisResult
- CartoucheAgent · class · L80-L152 — class CartoucheAgent
- extract · method · L83-L152 — def extract(self, text: str, filename: str) -> AgentMetadataOutput
- AsmeBomAgent · class · L158-L517 — class AsmeBomAgent
- extract_implicit_mto · method · L161-L365 — def extract_implicit_mto(self, text: str, default_spec: str) -> List[AgentBOMItem]
- extract · method · L367-L517 — def extract(self, text: str, default_spec: str) -> List[AgentBOMItem]: # Détection du mode : Plan avec bordereau explicite vs Plan sans MTO (tracé pur / cotes implicites)
- SpoolWeldsAgent · class · L523-L585 — class SpoolWeldsAgent
- analyze · method · L526-L585 — def analyze(self, text: str, bom_items: List[AgentBOMItem], pipe_length_m: float) -> AgentSpoolOutput: # Spools
- AuditorConsensusAgent · class · L591-L646 — class AuditorConsensusAgent
- audit · method · L594-L646 — def audit(self, metadata: AgentMetadataOutput, bom: List[AgentBOMItem], spool: AgentSpoolOutput) -> Dict[str, Any]
- IsoMultiAgentEnsemble · class · L652-L702 — class IsoMultiAgentEnsemble
- __init__ · method · L655-L659 — def __init__(self)
- process_drawing · method · L661-L702 — def process_drawing(self, text: str, filename: str) -> EnsembleAnalysisResult
- get_iso_multi_agent_ensemble · function · L707-L711 — def get_iso_multi_agent_ensemble() -> IsoMultiAgentEnsemble
