import os
print("DATABASE_URL =", os.getenv("DATABASE_URL"))
from dotenv import load_dotenv


env_path = os.path.join(os.path.dirname(__file__), "prisma", "prisma", ".env")
load_dotenv(dotenv_path=env_path)

import asyncio
from prisma.prisma.client import Prisma


async def check_titles():
    db = Prisma()
    await db.connect()

    threads = await db.thread.find_many(
        order={"updatedAt": "desc"},
        take=5
    )

    # 4️⃣ Print their IDs and names
    print("\nRecent thread titles:")
    for thread in threads:
        print(f"{thread.id} - {thread.name}")

    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check_titles())