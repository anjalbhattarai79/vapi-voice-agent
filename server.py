"""
Sama Wellness — Custom LLM Proxy Server
Bridges VAPI (cloud) ↔ Local Ollama via OpenAI-compatible API.

Usage:
  1. Start Ollama:        ollama serve
  2. Pull a model:        ollama pull llama3.2
  3. Start this server:   python server.py
  4. Expose via ngrok:    ngrok http 5000
  5. Paste ngrok URL in VAPI Dashboard → Custom LLM → https://xxxx.ngrok-free.app/chat/completions
"""

import os
import json
import requests
from flask import Flask, request, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Config ──────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:1b")  # change to your preferred model
# ────────────────────────────────────────────────────────────────────────────────


@app.route("/chat/completions", methods=["POST"])
@app.route("/", methods=["POST"])
def chat_completions():
    """
    Receives OpenAI-compatible chat completion requests from VAPI,
    forwards them to local Ollama, and streams the response back.
    
    Accepts POST on both "/" and "/chat/completions" because:
    - VAPI may append /chat/completions to your base URL automatically
    - So just paste the bare ngrok URL in the dashboard (without /chat/completions)
    """
    vapi_data = request.get_json()

    # Override model to whatever Ollama is servin   g locally
    vapi_data["model"] = OLLAMA_MODEL

    # Ensure streaming is enabled (VAPI expects SSE for real-time voice)
    vapi_data["stream"] = True

    # Forward to Ollama's OpenAI-compatible endpoint
    ollama_url = f"{OLLAMA_BASE_URL}/v1/chat/completions"

    try:
        ollama_response = requests.post(
            ollama_url,
            json=vapi_data,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=60,
        )
        ollama_response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("[ERROR] Cannot connect to Ollama. Is it running? (ollama serve)")
        error_payload = _error_response("Ollama is not running. Start it with: ollama serve")
        return Response(error_payload, status=502, content_type="application/json")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Ollama request failed: {e}")
        error_payload = _error_response(str(e))
        return Response(error_payload, status=502, content_type="application/json")

    # Stream SSE chunks back to VAPI
    def generate():
        for line in ollama_response.iter_lines(decode_unicode=True):
            if line:
                yield line + "\n\n"
        # Signal end of stream
        yield "data: [DONE]\n\n"

    return Response(generate(), content_type="text/event-stream")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    # Quick check if Ollama is reachable
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        ollama_status = "connected"
    except Exception:
        models = []
        ollama_status = "unreachable"

    return {
        "status": "ok",
        "ollama": ollama_status,
        "ollama_url": OLLAMA_BASE_URL,
        "configured_model": OLLAMA_MODEL,
        "available_models": models,
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


if __name__ == "__main__":
    print("=" * 60)
    print("  Sama Wellness — Custom LLM Proxy")
    print(f"  Ollama URL  : {OLLAMA_BASE_URL}")
    print(f"  Model       : {OLLAMA_MODEL}")
    print(f"  Endpoint    : http://localhost:5000/chat/completions")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
