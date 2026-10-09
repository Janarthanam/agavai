# Install the small Omarchy bundle

Models are downloaded on the receiving computer rather than shipped in the archive.
Extract `agavai-0.1.0-omarchy-light.tar.gz` into a permanent folder, then enter
`agavai-0.1.0-light`. Keep that folder: installed launchers link to its scripts.

Install prerequisites on the receiving Omarchy computer:

```bash
omarchy pkg add python curl uv espeak-ng libsndfile libpulse
```

Install a compatible Linux `llama-server` (or an LM Studio llama.cpp backend).
Keep its shared libraries beside it. It must support `--jinja` and tool calls.
Setup creates a config if needed and opens `~/.config/agavai/config.toml` in
`$VISUAL`, `$EDITOR`, or nano. Set `llama_bin = "/absolute/path/to/llama-server"`
under `[llm]`, and review the model, CPU/GPU, voice and search-folder settings.
Save and close the editor to continue. Existing settings are preserved for review.

Run the interactive setup as your desktop user:

```bash
bash scripts/setup.sh
```

Or choose directly:

| Command | Downloads |
| --- | --- |
| `bash scripts/setup.sh --models all` | Qwen (~2.5 GB), Parakeet (~481 MB), Kokoro (~192 MB), speech runtime |
| `bash scripts/setup.sh --models llm` | Active configured LLM; default Qwen; use typed requests |
| `bash scripts/setup.sh --models voice` | Parakeet, Kokoro and speech runtime; requires an existing LLM |
| `bash scripts/setup.sh --models none` | App only; reuse existing models and runtime |

Internet is required for downloads and Python dependencies. Existing valid model
files are reused; partial downloads resume. The LLM choice downloads the active
configured model, which may differ in size from Qwen. Selecting none does not make
a fresh installation functional without models. LLM-only can speak using eSpeak;
microphone recognition requires the voice models and runtime.

Setup validates the saved configuration, downloads the selected models, and checks
that the LLM binary and model exist. Only then does the installer register the app
and shell plugin, install and enable the model service, and restart it. Failed or
cancelled configuration stops before installation. Restart failures are reported.
Direct `scripts/install.sh` calls also require configuration and a ready LLM.

For unattended setup, explicitly accept a configuration you have already saved:
`bash scripts/setup.sh --models all --configured`. Validation still runs; this
does not bypass configuration or model checks. Configuration happens before
downloads so custom model choices and paths are used. The installer migrates legacy `oma-voice` names.
The defaults use CPU. The archive excludes personal settings, keys, environments
and llama-server binaries. No OpenRouter key is needed for keyword routing.

```bash
agavai status
agavai ask "what time is it"
agavai invoke
```

Launch Agavai from the app launcher or bar. For a shortcut, add
`bind = SUPER, M, exec, agavai invoke` to the receiving desktop's Hyprland bindings.
The receiving computer's live desktop and microphone still require verification.
