import asyncio
from sqlalchemy import select

from database.engine import engine
from models import User


async def test():
    async with engine.connect() as conn:
        result = await conn.execute(select(User))
        print("User table accessible:", result.fetchall() == [])


if __name__ == "__main__":
    asyncio.run(test())