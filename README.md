# ComfyUI LTX-2 Video Serverless Endpoint

Docker image for image-to-video generation using LTX-2 model via RunPod serverless.

## Docker Image
`sirdrafton/comfyui-ltx2-serverless:latest`

## API Usage
```json
{
  "input": {
    "image": "<base64_encoded_image>",
    "prompt": "Description of motion/action",
    "width": 720,
    "height": 720,
    "frame_count": 97,
    "steps": 4,
    "cfg": 1.0,
    "fps": 24,
    "seed": null
  }
}
```
