"""
DeerFlow Lite — Tool Maker (Agentic Tool Creation)
Permet à l'Agent Raisonneur de générer, valider (sandbox) et sauvegarder
des outils dynamiques (fonctions Python) à la volée.
"""
import ast
import inspect
import logging
from pathlib import Path
from typing import Callable, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Modules strictement interdits dans le code généré par l'agent
BANNED_MODULES = {
    'os', 'sys', 'subprocess', 'shutil', 'pathlib', 'socket', 
    'requests', 'httpx', 'urllib', 'http', 'ftplib', 'sqlite3', 
    'sqlalchemy', 'pymongo', 'threading', 'multiprocessing', 'builtins'
}

# Fichier où les outils dynamiques seront stockés de manière persistante
DYNAMIC_TOOLS_FILE = Path(__file__).parent / "dynamic_tools.py"


def _ensure_dynamic_tools_file():
    """Crée le fichier dynamic_tools.py s'il n'existe pas."""
    if not DYNAMIC_TOOLS_FILE.exists():
        DYNAMIC_TOOLS_FILE.write_text(
            "# Fichier généré automatiquement par Tool Maker.\n"
            "# Contient les outils Python créés dynamiquement par l'Agent Raisonneur.\n\n"
            "import math\n"
            "import json\n\n",
            encoding="utf-8"
        )


class SecurityNodeVisitor(ast.NodeVisitor):
    """Vérificateur AST pour s'assurer de l'innocuité du code généré."""
    
    def __init__(self):
        self.errors = []
        # On interdit l'accès à certaines fonctions natives critiques
        self.banned_functions = {'eval', 'exec', 'open', 'compile', 'globals', 'locals', '__import__'}

    def visit_Import(self, node):
        for alias in node.names:
            base_module = alias.name.split('.')[0]
            if base_module in BANNED_MODULES:
                self.errors.append(f"Import interdit : {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            base_module = node.module.split('.')[0]
            if base_module in BANNED_MODULES:
                self.errors.append(f"Import depuis interdit : {node.module}")
        self.generic_visit(node)
        
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in self.banned_functions:
                self.errors.append(f"Appel de fonction interdit : {node.func.id}")
        self.generic_visit(node)


def is_code_safe(code: str) -> Tuple[bool, str]:
    """
    Analyse le code Python généré via AST pour bloquer les opérations risquées.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Erreur de syntaxe Python: {e}"

    visitor = SecurityNodeVisitor()
    visitor.visit(tree)

    if visitor.errors:
        return False, "Faille de sécurité détectée : " + " | ".join(visitor.errors)

    # Vérifier qu'il y a au moins une fonction définie
    has_func = any(isinstance(node, ast.FunctionDef) for node in tree.body)
    if not has_func:
        return False, "Le code doit contenir la définition d'une fonction (def func_name(...):)."

    return True, "OK"


def tool_create_tool(tool_name: str, description: str, python_code: str, params: list[str]) -> str:
    """
    Outil appelé par l'agent pour écrire un nouvel outil.
    Valide la sécurité du code et l'ajoute à dynamic_tools.py.
    """
    try:
        # Nettoyage rudimentaire si le LLM renvoie des marqueurs markdown
        python_code = python_code.strip()
        if python_code.startswith("```python"):
            python_code = python_code[9:]
        if python_code.endswith("```"):
            python_code = python_code[:-3]
        python_code = python_code.strip()

        logger.info(f"[ToolMaker] Demande de création de l'outil '{tool_name}'")

        # 1. Vérification de la sécurité du code
        safe, message = is_code_safe(python_code)
        if not safe:
            logger.warning(f"[ToolMaker] Refus de sécurité pour '{tool_name}': {message}")
            return f"ECHEC: Le code généré a été rejeté par la sécurité. Raison: {message}"

        # 2. Sauvegarde dans le fichier persistant
        _ensure_dynamic_tools_file()
        
        # S'assurer qu'on ne duplique pas le nom de fonction
        # (Dans un système avancé on remplacerait, ici on ajoute bêtement si ça compile)
        with open(DYNAMIC_TOOLS_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n\n# --- Outil auto-généré : {tool_name} ---\n")
            f.write(f"# Description : {description}\n")
            f.write(python_code)
            f.write("\n")
            
        logger.info(f"[ToolMaker] Outil '{tool_name}' enregistré avec succès dans dynamic_tools.py")
        
        return f"SUCCES: L'outil '{tool_name}' a été créé, vérifié et compilé. Vous pouvez l'utiliser lors de votre prochaine Action."
    
    except Exception as e:
        logger.error(f"[ToolMaker] Erreur création outil: {e}", exc_info=True)
        return f"ECHEC: Une erreur inattendue s'est produite lors de la compilation de l'outil: {e}"


def get_dynamic_tools() -> Dict[str, Dict[str, Any]]:
    """
    Charge les fonctions de dynamic_tools.py pour les injecter dans l'Agent Raisonneur.
    """
    _ensure_dynamic_tools_file()
    loaded_tools = {}
    
    try:
        import dynamic_tools
        # On force le rechargement pour capter les nouveaux outils ajoutés pendant la runtime
        import importlib
        importlib.reload(dynamic_tools)
        
        # On extrait toutes les fonctions définies dans le module dynamique
        for name, obj in inspect.getmembers(dynamic_tools, inspect.isfunction):
            # Ignorer les fonctions internes/privées si besoin
            if name.startswith('_'):
                continue
                
            # Extraire la signature pour obtenir les paramètres
            sig = inspect.signature(obj)
            param_names = list(sig.parameters.keys())
            
            # Utiliser la docstring comme description (ou fallback)
            desc = obj.__doc__ or f"Outil auto-généré {name}. Paramètres: {', '.join(param_names)}."
            
            loaded_tools[name] = {
                "fn": obj,
                "description": desc.strip().replace('\n', ' '),
                "params": param_names
            }
            
        return loaded_tools
    except Exception as e:
        logger.error(f"[ToolMaker] Erreur lors du chargement des outils dynamiques: {e}")
        return {}

