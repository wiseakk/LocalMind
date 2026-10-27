# Архитектура LocalMind 0.1

```text
[Browser/UI & microphone]
      | /api/transcribe returns editable text; explicit Send calls /api/chat
      v
[FastAPI server: loopback guard + validation + optional LOCALMIND_KEY]
      |
      +--> [Action policy: negation/quote/ambiguity checks]
      |           | one exact server-authorized action and target
      |           v
      |      [Validated dispatcher]
      |           +--> [Device gateway] --> [Demo] OR [Home Assistant REST API]
      |           +--> [Verified absolute Windows executable]
      |
      +--> [Local Ollama /api/chat] --> [text response only; no executable tools]
      |
      v
[HTTP JSON response: answer + actions + timing]
```

**Trust boundaries**: non-loopback clients are rejected; client API key is optionally checked by the server; input is validated by Pydantic; model output is never dispatched; the action policy and dispatcher independently restrict names, exact arguments and targets; Home Assistant token lives in `.env`; the supported launcher binds only to `127.0.0.1`.

**Current limitations**: browser TTS is not guaranteed local; STT is optional and currently configured for CPU; no wake-word, satellite or multi-user sessions; LAN access is disabled because there is no paired TLS transport; `/api/transcribe` has file size/type checks but not an audio-duration cap; voice uploads may block a worker while STT runs; automatic app close is refused because a safe per-window handle is not available; there is no permanent audit log or recovery flow. These require work before production use.

**Future**: satellite (ESP32-S3 with compatible microphone/speaker or a second device), authenticated HTTPS/WebSocket audio, wake word, Piper TTS on PC, configurable safe skills, measurements and results dashboard.
