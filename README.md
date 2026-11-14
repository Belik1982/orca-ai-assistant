# 🤖 Orca AI Assistant

[![OrcaSlicer](https://img.shields.io/badge/OrcaSlicer-2.5%2B-0f968b?style=flat-square)](https://www.orcaslicer.com/)
[![Version](https://img.shields.io/badge/version-2.2.0-blue?style=flat-square)](https://github.com/Belik1982/orca-ai-assistant/releases)
[![Languages](https://img.shields.io/badge/languages-EN%20%7C%20UA%20%7C%20RU-brightgreen?style=flat-square)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

Interactive, **multilingual (English / Українська / Русский)** AI assistant plugin for **OrcaSlicer 2.5+** with **no hardcoded model lock-in**, real-time **3D geometry & overhang analysis**, **1-click slicer preset updates**, **print defect photo diagnostics**, and **G-code auditing**.

---

## ✨ Key Features

- **🌐 Multilingual UI & AI Responses (`EN` / `UA` / `RU`)**: Switch between **English**, **Ukrainian**, and **Russian** on the fly from the top bar without losing your chat session. Both the UI and the AI's technical answers/setting explanations adapt to the selected language.
- **🔌 Freedom of AI Models & API Keys**:
  - Supports **Anthropic Claude** (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-fable-5-2`, `claude-haiku-5-5`), **OpenAI** (`gpt-5.2`, `gpt-5.1`, `o4-mini`, `o3`), **Google Gemini** (`gemini-3.8-pro`, `gemini-3.8-flash`), **OpenRouter**, **DeepSeek**, **Zhipu GLM** (`glm-4.6`), **Groq**, **Cerebras**, **xAI Grok**, local **Ollama** / **LM Studio**, and **any Custom OpenAI/Anthropic-compatible endpoint**.
  - **Fetch Live Models (`🔄 Fetch via API`)**: Dynamically queries `/models` (or Ollama `/api/tags`).
  - **Custom Model ID & Favorites**: Type any arbitrary model ID and pin your favorite models to the quick-switch bar.
  - **Per-Provider & Per-Model API Keys**: Assign one key per provider or set dedicated API keys for individual models.
- **📐 Deep 3D Geometry & Overhang Inspector (`numpy`)**:
  - Automatically measures dimensions ($X \times Y \times Z$), volume ($\text{cm}^3$), triangle count, manifold status, and mesh errors.
  - Calculates **first-layer bed contact area ($\text{mm}^2$)** and height-to-base stability ratio to warn about warping/detachment risks (Brim recommendations).
  - Calculates **overhang surface areas ($>45^\circ$ and $>60^\circ$)** in real time based on the model's current rotation on the build plate.
- **⚡ 1-Click Apply to OrcaSlicer**:
  - Reads 70+ live parameters from active **Printer**, **Filament**, and **Process** presets.
  - When the AI suggests changes, an interactive **Current → New** comparison table with checkboxes appears directly inside the chat bubble — click **Apply Selected to OrcaSlicer** to commit changes via `orca.host.preset.<category>.begin_update()`.
- **📌 Two Workspace Modes + Diagnostics**:
  - Full **Orca AI Assistant** page tab in OrcaSlicer.
  - Compact **Dock Panel** right next to the 3D build plate (`📌 Dock Panel`).
  - Attach **photos of print defects** for multimodal troubleshooting and **inspect `.gcode` files** (manually or automatically after slicing via the Slicing Pipeline capability).

---

## 📦 Installation

### Option 1: Via OrcaCloud (Recommended)
1. Open **OrcaSlicer 2.5+** → **File → Plugins** → **Browse plugins** (or visit `cloud.orcaslicer.com`).
2. Search for **Orca AI Assistant** and click **Subscribe**, then enable it in OrcaSlicer's Plugins window.

### Option 2: Manual Local Installation
1. Download [`orca_ai_assistant_any.py`](orca_ai_assistant_any.py) from the [Latest Release](https://github.com/Belik1982/orca-ai-assistant/releases).
2. In OrcaSlicer, open **File → Plugins → Install local plugin** and select `orca_ai_assistant_any.py` (or place it into `%APPDATA%\OrcaSlicer\orca_plugins\orca_ai_assistant\` on Windows).
3. Activate the plugin and grant network/threading permissions when prompted.

---

## 🚀 Quick Setup
1. Open the **Orca AI Assistant** tab (or press `📌 Dock Panel`).
2. Select your language in the top-right corner (`🇷🇺 RU` / `🇺🇦 UA` / `🇬🇧 EN`).
3. Choose your **Provider** and **Model**, then click **🔑 Enter API Key** to paste your API key (either for the whole provider or for a specific model).
4. Load a 3D model onto the build plate and click **🔍 Full Model & Settings Audit**!

---

## 🔗 Publishing to OrcaCloud via GitHub
This repository includes the official [`.github/workflows/publish-orcacloud.yml`](.github/workflows/publish-orcacloud.yml) OIDC workflow:
1. On [cloud.orcaslicer.com](https://cloud.orcaslicer.com), go to **Plugins → Shared Plugins → Edit plugin**.
2. Under **GitHub publishing**, connect `Belik1982/orca-ai-assistant`.
3. Create a GitHub Release with a semantic version tag (e.g. `v2.2.0` or `v2.2.1`) — GitHub Actions will automatically publish `orca_ai_assistant_any.py` to OrcaCloud.
