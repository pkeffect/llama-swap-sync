# VERSION: 0.1.1
import argparse
import datetime
import glob
import logging
import os
import shutil
import sys
from typing import Dict, Any, Optional, Set, Tuple

import docker
import yaml

# --- CONFIGURATION (Defaults) ---
# These can be overridden by environment variables or command-line arguments.
MODELS_DIR = './models'
CONFIG_FILE_PATH = './config.yaml'
DOCKER_CONTAINER_NAME = 'llama-swap'
MAX_BACKUPS = 3

# --- PyYAML Customization for pretty multiline strings ---
class LiteralString(str): pass

def literal_representer(dumper, data):
    """Instructs PyYAML to dump a string as a literal block scalar (using '|')."""
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

yaml.add_representer(LiteralString, literal_representer, Dumper=yaml.SafeDumper)
# --- END PyYAML ---

CMD_TEMPLATE = (
    "/app/llama-server\n"
    "  -m /models/{model_filename}\n"
    "  -ngl 99\n"
    "  -c 4096\n"
    "  -b 2048\n"
    "  -ub 512\n"
    "  --temp 0.7\n"
    "  --top-p 0.95\n"
    "  --top-k 40\n"
    "  --repeat-penalty 1.1\n"
    "  --port ${{PORT}}\n"
    "  --host 0.0.0.0"
)

def create_model_entry(filename: str) -> Dict[str, Any]:
    """Creates a comprehensive, scaffolded dictionary for a model entry."""
    model_key = filename.replace('.gguf', '')
    pretty_name = model_key.replace('-', ' ').replace('_', ' ')
    entry: Dict[str, Any] = {
        'name': pretty_name, 'description': f"Auto-generated entry for {filename}",
        'cmd': LiteralString(CMD_TEMPLATE.format(model_filename=filename)),
        'aliases': [], 'env': [], 'ttl': 0, 'unlisted': False, 'filters': {},
        'metadata': {}, 'macros': {}, 'concurrencyLimit': 0, 'cmdStop': ""
    }
    return entry

# --- Core Logic Functions (Refactored for Modularity) ---

def manage_backups(config_path: str, dry_run: bool) -> None:
    """Creates a new timestamped backup and prunes old ones, respecting MAX_BACKUPS."""
    logging.info("--- Managing Backups ---")
    if not os.path.exists(config_path):
        logging.info("Config file '%s' does not exist. Skipping backup.", config_path)
        return

    backup_pattern = f"{config_path}.bak.*"
    existing_backups = sorted(glob.glob(backup_pattern))

    while len(existing_backups) >= MAX_BACKUPS:
        oldest_backup = existing_backups.pop(0)
        if dry_run:
            logging.info("DRY RUN: Would remove oldest backup: %s", oldest_backup)
        else:
            try:
                os.remove(oldest_backup)
                logging.info("Removed oldest backup: %s", oldest_backup)
            except OSError as e:
                logging.error("Failed to remove backup '%s': %s", oldest_backup, e)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    new_backup_path = f"{config_path}.bak.{timestamp}"
    if dry_run:
        logging.info("DRY RUN: Would create backup: %s", new_backup_path)
    else:
        try:
            shutil.copy2(config_path, new_backup_path)
            logging.info("Backup created: %s", new_backup_path)
        except OSError as e:
            logging.error("Failed to create backup '%s': %s", new_backup_path, e)

def load_config(config_path: str) -> Dict[str, Any]:
    """Loads and parses the YAML config file, handling errors gracefully."""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logging.warning("Config file not found at '%s'. A new one will be created.", config_path)
        return {}
    except yaml.YAMLError as e:
        logging.critical("Failed to parse config file '%s'. It may be corrupted.", config_path)
        logging.critical("YAML parsing error: %s", e)
        sys.exit(1)
    except PermissionError:
        logging.critical("Permission denied when trying to read config file '%s'.", config_path)
        sys.exit(1)

def audit_config_entries(config_models: Dict[str, Any]) -> int:
    """
    Audits existing entries, preserving manual changes by adding missing keys.

    This function iterates through each model entry and ensures it contains all
    the keys present in a default template. If any keys are missing, they are
    added with their default values. This process is non-destructive and
    preserves all user-customized values for existing keys, including 'cmd'.
    """
    logging.info("--- Auditing Existing Config Entries for Completeness ---")
    models_updated = 0
    for model_key in list(config_models.keys()):
        existing_entry = config_models[model_key]
        
        if not isinstance(existing_entry, dict):
            logging.warning("Found malformed entry for '%s' (not a dictionary). Forcibly reformatting.", model_key)
            config_models[model_key] = create_model_entry(f"{model_key}.gguf")
            models_updated += 1
            continue

        ideal_template = create_model_entry(f"{model_key}.gguf")
        entry_was_modified = False
        
        # Check for and add any missing keys from the template.
        for key, default_value in ideal_template.items():
            if key not in existing_entry:
                existing_entry[key] = default_value
                entry_was_modified = True
        
        if entry_was_modified:
            logging.info("UPDATING: Entry '%s' is missing one or more keys. Defaults have been added.", model_key)
            models_updated += 1

    if models_updated == 0:
        logging.info("All existing entries are structurally complete.")
    return models_updated

def find_models_on_disk(models_dir: str) -> Set[str]:
    """Scans the models directory for .gguf files and returns a set of model keys."""
    logging.info("--- Syncing with Models Directory ---")
    try:
        filenames = [f for f in os.listdir(models_dir) if f.endswith('.gguf')]
        return {f.replace('.gguf', '') for f in filenames}
    except FileNotFoundError:
        logging.error("Models directory '%s' not found. Cannot add new models.", models_dir)
        return set()
    except PermissionError:
        logging.error("Permission denied when trying to read models directory '%s'.", models_dir)
        return set()

def sync_disk_to_config(config_models: Dict[str, Any], disk_keys: Set[str], prune: bool) -> Tuple[int, int]:
    """Adds new models and removes stale ones. Returns counts of added/removed models."""
    models_added, models_removed = 0, 0
    
    for key in sorted(list(disk_keys)):
        if key not in config_models:
            filename = f"{key}.gguf"
            logging.info("ADDING: New model file found: '%s'", filename)
            config_models[key] = create_model_entry(filename)
            models_added += 1

    config_keys = set(config_models.keys())
    stale_keys = config_keys - disk_keys
    if stale_keys:
        if prune:
            for key in sorted(list(stale_keys)):
                logging.info("REMOVING: Stale entry '%s' as requested.", key)
                del config_models[key]
                models_removed += 1
        else:
            for key in sorted(list(stale_keys)):
                logging.warning("Stale entry '%s' found (no matching file). Use --prune to remove.", key)
    
    return models_added, models_removed

def save_config(config_path: str, config_data: Dict[str, Any], dry_run: bool) -> None:
    """Atomically saves the configuration, ensuring 'cmd' fields are correctly formatted."""
    if dry_run:
        logging.info("DRY RUN: Would save changes to '%s'.", config_path)
        return

    # Before dumping, ensure all 'cmd' fields are wrapped in LiteralString
    # for correct multi-line YAML output. This is a presentation-layer change
    # that avoids interfering with the audit logic.
    if 'models' in config_data and isinstance(config_data['models'], dict):
        for model_entry in config_data['models'].values():
            if isinstance(model_entry, dict) and 'cmd' in model_entry:
                # Ensure cmd value is a string before wrapping
                if not isinstance(model_entry['cmd'], str):
                     model_entry['cmd'] = str(model_entry['cmd'])
                model_entry['cmd'] = LiteralString(model_entry['cmd'])
    
    temp_path = f"{config_path}.tmp"
    try:
        with open(temp_path, 'w') as f:
            yaml.dump(config_data, f, Dumper=yaml.SafeDumper, sort_keys=False, indent=2)
        os.replace(temp_path, config_path)
        logging.info("Successfully updated '%s'.", config_path)
    except (OSError, PermissionError, yaml.YAMLError) as e:
        logging.critical("Failed to write to config file '%s'. Error: %s", config_path, e)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        sys.exit(1)

def restart_docker_container(container_name: str, dry_run: bool) -> None:
    """Attempts to restart the specified Docker container."""
    logging.info("--- Restarting Docker Container ---")
    if not container_name:
        logging.warning("No container name specified. Skipping restart.")
        return
    if dry_run:
        logging.info("DRY RUN: Would restart Docker container '%s'.", container_name)
        return
    
    try:
        client = docker.from_env()
        client.ping()
        container = client.containers.get(container_name)
        logging.info("Found container '%s' (ID: %s). Attempting to restart...", container_name, container.short_id)
        container.restart()
        logging.info("Successfully sent restart command to container '%s'.", container_name)
    except docker.errors.NotFound:
        logging.warning("Docker container '%s' not found. Cannot restart.", container_name)
    except docker.errors.DockerException as e:
        logging.error("An error occurred with Docker. Is the Docker daemon running? Details: %s", e)

# --- Main Orchestrator ---

def run_sync_process(config_path: str, models_dir: str, container_name: str, prune: bool, no_restart: bool, dry_run: bool) -> None:
    """Main function to backup, audit, sync, and conditionally restart."""
    lock_path = f"{config_path}.lock"
    if os.path.exists(lock_path):
        logging.warning("Lock file '%s' exists. Another sync process may be running. Exiting.", lock_path)
        sys.exit(0)
    
    try:
        with open(lock_path, 'w') as f:
            f.write(str(os.getpid()))

        logging.info("--- Llama-Swap Config Sync Script ---")
        if prune:
            logging.info("Prune mode is active. Stale entries will be removed.")
        if dry_run:
            logging.warning("DRY RUN MODE IS ACTIVE. No files will be changed and no services will be restarted.")

        manage_backups(config_path, dry_run)
        config_data = load_config(config_path)
        config_models = config_data.setdefault('models', {})
        
        models_updated = audit_config_entries(config_models)
        model_keys_on_disk = find_models_on_disk(models_dir)
        models_added, models_removed = sync_disk_to_config(config_models, model_keys_on_disk, prune)
        
        changes_made = models_added > 0 or models_updated > 0 or models_removed > 0
        if changes_made:
            logging.info("--- Saving Changes ---")
            logging.info("Summary: %d added, %d updated, %d removed.", models_added, models_updated, models_removed)
            save_config(config_path, config_data, dry_run)
            if not no_restart:
                restart_docker_container(container_name, dry_run)
            else:
                logging.info("--no-restart flag detected. Skipping Docker restart.")
        else:
            logging.info("--- No changes needed. Configuration is already up to date. ---")
    
    finally:
        if os.path.exists(lock_path):
            os.remove(lock_path)
            logging.debug("Lock file '%s' removed.", lock_path)

def main() -> None:
    """Parses command-line arguments and environment variables to run the sync process."""
    parser = argparse.ArgumentParser(
        description="Sync GGUF models in a directory with a llama-swap config file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--config', type=str,
        default=os.environ.get('LLAMA_SWAP_CONFIG', CONFIG_FILE_PATH),
        help=f"Path to the config file. Env: LLAMA_SWAP_CONFIG (default: {CONFIG_FILE_PATH})"
    )
    parser.add_argument(
        '--models-dir', type=str,
        default=os.environ.get('LLAMA_SWAP_MODELS_DIR', MODELS_DIR),
        help=f"Path to the models directory. Env: LLAMA_SWAP_MODELS_DIR (default: {MODELS_DIR})"
    )
    parser.add_argument(
        '--container', type=str,
        default=os.environ.get('LLAMA_SWAP_CONTAINER', DOCKER_CONTAINER_NAME),
        help=f"Docker container to restart. Env: LLAMA_SWAP_CONTAINER (default: {DOCKER_CONTAINER_NAME})"
    )
    parser.add_argument('--prune', action='store_true', help="Remove entries from config if their .gguf file is missing.")
    parser.add_argument('--no-restart', action='store_true', help="Do not restart the Docker container after changes.")
    parser.add_argument('--dry-run', action='store_true', help="Show what changes would be made without modifying files or services.")
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-v', '--verbose', action='store_true', help="Enable verbose, debug-level logging.")
    group.add_argument('-q', '--quiet', action='store_true', help="Enable quiet logging, showing only warnings and errors.")

    args = parser.parse_args()

    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING

    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M%S')

    run_sync_process(
        config_path=args.config,
        models_dir=args.models_dir,
        container_name=args.container,
        prune=args.prune,
        no_restart=args.no_restart,
        dry_run=args.dry_run
    )

if __name__ == '__main__':
    main()