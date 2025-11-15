# VERSION: 0.5.0
# Llama-Swap-Sync

![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

A robust, production-ready Python toolkit to automate the synchronization between a directory of `.gguf` model files and a `llama-swap` `config.yaml` file. This project provides utilities for downloading models from Hugging Face, verifying their integrity, and automatically maintaining your llama-swap configuration.

## Philosophy: Non-Destructive Operation

This toolkit is designed to be a safe assistant, not a destructive enforcer. Its core principle is to **never overwrite your work.**

-   **For New Models:** When a new `.gguf` file is detected, the sync script creates a complete, scaffolded entry in your `config.yaml` to get you started quickly.
-   **For Existing Models:** The script's "audit" is non-destructive. It only checks if an entry is missing essential keys from the default template. If so, it adds the missing keys with their default values. **Any changes you have made to existing values—including descriptions, TTLs, or even the `cmd` string—are preserved.**

You can customize your model entries with confidence, knowing this tool will not revert your changes.

## Project Structure
```
llama-swap-sync/
├── llama_swap_sync.py    # Main sync script - manages config.yaml
├── download_model.py      # Download models from Hugging Face
├── update_models.py       # Check for and apply model updates
├── hf_utils.py           # Shared utility functions
├── requirements.txt      # Python dependencies
├── compose.yml           # Docker Compose configuration
├── .env                  # Environment variables (example)
├── config.yaml           # Generated llama-swap config
├── example_config.yaml   # Example configuration
└── README.md            # This file
```

## Features

### llama_swap_sync.py - Configuration Management

-   **Recursive Model Detection:** Automatically scans the models directory and all subdirectories to discover `.gguf` files at any depth level
-   **Smart Key Generation:** Creates safe, shortened YAML keys for long model names with collision detection to prevent formatting issues
-   **Stale Entry Pruning:** Optionally removes entries from the config file if the corresponding `.gguf` model file is no longer present (`--prune`)
-   **Non-Destructive Auditing:** Preserves your manual edits while ensuring all entries have required fields
-   **Automated Backups:** Creates timestamped backups of your `config.yaml` before making changes and automatically maintains the most recent backups (configurable via `LLAMA_SWAP_MAX_BACKUPS`, default: 3)
-   **Docker Integration:** Automatically restarts your Docker container after configuration changes using the Docker CLI
-   **Production-Grade Safety:**
    -   **Dry Run Mode:** Use `--dry-run` to preview all proposed changes without modifying any files or restarting services
    -   **Atomic File Writes:** Prevents `config.yaml` corruption by writing changes to a temporary file before atomically replacing the original
    -   **Concurrency Lock:** A `.lock` file mechanism prevents multiple instances from running simultaneously
    -   **Path Validation:** Validates all file paths to prevent path traversal attacks
-   **Flexible Configuration:** Configure via command-line arguments, environment variables, or script defaults
-   **Structured Logging:** Provides clear, timestamped logs with verbosity controls (`--verbose`, `--quiet`)
-   **Cross-Platform Support:** Works on Windows, Linux, and macOS with appropriate symbol rendering

### download_model.py - Model Download Utility

-   **Direct Hugging Face Integration:** Download `.gguf` models directly from Hugging Face repositories
-   **Automatic Directory Structure:** Preserves the repository structure in your local models directory
-   **SHA256 Verification:** Automatically verifies downloaded files against Hugging Face LFS hashes
-   **Hash File Generation:** Creates `.sha256` files compatible with `sha256sum` for later verification
-   **Retry Logic:** Automatically retries failed downloads with exponential backoff
-   **Resume Support:** Downloads automatically resume if interrupted
-   **Exit Code Standards:** Uses distinct exit codes for different error types for better automation

### update_models.py - Update Checker

-   **Managed Model Detection:** Scans for models with `.sha256` files to check for updates
-   **Interactive Selection:** User-friendly menu for selecting which models to update
-   **Batch Processing:** Update multiple models or all at once
-   **Update Statistics:** Tracks and reports successful and failed updates
-   **Cross-Platform:** Proper symbol rendering on all operating systems

### hf_utils.py - Shared Utilities

-   URL parsing for Hugging Face links
-   SHA256 calculation with optional progress bars
-   Hash validation with hexadecimal verification
-   Local and remote hash file management
-   Recursive `.gguf` file discovery
-   Path validation and security checks
-   Download progress and error handling

## Prerequisites

-   **Python:** 3.11 or newer
-   **Docker:** Optional, only if you need automatic container restart
-   **Hugging Face Account:** Required for downloading models (some models may require acceptance of license terms)
-   **Disk Space:** At least 10GB free (models are typically 2-15GB each)
-   **GPU:** Optional, for running llama-swap, but not required for this toolkit

## Installation

1.  **Clone or download the repository:**
```bash
git clone https://github.com/pkeffect/llama-swap-sync
cd llama-swap-sync
```

2.  **Create and activate a Python virtual environment (recommended):**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3.  **Install the required dependencies:**
```bash
pip install -r requirements.txt
```

4.  **Configure environment variables (optional):**
```bash
cp .env.example .env
# Edit .env with your preferred settings
```

## Usage

### Downloading Models

Use `download_model.py` to download models from Hugging Face with automatic verification:
```bash
# Download a model
python download_model.py "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/blob/main/mistral-7b-instruct-v0.2.Q8_0.gguf"

# Download to a custom directory
python download_model.py \
  --dest-dir /mnt/models \
  "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/blob/main/Llama-3.2-3B-Instruct-f16.gguf"

# Skip hash verification (not recommended)
python download_model.py --skip-verification "https://..."

# Customize retry behavior
python download_model.py --retries 3 --retry-delay 5 "https://..."
```

**How it works:**
1. Parses the Hugging Face URL to extract repository and filename
2. Creates the destination directory structure (e.g., `./models/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/`)
3. Fetches the SHA256 hash from Hugging Face metadata
4. Downloads the model file (with automatic resume support)
5. Verifies the downloaded file against the hash with progress bar
6. Creates a `.sha256` file for future verification

### Checking for Updates

Use `update_models.py` to check for and apply updates to your models:
```bash
# Check for updates and interactively select which to apply
python update_models.py
```

The script will:
1. Scan for all models with `.sha256` files
2. Check each model against Hugging Face for updates
3. Present an interactive menu for selection
4. Download and verify selected updates
5. Report success/failure statistics

### Managing Configuration

The sync script runs from the command line and by default looks for `./models` and `./config.yaml`.

#### Basic Commands

-   **Perform a dry run to see what would change:**
```bash
python llama_swap_sync.py --dry-run
```

-   **Run the sync, adding new models and updating existing entries:**
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

#### Advanced Example

Specify custom paths for the config file and models directory, prune stale entries, and restart a specific container:
```bash
python llama_swap_sync.py \
  --config /opt/llama-swap/config.yaml \
  --models-dir /mnt/models \
  --container my-llama-swap-container \
  --prune \
  --verbose
```

## Configuration

### Environment Variables

Set these in your `.env` file or shell environment for convenience:

| Variable | Description | Default |
|----------|-------------|---------|
| `LLAMA_SWAP_CONFIG` | Path to config file | `./config.yaml` |
| `LLAMA_SWAP_MODELS_DIR` | Path to models directory | `./models` |
| `LLAMA_SWAP_CONTAINER` | Docker container name | `llama-swap` |
| `LLAMA_SWAP_MAX_BACKUPS` | Number of backups to keep | `3` |
| `LLAMA_SWAP_MAX_KEY_LENGTH` | Maximum YAML key length before shortening | `80` |
| `MODELS_PATH` | Models volume for Docker | `./models` |
| `CONFIG_PATH` | Config volume for Docker | `./config.yaml` |
| `LLAMA_SWAP_PORT` | Web interface port | `8080` |
| `NVIDIA_VISIBLE_DEVICES` | GPU visibility | `all` |
| `GPU_COUNT` | Number of GPUs to use | `1` |

**Linux/Mac:**
```bash
export LLAMA_SWAP_CONFIG="/opt/llama-swap/config.yaml"
export LLAMA_SWAP_MODELS_DIR="/mnt/nvme/models"
export LLAMA_SWAP_CONTAINER="my-llama-container"
```

**Windows (PowerShell):**
```powershell
$env:LLAMA_SWAP_CONFIG="C:\llama-swap\config.yaml"
$env:LLAMA_SWAP_MODELS_DIR="D:\models"
$env:LLAMA_SWAP_CONTAINER="my-llama-container"
```

### Command-Line Options

#### llama_swap_sync.py

| Option | Description |
|--------|-------------|
| `--config` | Path to the config file (default: `./config.yaml`) |
| `--models-dir` | Path to the models directory (default: `./models`) |
| `--container` | Docker container name to restart (default: `llama-swap`) |
| `--prune` | Remove entries from config if their `.gguf` file is missing |
| `--no-restart` | Do not restart the Docker container after changes |
| `--dry-run` | Show what changes would be made without modifying files or services |
| `-v, --verbose` | Enable verbose, debug-level logging |
| `-q, --quiet` | Enable quiet logging, showing only warnings and errors |

#### download_model.py

| Option | Description | Default |
|--------|-------------|---------|
| `url` | Full Hugging Face URL to the model file (required) | - |
| `--dest-dir` | Root destination directory for models | `./models` |
| `--retries` | Number of times to retry failed downloads | 5 |
| `--retry-delay` | Initial delay in seconds between retries (doubles each time) | 10 |
| `--skip-verification` | Skip SHA256 verification after download | False |

## How It Works

### Model Discovery and Key Generation

The sync script recursively scans the models directory using `os.walk()`, discovering all `.gguf` files regardless of their depth in the directory structure. For each model:

1. **Path Normalization:** Converts Windows paths to POSIX-style paths for consistency
2. **Key Generation:** Creates a unique key by replacing `/` with `--` (e.g., `TheBloke/model.gguf` → `TheBloke--model`)
3. **Smart Shortening:** For keys longer than 80 characters, the script intelligently shortens them using SHA256 hash suffixes
4. **Collision Detection:** Checks for and prevents any key collisions that would cause data loss

### Configuration Structure

Each model entry in `config.yaml` includes all required llama-swap fields:
```yaml
bartowski--Mistral-7B-Instruct-v0.2-GGUF--mistral-7b-instruct-v0.2.Q8_0:
  name: bartowski / Mistral 7B Instruct v0.2 GGUF / mistral 7b instruct v0.2.Q8 0
  description: Auto-generated entry for bartowski/Mistral-7B-Instruct-v0.2-GGUF/mistral-7b-instruct-v0.2.Q8_0.gguf
  cmd: |
    /app/llama-server
      -m /models/bartowski/Mistral-7B-Instruct-v0.2-GGUF/mistral-7b-instruct-v0.2.Q8_0.gguf
      -ngl 99
      -c 4096
      -b 2048
      -ub 512
      --temp 0.7
      --top-p 0.95
      --top-k 40
      --repeat-penalty 1.1
      --port ${PORT}
      --host 0.0.0.0
  aliases: []
  env: []
  ttl: 0
  unlisted: false
  filters: {}
  metadata: {}
  macros: {}
  concurrencyLimit: 0
  cmdStop: ''
```

### Backup Management

The script maintains up to 3 timestamped backups by default (configurable via `LLAMA_SWAP_MAX_BACKUPS`). Before creating a new backup, it removes the oldest backup if the limit is reached.

Backups are named: `config.yaml.bak.YYYYMMDD_HHMMSS`

**Restoring from Backup:**
```bash
# List available backups
ls -lh config.yaml.bak.*

# Restore a specific backup
cp config.yaml.bak.20250115_143022 config.yaml
```

### Docker Container Restart

The script uses the Docker CLI directly via subprocess to restart containers, bypassing Python library compatibility issues. This approach:

- Works reliably on Windows, Linux, and macOS
- Handles Docker Desktop configurations correctly
- Provides clear error messages if Docker is not running
- Times out after 60 seconds to prevent hanging
- Includes health check in compose.yml to verify container readiness

## Security Features

### Path Validation
- All file paths are validated to prevent path traversal attacks
- Relative paths only - absolute paths are rejected
- No `..` sequences allowed in paths

### Hash Verification
- SHA256 verification prevents file corruption and MITM attacks
- Hexadecimal validation ensures hash integrity
- Optional progress bars for large files

### YAML Safety
- Uses `yaml.safe_load()` and `yaml.SafeDumper` exclusively
- Prevents YAML injection attacks
- No code execution through YAML parsing

### Concurrency Protection
- Lock file mechanism prevents simultaneous execution
- Atomic file writes prevent corruption
- Proper cleanup in error conditions

## Typical Workflow

1. **Download a model from Hugging Face:**
```bash
python download_model.py "https://huggingface.co/bartowski/..."
```

2. **Sync your configuration:**
```bash
python llama_swap_sync.py
```

3. **Your llama-swap container automatically restarts with the new model available!**

4. **Periodically check for updates:**
```bash
python update_models.py
```

## Troubleshooting

### Docker Connection Issues

If you see errors about connecting to Docker:

1. Ensure Docker Desktop is running: `docker ps`
2. The script uses the Docker CLI directly, so if `docker ps` works, the script should work
3. Check that your container name matches (default: `llama-swap`)
4. Verify Docker is in your PATH

### YAML Formatting Issues

If llama-swap reports config errors:

1. Check for keys with `? ` and `:` on separate lines - these indicate formatting issues
2. Run the sync script again - it automatically detects and fixes these issues
3. Use `--prune` to remove old malformed entries

### Model Not Appearing

1. Verify the `.gguf` file exists in the models directory
2. Check file permissions
3. Run with `--verbose` to see detailed scanning output
4. Ensure the file path doesn't contain `..` or other invalid characters

### Hash Verification Failures

1. The download may have been interrupted - try downloading again
2. The file may be corrupted - delete and re-download
3. If persistent, use `--skip-verification` (not recommended) and report the issue

### Symbol Rendering Issues (Windows)

On some Windows terminals, you may see garbled characters instead of checkmarks. This is normal and doesn't affect functionality. The script automatically uses ASCII alternatives on Windows when possible.

## Common Use Cases

### Setting Up a New Model Library
```bash
# Create models directory
mkdir -p models

# Download several models
python download_model.py "https://huggingface.co/..."
python download_model.py "https://huggingface.co/..."

# Generate initial config
python llama_swap_sync.py

# Start llama-swap with docker-compose
docker-compose up -d
```

### Regular Maintenance
```bash
# Add this to a cron job or scheduled task
python llama_swap_sync.py --quiet --prune
python update_models.py
```

### Migrating to a New Server
```bash
# On old server: backup models and config
tar -czf models-backup.tar.gz models/
cp config.yaml config.yaml.backup

# On new server: restore and sync
tar -xzf models-backup.tar.gz
python llama_swap_sync.py --dry-run  # Preview changes
python llama_swap_sync.py            # Apply changes
```

### Validating Configuration
```bash
# Preview changes without applying
python llama_swap_sync.py --dry-run --verbose

# Check for stale entries
python llama_swap_sync.py --dry-run --prune
```

## Exit Codes

Understanding exit codes helps with automation and scripting:

### download_model.py
- `0` - Success
- `1` - Invalid URL format
- `2` - Download failed
- `3` - Verification failed

### llama_swap_sync.py
- `0` - Success (changes made or no changes needed)
- `1` - Critical error (lock file exists, YAML corrupt, etc.)

### update_models.py
- `0` - Success
- `1` - Error during update process

## Dependencies

Core dependencies (see `requirements.txt` for versions):

- **PyYAML** (~=6.0.1): YAML parsing and generation
- **huggingface-hub** (~=6.1.4): Downloading models from Hugging Face
- **tqdm** (~=4.67.1): Progress bars for long operations

Note: The `docker` Python library is no longer required - the script uses the Docker CLI directly.

## Version History

### v0.5.0 (Current)
- Removed unused dependencies (docker, blake3)
- Added SHA256 validation for hash files
- Added progress bars for hash calculation
- Improved cross-platform symbol support
- Added key collision detection
- Made MAX_BACKUPS and MAX_KEY_LENGTH configurable
- Improved Docker error messages
- Added exit code constants
- Added health check to docker-compose
- Added resource limits to docker-compose
- Enhanced module-level documentation
- Lock file now exits with error code on conflict
- Updated example_config.yaml to match actual structure

### v0.4.0
- Initial public release
- Core sync functionality
- Download utility
- Update checker
- Comprehensive documentation

## Contributing

Contributions are welcome! Please ensure:

1. Code follows the existing style and conventions
2. All functions have docstrings
3. Version numbers are updated in file headers
4. README is updated for new features
5. Security considerations are maintained

## License

This project is licensed under the MIT License.

## Acknowledgments

- Built for use with [llama-swap](https://github.com/mostlygeek/llama-swap) by mostlygeek
- Designed for managing GGUF models from Hugging Face repositories
- Thanks to the Python and open-source community
- Thanks to the llama.cpp team 

## Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review this README thoroughly before reporting issues

---

**Note:** This toolkit manages configuration files and Docker containers. Always review changes with `--dry-run` before applying them in production environments.
