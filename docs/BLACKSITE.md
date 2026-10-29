# Blacksite workspace

Start on Windows after initial setup:

```powershell
.\start_windows.ps1
```

The interface, fonts and rendering libraries are bundled. After installing the
chosen Ollama/STT/TTS models once, inference uses local services. No remote font,
image, analytics or cloud inference service was added. Initial installation and
model downloads require a network connection; downloading is not inference.

## Workspace

The conversation occupies one fullscreen scene. The constellation remains behind
it at desktop and phone sizes. The rail opens History, Files, Devices, application
permissions and Settings as native, keyboard-contained dialogs. The model badge
opens model settings. The plus button starts another conversation.

Ambient shows subtle context. Focus emphasizes conversation topics, session memory
and related targets. Map expands the scene with selection, dragging, recentering
and Alt+arrow movement through the node selector. Closing Map restores its previous
mode without changing the draft. Devices shows configured devices; Files shows
selected documents and sources actually used. Merely discovering an application
or permitting a retrieval source does not create a contextual relationship.
Selecting a node grants no operating-system permission.

The composer has separate document and image pickers, microphone, voice mode,
pause, stop, response interruption and send. Voice mode toggles local answer
playback; it never activates the microphone. Record deliberately, then review and
edit the transcript before sending. Wave amplitude in the existing Canvas scene
comes from the active capture/playback analyser, rather than simulated sound.
Reduced motion follows the OS or Settings; economy mode stops background drift.

## Documents

Drop or paste files into the composer, or use the document picker. Limits remain
eight files, 10 MiB each and 40 MiB total. TXT/MD/CSV support UTF-8, BOM-marked
UTF-16 and Windows-1251. Text-bearing PDF and DOCX are extracted on the local
server. Images use Canvas previews in the browser and are never sent for visual
understanding; this version does not enable vision or OCR.

Preparation, parsing, ready, added-to-context and errors reflect actual work.
Ready means extraction succeeded. Added-to-context means a chat response identified
that document in its authoritative context_sources. Documents are used for ordinary
knowledge answers, not as tool instructions or action authority. Action-only turns
do not claim document use. The file preview displays up to 6,000 extracted
characters, not a facsimile PDF page. Source names and truncation are displayed;
each file is bounded to 12,000 extracted characters and each request to 32,000.
Scans, encrypted PDFs, corrupt archives and resource-limit failures are explicit.

Complex parsers run in disposable application-owned worker processes, with a
10-second deadline, 256 MiB process memory cap and two concurrent slots. DOCX has
additional archive/XML limits. Uploaded paths are never interpreted as server
filesystem locations. Opaque document IDs belong to exactly one expiring server
conversation. Removing a document excludes it from future submissions; removal
cannot undo an inference request that already took its context snapshot.

## History and privacy

History supports new, switch, rename and delete, with separate drafts and messages.
By default this lives in browser-tab memory. Selecting “save text conversations on
this computer” explicitly enables localStorage. Keys, audio, file bytes, tool
permissions and server IDs are excluded. Saved message text can contain sensitive
information, including quoted document content. Turn persistence off to delete
the browser copy, or use “delete all history”. Storage denial keeps the session
usable and reports the problem.

Reloaded conversations are read-only archives. Live sessions are checked against
the server before switching; expired/restarted sessions become archives. Opening
an archive never sends its messages, replays actions or reinstates grants. Start
a new conversation to continue. Switching during generation or microphone work
is refused with a status message; stop or finish the current work first. Reset
invalidates pending transcription immediately. Attachments remain isolated between
live conversations and are not restored from persistent history.

Devices show DEMO simulation or REAL Home Assistant status explicitly. The drawer
prepares allowlisted lamp commands for review in the composer; the user still sends
the command. REAL request acceptance is not a confirmed physical device state.

## Offline demonstration and troubleshooting

1. Install dependencies and download the selected local models as described in
   README.md and docs/VOICE.md. Start with the command above.
2. Open the workspace, keep DEMO enabled, ask a knowledge question, upload a small
   text document and ask about its content. Inspect the context acknowledgement.
3. Create another conversation, switch back and inspect the independent draft.
   Expand Map and inspect source/topic relationships. Prepare a DEMO lamp command.
4. Disconnect external networking after assets/models are installed and repeat.
   A server/model error must remain visible; there is no cloud fallback.

If the configured port is occupied, select another port using LOCALMIND_PORT in
the project configuration. Do not terminate unrelated servers. If extraction
fails, check the exact error, reduce the document, or export plain UTF-8 text.
Scanned PDFs require OCR outside this version. If the parser memory boundary is
unavailable it fails closed. If Ollama is missing or the model is not installed,
install/select a local model; no answer is fabricated. Microphone use needs
localhost and browser permission; text remains available on denial. See README.md,
docs/KNOWN_LIMITATIONS.md and docs/VOICE.md for the existing troubleshooting paths.

## Verification limits for this change

The automated Python and DOM suites test actual parser processes and inference
payload construction, along with mocked local LLM/HA adapters. Mocks are not real
hardware integrations. Browser regression scenarios include desktop/mobile,
CSS-scale 100/125/140%, drawers, Map, attachments and history, with external HTTP
blocked, but execution was blocked by sandbox worker spawn EPERM in this Builder
session. Native browser fallback denied access to Zen. No new screenshots, native
zoom, GPU/FPS comparison, microphone capture or physical Home Assistant results are
claimed. Before/after benchmark attempts produced failure artifacts, not metrics.
The previous performance report predates this design and does not validate it.

The existing docs/DEFENSE_QA.md retains forty explanatory defense answers; the
student can additionally explain context IDs, parser budgets, read-only archives,
and why document content cannot authorize operating-system actions.
