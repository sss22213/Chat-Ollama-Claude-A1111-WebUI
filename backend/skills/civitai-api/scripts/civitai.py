#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://civitai.com/api/v1"
DOWNLOAD_BASE_URL = "https://civitai.com/api/download/models"


def load_env_file(start: Path) -> None:
    candidates = [start / ".env", start.parent / ".env"]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        return


def build_url(path: str, params: dict | None = None) -> str:
    url = f"{BASE_URL}{path}"
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "", False)}
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    return url


def request_json(url: str, token: str | None = None) -> dict:
    headers = {"User-Agent": "openclaw-civitai-skill/1.0", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# civitai baseModel names are exact and case-sensitive ("Illustrious", "SD 1.5");
# these aliases (lower-case) map what people type to them, families to several.
_WAN = ["Wan Video", "Wan Video 14B t2v", "Wan Video 14B i2v 480p", "Wan Video 14B i2v 720p", "Wan Video 1.3B t2v",
        "Wan Video 2.2 T2V-A14B", "Wan Video 2.2 I2V-A14B", "Wan Video 2.2 TI2V-5B"]
_KLEIN = ["Flux.2 Klein 9B", "Flux.2 Klein 9B-base", "Flux.2 Klein 4B", "Flux.2 Klein 4B-base"]
BASE_MODEL_ALIASES = {
    "sd 1.5": ["SD 1.5"], "sd1.5": ["SD 1.5"], "sd15": ["SD 1.5"], "1.5": ["SD 1.5"],
    "sd 1.4": ["SD 1.4"], "sd1.4": ["SD 1.4"],
    "sdxl": ["SDXL 1.0"], "sdxl 1.0": ["SDXL 1.0"], "xl": ["SDXL 1.0"],
    "pony": ["Pony"], "ponyxl": ["Pony"], "pony xl": ["Pony"], "pony diffusion": ["Pony"],
    "illustrious": ["Illustrious"], "illustrious xl": ["Illustrious"], "illustriousxl": ["Illustrious"],
    "illu": ["Illustrious"], "il": ["Illustrious"], "ilxl": ["Illustrious"],
    "noobai": ["NoobAI"], "noob": ["NoobAI"], "noobai xl": ["NoobAI"],
    "flux": ["Flux.1 D"], "flux.1": ["Flux.1 D", "Flux.1 S"], "flux.1 d": ["Flux.1 D"], "flux dev": ["Flux.1 D"],
    "flux.1 s": ["Flux.1 S"], "flux schnell": ["Flux.1 S"],
    "flux.2": ["Flux.2 D"] + _KLEIN, "flux 2": ["Flux.2 D"] + _KLEIN, "flux.2 d": ["Flux.2 D"],
    "klein": _KLEIN, "flux.2 klein": _KLEIN,
    "anima": ["Anima"], "krea": ["Krea 2"], "krea 2": ["Krea 2"],
    "z image": ["ZImageTurbo", "ZImageBase"], "z-image": ["ZImageTurbo", "ZImageBase"], "zimage": ["ZImageTurbo", "ZImageBase"],
    "z image turbo": ["ZImageTurbo"], "z-image turbo": ["ZImageTurbo"], "zit": ["ZImageTurbo"], "zimageturbo": ["ZImageTurbo"],
    "z image base": ["ZImageBase"], "zimagebase": ["ZImageBase"],
    "qwen": ["Qwen", "Qwen 2", "Qwen 2.1"], "qwen image": ["Qwen", "Qwen 2", "Qwen 2.1"],
    "wan": _WAN, "wan video": _WAN, "wan 2.2": [w for w in _WAN if "2.2" in w],
    "ltxv": ["LTXV", "LTXV2", "LTXV 2.3", "LTXV 2.5"], "ltx": ["LTXV", "LTXV2", "LTXV 2.3", "LTXV 2.5"],
    "hunyuan": ["Hunyuan Video"], "chroma": ["Chroma"], "hidream": ["HiDream"], "lumina": ["Lumina"],
    "ernie": ["Ernie"], "minimax": ["MiniMax H3"], "other": ["Other"],
}


def normalize_base_models(values) -> list:
    """['illustrious', 'SD1.5,pony'] -> ['Illustrious', 'SD 1.5', 'Pony']; unknown names pass through."""
    out = []
    for raw in values or []:
        for part in str(raw).split(","):
            key = part.strip()
            if not key:
                continue
            low = re.sub(r"\s+", " ", key.lower())
            names = BASE_MODEL_ALIASES.get(low) or BASE_MODEL_ALIASES.get(low.replace(" ", "")) or [key]
            out.extend(n for n in names if n not in out)
    return out


def _matches_base(model: dict, base_models: list) -> bool:
    return any(v.get("baseModel") in base_models for v in model.get("modelVersions") or [])


def cmd_models(args, token):
    base_models = normalize_base_models(args.base_model)
    params = {
        "query": args.query,
        "limit": args.limit,
        "page": args.page,
        "cursor": args.cursor,
        "types": args.types,
        "sort": args.sort,
        "period": args.period,
        "username": args.username,
        "tag": args.tag,
        "baseModels": base_models or None,
        "nsfw": str(args.nsfw).lower() if args.nsfw is not None else None,
    }
    data = request_json(build_url("/models", params), token)
    items = data.get("items") or []
    extra = []
    if base_models and args.query and not args.cursor and len(items) < args.limit:
        # civitai's text search combined with baseModels misses many models: also search the
        # text alone and with the base model name added, keeping models that have a version
        # for one of the wanted base models
        seen = {m.get("id") for m in items}
        queries = [args.query] + [f"{args.query} {bm}" for bm in base_models[:3]]
        for q in queries:
            p = {**params, "baseModels": None, "query": q, "limit": 100, "page": None}
            for m in request_json(build_url("/models", p), token).get("items") or []:
                if m.get("id") not in seen and _matches_base(m, base_models):
                    seen.add(m.get("id"))
                    extra.append(m)
            if len(items) + len(extra) >= args.limit:
                break
        if extra:
            data["items"] = (items + extra)[: args.limit]
            data["metadata"] = {}  # the cursor of the first query does not cover the merged list
    data["_query"] = {"base_models": base_models, "text_search_fallback": bool(extra)}
    print_json(data)


def cmd_model(args, token):
    print_json(request_json(build_url(f"/models/{args.model_id}"), token))


def cmd_version(args, token):
    print_json(request_json(build_url(f"/model-versions/{args.version_id}"), token))


def cmd_hash(args, token):
    print_json(request_json(build_url(f"/model-versions/by-hash/{args.hash_value}"), token))


def cmd_creators(args, token):
    params = {"query": args.query, "limit": args.limit, "page": args.page, "cursor": args.cursor}
    print_json(request_json(build_url("/creators", params), token))


def cmd_tags(args, token):
    params = {"query": args.query, "limit": args.limit, "page": args.page, "cursor": args.cursor}
    print_json(request_json(build_url("/tags", params), token))


def parse_model_ref(ref) -> tuple:
    """'12345' or a civitai page URL (…/models/12345/name?modelVersionId=678) -> (model_id, version_id)."""
    ref = str(ref or "").strip()
    if not ref:
        return None, None
    if ref.isdigit():
        return int(ref), None
    m = re.search(r"/models/(\d+)", ref)
    v = re.search(r"modelVersionId=(\d+)", ref)
    return (int(m.group(1)) if m else None), (int(v.group(1)) if v else None)


def _nsfw_param(value):
    if value is None:
        return None
    return value.lower() if value.lower() in ("true", "false") else value


def cmd_images(args, token):
    model_id, version_id = args.model_id, args.model_version_id
    if args.model:
        mid, vid = parse_model_ref(args.model)
        if mid is None and vid is None:
            raise ValueError(f"--model must be a civitai model id or model page URL, got {args.model!r}")
        model_id, version_id = model_id or mid, version_id or vid
    if not any((args.post_id, args.image_id, model_id, version_id, args.username)):
        raise ValueError("give at least one of --username, --model / --model-id / --model-version-id, --post-id, --image-id")
    params = {
        "postId": args.post_id,
        "imageId": args.image_id,
        "modelVersionId": version_id,
        "modelId": None if version_id else model_id,
        "username": args.username,
        "limit": args.limit,
        "page": args.page,
        "cursor": args.cursor,
        "sort": args.sort,
        "period": args.period,
        "nsfw": _nsfw_param(args.nsfw),
        # without withMeta the API leaves out prompt / sampler / seed / resources
        "withMeta": "false" if args.no_meta else "true",
    }
    data = request_json(build_url("/images", params), token)
    model_name = None
    if version_id:
        v = request_json(build_url(f"/model-versions/{version_id}"), token)
        model_name = f"{(v.get('model') or {}).get('name') or '?'} / {v.get('name') or version_id}"
        model_id = model_id or v.get("modelId")
    elif model_id:
        m = request_json(build_url(f"/models/{model_id}"), token)
        model_name = m.get("name")
        if not data.get("items") and not args.cursor:
            # the modelId filter returns nothing for some models; ask per version instead
            items = []
            for v in (m.get("modelVersions") or [])[:8]:
                p = {**params, "modelId": None, "modelVersionId": v.get("id")}
                items += request_json(build_url("/images", p), token).get("items") or []
                if len(items) >= args.limit:
                    break
            data = {"items": items[: args.limit], "metadata": {}}
    data["_query"] = {
        "username": args.username,
        "model_id": model_id,
        "model_version_id": version_id,
        "model_name": model_name,
        "sort": args.sort,
        "period": args.period,
        "nsfw": args.nsfw,
    }
    print_json(data)


def cmd_download(args, token):
    params = {}
    if args.type:
        params["type"] = args.type
    if args.format:
        params["format"] = args.format
    if args.size:
        params["size"] = args.size
    if args.fp:
        params["fp"] = args.fp
    if token:
        params["token"] = token
    url = f"{DOWNLOAD_BASE_URL}/{args.version_id}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    print(url)


def main():
    script_dir = Path(__file__).resolve().parent
    load_env_file(script_dir)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Query the Civitai public REST API.")
    parser.add_argument("--token", default=os.getenv("CIVITAI_API_KEY"), help="Civitai API token. Defaults to CIVITAI_API_KEY from .env or the environment.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("models", help="Search or list models")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--page", type=int)
    p.add_argument("--cursor")
    p.add_argument("--types")
    p.add_argument("--sort")
    p.add_argument("--period")
    p.add_argument("--username")
    p.add_argument("--tag")
    p.add_argument("--base-model", action="append",
                   help="Base model(s), repeatable or comma-separated: 'SD 1.5', 'SDXL 1.0', Pony, Illustrious, NoobAI, 'Flux.1 D', ... (aliases like sd1.5 / illu / noob work)")
    p.add_argument("--nsfw", choices=["true", "false"])
    p.set_defaults(func=cmd_models)

    p = subparsers.add_parser("model", help="Get one model by id")
    p.add_argument("model_id", type=int)
    p.set_defaults(func=cmd_model)

    p = subparsers.add_parser("version", help="Get one model version by id")
    p.add_argument("version_id", type=int)
    p.set_defaults(func=cmd_version)

    p = subparsers.add_parser("by-hash", help="Get one model version by file hash")
    p.add_argument("hash_value")
    p.set_defaults(func=cmd_hash)

    p = subparsers.add_parser("creators", help="Search or list creators")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--page", type=int)
    p.add_argument("--cursor")
    p.set_defaults(func=cmd_creators)

    p = subparsers.add_parser("tags", help="Search or list tags")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--page", type=int)
    p.add_argument("--cursor")
    p.set_defaults(func=cmd_tags)

    p = subparsers.add_parser("images", help="Search or list images (with their generation data)")
    p.add_argument("--post-id", type=int)
    p.add_argument("--image-id", type=int)
    p.add_argument("--model", help="civitai model id or model page URL (may carry ?modelVersionId=)")
    p.add_argument("--model-id", type=int)
    p.add_argument("--model-version-id", type=int)
    p.add_argument("--username")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--page", type=int)
    p.add_argument("--cursor")
    p.add_argument("--sort", help="Most Reactions | Most Comments | Most Collected | Newest | Oldest")
    p.add_argument("--period", help="AllTime | Year | Month | Week | Day")
    p.add_argument("--nsfw", choices=["None", "Soft", "Mature", "X", "true", "false"],
                   help="Highest NSFW level to include (default: SFW only)")
    p.add_argument("--no-meta", action="store_true", help="Leave out the generation data")
    p.set_defaults(func=cmd_images)

    p = subparsers.add_parser("download-url", help="Build an authenticated model download URL for a model version")
    p.add_argument("version_id", type=int)
    p.add_argument("--type")
    p.add_argument("--format")
    p.add_argument("--size")
    p.add_argument("--fp")
    p.set_defaults(func=cmd_download)

    args = parser.parse_args()
    try:
        args.func(args, args.token)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
