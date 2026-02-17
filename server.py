"""
Sama Wellness — Custom LLM Proxy Server
Bridges VAPI (cloud) ↔ Local Ollama via OpenAI-compatible API.

Features:
  • RAG — user query is embedded (Ollama) → similarity search (Pinecone)
          → relevant chunks are injected into the system prompt.
  • Conversation memory — full chat history per call is stored in SQLite
          so the LLM always has context (who you are, what was said, etc.).

Usage:
  1. Copy .env.example → .env and fill in your keys
  2. Start Ollama:        ollama serve
  3. Pull models:         ollama pull mistral:7b && ollama pull nomic-embed-text
  4. (first time) Ingest: python ingest.py
  5. Start this server:   python server.py
  6. Expose via ngrok:    ngrok http 5000
  7. Paste ngrok URL in VAPI Dashboard → Custom LLM
"""

import os
import json
import requests
from flask import Flask, request, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

from conversation_store import ConversationStore  # noqa: E402
from rag import search_context                    # noqa: E402

app = Flask(__name__)
CORS(app)

# ── Config ──────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "mistral:7b")
# ────────────────────────────────────────────────────────────────────────────

# Conversation store (SQLite — auto-created on first run)
store = ConversationStore()


# ── Main endpoint ───────────────────────────────────────────────────────────

@app.route("/chat/completions", methods=["POST"])
@app.route("/", methods=["POST"])
def chat_completions():
    """
    Receives OpenAI-compatible chat completion requests from VAPI,
    augments with RAG context + conversation history, forwards to
    local Ollama, and streams the response back.
    """
    vapi_data = request.get_json()

    # 1. Identify the call (for conversation tracking)
    call_id = _extract_call_id(vapi_data)

    # 2. Pull out the latest user message
    incoming_messages = vapi_data.get("messages", [])
    user_message = _get_latest_user_message(incoming_messages)

    # 3. Persist the user turn
    if user_message:
        store.add_message(call_id, "user", user_message)

    # 4. RAG: embed → search Pinecone → get relevant chunks
    rag_context = ""
    if user_message:
        try:
            chunks = search_context(user_message)
            if chunks:
                rag_context = (
                    "\n\n--- Relevant knowledge-base context ---\n"
                    + "\n\n".join(chunks)
                    + "\n--- End of context ---\n"
                )
        except Exception as e:
            print(f"[RAG] Search failed (continuing without context): {e}")

    # 5. Build the full messages array: system + RAG + conversation history
    messages = _build_messages(call_id, rag_context, incoming_messages)

    # 6. Prepare & forward to Ollama
    ollama_payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
    }
    ollama_url = f"{OLLAMA_BASE_URL}/v1/chat/completions"

    # Debug: print the full messages payload sent to the LLM
    print("\n" + "=" * 60)
    print("  MESSAGES SENT TO LLM")
    print("=" * 60)
    for i, msg in enumerate(messages):
        role = msg["role"].upper()
        content = msg["content"]
        # Truncate long content for readability
        # preview = content if len(content) <= 300 else content[:300] + "…"
        print(f"  [{i}] {role}: {content}")
    print("=" * 60 + "\n")

    try:
        ollama_response = requests.post(
            ollama_url,
            json=ollama_payload,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=60,
        )
        ollama_response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("[ERROR] Cannot connect to Ollama. Is it running? (ollama serve)")
        return Response(
            _error_response("Ollama is not running. Start it with: ollama serve"),
            status=502, content_type="application/json",
        )
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Ollama request failed: {e}")
        return Response(
            _error_response(str(e)),
            status=502, content_type="application/json",
        )

    # 7. Stream SSE chunks back to VAPI — capture content for history
    def generate():
        full_response: list[str] = []
        try:
            for line in ollama_response.iter_lines(decode_unicode=True):
                if line:
                    yield line + "\n\n"
                    # Parse the SSE data to accumulate the assistant reply
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        try:
                            data = json.loads(line[6:])
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                full_response.append(token)
                        except (json.JSONDecodeError, IndexError, KeyError):
                            pass
            yield "data: [DONE]\n\n"
        finally:
            # Always persist the assistant reply (even on early disconnect)
            assistant_text = "".join(full_response)
            if assistant_text:
                store.add_message(call_id, "assistant", assistant_text)
                print(f"[CTX] Stored assistant reply for call {call_id[:12]}…")

    return Response(generate(), content_type="text/event-stream")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _extract_call_id(vapi_data: dict) -> str:
    """Extract a stable call identifier from VAPI's request."""
    return (
        # VAPI embeds call metadata in the body
        vapi_data.get("call", {}).get("id")
        # Some VAPI versions send it as a header instead
        or request.headers.get("x-vapi-call-id")
        or request.headers.get("x-request-id")
        # Fallback (single-session mode)
        or "default_session"
    )


def _get_latest_user_message(messages: list[dict]) -> str:
    """Return the content of the most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _build_messages(
    call_id: str,
    rag_context: str,
    incoming_messages: list[dict],
) -> list[dict]:
    """
    Assemble the messages array sent to the LLM:
        [system prompt + RAG]  →  [full conversation history from SQLite]

    The system prompt is taken from VAPI's incoming messages (so you can
    still edit it in the VAPI dashboard).  RAG chunks are appended to it.
    """
    # Use VAPI's system prompt if present, otherwise a sensible default
    system_content = (
        "You are a compassionate and knowledgeable wellness assistant for "
        "Sama Wellness. You speak warmly and provide helpful guidance."
    )
    for msg in incoming_messages:
        if msg.get("role") == "system":
            system_content = msg.get("content", system_content)
            break

    # Append retrieved RAG context
    if rag_context:
        system_content += rag_context

    messages: list[dict] = [{"role": "system", "content": system_content}]

    # Full conversation history from our store (already includes latest user msg)
    history = store.get_history(call_id)
    messages.extend(history)

    return messages


# ── Health ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        ollama_status = "connected"
    except Exception:
        models = []
        ollama_status = "unreachable"

    # Check Pinecone connectivity
    pinecone_status = "not configured"
    if os.environ.get("PINECONE_API_KEY") and os.environ.get("PINECONE_INDEX_NAME"):
        try:
            from pinecone import Pinecone
            pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
            pc.list_indexes()
            pinecone_status = "connected"
        except Exception:
            pinecone_status = "error"

    return {
        "status": "ok",
        "ollama": ollama_status,
        "ollama_url": OLLAMA_BASE_URL,
        "configured_model": OLLAMA_MODEL,
        "available_models": models,
        "pinecone": pinecone_status,
        "conversation_db": "SQLite (conversations.db)",
    }


def _error_response(message: str) -> str:
    """Build a JSON error payload."""
    return json.dumps({
        "error": {
            "message": message,
            "type": "server_error",
            "code": "ollama_error",
        }
    })


# ── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    rag_mode = "ON" if os.environ.get("PINECONE_API_KEY") else "OFF (set PINECONE_API_KEY)"
    print("=" * 60)
    print("  Sama Wellness — Custom LLM Proxy")
    print(f"  Ollama URL  : {OLLAMA_BASE_URL}")
    print(f"  Model       : {OLLAMA_MODEL}")
    print(f"  RAG         : {rag_mode}")
    print(f"  Memory      : SQLite (conversations.db)")
    print(f"  Endpoint    : http://localhost:5000/chat/completions")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
