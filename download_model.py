# VERSION: 0.2.0
import argparse
import logging
import os
import sys
from huggingface_hub import HfApi

from hf_utils import (
    create_hash_file, download_with_progress, get_remote_lfs_hash,
    parse_hf_url, verify_file_hash
)

# --- CONFIGURATION ---
MODELS_DIR = './models'

def main():
    """Main script logic."""
    parser = argparse.ArgumentParser(
        description="Download a model file from Hugging Face with integrity verification.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        'url', type=str,
        help="The full URL to the model file on Hugging Face."
    )
    parser.add_argument(
        '--dest-dir', type=str, default=MODELS_DIR,
        help="The root destination directory for models."
    )
    parser.add_argument(
        '--retries', type=int, default=5,
        help="Number of times to retry the download on failure."
    )
    parser.add_argument(
        '--retry-delay', type=int, default=10,
        help="Initial delay in seconds between retries (will double each time)."
    )
    parser.add_argument(
        '--skip-verification', action='store_true',
        help="Skip hash verification after download."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    api = HfApi()
    repo_id, filename = parse_hf_url(args.url)

    if not repo_id or not filename:
        logging.error("Invalid Hugging Face URL format.")
        logging.error("Expected format: https://huggingface.co/<user>/<repo>/blob/main/<filename>")
        sys.exit(1)

    logging.info(f"Repository ID: {repo_id}")
    logging.info(f"Filename:      {filename}")

    dest_path = os.path.join(args.dest_dir, *repo_id.split('/'))
    os.makedirs(dest_path, exist_ok=True)
    logging.info(f"Destination:   {dest_path}")

    # Retrieve expected hash before downloading
    expected_hash = None
    if not args.skip_verification:
        expected_hash = get_remote_lfs_hash(api, repo_id, filename)
        if not expected_hash:
            logging.warning("Could not retrieve hash. Proceeding without verification.")

    # Download the file
    downloaded_file = download_with_progress(repo_id, filename, dest_path, args.retries, args.retry_delay)

    if not downloaded_file:
        logging.error("\n--- Download Failed ---")
        sys.exit(1)

    # Verify integrity if hash was retrieved
    if expected_hash and not args.skip_verification:
        if not verify_file_hash(downloaded_file, expected_hash):
            logging.error("File integrity check failed. The downloaded file may be corrupted.")
            sys.exit(1)

        # Create hash file after successful verification
        create_hash_file(downloaded_file, expected_hash)
    elif not args.skip_verification:
        logging.warning("Skipping hash file creation (no hash available for verification).")

    logging.info("\n--- Download Complete ---")

if __name__ == '__main__':
    main()