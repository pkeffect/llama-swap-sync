# VERSION: 0.6.0
"""
llama_swap_sync.py - GGUF Model Configuration Synchronizer

Automatically synchronizes GGUF model files with llama-swap configuration,
managing backups, auditing entries, and optionally restarting Docker containers.

Features:
- Recursive model discovery
- Smart key generation with collision detection
- Non-destructive configuration updates
- Atomic file writes with backup management
- Optional Docker container restart
- Dry-run mode for safe preview

Author: pkeffect
Version: 0.6.0
"""
import argparse
import copy
import datetime
import glob
import hashlib
import logging
import os
import shutil
import subprocess
import sys
from typing import Dict, Any, Tuple

import yaml

from hf_utils import list_local_gguf_files, validate_gguf_filepath

# --- CONFIGURATION (Defaults - Override via CLI args or environment variables) ---
MODELS_DIR = './models'
CONFIG_FILE_PATH = './config.yaml'
DOCKER_CONTAINER_NAME = 'llama-swap'

# Configurable via environment variables
MAX_BACKUPS = int(os.getenv('LLAMA_SWAP_MAX_BACKUPS', '3'))
MAX_KEY_LENGTH = int(os.getenv('LLAMA_SWAP_MAX_KEY_LENGTH', '80'))

# YAML width for optimal formatting (prevents very long single lines while maintaining readability)
YAML_WIDTH = 120

# --- CROSS-PLATFORM SYMBOLS ---
CHECK_MARK = "✓" if sys.platform != "win32" else "[OK]"
CROSS_MARK = "✗" if sys.platform != "win32" else "[X]"

# --- PyYAML Customization for pretty multiline strings ---
class LiteralString(str): pass

def literal_representer(dumper, data) -> yaml.ScalarNode:
    """Instructs PyYAML to dump a string as a literal block scalar (using '|')."""
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

yaml.add_representer(LiteralString, literal_representer, Dumper=yaml.SafeDumper)

def create_safe_model_key(filepath: str) -> str:
    """
    Creates a safe, shortened YAML key from filepath.
    Long keys cause PyYAML to use '? key:' format which breaks llama-swap.
    Uses SHA256 for hash suffix instead of MD5 for consistency.
    """
    # Normalize filepath to use forward slashes
    filepath_posix = filepath.replace(os.path.sep, '/')
    
    # Create base key
    base_key = filepath_posix.replace('.gguf', '').replace('/', '--')
    
    # If key is too long, create a shortened version
    if len(base_key) > MAX_KEY_LENGTH:
        # Split into parts
        parts = base_key.split('--')
        
        # Keep first part (author) and last part (model variant)
        if len(parts) >= 3:
            # author--shortened_repo--variant
            author = parts[0]
            variant = parts[-1]
            # Take first 20 chars of middle parts
            middle = '--'.join(parts[1:-1])
            if len(middle) > 20:
                middle = middle[:20]
            
            shortened_key = f"{author}--{middle}--{variant}"
            
            # If still too long, hash it
            if len(shortened_key) > MAX_KEY_LENGTH:
                hash_suffix = hashlib.sha256(base_key.encode()).hexdigest()[:8]
                shortened_key = f"{author}--{variant}--{hash_suffix}"
            
            logging.debug(f"Shortened key: {base_key} -> {shortened_key}")
            return shortened_key
    
    return base_key

def create_model_entry(filepath: str) -> Dict[str, Any]:
    """Creates a comprehensive, scaffolded dictionary for a model entry from its relative path."""
    # Normalize filepath to use forward slashes for consistency
    filepath_posix = filepath.replace(os.path.sep, '/')
    
    # Create a prettier name for display purposes
    model_key = filepath_posix.replace('.gguf', '').replace('/', '--')
    pretty_name = model_key.replace('--', ' / ').replace('-', ' ').replace('_', ' ')
    
    # Dynamic command generation
    cmd_string = (
        "/app/llama-server\n"
        f"  -m /models/{filepath_posix}\n"
        "  -ngl 99\n"
        "  -c 4096\n"
        "  -b 2048\n"
        "  -ub 512\n"
        "  --temp 0.7\n"
        "  --top-p 0.95\n"
        "  --top-k 40\n"
        "  --repeat-penalty 1.1\n"
        "  --port ${PORT}\n"
        "  --host 0.0.0.0"
    )

    entry: Dict[str, Any] = {
        'name': pretty_name,
        'description': f"Auto-generated entry for {filepath_posix}",
        'cmd': LiteralString(cmd_string),
        'aliases': [],
        'env': [],
        'ttl': 0,
        'unlisted': False,
        'filters': {},
        'metadata': {},
        'macros': {},
        'concurrencyLimit': 0,
        'cmdStop': ""
    }
    return entry

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
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            if data is None or not isinstance(data, dict):
                logging.warning("Config file is empty or invalid. Starting with default structure.")
                return {'models': {}}
            if 'models' not in data:
                data['models'] = {}
            if not isinstance(data.get('models'), dict):
                logging.error("'models' key in config is not a dictionary. Resetting to empty dict.")
                data['models'] = {}
            return data
    except FileNotFoundError:
        logging.warning("Config file not found at '%s'. A new one will be created.", config_path)
        return {'models': {}}
    except yaml.YAMLError as e:
        logging.critical("Failed to parse config file '%s'. It may be corrupted. Error: %s", config_path, e)
        sys.exit(1)
    except PermissionError:
        logging.critical("Permission denied when trying to read config file '%s'.", config_path)
        sys.exit(1)

def audit_config_entries(config_models: Dict[str, Any]) -> int:
    """Audits existing entries, preserving manual changes by adding missing keys."""
    logging.info("--- Auditing Existing Config Entries for Completeness ---")
    models_updated = 0
    template_keys = set(create_model_entry("dummy/dummy.gguf").keys())
    
    for model_key, existing_entry in list(config_models.items()):
        if not isinstance(existing_entry, dict):
            logging.warning("Found malformed entry for '%s' (not a dictionary). Forcibly reformatting.", model_key)
            reconstructed_filepath = model_key.replace('--', '/') + '.gguf'
            config_models[model_key] = create_model_entry(reconstructed_filepath)
            models_updated += 1
            continue

        missing_keys = template_keys - set(existing_entry.keys())
        if missing_keys:
            reconstructed_filepath = model_key.replace('--', '/') + '.gguf'
            ideal_template = create_model_entry(reconstructed_filepath)
            for key in missing_keys:
                existing_entry[key] = ideal_template[key]
            logging.info("UPDATING: Entry '%s' was missing keys: %s", model_key, sorted(list(missing_keys)))
            models_updated += 1

    if models_updated == 0:
        logging.info("All existing entries are structurally complete.")
    return models_updated

def sync_disk_to_config(config_models: Dict[str, Any], disk_models: Dict[str, str], prune: bool) -> Tuple[int, int]:
    """Adds new models and removes stale ones. Returns counts of added/removed models."""
    models_added, models_removed = 0, 0
    
    # Build mapping of safe keys for disk models with collision detection
    disk_safe_keys = {}
    for filepath in disk_models.values():
        safe_key = create_safe_model_key(filepath)
        
        # Check for collision
        if safe_key in disk_safe_keys:
            logging.error(f"Key collision detected: '{safe_key}' for both:")
            logging.error(f"  - {disk_safe_keys[safe_key]}")
            logging.error(f"  - {filepath}")
            logging.error("This is a critical error. Cannot continue safely.")
            sys.exit(1)
        
        disk_safe_keys[safe_key] = filepath
    
    disk_keys = set(disk_safe_keys.keys())
    config_keys = set(config_models.keys())

    new_keys = disk_keys - config_keys
    for safe_key in sorted(list(new_keys)):
        filepath = disk_safe_keys[safe_key]
        logging.info("ADDING: New model file found: '%s' (key: %s)", filepath, safe_key)
        config_models[safe_key] = create_model_entry(filepath)
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
    """Creates a deep copy of config with 'cmd' fields wrapped in LiteralString."""
    save_data = copy.deepcopy(config_data)
    
    if 'models' in save_data and isinstance(save_data['models'], dict):
        for model_entry in save_data['models'].values():
            if isinstance(model_entry, dict) and 'cmd' in model_entry:
                if not isinstance(model_entry['cmd'], str):
                    model_entry['cmd'] = str(model_entry['cmd'])
                model_entry['cmd'] = LiteralString(model_entry['cmd'])
    return save_data

def save_config(config_path: str, config_data: Dict[str, Any], dry_run: bool) -> None:
    """Atomically saves the configuration with corrected formatting."""
    if dry_run:
        logging.info("DRY RUN: Would save changes to '%s'.", config_path)
        return

    save_data = prepare_config_for_save(config_data)
    temp_path = f"{config_path}.tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            # Using explicit settings to prevent '? key:' format
            # YAML_WIDTH set to 120 to balance line length with readability
            yaml.dump(
                save_data, f,
                Dumper=yaml.SafeDumper,
                sort_keys=False,
                indent=2,
                width=YAML_WIDTH,
                default_flow_style=False,
                allow_unicode=True
            )
        os.replace(temp_path, config_path)
        logging.info("Successfully updated '%s'.", config_path)
    except (OSError, yaml.YAMLError) as e:
        logging.critical("Failed to write to config file '%s'. Error: %s", config_path, e)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        sys.exit(1)

def restart_docker_container(container_name: str, dry_run: bool) -> None:
    """Restarts the Docker container using Docker CLI via subprocess."""
    logging.info("--- Restarting Docker Container ---")
    if not container_name:
        logging.warning("No container name specified. Skipping restart.")
        return
    if dry_run:
        logging.info("DRY RUN: Would restart Docker container '%s'.", container_name)
        return
    
    try:
        # Use Docker CLI directly - it handles Windows named pipes correctly
        logging.debug(f"Executing: docker restart {container_name}")
        result = subprocess.run(
            ['docker', 'restart', container_name],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            logging.info(f"{CHECK_MARK} Successfully restarted container '{container_name}'.")
            if result.stdout.strip():
                logging.debug(f"Docker output: {result.stdout.strip()}")
        else:
            logging.error(f"Failed to restart container '{container_name}'.")
            if result.stderr.strip():
                logging.error(f"Docker error: {result.stderr.strip()}")
    
    except subprocess.TimeoutExpired:
        logging.error(f"Timeout while trying to restart container '{container_name}'.")
    except FileNotFoundError:
        logging.error("Docker CLI not found. Ensure 'docker' command is in your PATH.")
        logging.error("Install Docker Desktop: https://docs.docker.com/get-docker/")
    except Exception as e:
        logging.error(f"Unexpected error restarting container: {e}")

def run_sync_process(config_path: str, models_dir: str, container_name: str, prune: bool, no_restart: bool, dry_run: bool) -> None:
    """Main function to backup, audit, sync, and conditionally restart."""
    lock_path = f"{config_path}.lock"
    lock_fd = None
    
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(lock_fd, str(os.getpid()).encode())
    except FileExistsError:
        logging.error("Lock file '%s' exists. Another sync process is running. Exiting.", lock_path)
        sys.exit(1)

    try:
        if dry_run:
            logging.warning("DRY RUN MODE IS ACTIVE. No files will be changed and no services will be restarted.")
        
        # Check for malformed YAML formatting
        formatting_needs_fix = False
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if '? ' in content and '\n  :' in content:
                    logging.info("Detected malformed YAML key format ('? key'). Scheduling a rewrite to fix it.")
                    formatting_needs_fix = True

        manage_backups(config_path, dry_run)
        config_data = load_config(config_path)
        config_models = config_data.get('models', {})
        
        models_updated = audit_config_entries(config_models)
        disk_model_map = list_local_gguf_files(models_dir)
        models_added, models_removed = sync_disk_to_config(config_models, disk_model_map, prune)
        
        changes_made = any((models_added, models_updated, models_removed, formatting_needs_fix))
        if changes_made:
            logging.info("--- Saving Changes ---")
            summary = f"Summary: {models_added} added, {models_updated} updated, {models_removed} removed."
            if formatting_needs_fix:
                summary += " (Config formatting will be corrected)."
            logging.info(summary)
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
            except OSError as e:
                logging.error("Failed to remove lock file '%s': %s", lock_path, e)

def main() -> None:
    """Parses arguments and runs the sync process."""
    parser = argparse.ArgumentParser(
        description="Sync GGUF models with a llama-swap config file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--config', default=os.environ.get('LLAMA_SWAP_CONFIG', CONFIG_FILE_PATH),
        help="Path to the config file. Env: LLAMA_SWAP_CONFIG"
    )
    parser.add_argument(
        '--models-dir', default=os.environ.get('LLAMA_SWAP_MODELS_DIR', MODELS_DIR),
        help="Path to the models directory. Env: LLAMA_SWAP_MODELS_DIR"
    )
    parser.add_argument(
        '--container', default=os.environ.get('LLAMA_SWAP_CONTAINER', DOCKER_CONTAINER_NAME),
        help="Docker container to restart. Env: LLAMA_SWAP_CONTAINER"
    )
    parser.add_argument(
        '--prune', action='store_true',
        help="Remove entries from config if GGUF file is missing."
    )
    parser.add_argument(
        '--no-restart', action='store_true',
        help="Do not restart Docker container after changes."
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help="Show changes without modifying files or services."
    )
    
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        '-v', '--verbose', action='store_true',
        help="Enable verbose, debug-level logging."
    )
    log_group.add_argument(
        '-q', '--quiet', action='store_true',
        help="Enable quiet logging (warnings and errors only)."
    )

    args = parser.parse_args()

    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

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
