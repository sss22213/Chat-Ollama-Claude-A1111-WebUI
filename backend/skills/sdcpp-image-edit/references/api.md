# stable-diffusion.cpp MCP tools (reference for this skill)

The app calls the MCP server of the stable-diffusion.cpp bridge: `{sd.cpp URL}/mcp` (Settings → Sources → sd.cpp;
default `http://127.0.0.1:7861`, docker: `http://host.docker.internal:7861`).

| Tool | What the server does |
|---|---|
| sdcpp_edit_image | `POST /sdcpp/v1/img_gen` with the source picture as `ref_images` (the app fills `image` from the most recent image in the chat), `prompt`, `negative_prompt`, `width` / `height` (default: the source's aspect ratio, about 1 MP, multiples of 32), `seed`; 20 steps, euler, text CFG 6 |
| sdcpp_img2img | the same with `init_image` + `strength` (default 0.55); 24 steps, euler_a, CFG 6 |
| sdcpp_status | `GET /sdcpp/v1/capabilities` summed up: loaded model, whether it looks like an editing model, features, size limits |

The server waits for the job (progress is shown while it runs) and returns the image; the app saves it into its image
folder and shows it in the chat like a generated image. `<lora:name:weight>` in the prompt becomes sd-server's `lora`
field. If an edit runs on a plain SD checkpoint the result carries a warning that the reference image was most likely
ignored.

Editing models (Qwen-Image-Edit, FLUX Kontext, …) take the source picture as `ref_images`; plain SD checkpoints ignore it
and need `init_image` + `strength` (img2img) instead.
