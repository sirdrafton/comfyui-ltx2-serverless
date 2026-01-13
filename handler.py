"""
ComfyUI LTX-2 Video Serverless Handler for RunPod
"""

import runpod
import json
import urllib.request
import urllib.parse
import base64
import time
import os
import sys
import logging
import traceback
from datetime import datetime
from typing import Optional, Dict, Any
import random

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    blue = "\x1b[34;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    green = "\x1b[32;20m"
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

# ============================================================================
# CONFIGURATION
# ============================================================================

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"

DEFAULT_PARAMS = {
    "width": 720,
    "height": 720,
    "frame_count": 97,
    "steps": 4,
    "cfg": 1.0,
    "fps": 24,
    "seed": None,
    "timeout": 600
}

DEFAULT_NEGATIVE_PROMPT = "blurry, low quality, distorted, extra limbs, bad anatomy, watermark, text, deformed"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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
                logger.info("✓ ComfyUI server is ready!")
                return True
        except Exception as e:
            logger.debug(f"Waiting... ({e})")
        time.sleep(2)
    
    logger.error(f"✗ ComfyUI server did not start within {timeout} seconds")
    return False

def save_input_image(image_data: str, filename: str = "input_image.png") -> str:
    logger.info("Saving input image...")
    
    try:
        if "base64," in image_data:
            image_data = image_data.split("base64,")[1]
        
        image_bytes = base64.b64decode(image_data)
        filepath = f"/comfyui/input/{filename}"
        
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        
        logger.info(f"✓ Saved input image to {filepath}")
        return filepath
        
    except Exception as e:
        logger.error(f"✗ Failed to save input image: {e}")
        raise

def load_workflow(workflow_path: str = "/workflow.json") -> Dict:
    logger.info(f"Loading workflow from {workflow_path}...")
    
    try:
        with open(workflow_path, "r") as f:
            workflow = json.load(f)
        logger.info("✓ Workflow loaded successfully")
        return workflow
    except Exception as e:
        logger.error(f"✗ Failed to load workflow: {e}")
        raise

def modify_workflow(workflow: Dict, params: Dict) -> Dict:
    logger.info("Modifying workflow parameters...")
    
    seed = params.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**32 - 1)
        logger.info(f"  Generated random seed: {seed}")
        params["seed"] = seed
    
    # Update Load Image node
    if "1" in workflow:
        workflow["1"]["inputs"]["image"] = "input_image.png"
    
    # Update Resize node
    if "2" in workflow:
        workflow["2"]["inputs"]["width"] = params["width"]
        workflow["2"]["inputs"]["height"] = params["height"]
    
    # Update Text to Video node
    if "4" in workflow:
        workflow["4"]["inputs"]["prompt"] = params["prompt"]
        workflow["4"]["inputs"]["negative_prompt"] = params.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
    
    # Update LTX I2V node
    if "5" in workflow:
        workflow["5"]["inputs"]["frame_count"] = params["frame_count"]
        workflow["5"]["inputs"]["noise_seed"] = seed
        workflow["5"]["inputs"]["steps"] = params["steps"]
        workflow["5"]["inputs"]["cfg"] = params["cfg"]
    
    # Update Save Video node
    if "6" in workflow:
        workflow["6"]["inputs"]["frame_rate"] = params["fps"]
    
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
        
        logger.info(f"✓ Prompt queued with ID: {prompt_id}")
        return prompt_id
        
    except Exception as e:
        logger.error(f"✗ Failed to queue prompt: {e}")
        raise

def wait_for_completion(prompt_id: str, timeout: int = 600) -> Dict:
    logger.info(f"Waiting for completion (timeout: {timeout}s)...")
    
    start_time = time.time()
    last_progress = 0
    
    while time.time() - start_time < timeout:
        try:
            response = urllib.request.urlopen(
                f"{COMFYUI_URL}/history/{prompt_id}",
                timeout=10
            )
            history = json.loads(response.read().decode("utf-8"))
            
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                if outputs:
                    elapsed = time.time() - start_time
                    logger.info(f"✓ Generation completed in {elapsed:.1f}s")
                    return outputs
            
            current_time = int(time.time() - start_time)
            if current_time % 10 == 0 and current_time != last_progress:
                logger.info(f"  Progress: {current_time}s elapsed...")
                last_progress = current_time
            
        except Exception as e:
            logger.debug(f"Status check error: {e}")
        
        time.sleep(1)
    
    logger.error(f"✗ Generation timed out after {timeout}s")
    raise TimeoutError(f"Generation timed out after {timeout} seconds")

def get_output_video(outputs: Dict) -> Optional[str]:
    logger.info("Extracting output video...")
    
    for node_id, node_output in outputs.items():
        if "gifs" in node_output:
            for video in node_output["gifs"]:
                filename = video.get("filename")
                subfolder = video.get("subfolder", "")
                
                if subfolder:
                    filepath = f"/comfyui/output/{subfolder}/{filename}"
                else:
                    filepath = f"/comfyui/output/{filename}"
                
                if os.path.exists(filepath):
                    logger.info(f"✓ Found output video: {filepath}")
                    
                    with open(filepath, "rb") as f:
                        video_data = base64.b64encode(f.read()).decode("utf-8")
                    
                    return video_data
    
    logger.warning("✗ No output video found in results")
    return None

# ============================================================================
# MAIN HANDLER
# ============================================================================

def handler(job: Dict) -> Dict:
    job_id = job.get("id", "unknown")
    log_section(f"LTX-2 VIDEO GENERATION JOB: {job_id}")
    
    start_time = time.time()
    
    try:
        job_input = job.get("input", {})
        
        if "image" not in job_input:
            logger.error("Missing required field: image")
            return {"error": "Missing required field: image"}
        
        if "prompt" not in job_input:
            logger.error("Missing required field: prompt")
            return {"error": "Missing required field: prompt"}
        
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
            "timeout": job_input.get("timeout", DEFAULT_PARAMS["timeout"])
        }
        
        logger.info("Input parameters:")
        logger.info(f"  Prompt: {params['prompt'][:100]}..." if len(params['prompt']) > 100 else f"  Prompt: {params['prompt']}")
        logger.info(f"  Size: {params['width']}x{params['height']}")
        logger.info(f"  Frames: {params['frame_count']}")
        logger.info(f"  Steps: {params['steps']}")
        logger.info(f"  CFG: {params['cfg']}")
        logger.info(f"  FPS: {params['fps']}")
        logger.info(f"  Seed: {params['seed'] or 'random'}")
        
        if not wait_for_comfyui():
            return {"error": "ComfyUI server not available"}
        
        save_input_image(params["image"])
        
        workflow = load_workflow()
        workflow = modify_workflow(workflow, params)
        
        prompt_id = queue_prompt(workflow)
        
        outputs = wait_for_completion(prompt_id, params["timeout"])
        
        video_data = get_output_video(outputs)
        
        if not video_data:
            return {"error": "No video output generated"}
        
        elapsed = time.time() - start_time
        log_section("JOB COMPLETED SUCCESSFULLY")
        logger.info(f"Total time: {elapsed:.1f}s")
        
        return {
            "video": video_data,
            "seed": params["seed"],
            "parameters": {
                "prompt": params["prompt"],
                "width": params["width"],
                "height": params["height"],
                "frame_count": params["frame_count"],
                "steps": params["steps"],
                "cfg": params["cfg"],
                "fps": params["fps"]
            },
            "elapsed_time": elapsed
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Job failed after {elapsed:.1f}s")
        logger.error(f"Error: {str(e)}")
        logger.error(traceback.format_exc())
        
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "elapsed_time": elapsed
        }

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    log_section("LTX-2 VIDEO SERVERLESS HANDLER STARTING")
    logger.info(f"ComfyUI URL: {COMFYUI_URL}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Start time: {datetime.now().isoformat()}")
    
    log_separator()
    logger.info("Starting RunPod serverless handler...")
    runpod.serverless.start({"handler": handler})
