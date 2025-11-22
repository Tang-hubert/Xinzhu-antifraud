import os
from google.cloud import storage
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_from_gcs(bucket_name, gcs_path, local_path="tmp/model"):
    """
    從 GCS 下載單個檔案到本地
    """
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)
    blob.download_to_filename(local_path)
    print(f"Downloaded {gcs_path} to {local_path}")
    logger.info(f"Downloaded {gcs_path} to {local_path}")

def download_multiple(bucket_name, file_list, local_dir="/tmp/model"):
    """
    file_list: ['models/model.pth', 'models/scaler.pkl', ...]
    local_dir: 本地儲存路徑，Cloud Run 可寫 /tmp
    """
    os.makedirs(local_dir, exist_ok=True)
    local_paths = {}
    for f in file_list:
        local_path = os.path.join(local_dir, os.path.basename(f))
        if not os.path.exists(local_path):
            download_from_gcs(bucket_name, f, local_path)
        local_paths[os.path.basename(f)] = local_path
    return local_paths