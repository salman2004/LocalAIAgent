# Local Assistant

A fully local AI assistant: reasoning, coding help, research (local docs +
live web), and workspace file access - run entirely from PowerShell, styled
after Claude Code. Voice (wake-word listening + speech output) is planned
but currently paused. No cloud LLM APIs are used for the core loop.

## Architecture

```
cli/tui.py (Textual, primary)  --\
cli/chat.py (plain fallback)    --->--HTTP-->  assistant_core (FastAPI, port 8090)
                                                    |  tool-calling loop (orchestrator.py)
                                                    |-- rag_search   --> LanceDB (rag_store/)
                                                    |-- web_search / web_fetch --> live internet
                                                    |-- list_directory / read_file
                                                    |-- write_file / delete_file  --> workspace/
                                                    |     (these two require an explicit
                                                    |      y/n confirmation in the terminal
                                                    |      before they run)
                                                    v
                                    llama.cpp server (port 8080, chat model, Qwen3-14B)
                                    llama.cpp server (port 8081, embedding model)
```

`cli/tui.py` is the primary interface: a Textual terminal app that streams
replies, shows the model's reasoning in a collapsible panel, shows tool-use
status lines, and pops a modal asking for approval before any file write or
delete. `cli/chat.py` is a minimal fallback that talks to the same `/chat`
endpoint without any of that (and can't approve mutating file actions at
all - see "Workspace file access" below).

Everything runs locally except `web_search`/`web_fetch`, which make real
outbound requests to search the live web. That's the one deliberate
exception to "fully local" - no cloud LLM/inference API is ever called.

## Hardware this is tuned for

- AMD RX 9070 XT (16GB VRAM, RDNA4)
- Ryzen 7 7800X3D, 32GB DDR5
- Windows 11

We use llama.cpp's **Vulkan** backend rather than ROCm: ROCm support for
RDNA4 is still new and Linux-focused, while Vulkan works well on AMD/Windows
today without needing the HIP SDK installed at all.

## Setup

### Prerequisites

- Up-to-date AMD Adrenalin drivers (for Vulkan support)
- Windows 11 with PowerShell (Python itself is installed automatically if missing)
- ~13GB free disk space for the default models

### One-shot install

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

This single script:

1. Installs Python via `winget` if it isn't already on your system.
2. Creates `.venv` and installs `requirements.txt` into it.
3. Downloads the latest llama.cpp **Vulkan** Windows build into `.\vendor\llama.cpp\`.
4. Downloads the two default GGUF models into `.\models\`:
   - `Qwen3-14B` (Q5_K_M, ~10GB) - the chat/coding model. Chosen over the
     earlier Qwen2.5-Coder default specifically because it has a thinking
     mode: it emits its reasoning before its answer, which the terminal UI
     shows in a collapsible panel.
   - `nomic-embed-text-v1.5` (Q8_0, ~150MB) - the RAG embedding model

It's safe to re-run if something fails partway (a dropped download, etc.) -
already-completed steps are skipped.

> Model choice is just a config value (`config.yaml`), not an architectural
> decision - swap it any time. `Qwen3-30B-A3B` (a mixture-of-experts model
> with ~3B active params) is worth trying later: often better reasoning than
> a 14B dense model at similar speed, since only a fraction of its weights
> activate per token. Just download the new GGUF into `.\models\` and update
> `llm.model_path`. Whatever you pick, keep `--reasoning-format deepseek` in
> `scripts\start_llm_server.ps1` if you want the reasoning panel to keep
> working - it depends on the model actually emitting `<think>` content.

### Run it

```powershell
.\start_all.ps1
```

This opens the chat model server and the embedding server in their own
background windows, starts `assistant_core`, and then runs the terminal UI
right there in your current window.

If you'd rather run the pieces by hand (e.g. to watch one of the logs
directly): `scripts\start_llm_server.ps1`, `scripts\start_embedding_server.ps1`,
and `.venv\Scripts\python.exe -m assistant_core.main` in three terminals,
then `.venv\Scripts\python.exe -m cli.tui` in a fourth.

There's also a minimal fallback that skips Textual entirely (no reasoning
panel, no file-write approval - it just refuses mutating file actions):

```powershell
.venv\Scripts\python.exe -m cli.chat
```

### Workspace file access

The model can list/read/write/delete files, but only inside the folder
configured as `workspace.root` in `config.yaml` (defaults to `.\workspace\`
inside the repo). It can't escape that folder - paths outside it, or
containing `..`, are rejected before any file I/O happens. Point
`workspace.root` at wherever you actually want it working (a notes or
projects folder) once you're comfortable with how it behaves.

Reading and listing happen immediately. Every `write_file` or `delete_file`
call pops a modal in the terminal UI showing exactly what it wants to do
(the path, and a preview of the content for writes) and waits for you to
press `y` or `n` before anything happens on disk.

### (Optional) Feed it your own documents for RAG

With the embedding server running:

```powershell
.venv\Scripts\python.exe scripts\ingest_docs.py --path "C:\path\to\your\notes"
```

Currently handles plain text formats (`.txt .md .py .js .ts .json .yaml
.yml .csv`). PDF support isn't wired up yet - convert to text first, or
extend `scripts/ingest_docs.py`.

Note this is separate from workspace file access above: RAG is a searchable
index built from documents you explicitly ingest; the file tools operate
directly on live files in `workspace.root`.

## Configuration

Everything lives in `config.yaml` at the repo root: ports, model paths, RAG
chunking, web search limits, and the workspace root. Paths are resolved
relative to the repo root, so the whole folder can be copied to another
machine without editing anything except the model file paths (which are
machine-specific by nature - you'll download models separately on each
machine, they're not committed to the repo).

## Roadmap

- **Done**: text-based reasoning/coding assistant with local RAG, live web
  research, and workspace file access (read/write/delete with approval),
  via a terminal UI styled after Claude Code.
- **Paused**: wake-word voice front-end (always-listening: openWakeWord for
  wake detection, whisper.cpp for speech-to-text, Piper for speech output) -
  scoped but not built. It would be a new thin client hitting the same
  `assistant_core` service, same as the terminal UI and CLI fallback are
  now, so no changes to the orchestrator/tools/RAG store are expected when
  it resumes.
