# Changelog

## [3.0.1] - 2026-11-25
### Fixed
- **Anthropic Adaptive Thinking (`claude-opus-5-5` / 5.x / 4.7+)**: Passed `output_config.effort` (or `thinking: {"type": "disabled"}` for `"none"` mode), ensured automatic `max_tokens` headroom (8192 for `low`, 16384 for `medium`/`high`/`auto`) so hidden reasoning no longer exhausts a 4096-token budget, stripped rejected `output_config`/`thinking` cleanly on HTTP 400, and added automatic recovery retry when Anthropic returns an omitted-thinking-only / `max_tokens` response with empty text.

## [3.0.0] - 2026-11-25
### Added
- **Modular Package Architecture & Deterministic Single-File Bundler**: Refactored the codebase into `src/orca_ai_assistant/` (`core/`, `providers/`, `orca_bridge/`, `controller/`, `assets/`, `ui/`) with `pyproject.toml`, `scripts/build_singlefile.py` (`--check` verified), and `.github/workflows/ci.yml`.
- **Dedicated Compact Dock Panel (`data-view="dock"`)**: Added a sleek 1-row Dock header with always-visible **➕ New Chat**, **☰ Chat History slide-over drawer** (switch/rename/delete/clear), compact model pill + inline model/key drawer, live Pre-Flight score badge, and stacked vertical setting cards for narrow 460×740 viewports.
- **Zero-Token Pre-Flight Scorecard & Before/After Slice Tracker**: Added a deterministic local FDM rule engine (15+ rules, 0–100 score, 1-click fixes & Ask AI) plus automatic `GCodeExportFinished` lifecycle capture streaming `.gcode` / `.gcode.3mf` files for print time, total/per-slot grams, flush/tower waste, verified Before → After deltas, and optional native OrcaSlicer warning notifications.
- **Printer & Filament Custom G-code Access + Safety Diff Gate**: Exposed all 16 OrcaSlicer custom G-code keys (`machine_start_gcode`, `machine_end_gcode`, `layer_change_gcode`, per-slot `filament_start_gcode` / `filament_end_gcode`, etc.) with exact `coString` / `coStrings` C-escaping (preventing `;` comment splitting), an on-demand `📜 Start/End G-code` toggle + auto-detection, read-only Inspector G-code Viewer, and a mandatory **Unified Diff + Static Safety Linter confirmation card** (`G28`, `M104 S0` / `M140 S0`, temperature bounds, empty wipe, unbalanced `[...]`).
- **Multi-Slot AMS / MMU Support**: Reads all loaded filament slots (`Slot 1..N`), displays AMS overview & material/temp clash warnings, preserves `slot` in `orca-settings` cards with `Slot N` badges, and commits directly to the targeted slot.
- **1-Click `↩ Undo`, Apply History & Named Preset Snapshots**: Captures live pre-apply rollback values before every `tx.commit()`, persists apply history (`apply_history.json`) for 1-click Undo, and adds named Preset Snapshots (`snapshots.json`, up to 30) with Save / Restore / Delete.
- **Interactive Wizards (Defect Troubleshooter & Calibration Co-Pilot)**: Added a 12-defect visual wizard with `Ctrl+V` paste / drag-and-drop & `<canvas>` photo downscaling (≤1600 px JPEG), plus a 5-stage Calibration Co-Pilot (Temp Tower, Max Volumetric Speed with 15% safety margin, Pressure Advance, Flow Rate, Retraction) with Calibration Mode Trap guidance.
- **Stop/Cancel Generation, Thinking Preview & Local Slash Commands**: Added thread-safe `CancelToken` with immediate socket close (`⏹ Stop` button), collapsible `🧠 Thinking` streaming preview, and zero-token local commands (`/context`, `/gcode`, `/undo`, `/debug`, `/clear`).
- **Mistral Provider, Usage Meter & Native OrcaSlicer Polish**: Added `mistral` provider preset, monthly/total token usage tracking (`usage.json`), OrcaSlicer light/dark live theme sync (`data-orca-theme`), `app_info()["language"]` auto-detection, and native `get_config_ui()` toggles.

### Fixed
- **Enum Validation & All-or-Nothing Rollback**: Verified all 24 OrcaSlicer 2.5.2 enum lists (`cross_hatch` → `crosshatch`, `support_type` → `normal(auto)`/`tree(auto)`, `z_hop_types` → `Auto Lift`, etc.), fixed `slow_down_for_layer_cooling` category from `process` to `filament`, and added pre-commit validation + per-key fallback commit so one invalid key never rolls back valid settings.
- **Concurrent Stream / Cross-Chat Corruption**: Scoped streaming by `request_id` and captured `target_chat_id`, preserved `active_request_id` in `chats_updated` so the Stop/busy lock stays intact, and wrote replies via `append_message(target_chat_id, ...)` instead of `append_message_to_active`.
- **UI Thread Freeze on Unrelated Clicks**: Removed synchronous NumPy mesh scanning from fast UI actions (`save_settings`, `select_chat`, `new_chat`, `delete_chat`, `rename_chat`, `fetch_models`, `stop_generation`, `save_snapshot`).
- **Tab + Dock Sync & Dead View Cleanup**: `init`/`ready` sends `full_state` only to the requesting view (never wiping an active stream in the other view), broadcasts settings/chat updates to all open views, and prunes closed views cleanly.
- **Stable Capability Names & Atomic Storage**: Kept capability `get_name()` stable across UI languages (fixing `.install_state.json` persistence), implemented atomic `.tmp` + `fsync` + `os.replace` writes with v1/v2/v3 → v4 `.bak` migration, retired-model migration inside `favorite_models`, and `temperature = 0` preservation.
- **3D Geometry, Markdown, Anthropic & Per-Model Key Fixes**: Fixed mirrored mesh normal inversion (`det(rot) < 0`), global object `z_min` bed contact, union bounding box, and scaled volume; replaced Markdown parser with a code-fence-first GFM renderer (tables, nested/ordered lists, streaming-safe `orca-settings` hiding, Copy buttons); fixed Anthropic role-alternation HTTP 400 and multi-pass 400/429/503 retries; stopped `fetch_models` from leaking per-model keys into `api_keys[provider]`; stopped `get_icon()` from rewriting SVG on every call; switched `OrcaAIGcodeAuditor` to streaming disk reads.

## [2.3.1] - 2026-11-17
### Fixed
- Fixed Anthropic SSE streaming (`Accept: text/event-stream`, `content_block_start`/`content_block_delta` parsing, and in-stream `error` event handling).
- Added automatic fallback to a non-streaming POST (`stream: false`) if any provider returns an empty SSE stream.

## [2.3.0] - 2026-11-17
### Added
- **Real-time SSE Streaming (`stream: true`)**: AI replies now stream token-by-token into the chat bubble (supports OpenAI-compatible APIs including Gemini, OpenRouter, DeepSeek, Groq, Ollama, and Anthropic SSE), with automatic fallback to standard JSON if a proxy does not support SSE.
- **Fast Gemini / Thinking Speed Selector (`reasoning_effort`)**: Added a quick speed/thinking selector (`Instant / none`, `Fast / low`, `Balanced / medium`, `Deep / high`, `Auto`) right below the chat input. Defaulting to `low` drastically cuts Gemini 2.5/3.x response latency by limiting hidden thinking tokens, with automatic HTTP 400 fallback for models that do not use `reasoning_effort`.

## [2.2.3] - 2026-11-16
### Fixed
- Fixed GitHub Actions OrcaCloud publish workflow (`curl --form-string` for `metadata` JSON so semicolons/special chars in release notes do not break multipart encoding).

## [2.2.2] - 2026-11-16
### Added
- Localized OrcaSlicer top tab name, Dock Panel script name, and G-code Audit capability name (`Orca AI Assistant`, `Orca AI: Dock Panel`, `Orca AI: G-code Audit` in English; localized equivalents in Ukrainian and Russian).
- Automatic default language detection from OS locale (`en` by default for international users, `uk` / `ru` for matching locales).
- Unified international PEP 723 plugin name (`Orca AI Assistant`).

## [2.2.1] - 2026-11-16
### Fixed
- Fixed applying filament settings in OrcaSlicer (`orca.host.preset.filament.begin_update(slot_number)` requires a 1-based slot index, whereas `process` and `printer` take no arguments).
- Added automatic category resolution via `FLAT_SETTING_INFO` and category aliases so filament keys (e.g. `nozzle_temperature`, `hot_plate_temp`, `filament_flow_ratio`, `fan_max_speed`) are always routed to the `filament` preset editor even if an AI omits or mislabels `category`.
- Fixed transaction reporting so `applied` items are recorded only after `tx.commit()` succeeds.

## [2.2.0] - 2026-11-14
### Added
- Full multilingual support (**English**, **Ukrainian**, **Russian**) with an instant top-bar language switcher (`🇷🇺 RU` / `🇺🇦 UA` / `🇬🇧 EN`).
- Localized UI labels, 3D Inspector warnings, 70+ OrcaSlicer preset labels, quick action prompts, G-code audit prompts, and AI system instructions.
- OrcaCloud publishing readiness (`orca_ai_assistant_any.py` + GitHub Actions OIDC workflow).

## [2.1.0] - 2026-11-14
### Added
- Unified top control bar with inline API key drawer (`🔑 Enter API Key`) supporting both **provider-wide keys** and **per-model API keys**.
- Updated model lists for late 2026 (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-fable-5-2`, `claude-haiku-5-5`, `gpt-5.2`, `gemini-3.8-pro`, `gemini-3.8-flash`, `glm-4.6`, etc.).
- Automatic `HTTP 400` fallback retry when a model rejects `temperature` or requires `max_completion_tokens`.
### Fixed
- Replaced `<input list="datalist">` with a native `<select>` dropdown + separate custom model ID input so WebView2 always displays all models.

## [2.0.0] - 2026-11-13
### Added
- Initial release of Orca AI Assistant for OrcaSlicer 2.5+.
- 3D plate geometry & overhang analyzer (`numpy`), preset inspector, 1-click `orca-settings` application, dock panel, photo defect diagnostics, and G-code audit pipeline.
