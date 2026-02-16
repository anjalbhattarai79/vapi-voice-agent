## Frontend
cd "c:\Users\Anjal Bhattarai\Desktop\Sama Wellness\vapi-voice-agent" && npx -y http-server -p 5500 -c-1

## Custom LLM Proxy (Ollama)

### One-time setup
```bash
pip install -r requirements.txt
ollama pull llama3.2
```

### Run (3 terminals)
```bash
# Terminal 1 — Ollama
ollama serve

# Terminal 2 — Proxy server
python server.py

# Terminal 3 — Ngrok tunnel
ngrok http 5000
```

### VAPI Dashboard config
1. Go to VAPI Dashboard → your assistant → Model section
2. Select **Custom LLM**
3. Paste ngrok URL: `https://xxxx.ngrok-free.app/chat/completions`
4. Save & test

### Health check
Visit `http://localhost:5000/health` to verify Ollama connectivity.

### Environment overrides
```bash
set OLLAMA_MODEL=mistral        # use a different model
set OLLAMA_BASE_URL=http://localhost:11434  # custom Ollama URL
```