"""
ComfyUI LTX-2 Video Serverless Handler for RunPod
Supports two modes:
1. Generated Audio: LTX-2 generates audio based on prompt
2. Custom Audio: Use pre-generated audio (e.g., from ElevenLabs)
"""

import runpod
import json
import urllib.request
import base64
import time
import os
import sys
import logging
import traceback
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import random

class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    blue = "\x1b[34;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: blue + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset,
    }
    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)

def setup_logging():
    logger = logging.getLogger("LTX2-Handler")
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(CustomFormatter())
    logger.handlers = []
    logger.addHandler(console_handler)
    return logger

logger = setup_logging()

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"

DEFAULT_PARAMS = {
    "width": 720,
    "height": 720,
    "frame_count": 97,
    "steps": 20,
    "cfg": 4.0,
    "fps": 25,
    "seed": None,
    "timeout": 600,
    "img_compression": 33,
    "i2v_strength_first": 1.0,
    "i2v_strength_second": 1.0
}

DEFAULT_NEGATIVE_PROMPT = "static, frozen, no movement, still frame, blurry, jittery, morphing, deformed, warping, extra limbs, bad anatomy, watermark, text, overlay, titles, subtitles, glitch, artifact, low quality, distorted face"

def log_separator(char="-", length=80):
    logger.info(char * length)

def log_section(title: str):
    log_separator("=")
    logger.info(f"  {title}")
    log_separator("=")

def wait_for_comfyui(timeout: int = 120) -> bool:
    logger.info(f"Waiting for ComfyUI server at {COMFYUI_URL}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=5)
            if response.status == 200:
                logger.info("ComfyUI server is ready!")
                return True
        except Exception as e:
            logger.debug(f"Waiting... ({e})")
        time.sleep(2)
    logger.error(f"ComfyUI server did not start within {timeout} seconds")
    return False

def save_input_image(image_data: str, filename: str = "input_image.png") -> str:
    logger.info("Saving input image...")
    try:
        if "base64," in image_data:
            image_data = image_data.split("base64,")[1]
        image_bytes = base64.b64decode(image_data)
        filepath = f"/comfyui/input/{filename}"
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        file_size = os.path.getsize(filepath)
        logger.info(f"Saved input image to {filepath} ({file_size} bytes)")
        return filepath
    except Exception as e:
        logger.error(f"Failed to save input image: {e}")
        raise

def save_input_audio(audio_data: str, filename: str = "input_audio.mp3") -> Tuple[str, float]:
    logger.info("Saving input audio...")
    try:
        if "base64," in audio_data:
            audio_data = audio_data.split("base64,")[1]
        audio_bytes = base64.b64decode(audio_data)
        temp_filepath = f"/comfyui/input/temp_{filename}"
        filepath = f"/comfyui/input/{filename}"
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(temp_filepath, "wb") as f:
            f.write(audio_bytes)
        file_size = os.path.getsize(temp_filepath)
        logger.info(f"Saved temp audio to {temp_filepath} ({file_size} bytes)")

        # Check number of channels
        try:
            result = subprocess.run([
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=channels",
                "-of", "default=noprint_wrappers=1:nokey=1",
                temp_filepath
            ], capture_output=True, text=True, timeout=30)
            channels = int(result.stdout.strip())
            logger.info(f"Audio channels: {channels}")
        except Exception as e:
            logger.warning(f"Could not determine audio channels: {e}")
            channels = 1  # Assume mono if detection fails

        # Convert mono to stereo if needed (LTX-2 Audio VAE requires stereo)
        if channels == 1:
            logger.info("Converting mono audio to stereo...")
            convert_result = subprocess.run([
                "ffmpeg", "-y", "-i", temp_filepath,
                "-ac", "2",  # Convert to 2 channels (stereo)
                "-ar", "44100",  # Standard sample rate
                filepath
            ], capture_output=True, text=True, timeout=60)
            if convert_result.returncode != 0:
                logger.error(f"FFmpeg conversion failed: {convert_result.stderr}")
                # Fall back to original file
                os.rename(temp_filepath, filepath)
            else:
                logger.info("Converted to stereo successfully")
                os.remove(temp_filepath)
        else:
            # Already stereo, just rename
            os.rename(temp_filepath, filepath)

        # Get duration from final file
        try:
            result = subprocess.run([
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath
            ], capture_output=True, text=True, timeout=30)
            duration = float(result.stdout.strip())
            logger.info(f"Audio duration: {duration:.2f} seconds")
            return filepath, duration
        except Exception as e:
            logger.warning(f"Could not determine audio duration: {e}")
            return filepath, 4.0
    except Exception as e:
        logger.error(f"Failed to save input audio: {e}")
        raise

def load_workflow(workflow_name: str = "generated_audio") -> Dict:
    workflow_path = f"/workflow_{workflow_name}.json"
    if not os.path.exists(workflow_path):
        workflow_path = "/workflow.json"
    logger.info(f"Loading workflow from {workflow_path}...")
    try:
        with open(workflow_path, "r") as f:
            workflow = json.load(f)
        logger.info("Workflow loaded successfully")
        return workflow
    except Exception as e:
        logger.error(f"Failed to load workflow: {e}")
        raise

def modify_workflow_generated_audio(workflow: Dict, params: Dict) -> Dict:
    logger.info("Configuring workflow for GENERATED AUDIO mode...")
    seed = params.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**31 - 1)
        logger.info(f"Generated random seed: {seed}")
        params["seed"] = seed

    if "98" in workflow:
        workflow["98"]["inputs"]["image"] = "input_image.png"
    if "92:3" in workflow:
        workflow["92:3"]["inputs"]["text"] = params["prompt"]
    if "92:4" in workflow:
        workflow["92:4"]["inputs"]["text"] = params.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
    for node_id in ["92:11", "92:67"]:
        if node_id in workflow:
            workflow[node_id]["inputs"]["noise_seed"] = seed
    if "92:62" in workflow:
        workflow["92:62"]["inputs"]["value"] = params["frame_count"]
    if "92:9" in workflow:
        workflow["92:9"]["inputs"]["steps"] = params["steps"]
    if "92:47" in workflow:
        workflow["92:47"]["inputs"]["cfg"] = params["cfg"]
    if "92:22" in workflow:
        workflow["92:22"]["inputs"]["frame_rate"] = params["fps"]
    if "92:51" in workflow:
        workflow["92:51"]["inputs"]["frame_rate"] = params["fps"]
    if "92:97" in workflow:
        workflow["92:97"]["inputs"]["fps"] = params["fps"]
    if "92:99" in workflow:
        workflow["92:99"]["inputs"]["img_compression"] = params.get("img_compression", 33)
    if "92:107" in workflow:
        workflow["92:107"]["inputs"]["strength"] = params.get("i2v_strength_first", 1.0)
    if "92:108" in workflow:
        workflow["92:108"]["inputs"]["strength"] = params.get("i2v_strength_second", 1.0)
    return workflow

def modify_workflow_custom_audio(workflow: Dict, params: Dict, audio_duration: float) -> Dict:
    logger.info("Configuring workflow for CUSTOM AUDIO mode...")
    seed = params.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**31 - 1)
        logger.info(f"Generated random seed: {seed}")
        params["seed"] = seed

    fps = params["fps"]
    frame_count = int(audio_duration * fps) + 1
    logger.info(f"Calculated frame count: {frame_count} ({audio_duration:.2f}s x {fps}fps)")

    if "98" in workflow:
        workflow["98"]["inputs"]["image"] = "input_image.png"
    if "92:3" in workflow:
        workflow["92:3"]["inputs"]["text"] = params["prompt"]
    if "92:4" in workflow:
        workflow["92:4"]["inputs"]["text"] = params.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
    for node_id in ["92:11", "92:67"]:
        if node_id in workflow:
            workflow[node_id]["inputs"]["noise_seed"] = seed
    if "92:9" in workflow:
        workflow["92:9"]["inputs"]["steps"] = params["steps"]
    if "92:47" in workflow:
        workflow["92:47"]["inputs"]["cfg"] = params["cfg"]
    if "92:114" in workflow:
        workflow["92:114"]["inputs"]["audio"] = "input_audio.mp3"
    if "92:115" in workflow:
        workflow["92:115"]["inputs"]["value"] = float(fps)
    if "92:97" in workflow:
        workflow["92:97"]["inputs"]["fps"] = fps
    if "92:99" in workflow:
        workflow["92:99"]["inputs"]["img_compression"] = params.get("img_compression", 33)
    if "92:107" in workflow:
        workflow["92:107"]["inputs"]["strength"] = params.get("i2v_strength_first", 1.0)
    if "92:108" in workflow:
        workflow["92:108"]["inputs"]["strength"] = params.get("i2v_strength_second", 0.7)
    return workflow

def queue_prompt(workflow: Dict) -> str:
    logger.info("Queueing prompt to ComfyUI...")
    try:
        data = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            f"{COMFYUI_URL}/prompt",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode("utf-8"))
        prompt_id = result.get("prompt_id")
        logger.info(f"Prompt queued with ID: {prompt_id}")
        return prompt_id
    except Exception as e:
        logger.error(f"Failed to queue prompt: {e}")
        raise

def wait_for_completion(prompt_id: str, timeout: int = 600) -> Dict:
    logger.info(f"Waiting for completion (timeout: {timeout}s)...")
    start_time = time.time()
    last_progress = 0
    while time.time() - start_time < timeout:
        try:
            response = urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            history = json.loads(response.read().decode("utf-8"))
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                status = history[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    error_msg = status.get("messages", [["Unknown error"]])[0]
                    logger.error(f"Workflow execution error: {error_msg}")
                    raise RuntimeError(f"Workflow error: {error_msg}")
                if outputs:
                    elapsed = time.time() - start_time
                    logger.info(f"Generation completed in {elapsed:.1f}s")
                    return outputs
            current_time = int(time.time() - start_time)
            if current_time % 10 == 0 and current_time != last_progress:
                logger.info(f"Progress: {current_time}s elapsed...")
                last_progress = current_time
        except urllib.error.URLError as e:
            logger.debug(f"Status check error: {e}")
        except RuntimeError:
            raise
        except Exception as e:
            logger.debug(f"Status check error: {e}")
        time.sleep(1)
    logger.error(f"Generation timed out after {timeout}s")
    raise TimeoutError(f"Generation timed out after {timeout} seconds")

def get_output_video(outputs: Dict) -> Optional[str]:
    logger.info("Extracting output video...")
    for node_id, node_output in outputs.items():
        for key in ["gifs", "videos", "video", "images", "files"]:
            if key in node_output:
                items = node_output[key]
                if not isinstance(items, list):
                    items = [items]
                for item in items:
                    if isinstance(item, dict):
                        filename = item.get("filename")
                        subfolder = item.get("subfolder", "")
                    elif isinstance(item, str):
                        filename = item
                        subfolder = ""
                    else:
                        continue
                    if not filename:
                        continue
                    if subfolder:
                        filepath = f"/comfyui/output/{subfolder}/{filename}"
                    else:
                        filepath = f"/comfyui/output/{filename}"
                    if os.path.exists(filepath):
                        file_size = os.path.getsize(filepath)
                        logger.info(f"Found output video: {filepath} ({file_size} bytes)")
                        with open(filepath, "rb") as f:
                            video_data = base64.b64encode(f.read()).decode("utf-8")
                        return video_data
    output_dir = "/comfyui/output"
    if os.path.exists(output_dir):
        for root, dirs, files in os.walk(output_dir):
            for file in sorted(files, reverse=True):
                if file.endswith(('.mp4', '.webm', '.gif', '.avi', '.mov')):
                    filepath = os.path.join(root, file)
                    file_size = os.path.getsize(filepath)
                    logger.info(f"Found video file: {filepath} ({file_size} bytes)")
                    with open(filepath, "rb") as f:
                        video_data = base64.b64encode(f.read()).decode("utf-8")
                    return video_data
    logger.warning("No output video found in results")
    return None

def handler(job: Dict) -> Dict:
    job_id = job.get("id", "unknown")
    log_section(f"LTX-2 VIDEO GENERATION JOB: {job_id}")
    start_time = time.time()
    try:
        job_input = job.get("input", {})
        if "image" not in job_input:
            return {"error": "Missing required field: image"}
        if "prompt" not in job_input:
            return {"error": "Missing required field: prompt"}

        has_custom_audio = "audio" in job_input and job_input["audio"]
        mode = "custom_audio" if has_custom_audio else "generated_audio"
        logger.info(f"Mode: {mode.upper()}")

        params = {
            "image": job_input["image"],
            "prompt": job_input["prompt"],
            "negative_prompt": job_input.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT),
            "width": job_input.get("width", DEFAULT_PARAMS["width"]),
            "height": job_input.get("height", DEFAULT_PARAMS["height"]),
            "frame_count": job_input.get("frame_count", DEFAULT_PARAMS["frame_count"]),
            "steps": job_input.get("steps", DEFAULT_PARAMS["steps"]),
            "cfg": job_input.get("cfg", DEFAULT_PARAMS["cfg"]),
            "fps": job_input.get("fps", DEFAULT_PARAMS["fps"]),
            "seed": job_input.get("seed", DEFAULT_PARAMS["seed"]),
            "timeout": job_input.get("timeout", DEFAULT_PARAMS["timeout"]),
            "img_compression": job_input.get("img_compression", DEFAULT_PARAMS["img_compression"]),
            "i2v_strength_first": job_input.get("i2v_strength_first", DEFAULT_PARAMS["i2v_strength_first"]),
            "i2v_strength_second": job_input.get("i2v_strength_second", DEFAULT_PARAMS["i2v_strength_second"])
        }

        logger.info("Input parameters:")
        logger.info(f"  Prompt: {params['prompt'][:100]}...")
        logger.info(f"  Steps: {params['steps']}, CFG: {params['cfg']}, FPS: {params['fps']}")
        logger.info(f"  Seed: {params['seed'] or 'random'}")
        logger.info(f"  I2V Strength: first={params['i2v_strength_first']}, second={params['i2v_strength_second']}")

        if not wait_for_comfyui():
            return {"error": "ComfyUI server not available"}

        save_input_image(params["image"])

        audio_duration = None
        if has_custom_audio:
            _, audio_duration = save_input_audio(job_input["audio"])
            workflow = load_workflow("custom_audio")
            workflow = modify_workflow_custom_audio(workflow, params, audio_duration)
        else:
            workflow = load_workflow("generated_audio")
            workflow = modify_workflow_generated_audio(workflow, params)

        prompt_id = queue_prompt(workflow)
        outputs = wait_for_completion(prompt_id, params["timeout"])
        video_data = get_output_video(outputs)

        if not video_data:
            return {"error": "No video output generated"}

        elapsed = time.time() - start_time
        log_section("JOB COMPLETED SUCCESSFULLY")
        logger.info(f"Total time: {elapsed:.1f}s")

        result = {
            "video": video_data,
            "seed": params["seed"],
            "mode": mode,
            "parameters": {
                "prompt": params["prompt"],
                "width": params["width"],
                "height": params["height"],
                "steps": params["steps"],
                "cfg": params["cfg"],
                "fps": params["fps"],
                "img_compression": params["img_compression"],
                "i2v_strength_first": params["i2v_strength_first"],
                "i2v_strength_second": params["i2v_strength_second"]
            },
            "elapsed_time": elapsed
        }
        if audio_duration:
            result["audio_duration"] = audio_duration
            result["parameters"]["frame_count"] = int(audio_duration * params["fps"]) + 1
        else:
            result["parameters"]["frame_count"] = params["frame_count"]
        return result

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Job failed after {elapsed:.1f}s: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": str(e), "traceback": traceback.format_exc(), "elapsed_time": elapsed}

if __name__ == "__main__":
    log_section("LTX-2 VIDEO SERVERLESS HANDLER STARTING")
    logger.info(f"ComfyUI URL: {COMFYUI_URL}")
    logger.info(f"Supported modes: generated_audio, custom_audio")
    runpod.serverless.start({"handler": handler})
