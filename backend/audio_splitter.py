
"""
audio_splitter.py
-----------------
Handles audio separation using Demucs.
Runs Demucs completely silent except for start and completion logs.
"""

import subprocess
import os

def split_audio(input_path, output_dir="separated", stem_type="all", job_id=None, logger=None):
    """
    Split an audio file into stems using Demucs silently.

    Args:
        input_path (str): Path to the audio file to split.
        output_dir (str): Directory where separated stems are saved.
        stem_type (str): Type of separation ('all' or '2stems').
        job_id (str): Optional job ID for log prefixing.
        logger (logging.Logger): Optional Flask logger.

    Returns:
        str: Path to the directory containing separated stems.
    """
    os.makedirs(output_dir, exist_ok=True)
    model_args = []

    if stem_type == "2stems":
        model_args = ["--two-stems", "vocals"]

    command = ["demucs", input_path, "-o", output_dir] + model_args

    if logger:
        logger.info(f"[{job_id}] Demucs process starting...")
    else:
        print(f"[{job_id}] Demucs process starting...")

    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    if logger:
        logger.info(f"[{job_id}] Demucs process complete.")
    else:
        print(f"[{job_id}] Demucs process complete.")

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    model_output_dir = os.listdir(output_dir)[0]
    output_path = os.path.join(output_dir, model_output_dir, base_name)

    if logger:
        logger.info(f"[{job_id}] Demucs wrote to: {os.path.join(output_dir, model_output_dir)}")

    return output_path
