"""
ComfyUI LTX-2 Video Serverless Handler for RunPod
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
# CONFIGURATION - DEFAULTS
# ============================================================================

COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"

# Default values - these match the workflow.json defaults
DEFAULTS = {
    "width": 720,
    "height": 720,
    "frame_count": 97,
    "steps": 20,
    "cfg": 4,
    "fps": 25,
    "seed": None,  # None = random
    "prompt": "A 3D animated scene in a cozy library. The elderly tortoise and young fox sit together in comfortable silence. The tortoise blinks slowly and breathes gently. The fox's ears twitch slightly, tail sways softly. No talking, no dialogue, both mouths stay closed. Warm firelight flickers in the background. The camera remains static.",
    "negative_prompt": "blurry, low quality, still frame, frames, watermark, overlay, titles, has blurbox, has subtitles",
    "timeout": 600
}

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
    """Modify workflow with dynamic parameters, using defaults for missing values"""
    logger.info("Modifying workflow parameters...")
    
    # Generate random seed if not provided
    seed = params.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**32 - 1)
        logger.info(f"  Generated random seed: {seed}")
    params["seed"] = seed
    
    # Node 98: LoadImage - set input image filename
    if "98" in workflow:
        workflow["98"]["inputs"]["image"] = "input_image.png"
        logger.debug("  Updated node 98 (LoadImage)")
    
    # Node 102: ResizeImageMaskNode - width and height
    if "102" in workflow:
        workflow["102"]["inputs"]["resize_type.width"] = params.get("width", DEFAULTS["width"])
        workflow["102"]["inputs"]["resize_type.height"] = params.get("height", DEFAULTS["height"])
        logger.debug(f"  Updated node 102 (Resize): {params.get('width', DEFAULTS['width'])}x{params.get('height', DEFAULTS['height'])}")
    
    # Node 92:3: Positive prompt (CLIPTextEncode)
    if "92:3" in workflow:
        workflow["92:3"]["inputs"]["text"] = params.get("prompt", DEFAULTS["prompt"])
        logger.debug("  Updated node 92:3 (Positive prompt)")
    
    # Node 92:4: Negative prompt (CLIPTextEncode)
    if "92:4" in workflow:
        workflow["92:4"]["inputs"]["text"] = params.get("negative_prompt", DEFAULTS["negative_prompt"])
        logger.debug("  Updated node 92:4 (Negative prompt)")
    
    # Node 92:11: RandomNoise - seed for first stage
    if "92:11" in workflow:
        workflow["92:11"]["inputs"]["noise_seed"] = seed
        logger.debug(f"  Updated node 92:11 (Noise seed stage 1): {seed}")
    
    # Node 92:67: RandomNoise - seed for second stage
    if "92:67" in workflow:
        workflow["92:67"]["inputs"]["noise_seed"] = seed + 1  # Different seed for stage 2
        logger.debug(f"  Updated node 92:67 (Noise seed stage 2): {seed + 1}")
    
    # Node 92:62: PrimitiveInt - frame count (Length)
    if "92:62" in workflow:
        workflow["92:62"]["inputs"]["value"] = params.get("frame_count", DEFAULTS["frame_count"])
        logger.debug(f"  Updated node 92:62 (Frame count): {params.get('frame_count', DEFAULTS['frame_count'])}")
    
    # Node 92:9: LTXVScheduler - steps
    if "92:9" in workflow:
        workflow["92:9"]["inputs"]["steps"] = params.get("steps", DEFAULTS["steps"])
        logger.debug(f"  Updated node 92:9 (Steps): {params.get('steps', DEFAULTS['steps'])}")
    
    # Node 92:47: CFGGuider - cfg scale (stage 1)
    if "92:47" in workflow:
        workflow["92:47"]["inputs"]["cfg"] = params.get("cfg", DEFAULTS["cfg"])
        logger.debug(f"  Updated node 92:47 (CFG stage 1): {params.get('cfg', DEFAULTS['cfg'])}")
    
    # Node 92:22: LTXVConditioning - frame_rate
    if "92:22" in workflow:
        workflow["92:22"]["inputs"]["frame_rate"] = params.get("fps", DEFAULTS["fps"])
        logger.debug(f"  Updated node 92:22 (Conditioning frame_rate): {params.get('fps', DEFAULTS['fps'])}")
    
    # Node 92:51: LTXVEmptyLatentAudio - frame_rate
    if "92:51" in workflow:
        workflow["92:51"]["inputs"]["frame_rate"] = params.get("fps", DEFAULTS["fps"])
        logger.debug(f"  Updated node 92:51 (Audio frame_rate): {params.get('fps', DEFAULTS['fps'])}")
    
    # Node 92:97: CreateVideo - fps
    if "92:97" in workflow:
        workflow["92:97"]["inputs"]["fps"] = params.get("fps", DEFAULTS["fps"])
        logger.debug(f"  Updated node 92:97 (Output fps): {params.get('fps', DEFAULTS['fps'])}")
    
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
        # Check for 'videos' key (SaveVideo node)
        if "videos" in node_output:
            for video in node_output["videos"]:
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
        
        # Check for 'gifs' key (VHS_VideoCombine node)
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
    """
    Main handler function for RunPod serverless
    
    Expected input format:
    {
        "input": {
            "image": "<base64_encoded_image>",  # REQUIRED
            "prompt": "Description of motion/action",  # Optional, has default
            "negative_prompt": "What to avoid",  # Optional, has default
            "width": 720,  # Optional, default 720
            "height": 720,  # Optional, default 720
            "frame_count": 97,  # Optional, default 97
            "steps": 20,  # Optional, default 20
            "cfg": 4,  # Optional, default 4
            "fps": 25,  # Optional, default 25
            "seed": null,  # Optional, null = random
            "timeout": 600  # Optional, default 600
        }
    }
    """
    job_id = job.get("id", "unknown")
    log_section(f"LTX-2 VIDEO GENERATION JOB: {job_id}")
    
    start_time = time.time()
    
    try:
        job_input = job.get("input", {})
        
        # Validate required field
        if "image" not in job_input:
            logger.error("Missing required field: image")
            return {"error": "Missing required field: image"}
        
        # Build params with defaults
        params = {
            "image": job_input["image"],
            "prompt": job_input.get("prompt", DEFAULTS["prompt"]),
            "negative_prompt": job_input.get("negative_prompt", DEFAULTS["negative_prompt"]),
            "width": job_input.get("width", DEFAULTS["width"]),
            "height": job_input.get("height", DEFAULTS["height"]),
            "frame_count": job_input.get("frame_count", DEFAULTS["frame_count"]),
            "steps": job_input.get("steps", DEFAULTS["steps"]),
            "cfg": job_input.get("cfg", DEFAULTS["cfg"]),
            "fps": job_input.get("fps", DEFAULTS["fps"]),
            "seed": job_input.get("seed", DEFAULTS["seed"]),
            "timeout": job_input.get("timeout", DEFAULTS["timeout"])
        }
        
        # Log parameters
        logger.info("Input parameters:")
        prompt_display = params['prompt'][:80] + "..." if len(params['prompt']) > 80 else params['prompt']
        logger.info(f"  Prompt: {prompt_display}")
        logger.info(f"  Negative: {params['negative_prompt'][:50]}...")
        logger.info(f"  Size: {params['width']}x{params['height']}")
        logger.info(f"  Frames: {params['frame_count']}")
        logger.info(f"  Steps: {params['steps']}")
        logger.info(f"  CFG: {params['cfg']}")
        logger.info(f"  FPS: {params['fps']}")
        logger.info(f"  Seed: {params['seed'] or 'random'}")
        
        # Wait for ComfyUI to be ready
        if not wait_for_comfyui():
            return {"error": "ComfyUI server not available"}
        
        # Save input image
        save_input_image(params["image"])
        
        # Load and modify workflow
        workflow = load_workflow()
        workflow = modify_workflow(workflow, params)
        
        # Queue the prompt
        prompt_id = queue_prompt(workflow)
        
        # Wait for completion
        outputs = wait_for_completion(prompt_id, params["timeout"])
        
        # Get output video
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
                "negative_prompt": params["negative_prompt"],
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
    logger.info("Default parameters:")
    for key, value in DEFAULTS.items():
        if key == "prompt":
            logger.info(f"  {key}: {value[:50]}...")
        elif key == "negative_prompt":
            logger.info(f"  {key}: {value[:50]}...")
        else:
            logger.info(f"  {key}: {value}")
    
    log_separator()
    logger.info("Starting RunPod serverless handler...")
    runpod.serverless.start({"handler": handler})
