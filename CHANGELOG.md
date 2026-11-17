# Changelog

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
