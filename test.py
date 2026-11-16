import asyncio
import traceback

async def main():
    try:
        from api_enhanced import get_stats
        print("Import successful. Running get_stats...")
        stats = await get_stats()
        print("SUCCESS:", stats)
    except Exception as e:
        print("ERROR OCCURRED:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
