
# Llama-Swap-Sync

![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)

A robust, production-ready Python script to automate the synchronization between a directory of `.gguf` model files and a `llama-swap` `config.yaml` file. This tool safely manages your configuration by adding new models and ensuring structural completeness, **while preserving all of your manual customizations.**

## Philosophy: Non-Destructive Operation

This script is designed to be a safe assistant, not a destructive enforcer. Its core principle is to **never overwrite your work.**

-   **For New Models:** When a new `.gguf` file is detected, the script creates a complete, scaffolded entry in your `config.yaml` to get you started quickly.
-   **For Existing Models:** The script's "audit" is non-destructive. It only checks if an entry is missing essential keys from the default template. If so, it adds the missing keys with their default values. **Any changes you have made to existing values—including descriptions, TTLs, or even the `cmd` string—are preserved.**

You can customize your model entries with confidence, knowing this tool will not revert your changes.

## Features

-   **Automatic Model Detection:** Scans a specified directory and adds new `.gguf` models with a complete, default configuration entry.
-   **Stale Entry Pruning:** Optionally removes entries from the config file if the corresponding `.gguf` model file is no longer present (`--prune`).
-   **Non-Destructive Auditing:** Preserves your manual edits. The script audits existing entries only to add missing keys, never overwriting your custom values.
-   **Automated Backups:** Creates a timestamped backup of your `config.yaml` before making changes and automatically manages the number of retained backups.
-   **Docker Integration:** Can automatically restart a specified Docker container (e.g., the `llama-swap` instance) after successful changes.
-   **Production-Grade Safety:**
    -   **Dry Run Mode:** Use `--dry-run` to preview all proposed changes without modifying any files or restarting services.
    -   **Atomic File Writes:** Prevents `config.yaml` corruption by writing changes to a temporary file before atomically replacing the original.
    -   **Concurrency Lock:** A `.lock` file mechanism prevents multiple instances of the script from running simultaneously and causing race conditions.
-   **Flexible Configuration:** Configure via command-line arguments, environment variables, or script defaults.
-   **Structured Logging:** Provides clear, timestamped logs with verbosity controls (`--verbose`, `--quiet`).
-   **Unit Tested:** Core logic is validated with a `pytest` test suite to ensure reliability and prevent regressions.

## Prerequisites

-   Python 3.8 or newer
-   Docker (optional, only if you need to automatically restart a container)

## Installation

1.  **Clone the repository or download the files:**
    ```bash
    git clone [<repository_url>](https://github.com/pkeffect/llama-swap-sync)
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

### Advanced Example

Specify custom paths for the config file and models directory, prune stale entries, and restart a specific container.

```bash
python sync.py \
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

## Running Tests

The project includes a test suite to verify the core logic.

1.  Ensure you have installed the dependencies from `requirements.txt`, which includes `pytest`.
2.  Run the test suite from the project's root directory:
    ```bash
    pytest
    ```

## License

This project is licensed under the MIT License.
