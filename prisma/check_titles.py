from prisma import prisma
import asyncio

async def check_titles():
    db = prisma()
    await db.connect()

    threads = await db.thread.find_many(
        order={"updatedAt": "desc"},
        take=5
    )
    for thread in threads:
        print(f"{thread.id} - {thread.name}")

    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check_titles())