"""
audio_splitter.py
-----------------
Handles audio separation using Demucs (CPU).
"""

import os
import shutil
import subprocess
import sys


def _demucs_bin():
    """
    Find the demucs executable: DEMUCS_BIN if set, otherwise the one installed
    next to the running Python (the venv), otherwise whatever is on PATH.
    """
    configured = os.getenv("DEMUCS_BIN")
    if configured:
        return configured
    venv_bin = os.path.join(os.path.dirname(sys.executable), "demucs")
    if os.path.exists(venv_bin):
        return venv_bin
    return shutil.which("demucs") or "demucs"


def split_audio(input_path, output_dir="separated", stem_type="all", job_id=None, logger=None):
    """
    Split an audio file into stems using Demucs locally (CPU).
    """
    os.makedirs(output_dir, exist_ok=True)
    model_args = []

    if stem_type == "2stems":
        model_args = ["--two-stems", "vocals"]

    command = [_demucs_bin(), input_path, "-o", output_dir] + model_args

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
