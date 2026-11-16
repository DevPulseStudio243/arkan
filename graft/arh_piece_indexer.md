# arh_piece_indexer.py

- ARHPieceIndexer · class · L45-L225 — class ARHPieceIndexer
- __init__ · method · L46-L56 — def __init__(self, chroma_path: Optional[str] = None)
- _get_embedding · method · L58-L73 — def _get_embedding(self, text: str) -> List[float]
- _batch_get_embeddings · method · L75-L79 — def _batch_get_embeddings(self, texts: List[str]) -> List[List[float]]
- index_dossier_pieces · method · L81-L176 — def index_dossier_pieces(self, dossier_id: str) -> Dict[str, Any]
- search_pieces · method · L179-L225 — def search_pieces(self, dossier_id: str, query: str, piece_code: Optional[str] = None, discipline: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]
