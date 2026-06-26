# Manga prompt rules (Stable Diffusion)

- Write prompts as comma-separated English danbooru tags, ordered: style/medium → subject count (1girl/1boy) → character identity tags → pose/expression → camera/shot → background → quality tags.
- Black-and-white manga: lead with `monochrome, manga, greyscale` and optionally `screentone`. Color pages: drop those and add palette tags.
- Camera/shot tags that read well: `close-up`, `bust shot`, `cowboy shot`, `full body`, `wide shot`, `from above`, `from below`, `dutch angle`, `over-the-shoulder`.
- Expression tags: `smiling`, `angry`, `surprised`, `crying`, `determined`, `smug`, `blush`.
- Keep one clear subject/action per panel. Avoid cramming multiple beats into one image.
- Quality tail commonly used: `masterpiece, best quality, amazing quality`. Negative commonly: `lowres, bad anatomy, bad hands, worst quality, text, watermark, signature`.
- Avoid asking SD to render readable dialogue text — it produces gibberish. Generate clean art; add real lettering afterward.
- Consistency: the character's identity tags + LoRA + seed must be byte-for-byte identical across panels. Only change pose/expression/camera/background.
