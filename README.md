# 🤖 Orca AI Assistant

[![OrcaSlicer](https://img.shields.io/badge/OrcaSlicer-2.5%2B-0f968b?style=flat-square)](https://www.orcaslicer.com/)
[![Version](https://img.shields.io/badge/version-3.0.0-blue?style=flat-square)](https://github.com/Belik1982/orca-ai-assistant/releases)
[![Languages](https://img.shields.io/badge/languages-EN%20%7C%20UA%20%7C%20RU-brightgreen?style=flat-square)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

Interactive, **multilingual (English / Українська / Русский)** AI co-pilot plugin for **OrcaSlicer 2.5+** combining real-time **`numpy` 3D geometry & overhang analysis**, a zero-token **Pre-Flight Scorecard**, **multi-slot AMS awareness**, **Custom G-code diff & safety linting**, **1-click reversible preset apply with Undo & Snapshots**, **Defect & Calibration Wizards**, and **13+ BYOK & local AI providers** with zero vendor lock-in.

---

## ✨ Key Features in v3.0.0

- **🌐 Complete Multilingual UI & AI Responses (`EN` / `UA` / `RU`)**: Switch between **English**, **Ukrainian**, and **Russian** on the fly. Automatically detects OrcaSlicer's UI language (`orca.host.app_info()["language"]`) on first run and dynamically syncs with OrcaSlicer's light/dark theme (`data-orca-theme`).
- **📌 Dedicated Compact Dock Panel (`data-view="dock"`) & Full Page Tab**:
  - Compact 1-row Dock header with always-accessible **➕ New Chat**, **☰ Chat History slide-over drawer** (switch, rename, delete, clear), compact model pill + inline key drawer, and live Pre-Flight score badge — designed for 460×740 side-by-side slicing next to the 3D build plate.
  - Full-width Tab and Dock Panel stay synced in real time without wiping active streams.
- **🛡 Zero-Token Deterministic Pre-Flight Scorecard & Post-Slice Tracker**:
  - Runs 15+ local FDM checks (<50 ms, 0 LLM tokens) covering non-manifold geometry, small first-layer bed contact, tall/narrow stability, `grid` infill nozzle-knock risk, critical overhangs (>45° / >60°), multi-slot AMS material/temp clashes, bed/nozzle thermal envelopes, estimated peak volumetric flow vs. MVS, Classic thin walls, layer height vs. nozzle ratio, high flush/prime-tower waste, and Start/End G-code safety.
  - Hooks into OrcaSlicer `GCodeExportFinished` to automatically stream-parse `.gcode` / `.gcode.3mf` metrics (print time, total & per-slot grams, purge/tower waste), compute verified **Before → After slice deltas**, and show optional native OrcaSlicer warning banners.
- **📜 Printer & Filament Custom G-code Access + Safety Diff Gate**:
  - Inspects and safely edits all 16 OrcaSlicer custom G-code blocks (`machine_start_gcode`, `machine_end_gcode`, `before_layer_change_gcode`, `layer_change_gcode`, `change_filament_gcode`, per-slot `filament_start_gcode` / `filament_end_gcode`, etc.) with exact `coString` / `coStrings` C-escaping (preventing `;` comment splitting).
  - Never silently overwrites G-code: renders a dedicated **Unified Diff + Static Safety Linter Card** (checks empty wipe, `G28` homing before motion, `M104 S0` / `M140 S0` cooldown, extreme temperatures, and unbalanced `[...]` placeholders) requiring explicit user confirmation.
- **⚡ Validated 1-Click Apply, Multi-Slot AMS Targeting, `↩ Undo` & Preset Snapshots**:
  - Reads 90+ live parameters across **Process**, **Printer**, and **all loaded AMS/MMU Filament Slots (`Slot 1..N`)**.
  - Normalizes and validates OrcaSlicer 2.5.2 internal enums (`cross_hatch` → `crosshatch`, `normal(auto)` / `tree(auto)`, `Auto Lift`, booleans, percentages) before committing, with automatic per-key fallback if a batch commit fails.
  - Snapshots pre-apply values automatically for persistent **1-click `↩ Undo`** (across restarts) and lets you save/restore named **Preset Snapshots**.
- **📐 Accurate 3D Geometry & Overhang Inspector (`numpy`)**:
  - Measures true union dimensions (`X × Y × Z`), scaled volume (`cm³`), triangle count, manifold status, per-part AMS `extruder_ids`, and object/modifier overrides.
  - Computes **first-layer bed contact area (`mm²`)** against the global object Z-min, height-to-base ratio, and **overhang areas (>45° and >60°)** with proper mirroring (`det(rot) < 0`) normal correction.
- **🔧 Interactive Wizards (Defect Troubleshooter & Calibration Co-Pilot)**:
  - **Defect Wizard**: 12 common FDM defects + `Ctrl+V` clipboard photo paste / drag-and-drop with client-side `<canvas>` resizing (≤1600 px JPEG) + automatic cross-reference against live presets and last slice.
  - **Calibration Co-Pilot**: 5-stage workflow (**Temp Tower → Max Volumetric Speed → Pressure Advance → Flow Rate → Retraction**) with OrcaSlicer formulas, 15% MVS safety margin, Calibration Mode Trap reminder, target AMS Slot selector, and 1-click apply.
- **💬 Streaming, Thinking Preview, Stop/Cancel & Local Slash Commands**:
  - Token-by-token SSE streaming with collapsible `🧠 Thinking` preview, **`⏹ Stop`** abort button (immediate socket close via `CancelToken`), and request/chat-scoped streaming so switching chats mid-stream never corrupts history.
  - Zero-token local slash commands: `/context`, `/gcode`, `/undo`, `/debug`, `/clear`.
- **🔌 13+ AI Providers & Local Models (Zero Lock-In)**:
  - **Anthropic Claude**, **OpenAI**, **Google Gemini**, **OpenRouter**, **DeepSeek**, **Mistral**, **Zhipu GLM**, **Groq**, **Cerebras**, **xAI Grok**, local **Ollama** / **LM Studio**, and **Custom OpenAI/Anthropic-compatible endpoints**, with live model fetching, per-provider & per-model API keys, favorites, and a monthly/total token usage meter.

---

## 📦 Installation

### Option 1: Via OrcaCloud (Recommended)
1. Open **OrcaSlicer 2.5+** → **File → Plugins → Browse plugins** (or visit `cloud.orcaslicer.com`).
2. Search for **Orca AI Assistant**, click **Subscribe**, and enable it in OrcaSlicer's Plugins window.

### Option 2: Manual Local Installation
1. Download [`orca_ai_assistant_any.py`](orca_ai_assistant_any.py) from the [Latest Release](https://github.com/Belik1982/orca-ai-assistant/releases).
2. In OrcaSlicer, open **File → Plugins → Install local plugin** and select `orca_ai_assistant_any.py`.
3. Activate the plugin and grant network/threading permissions when prompted.

---

## 🚀 Quick Setup
1. Open the **Orca AI Assistant** tab or open the **Orca AI: Dock Panel** right next to the 3D build plate.
2. Select your preferred language (`🇷🇺 RU` / `🇺🇦 UA` / `🇬🇧 EN`).
3. Pick your **Provider** and **Model**, then enter your API key (provider-wide or per-model).
4. Load a 3D model onto the build plate, review the instant **🛡 Pre-Flight** scorecard, or run **🔍 Full Model & Settings Audit** in **💬 Chat**!

---

## 🏗 Project Architecture & Development

The plugin is developed as a clean modular Python 3.12 package (zero third-party runtime dependencies; optional `numpy` from OrcaSlicer) and bundled deterministically into the single-file `orca_ai_assistant_any.py` artifact for OrcaSlicer / OrcaCloud distribution:

```text
orca-ai-assistant/
├── pyproject.toml
├── scripts/
│   └── build_singlefile.py           # Deterministic bundler -> orca_ai_assistant_any.py
├── orca_ai_assistant_any.py          # Generated self-contained OrcaSlicer plugin
├── src/orca_ai_assistant/
│   ├── __init__.py                   # @orca.plugin entry point & stable capabilities
│   ├── core/                         # Constants, atomic storage, schema v1-v3->v4 migration
│   ├── providers/                    # 13+ provider registry, abortable SSE/HTTP client
│   ├── orca_bridge/                  # Verified 2.5.2 enums, G-code codec, presets, numpy geometry,
│   │                                 # Pre-Flight engine, streaming G-code analyzer, prompts
│   ├── controller/                   # Multi-view controller, slash commands, resilient parser
│   ├── assets/                       # Static icon.svg + locales/{ru,uk,en}.json
│   └── ui/                           # template.html, styles.css, markdown.js, app.js
├── tests/                            # Automated unit & integration test suite
└── .github/workflows/
    ├── ci.yml                        # Tests, JS syntax check, bundle freshness & smoke-import
    └── publish-orcacloud.yml         # Verified bundle check + OIDC OrcaCloud release upload
```

### Build & Test Commands

```bash
# Rebuild the single-file plugin bundle from src/orca_ai_assistant/
python scripts/build_singlefile.py

# Verify the generated bundle matches src/ byte-for-byte
python scripts/build_singlefile.py --check
python -m py_compile orca_ai_assistant_any.py

# Run the automated test suite (pytest or stdlib unittest)
pytest
python -m unittest discover -s tests -v

# Syntax-check frontend JavaScript
node --check src/orca_ai_assistant/ui/markdown.js
node --check src/orca_ai_assistant/ui/app.js
```

---

## 🔗 Publishing to OrcaCloud via GitHub
This repository includes [`.github/workflows/publish-orcacloud.yml`](.github/workflows/publish-orcacloud.yml):
1. On [cloud.orcaslicer.com](https://cloud.orcaslicer.com), go to **Plugins → Shared Plugins → Edit plugin**.
2. Under **GitHub publishing**, connect `Belik1982/orca-ai-assistant`.
3. Create a GitHub Release with a semantic version tag (e.g. `v3.0.0`) — GitHub Actions verifies `scripts/build_singlefile.py --check` and automatically publishes `orca_ai_assistant_any.py` to OrcaCloud via OIDC.
