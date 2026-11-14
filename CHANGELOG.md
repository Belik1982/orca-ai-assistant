# Changelog

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
