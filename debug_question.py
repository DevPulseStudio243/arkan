import sys
import asyncio
from api_enhanced import process_question, QuestionRequest, lifespan, app

async def test():
    # Simulate FastAPI lifespan
    async with lifespan(app):
        req = QuestionRequest(question="equipement list Unite de boosting LDBP4_CIS", use_agents=True)
        try:
            res = await process_question(req, "test_key")
            print("Success:", res)
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
