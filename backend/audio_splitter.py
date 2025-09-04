"""
audio_splitter.py
-----------------
Handles audio separation using Demucs.
Supports both local CPU splitting and GPU splitting via remote container.
"""

import os
import subprocess
import uuid
import shutil
import requests

def split_audio(input_path, output_dir="separated", stem_type="all", job_id=None, logger=None):
    """
    Split an audio file into stems using Demucs locally (CPU).
    """
    os.makedirs(output_dir, exist_ok=True)
    model_args = []

    if stem_type == "2stems":
        model_args = ["--two-stems", "vocals"]

    command = ["demucs", input_path, "-o", output_dir] + model_args

    if logger:
        logger.info(f"[{job_id}] Demucs process starting (CPU)...")
    else:
        print(f"[{job_id}] Demucs process starting (CPU)...")

    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    if logger:
        logger.info(f"[{job_id}] Demucs process complete (CPU).")
    else:
        print(f"[{job_id}] Demucs process complete (CPU).")

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    model_output_dir = os.listdir(output_dir)[0]
    output_path = os.path.join(output_dir, model_output_dir, base_name)

    if logger:
        logger.info(f"[{job_id}] Demucs wrote to: {os.path.join(output_dir, model_output_dir)}")

    return output_path


# def split_via_gpu(input_path, selected_stems=None, job_id=None, logger=None):
#     """
#     Sends the file to the remote GPU container to process via Demucs.
#     Returns the path to the saved ZIP file with stems.
#     """
#     if logger:
#         logger.info(f"[{job_id}] Sending job to GPU pod...")
#
#     gpu_url = "http://YOUR_GPU_IP:5000/split"  # 🔁 Replace with real IP/URL
#     files = {"file": open(input_path, "rb")}
#     data = [("stems", s) for s in (selected_stems or ["vocals", "other"])]
#
#     try:
#         res = requests.post(gpu_url, files=files, data=data, timeout=120)
#         if res.status_code != 200:
#             raise Exception(f"GPU split failed: {res.text}")
#
#         # Save to temp dir
#         base_dir = os.path.join("temp", job_id or str(uuid.uuid4()))
#         os.makedirs(base_dir, exist_ok=True)
#         zip_path = os.path.join(base_dir, "stems.zip")
#         with open(zip_path, "wb") as f:
#             f.write(res.content)
#
#         if logger:
#             logger.info(f"[{job_id}] GPU split complete. ZIP saved to {zip_path}")
#
#         return zip_path
#
#     except Exception as e:
#         if logger:
#             logger.error(f"[{job_id}] GPU split error: {e}")
#         raise
#
#     finally:
#         files["file"].close()

