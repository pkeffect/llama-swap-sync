# VERSION: 0.3.0
"""
hf_utils.py - Hugging Face Utility Functions

This module provides utility functions for downloading, verifying, and managing
GGUF model files from Hugging Face repositories.

Key Features:
- SHA256 hash calculation and verification with progress bars
- Hugging Face URL parsing
- Download with retry logic and resume support
- Local file integrity checking
- Recursive .gguf file discovery

Usage:
    from hf_utils import download_with_progress, verify_file_hash
    
    downloaded = download_with_progress('repo/model', 'file.gguf', './dest', 5, 10)
    if verify_file_hash(downloaded, expected_hash):
        print("Download successful and verified")

Author: pkeffect
Version: 0.3.0
"""
import hashlib
import logging
import os
import re
import sys
import time
from typing import Dict, Any
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import HfHubHTTPError
from tqdm import tqdm

# Constants
DEFAULT_CHUNK_SIZE = 8192

def parse_hf_url(url: str) -> tuple[str | None, str | None]:
    """Parses a Hugging Face URL to extract the repository ID and filename."""
    pattern = r"huggingface\.co/([^/]+/[^/]+)/blob/main/(.+)"
    match = re.search(pattern, url)
    if match:
        repo_id = match.group(1)
        filename = match.group(2)
        return repo_id, filename
    return None, None

def calculate_sha256(filepath: str, chunk_size: int = DEFAULT_CHUNK_SIZE, show_progress: bool = False) -> str:
    """
    Calculate SHA256 hash of a file with optional progress bar.
    
    Args:
        filepath: Path to the file to hash
        chunk_size: Size of chunks to read (default: 8192 bytes)
        show_progress: Whether to display a progress bar
    
    Returns:
        Hexadecimal SHA256 hash string
    """
    sha256_hash = hashlib.sha256()
    file_size = os.path.getsize(filepath)
    
    with open(filepath, 'rb') as f:
        if show_progress and file_size > 1024 * 1024:  # Only show for files > 1MB
            with tqdm(total=file_size, unit='B', unit_scale=True, desc="Hashing") as pbar:
                for chunk in iter(lambda: f.read(chunk_size), b''):
                    sha256_hash.update(chunk)
                    pbar.update(len(chunk))
        else:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                sha256_hash.update(chunk)
    
    return sha256_hash.hexdigest()

def verify_file_hash(filepath: str, expected_hash: str) -> bool:
    """Verify that a file's SHA256 hash matches the expected hash."""
    logging.info(f"Verifying file integrity for {os.path.basename(filepath)}...")
    actual_hash = calculate_sha256(filepath, show_progress=True)

    if actual_hash.lower() == expected_hash.lower():
        logging.info("✓ File integrity verified successfully.")
        return True
    else:
        logging.error(f"✗ Hash mismatch for {os.path.basename(filepath)}!")
        logging.error(f"  Expected: {expected_hash}")
        logging.error(f"  Actual:   {actual_hash}")
        return False

def get_remote_lfs_hash(api: HfApi, repo_id: str, filename: str) -> str | None:
    """
    Fetches repo metadata and returns the LFS SHA256 hash for the specified file.
    Returns None if hash cannot be retrieved.
    """
    logging.info(f"Fetching remote hash for {filename} from {repo_id}...")
    try:
        repo_info = api.repo_info(repo_id=repo_id, files_metadata=True)

        for file_meta in repo_info.siblings:
            if file_meta.rfilename == filename:
                if file_meta.lfs and file_meta.lfs.get("sha256"):
                    sha256_hash = file_meta.lfs["sha256"]
                    logging.info(f"✓ Retrieved remote SHA256 hash.")
                    return sha256_hash
                else:
                    logging.warning(f"File metadata found for {filename} but no LFS SHA256 hash available.")
                    return None

        logging.warning(f"File '{filename}' not found in repository metadata for {repo_id}.")
        return None

    except Exception as e:
        logging.error(f"Failed to retrieve repository metadata for {repo_id}: {e}")
        return None

def create_hash_file(filepath: str, sha256_hash: str) -> None:
    """Creates a .sha256 file in the format compatible with sha256sum."""
    hash_filepath = f"{filepath}.sha256"
    filename = os.path.basename(filepath)

    try:
        with open(hash_filepath, 'w') as f:
            f.write(f"{sha256_hash}  {filename}\n")
        logging.info(f"✓ Created/Updated hash file: {os.path.basename(hash_filepath)}")
    except OSError as e:
        logging.error(f"Failed to create hash file: {e}")

def read_hash_file(filepath: str) -> str | None:
    """
    Reads a .sha256 file and extracts the hash value.
    Returns None if file doesn't exist or is malformed.
    """
    hash_filepath = f"{filepath}.sha256"
    
    if not os.path.exists(hash_filepath):
        return None
    
    try:
        with open(hash_filepath, 'r') as f:
            content = f.read().strip()
            # Format is: "hash  filename" or "hash *filename"
            parts = re.split(r'\s+', content, maxsplit=1)
            if parts and len(parts[0]) == 64:
                # Validate it's actually hexadecimal
                if re.match(r'^[a-fA-F0-9]{64}$', parts[0]):
                    return parts[0]
            logging.warning(f"Malformed hash file: {os.path.basename(hash_filepath)}")
            return None
    except OSError as e:
        logging.error(f"Failed to read hash file {os.path.basename(hash_filepath)}: {e}")
        return None

def verify_local_file_integrity(filepath: str) -> bool:
    """
    Verifies a local file against its accompanying .sha256 file if it exists.
    Returns True if verified or if no hash file exists (no verification needed).
    Returns False only if hash file exists but verification fails.
    """
    expected_hash = read_hash_file(filepath)
    
    if expected_hash is None:
        logging.info(f"No hash file found for {os.path.basename(filepath)}, skipping verification.")
        return True
    
    return verify_file_hash(filepath, expected_hash)

def download_with_progress(repo_id: str, filename: str, dest_path: str, retries: int, retry_delay: int) -> str | None:
    """
    Download a file from Hugging Face Hub with retry logic.
    Downloads automatically resume whenever possible.
    Returns the full path to the downloaded file on success, None on failure.
    """
    for attempt in range(retries):
        try:
            logging.info(f"\nDownloading '{filename}' (Attempt {attempt + 1}/{retries})...")

            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=dest_path,
                local_dir_use_symlinks=False
            )

            logging.info(f"✓ Successfully downloaded to: {downloaded_path}")
            return downloaded_path

        except HfHubHTTPError as e:
            logging.error(f"HTTP error during download attempt {attempt + 1}: {e}")
            if attempt + 1 < retries:
                delay = retry_delay * (2 ** attempt)
                logging.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logging.error("All download attempts failed due to HTTP errors.")

        except OSError as e:
            logging.error(f"File system error during download attempt {attempt + 1}: {e}")
            if attempt + 1 < retries:
                delay = retry_delay * (2 ** attempt)
                logging.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logging.error("All download attempts failed due to file system errors.")

        except Exception as e:
            logging.error(f"Unexpected error during download attempt {attempt + 1}: {e}")
            if attempt + 1 < retries:
                delay = retry_delay * (2 ** attempt)
                logging.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logging.error("All download attempts failed.")

    return None

def get_model_destination_path(models_base_dir: str, repo_id: str) -> str:
    """
    Constructs the destination path for a model based on repository structure.
    e.g., 'TheBloke/Llama-2-7B-GGUF' -> './models/TheBloke/Llama-2-7B-GGUF'
    """
    return os.path.join(models_base_dir, *repo_id.split('/'))

def list_local_gguf_files(models_dir: str) -> Dict[str, str]:
    """
    Recursively scans models directory for .gguf files.
    Returns a dictionary mapping model_key to relative filepath.
    
    Example:
        {'TheBloke--model-name': 'TheBloke/model-name.gguf'}
    """
    model_paths: Dict[str, str] = {}
    
    if not os.path.isdir(models_dir):
        logging.warning(f"Models directory '{models_dir}' not found.")
        return model_paths
    
    for root, _, files in os.walk(models_dir):
        for file in files:
            if file.endswith('.gguf'):
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, models_dir)
                # Normalize to POSIX-style paths
                path_posix = relative_path.replace(os.path.sep, '/')
                # Create key by replacing / with --
                model_key = path_posix.replace('.gguf', '').replace('/', '--')
                model_paths[model_key] = path_posix
    
    return model_paths

def validate_gguf_filepath(filepath: str) -> bool:
    """
    Validate that a relative filepath is safe and is a GGUF file.
    Prevents path traversal and ensures proper format.
    """
    if not filepath:
        return False
    
    # Normalize and check for path traversal
    normalized = filepath.replace('\\', '/')
    if '..' in normalized.split('/'):
        return False
    
    # Disallow absolute paths
    if os.path.isabs(filepath):
        return False
    
    # Ensure it's a gguf file
    return filepath.lower().endswith('.gguf')
