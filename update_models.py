# VERSION: 0.2.0
"""
update_models.py - Model Update Checker

Scans for managed models with .sha256 files and checks for updates
from Hugging Face repositories.

Author: pkeffect
Version: 0.2.0
"""
import logging
import os
import sys
from pathlib import Path
from huggingface_hub import HfApi

from hf_utils import (
    create_hash_file, download_with_progress, get_remote_lfs_hash,
    verify_file_hash
)

# --- CONFIGURATION ---
MODELS_DIR = './models'

# --- CROSS-PLATFORM SYMBOLS ---
CHECK_MARK = "✓" if sys.platform != "win32" else "[OK]"
CROSS_MARK = "✗" if sys.platform != "win32" else "[X]"

def find_managed_models(root_dir: str) -> list[dict]:
    """Scans for .sha256 files and returns a list of managed models."""
    managed_models = []
    logging.info(f"Scanning for managed models in '{root_dir}'...")
    
    for hash_path in Path(root_dir).rglob('*.sha256'):
        try:
            with open(hash_path, 'r') as f:
                content = f.read().strip().split()
                if len(content) < 2:
                    logging.warning(f"Skipping malformed hash file: {hash_path}")
                    continue
                
                local_hash = content[0]
                filename = " ".join(content[1:]) # Handle filenames with spaces
                
                model_path = hash_path.with_suffix('')
                if not model_path.exists():
                    logging.warning(f"Model file for {hash_path} not found. Skipping.")
                    continue

                repo_path = model_path.parent.relative_to(root_dir)
                repo_id = '/'.join(repo_path.parts)

                managed_models.append({
                    "repo_id": repo_id,
                    "filename": filename,
                    "local_path": str(model_path),
                    "local_hash": local_hash,
                })
        except Exception as e:
            logging.error(f"Error processing hash file {hash_path}: {e}")
            
    logging.info(f"Found {len(managed_models)} managed models.")
    return managed_models

def validate_selection_input(choice: str, max_options: int) -> list[int] | None:
    """
    Validates and parses user input for model selection.
    Returns list of indices (0-based) or None if invalid.
    """
    if not choice or not choice.strip():
        return None
    
    choice = choice.strip()
    
    # Check for 'all' keyword
    if choice.lower() == 'all' or choice == str(max_options):
        return list(range(max_options - 1))  # All models (not including 'all' option itself)
    
    # Check for cancel
    if choice == '0':
        return []
    
    # Parse comma-separated numbers
    try:
        indices = []
        for part in choice.split(','):
            part = part.strip()
            if not part:
                continue
            num = int(part)
            if num < 1 or num >= max_options:
                logging.error(f"Invalid selection: {num}. Must be between 1 and {max_options - 1}.")
                return None
            indices.append(num - 1)  # Convert to 0-based
        return indices if indices else None
    except ValueError:
        return None

def main():
    """Main script logic."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    api = HfApi()
    local_models = find_managed_models(MODELS_DIR)
    
    if not local_models:
        logging.info("No managed models found to check for updates.")
        sys.exit(0)

    outdated_models = []
    logging.info("\n--- Checking for updates ---")
    for model in local_models:
        remote_hash = get_remote_lfs_hash(api, model['repo_id'], model['filename'])
        if remote_hash and remote_hash.lower() != model['local_hash'].lower():
            model['remote_hash'] = remote_hash
            outdated_models.append(model)
            logging.info(f"{CROSS_MARK} Update available for {model['repo_id']}/{model['filename']}")
        elif remote_hash:
            logging.info(f"{CHECK_MARK} {model['repo_id']}/{model['filename']} is up-to-date.")
    
    if not outdated_models:
        logging.info("\n--- All models are up-to-date. ---")
        sys.exit(0)

    print("\n--- Updates Available ---")
    for i, model in enumerate(outdated_models):
        print(f"  {i + 1}. {model['repo_id']}/{model['filename']}")
    
    all_option = len(outdated_models) + 1
    print(f"  {all_option}. Update All")
    print("   0. Cancel")

    try:
        choice = input("\nEnter number(s) to update (e.g., 1,3 or 'all'): ")
        indices = validate_selection_input(choice, all_option + 1)
        
        if indices is None:
            logging.error("Invalid selection. Please enter valid numbers separated by commas, 'all', or '0' to cancel.")
            sys.exit(1)
        
        if not indices:
            print("Update cancelled.")
            sys.exit(0)
        
        models_to_update = [outdated_models[i] for i in indices]
    except KeyboardInterrupt:
        print("\n\nUpdate cancelled by user.")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Error processing selection: {e}")
        sys.exit(1)

    if not models_to_update:
        logging.info("No models selected for update.")
        sys.exit(0)

    # Track update statistics
    successful_updates = 0
    failed_updates = 0

    logging.info("\n--- Starting Updates ---")
    for model in models_to_update:
        dest_path = os.path.dirname(model['local_path'])
        
        # Download the updated file
        downloaded_file = download_with_progress(model['repo_id'], model['filename'], dest_path, 5, 10)
        
        if not downloaded_file:
            logging.error(f"Update failed for {model['filename']}. Skipping.")
            failed_updates += 1
            continue
        
        # Verify and create new hash file
        if verify_file_hash(downloaded_file, model['remote_hash']):
            create_hash_file(downloaded_file, model['remote_hash'])
            successful_updates += 1
        else:
            failed_updates += 1
    
    logging.info("\n--- Update Process Complete ---")
    logging.info(f"Successfully updated: {successful_updates}")
    if failed_updates > 0:
        logging.warning(f"Failed updates: {failed_updates}")

if __name__ == '__main__':
    main()
