# stable-diffusion.cpp server API (reference for this skill)

Base: `{sdcpp_url}` (default `http://127.0.0.1:7861`; docker: `http://host.docker.internal:7861`).

| Tool | HTTP | Body / notes |
|---|---|---|
| sdcpp_edit_image | POST /sdcpp/v1/img_gen | `prompt`, `negative_prompt`, `width`, `height`, `seed`, `ref_images: [dataURL]` (the app fills it from the attached image), `sample_params{sample_steps, sample_method, scheduler, guidance{txt_cfg, distilled_guidance}}` |
| sdcpp_img2img | POST /sdcpp/v1/img_gen | same, but `init_image: dataURL` + `strength` |
| sdcpp_status | GET /sdcpp/v1/capabilities | `model{name,path}`, `features{ref_images, init_image, mask_image, ...}`, `limits`, `samplers`, `schedulers`, `loras` |

`img_gen` answers immediately with `{id, status: "queued", poll_url}`; the app polls `GET /sdcpp/v1/jobs/{id}` every 2 s until `status` is `completed` (result: `{images: [{b64_json}], output_format}`) or `failed`, saves the image into the app's image folder and shows it in the chat like a generated image. `POST /sdcpp/v1/jobs/{id}/cancel` cancels a queued job.

Editing models (Qwen-Image-Edit, FLUX Kontext, …) take the source picture as `ref_images`; plain SD checkpoints ignore it and need `init_image` + `strength` (img2img) instead.
