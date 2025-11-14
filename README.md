# VERSION: 0.3.0
# Llama-Swap-Sync

![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)

A robust, production-ready Python script to automate the synchronization between a directory of `.gguf` model files and a `llama-swap` `config.yaml` file. This tool safely manages your configuration by adding new models and ensuring structural completeness, **while preserving all of your manual customizations.**

## Philosophy: Non-Destructive Operation

This script is designed to be a safe assistant, not a destructive enforcer. Its core principle is to **never overwrite your work.**

-   **For New Models:** When a new `.gguf` file is detected, the script creates a complete, scaffolded entry in your `config.yaml` to get you started quickly.
-   **For Existing Models:** The script's "audit" is non-destructive. It only checks if an entry is missing essential keys from the default template. If so, it adds the missing keys with their default values. **Any changes you have made to existing values—including descriptions, TTLs, or even the `cmd` string—are preserved.**

You can customize your model entries with confidence, knowing this tool will not revert your changes.

## Features

-   **Recursive Model Detection:** Automatically scans the models directory and all subdirectories to discover `.gguf` files at any depth level.
-   **Automatic Model Configuration:** Adds new `.gguf` models with a complete, default configuration entry that includes a well-structured `cmd` template.
-   **Stale Entry Pruning:** Optionally removes entries from the config file if the corresponding `.gguf` model file is no longer present (`--prune`).
-   **Non-Destructive Auditing:** Preserves your manual edits. The script audits existing entries only to add missing keys, never overwriting your custom values.
-   **Automated Backups:** Creates timestamped backups of your `config.yaml` before making changes and automatically maintains the most recent backups (default: 3).
-   **Docker Integration:** Can automatically restart a specified Docker container (e.g., the `llama-swap` instance) after successful changes.
-   **Production-Grade Safety:**
    -   **Dry Run Mode:** Use `--dry-run` to preview all proposed changes without modifying any files or restarting services.
    -   **Atomic File Writes:** Prevents `config.yaml` corruption by writing changes to a temporary file before atomically replacing the original.
    -   **Concurrency Lock:** A `.lock` file mechanism prevents multiple instances of the script from running simultaneously and causing race conditions.
    -   **Path Validation:** Validates all file paths to prevent path traversal attacks and ensure only `.gguf` files are processed.
-   **Flexible Configuration:** Configure via command-line arguments, environment variables, or script defaults.
-   **Structured Logging:** Provides clear, timestamped logs with verbosity controls (`--verbose`, `--quiet`).

## Prerequisites

-   Python 3.8 or newer
-   Docker (optional, only if you need to automatically restart a container)

## Installation

1.  **Clone the repository or download the files:**
```bash
    git clone https://github.com/pkeffect/llama-swap-sync
    cd llama-swap-sync
```

2.  **Create and activate a Python virtual environment (recommended):**
```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

3.  **Install the required dependencies:**
```bash
    pip install -r requirements.txt
```

## Usage

The script is run from the command line. By default, it looks for `./models` and `./config.yaml`.

### Basic Commands

-   **Perform a dry run to see what would change:**
```bash
    python llama_swap_sync.py --dry-run
```

-   **Run the sync, adding new models and updating existing entries with any missing keys:**
```bash
    python llama_swap_sync.py
```

-   **Sync and remove stale entries from the config:**
```bash
    python llama_swap_sync.py --prune
```

-   **Run with verbose logging to see detailed operation information:**
```bash
    python llama_swap_sync.py --verbose
```

-   **Run in quiet mode, showing only warnings and errors:**
```bash
    python llama_swap_sync.py --quiet
```

-   **Sync without restarting the Docker container:**
```bash
    python llama_swap_sync.py --no-restart
```

### Advanced Example

Specify custom paths for the config file and models directory, prune stale entries, and restart a specific container.
```bash
python llama_swap_sync.py \
  --config /opt/llama-swap/config.yaml \
  --models-dir /mnt/models \
  --container my-llama-swap-container \
  --prune
```

## Configuration

The script can be configured in three ways, with the following order of precedence:

1.  **Command-Line Arguments** (e.g., `--config`)
2.  **Environment Variables** (e.g., `LLAMA_SWAP_CONFIG`)
3.  **Hard-coded Defaults** in the script

| Feature               | Argument           | Environment Variable      | Default Value      | Description                                     |
| --------------------- | ------------------ | ------------------------- | ------------------ | ----------------------------------------------- |
| Config File Path      | `--config`         | `LLAMA_SWAP_CONFIG`       | `./config.yaml`    | Path to the `llama-swap` configuration file.    |
| Models Directory Path | `--models-dir`     | `LLAMA_SWAP_MODELS_DIR`   | `./models`         | Path to the directory containing `.gguf` files. |
| Docker Container Name | `--container`      | `LLAMA_SWAP_CONTAINER`    | `llama-swap`       | Name of the container to restart on changes.    |

### Command-Line Options

| Option           | Description                                                                                           |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| `--config`       | Path to the config file (default: `./config.yaml`)                                                    |
| `--models-dir`   | Path to the models directory (default: `./models`)                                                    |
| `--container`    | Docker container name to restart (default: `llama-swap`)                                              |
| `--prune`        | Remove entries from config if their `.gguf` file is missing                                           |
| `--no-restart`   | Do not restart the Docker container after changes                                                     |
| `--dry-run`      | Show what changes would be made without modifying files or services                                   |
| `-v, --verbose`  | Enable verbose, debug-level logging                                                                   |
| `-q, --quiet`    | Enable quiet logging, showing only warnings and errors                                                |

## How It Works

### Model Discovery

The script recursively scans the models directory using `os.walk()`, discovering all `.gguf` files regardless of their depth in the directory structure. Subdirectories are preserved in the model key and configuration:

-   Model files in subdirectories are tracked with keys using `--` as a separator (e.g., `subfolder--model-name`)
-   The `cmd` field in the configuration correctly references the subdirectory path (e.g., `/models/subfolder/model-name.gguf`)

### Configuration Structure

Each model entry in `config.yaml` includes:

-   `name`: A human-readable name derived from the file path
-   `description`: Auto-generated description (can be customized)
-   `cmd`: Multi-line command template for llama-server with sensible defaults
-   `aliases`: List of alternative names (empty by default)
-   `env`: Environment variables (empty by default)
-   `ttl`: Time-to-live setting (0 by default)
-   `unlisted`: Visibility flag (false by default)
-   `filters`: Request filtering rules (empty by default)
-   `metadata`: Additional metadata (empty by default)
-   `macros`: Command macros (empty by default)
-   `concurrencyLimit`: Concurrency control (0 by default)
-   `cmdStop`: Stop command (empty by default)

### Backup Management

The script maintains up to 3 timestamped backups by default (configurable via `MAX_BACKUPS` constant). Before creating a new backup, it removes the oldest backup if the limit is reached.

## License

This project is licensed under the MIT License.