# Архитектура LocalMind 0.1

```text
[Browser/UI & microphone]
      | HTTP /api/chat (JSON) or /api/transcribe (audio)
      v
[FastAPI server: validation + optional LOCALMIND_KEY]
      |
      +--> [Fast deterministic routing]
      |           | only if command exactly recognizable
      |           v
      |      [Device gateway] --> [Demo simulator] OR [Home Assistant REST API]
      |
      +--> [Local Ollama /api/chat] --> [LLM text or tool call]
                  | tool request, NEVER arbitrary executable code
                  v
             [Tool dispatcher allowlist]
                  | set_light (restricted ID and state) or open_app (restricted app)
                  v
             [Device gateway / OS]
      |
      v
[HTTP JSON response: answer + actions + timing]
```

**Trust boundaries**: client API key checked by server; input validated by Pydantic; model output treated as untrusted proposal; dispatcher restricts allowed names and arguments; Home Assistant token lives in `.env`; API only listens on loopback by default.

**Current limitations**: browser TTS not guaranteed local; STT optional & CPU; microphone on another LAN device needs secure context; no wake-word; no satellite; no multi-user sessions; network transport lacks TLS; `/api/transcribe` has simple file size/type checks but not an audio-duration cap; voice uploads may block worker while running STT; no permanent audit-log or recovery flow; cannot guarantee safety for every malicious prompt. These require work before production use.

**Future**: satellite (ESP32-S3 with compatible microphone/speaker or a second device), authenticated HTTPS/WebSocket audio, wake word, Piper TTS on PC, configurable safe skills, measurements and results dashboard.
