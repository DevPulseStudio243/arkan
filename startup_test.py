"""Test the lifespan components one by one to find crash"""
import asyncio, traceback, sys

async def test_startup():
    print("Testing startup...")
    
    # 1. AgentOrchestrator
    try:
        from agents import AgentOrchestrator
        o = AgentOrchestrator()
        print(f"[OK] AgentOrchestrator: {len(o.agents)} agents")
    except Exception as e:
        print(f"[FAIL] AgentOrchestrator: {e}")

    # 2. ProjectAnalyzer
    try:
        from project_understanding import ProjectAnalyzer
        pa = ProjectAnalyzer(model_path="project_model.json")
        print("[OK] ProjectAnalyzer")
    except Exception as e:
        print(f"[FAIL] ProjectAnalyzer: {e}")

    # 3. Training
    try:
        from training import ContinuousTrainer
        t = ContinuousTrainer()
        print("[OK] ContinuousTrainer")
    except Exception as e:
        print(f"[FAIL] ContinuousTrainer: {e}")

    # 4. QueryUnderstanding
    try:
        from project_understanding import SemanticQueryUnderstanding, ContextEnricher
        qu = SemanticQueryUnderstanding()
        ce = ContextEnricher()
        print("[OK] QueryUnderstanding + ContextEnricher")
    except Exception as e:
        print(f"[FAIL] QueryUnderstanding: {e}")

    # 5. FileProcessor
    try:
        from file_processor import FileProcessor
        fp = FileProcessor()
        print("[OK] FileProcessor")
    except Exception as e:
        print(f"[FAIL] FileProcessor: {e}")

    # 6. Vocabulary
    try:
        from vocabulary import expand_query
        expand_query("test")
        print("[OK] Vocabulary")
    except Exception as e:
        print(f"[FAIL] Vocabulary: {e}")

    # 7. AutoIndexer (start only, no scan)
    try:
        from auto_indexer import AutoIndexer
        ai = AutoIndexer()
        ai.start()
        print("[OK] AutoIndexer started")
        ai.stop()
        print("[OK] AutoIndexer stopped")
    except Exception as e:
        print(f"[FAIL] AutoIndexer: {e}")
        traceback.print_exc()

    # 8. AutoRetrainScheduler
    try:
        from learning import get_auto_retrain_scheduler
        sched = get_auto_retrain_scheduler()
        sched.start()
        print("[OK] AutoRetrainScheduler")
    except Exception as e:
        print(f"[FAIL] AutoRetrainScheduler: {e}")

    print("\nAll startup tests complete.")

asyncio.run(test_startup())
