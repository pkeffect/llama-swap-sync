# VERSION: 0.3.0
import argparse
import datetime
import glob
import logging
import os
import re
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

def literal_representer(dumper, data) -> yaml.ScalarNode:
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

def validate_filepath(filepath: str) -> bool:
    """
    Validate that the relative filepath is safe.
    Prevents path traversal and ensures it's a GGUF file.
    """
    if not filepath:
        return False
    # Check for path traversal attempts '..'
    if '..' in filepath.replace('\\', '/').split('/'):
        return False
    # Disallow absolute paths
    if os.path.isabs(filepath):
        return False
    # Ensure it's a gguf file
    return filepath.endswith('.gguf')

def create_model_entry(filepath: str) -> Dict[str, Any]:
    """Creates a comprehensive, scaffolded dictionary for a model entry from its relative path."""
    # Normalize filepath to use forward slashes for consistency in keys and names
    filepath_posix = filepath.replace(os.path.sep, '/')
    
    # Key must be a safe, unique string for YAML. Replace path separators with '--'.
    model_key = filepath_posix.replace('.gguf', '').replace('/', '--')
    
    # Create a prettier name for display purposes
    pretty_name = model_key.replace('--', ' / ').replace('-', ' ').replace('_', ' ')
    
    entry: Dict[str, Any] = {
        'name': pretty_name, 'description': f"Auto-generated entry for {filepath_posix}",
        'cmd': LiteralString(CMD_TEMPLATE.format(model_filename=filepath_posix)),
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

    # Keep MAX_BACKUPS total - delete oldest if we're at the limit
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
            data = yaml.safe_load(f)
            # Handle empty or invalid config files
            if data is None or not isinstance(data, dict):
                logging.warning("Config file is empty or invalid. Starting with default structure.")
                return {'models': {}}
            # Ensure models key exists
            if 'models' not in data:
                data['models'] = {}
            # Validate that models is a dict
            if not isinstance(data['models'], dict):
                logging.error("'models' key in config is not a dictionary. Resetting to empty dict.")
                data['models'] = {}
            return data
    except FileNotFoundError:
        logging.warning("Config file not found at '%s'. A new one will be created.", config_path)
        return {'models': {}}
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
    
    # Create template keys set once for efficiency using a valid dummy path
    template_keys = set(create_model_entry("dummy/dummy.gguf").keys())
    
    for model_key in list(config_models.keys()):
        existing_entry = config_models[model_key]
        
        if not isinstance(existing_entry, dict):
            logging.warning("Found malformed entry for '%s' (not a dictionary). Forcibly reformatting.", model_key)
            # Reconstruct the original filepath from the key to create a valid new entry
            reconstructed_filepath = model_key.replace('--', '/') + '.gguf'
            config_models[model_key] = create_model_entry(reconstructed_filepath)
            models_updated += 1
            continue

        entry_was_modified = False
        
        # Check for missing keys
        missing_keys = template_keys - existing_entry.keys()
        if missing_keys:
            # Reconstruct filepath from key to get accurate default values
            reconstructed_filepath = model_key.replace('--', '/') + '.gguf'
            ideal_template = create_model_entry(reconstructed_filepath)
            for key in missing_keys:
                existing_entry[key] = ideal_template[key]
            entry_was_modified = True
            logging.info("UPDATING: Entry '%s' was missing keys: %s", model_key, sorted(missing_keys))
            models_updated += 1

    if models_updated == 0:
        logging.info("All existing entries are structurally complete.")
    return models_updated

def find_models_on_disk(models_dir: str) -> Dict[str, str]:
    """Scans the models directory recursively for .gguf files. Returns a map of {model_key: relative_filepath}."""
    logging.info("--- Syncing with Models Directory (Recursive Scan) ---")
    model_paths: Dict[str, str] = {}
    
    try:
        if not os.path.isdir(models_dir):
            raise FileNotFoundError

        all_paths = []
        for root, _, files in os.walk(models_dir):
            for file in files:
                if file.endswith('.gguf'):
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, models_dir)
                    all_paths.append(relative_path)
        
        invalid_paths = []
        for path in all_paths:
            # Normalize to POSIX-style paths for consistent key generation and validation
            path_posix = path.replace(os.path.sep, '/')
            if validate_filepath(path_posix):
                model_key = path_posix.replace('.gguf', '').replace('/', '--')
                model_paths[model_key] = path_posix
            else:
                invalid_paths.append(path)
        
        if invalid_paths:
            logging.warning("Ignored %d file(s) with invalid/unsafe filepaths: %s", 
                            len(invalid_paths), ', '.join(sorted(invalid_paths)))
        
        return model_paths
    except FileNotFoundError:
        logging.error("Models directory '%s' not found. Cannot add new models.", models_dir)
        return {}
    except PermissionError:
        logging.error("Permission denied when trying to read models directory '%s'.", models_dir)
        return {}

def sync_disk_to_config(config_models: Dict[str, Any], disk_models: Dict[str, str], prune: bool) -> Tuple[int, int]:
    """Adds new models and removes stale ones. Returns counts of added/removed models."""
    models_added, models_removed = 0, 0
    
    disk_keys = set(disk_models.keys())
    config_keys = set(config_models.keys())

    new_keys = disk_keys - config_keys
    for key in sorted(list(new_keys)):
        filepath = disk_models[key]
        logging.info("ADDING: New model file found: '%s'", filepath)
        config_models[key] = create_model_entry(filepath)
        models_added += 1

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

def prepare_config_for_save(config_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a deep copy of config with cmd fields wrapped in LiteralString for YAML output.
    This prevents mutation of the original config_data dictionary.
    """
    import copy
    save_data = copy.deepcopy(config_data)
    
    if 'models' in save_data and isinstance(save_data['models'], dict):
        for model_entry in save_data['models'].values():
            if isinstance(model_entry, dict) and 'cmd' in model_entry:
                # Ensure cmd value is a string before wrapping
                if not isinstance(model_entry['cmd'], str):
                    model_entry['cmd'] = str(model_entry['cmd'])
                model_entry['cmd'] = LiteralString(model_entry['cmd'])
    
    return save_data

def save_config(config_path: str, config_data: Dict[str, Any], dry_run: bool) -> None:
    """Atomically saves the configuration, ensuring 'cmd' fields are correctly formatted."""
    if dry_run:
        logging.info("DRY RUN: Would save changes to '%s'.", config_path)
        return

    # Prepare a copy with proper formatting
    save_data = prepare_config_for_save(config_data)
    
    temp_path = f"{config_path}.tmp"
    try:
        with open(temp_path, 'w') as f:
            yaml.dump(save_data, f, Dumper=yaml.SafeDumper, sort_keys=False, indent=2)
        os.replace(temp_path, config_path)
        logging.info("Successfully updated '%s'.", config_path)
    except (OSError, PermissionError, yaml.YAMLError) as e:
        logging.critical("Failed to write to config file '%s'. Error: %s", config_path, e)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
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
        container.restart(timeout=30)
        logging.info("Successfully sent restart command to container '%s'.", container_name)
    except docker.errors.NotFound:
        logging.warning("Docker container '%s' not found. Cannot restart.", container_name)
    except docker.errors.DockerException as e:
        logging.error("An error occurred with Docker. Is the Docker daemon running? Details: %s", e)

# --- Main Orchestrator ---

def run_sync_process(config_path: str, models_dir: str, container_name: str, prune: bool, no_restart: bool, dry_run: bool) -> None:
    """Main function to backup, audit, sync, and conditionally restart."""
    lock_path = f"{config_path}.lock"
    lock_fd = None
    
    # Try to acquire lock
    try:
        # Use O_CREAT | O_EXCL for atomic lock creation
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(lock_fd, str(os.getpid()).encode())
    except OSError:
        logging.warning("Lock file '%s' exists. Another sync process may be running. Exiting.", lock_path)
        sys.exit(0)
    
    try:
        logging.info("--- Llama-Swap Config Sync Script ---")
        if prune:
            logging.info("Prune mode is active. Stale entries will be removed.")
        if dry_run:
            logging.warning("DRY RUN MODE IS ACTIVE. No files will be changed and no services will be restarted.")

        manage_backups(config_path, dry_run)
        config_data = load_config(config_path)
        config_models = config_data['models']
        
        models_updated = audit_config_entries(config_models)
        disk_model_map = find_models_on_disk(models_dir)
        models_added, models_removed = sync_disk_to_config(config_models, disk_model_map, prune)
        
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
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
                logging.debug("Lock file '%s' removed.", lock_path)
            except OSError as e:
                logging.error("Failed to remove lock file '%s': %s", lock_path, e)

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

    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

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