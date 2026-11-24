import asyncio
import sys

if sys.platform == "win32":
    # psycopg's async mode (used by the LangGraph Postgres checkpointer) cannot run on the
    # default Proactor loop. Production runs on Linux, where this is not needed.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
