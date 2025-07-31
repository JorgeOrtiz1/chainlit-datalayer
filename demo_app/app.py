import os
import json
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from openai import AzureOpenAI
import chainlit as cl
from chainlit.types import ThreadDict

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")
PG_DATABASE = os.getenv("PG_DATABASE")

@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    if (username, password) == ("admin", "admin"):
        return cl.User(
            identifier="admin", metadata={"role": "admin", "provider": "credentials"}
        )
    else:
        return None
    
# Azure OpenAI configuration    
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2025-01-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME")
SESSION_FILE = "chat_history.json"

def timestamp_now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def load_global_sessions():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("⚠️ Corrupted JSON file. Starting fresh.")
            return []
    return []

def save_global_session(new_session):
    try:
        sessions = load_global_sessions()
        sessions.append(new_session)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)
        print(f"✅ Session saved. Total sessions: {len(sessions)}")
    except Exception as e:
        print(f"❌ Error saving session: {e}")


def get_last_session_messages():
    sessions = load_global_sessions()
    if not sessions:
        return []

    last_log = sessions[-1]["full_log"]
    messages = []
    for line in last_log.split("\n"):
        if not line.strip():
            continue
        try:
            # Format: [YYYY-MM-DD HH:MM:SS] Role: Message
            timestamp_end = line.find("]")
            role_start = timestamp_end + 2
            role_end = line.find(":", role_start)
            role = line[role_start:role_end].strip().lower()
            content = line[role_end + 1:].strip()
            if role in ["user", "assistant"]:
                messages.append({"role": role, "content": content})
        except Exception as e:
            print(f"⚠️ Skipping malformed log line: {line}")
    return messages

def get_pg_connection():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE,
        cursor_factory=RealDictCursor
    )

def update_session_title(session_id: str, new_title: str):
    sql = """
    UPDATE "Thread"
    SET name = %s
    WHERE id = %s
    """
    try:
        conn = get_pg_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, (new_title, session_id))
        print(f"✅ Session title updated to '{new_title}' for session id {session_id}")
    except Exception as e:
        print(f"❌ Error updating session title: {e}")
    finally:
        if conn:
            conn.close()

@cl.on_chat_start
async def on_chat_start():
    session_id = cl.context.session.id
    cl.user_session.set("session_id", session_id)

@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict):
    # ✅ Store the thread.id into user session so we can later update the DB
    cl.user_session.set("session_id", thread["id"])

    prev_messages = get_last_session_messages()

    if prev_messages:
        cl.user_session.set("chat_history", prev_messages)
        await cl.Message(content="✅ Previous session history loaded.").send()
    else:
        cl.user_session.set("chat_history", [])
        await cl.Message(content="⚠️ No previous session history found. Starting fresh.").send()


@cl.on_message  # this function will be called every time a user inputs a message in the UI
async def main(message: cl.Message):
    chat_history = cl.user_session.get("chat_history") or []
    chat_history.append({"role":"user", "content": message.content, "timestamp": timestamp_now()})

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        *[{"role": m["role"], "content": m["content"]} for m in chat_history]
    ]
    # Build the full message history (excluding timestamps for OpenAI)

    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages
    )
    
    # Llama a la API de OpenAI para obtener una respuesta del modelo.
    reply = response.choices[0].message.content
    # Extrae el contenido de la respuesta generada por el modelo.

    chat_history.append({"role":"assistant", "content": reply, "timestamp": timestamp_now()})
    # Añade la respuesta del modelo al historial de chat.

    cl.user_session.set("chat_history", chat_history)
    await cl.Message(content=reply).send()


@cl.on_chat_end
async def store_full_session():
    chat_history = cl.user_session.get("chat_history") or []
    if not chat_history:
        return

    # Full readable chat log
    log_text = "\n".join(
        f"[{m['timestamp']}] {m['role'].capitalize()}: {m['content']}"
        for m in chat_history
    )

    # Title generation
    title_prompt = [
        {"role": "system", "content": "Write a short 5–8 word title for this chat."},
        {"role": "user", "content": log_text}
    ]
    title_response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=title_prompt
    )
    title = title_response.choices[0].message.content.strip().title()

    session_id = cl.user_session.get("session_id")  # or wherever you store it
    print(session_id)

    if session_id: 
        # Update the session title in the database
        update_session_title(session_id, title) 
        # As a fallback: set a metadata flag to tell frontend the title changed
        print(f"✅ Session title updated to '{title}' for session id {session_id}")
        await cl.Message(f"✅ Updated session title to: **{title}**").send()

        
    else:
        print("⚠️ No session_id found in user_session; skipping DB title update")


    # Summary generation
    summary_prompt = [
        {"role": "system", "content": "Summarize this chat in 1–2 short sentences."},
        {"role": "user", "content": log_text}
    ]
    summary_response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=summary_prompt
    )
    summary = summary_response.choices[0].message.content.strip()

    
    # Save to file
    save_global_session({
        "title": title,
        "summary": summary,
        "full_log": log_text,
        "timestamp": timestamp_now()
    })

    
