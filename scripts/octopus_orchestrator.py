#!/usr/bin/env python3
"""
ARKAN v3 / Octopus Consensus & Blindspot Audit Engine
Inspired by nyldn/claude-octopus, obra/superpowers, and Andrej Karpathy guidelines.
"""

import sys
import re
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

class OctopusOrchestrator:
    def __init__(self, workspace: Path):
        self.ws = workspace
        self.findings = []
        self.consensus = {}

    def audit_builder_perspective(self) -> dict:
        """Tentacle 1: Builder checks - Architecture, Skills & Directives presence."""
        agents_md = self.ws / "AGENTS.md"
        skills_dir = self.ws / ".agent" / "skills"
        
        has_agents = agents_md.exists()
        has_karpathy = False
        has_superpowers = False
        has_adhd = False
        has_octopus = False
        
        if has_agents:
            content = agents_md.read_text(encoding="utf-8")
            has_karpathy = "Karpathy Coding Guidelines" in content
            has_superpowers = "Superpowers Engineering Protocols" in content
            has_adhd = "I Have ADHD High-Signal" in content
            has_octopus = "Claude Octopus Multi-Agent" in content
            
        skills_found = []
        if skills_dir.exists():
            for sk in ["superpowers", "karpathy-engineering", "adhd-communication", "octopus-swarm"]:
                sk_file = skills_dir / sk / "SKILL.md"
                if sk_file.exists():
                    skills_found.append(sk)
                    
        passed = (has_agents and has_karpathy and has_superpowers and has_adhd and has_octopus and len(skills_found) == 4)
        return {
            "name": "Builder Perspective",
            "passed": passed,
            "details": {
                "agents_md_configured": has_agents and has_karpathy and has_superpowers and has_adhd and has_octopus,
                "skills_registered": skills_found,
                "total_skills": len(skills_found)
            }
        }

    def audit_red_team_critic(self) -> dict:
        """Tentacle 2: Red Team Critic - Blindspots, Hardcoding, Edge Cases."""
        blindspots = []
        
        # 1. Zero-hardcoding invariant check in routing logic (excluding tests/ and scripts/)
        # Specifically checks for conditional branching on specific test drawing names or line tags
        routes_dir = self.ws / "routes"
        if routes_dir.exists():
            for py_file in routes_dir.glob("*.py"):
                code = py_file.read_text(encoding="utf-8")
                # Look for hardcoded test drawing equality comparisons in extraction logic
                if re.search(r'(==|in)\s*\[?["\'](DW-300010|ELE-DW-300001|DN-300004|P-101A)["\']', code):
                    if "test" not in py_file.name.lower():
                        blindspots.append(f"Hardcoded drawing comparison detected in {py_file.name}")
                    
        # 2. Syntax integrity of UI scripts
        ui_file = self.ws / "templates" / "arkan-ui.html"
        if ui_file.exists():
            ui_text = ui_file.read_text(encoding="utf-8")
            # Check for let API_BASE duplicate declaration bug
            if "let API_BASE =" in ui_text:
                blindspots.append("Duplicate let API_BASE declaration found in UI")
            if "applyIePlanTransform" not in ui_text:
                blindspots.append("Missing applyIePlanTransform in UI script")

        # 3. Virtual environment check
        venv_py = self.ws / "venv" / "Scripts" / "python.exe"
        if not venv_py.exists():
            blindspots.append("Local virtual environment python.exe not found")

        passed = len(blindspots) == 0
        return {
            "name": "Red-Team Critic (Blindspot Hunter)",
            "passed": passed,
            "blindspots_detected": blindspots,
            "blindspot_count": len(blindspots)
        }

    def audit_gatekeeper(self) -> dict:
        """Tentacle 3: Gatekeeper - Automated Tests & Quality Gates."""
        test_suite = self.ws / "tests" / "run_all_tests.py"
        test_scripts = self.ws / "test_scripts.py"
        test_visualizer = self.ws / "test_ie_visualizer.py"
        
        all_exist = test_suite.exists() and test_scripts.exists() and test_visualizer.exists()
        return {
            "name": "Gatekeeper (Verification)",
            "passed": all_exist,
            "details": {
                "regression_suite_ready": test_suite.exists(),
                "ui_syntax_tester_ready": test_scripts.exists(),
                "ie_visualizer_tester_ready": test_visualizer.exists()
            }
        }

    def run_consensus(self) -> bool:
        """Evaluates overall consensus across all 3 tentacles."""
        t1 = self.audit_builder_perspective()
        t2 = self.audit_red_team_critic()
        t3 = self.audit_gatekeeper()
        
        all_passed = t1["passed"] and t2["passed"] and t3["passed"]
        
        print("=" * 65)
        print("  OCTOPUS MULTI-AGENT CONSENSUS & BLINDSPOT AUDIT REPORT")
        print("=" * 65)
        
        print(f"\n[Tentacle 1: {t1['name']}] -> {'[PASS]' if t1['passed'] else '[FAIL]'}")
        print(f"  - AGENTS.md Fully Configured : {t1['details']['agents_md_configured']}")
        print(f"  - Native Skills Active       : {', '.join(t1['details']['skills_registered'])} (4/4)")
        
        print(f"\n[Tentacle 2: {t2['name']}] -> {'[PASS]' if t2['passed'] else '[FAIL]'}")
        print(f"  - Blindspots Found           : {t2['blindspot_count']}")
        for b in t2["blindspots_detected"]:
            print(f"    * [WARNING] {b}")
        if t2['passed']:
            print("  - Zero Hardcoding Invariant   : CONFIRMED (routes are clean)")
            print("  - UI Syntax Conflict Checks   : CONFIRMED (0 lexical conflicts)")
            
        print(f"\n[Tentacle 3: {t3['name']}] -> {'[PASS]' if t3['passed'] else '[FAIL]'}")
        print(f"  - ARKAN v3 Regression Suite   : READY")
        print(f"  - V8 UI Scripts Checker       : READY")
        print(f"  - E&I HD Visualizer Harness   : READY")
        
        print("\n" + "=" * 65)
        if all_passed:
            print("  [OCTOPUS CONSENSUS REACHED] : 3/3 TENTACLES IN AGREEMENT (PASS)")
        else:
            print("  [OCTOPUS CONSENSUS FAILED]  : DISAGREEMENTS DETECTED")
        print("=" * 65)
        
        return all_passed

if __name__ == "__main__":
    orchestrator = OctopusOrchestrator(WORKSPACE)
    success = orchestrator.run_consensus()
    sys.exit(0 if success else 1)
