import sys
import os
import json
import urllib.request
import urllib.error
import tarfile
import hashlib
import tempfile
import time

import ssl

ctx = ssl._create_unverified_context()

def pull_image(image_tag: str, output_tar: str):
    if ":" in image_tag:
        repo, tag = image_tag.split(":", 1)
    else:
        repo, tag = image_tag, "latest"

    if "/" not in repo:
        repo_path = f"library/{repo}"
    else:
        repo_path = repo

    print(f"[*] Resolving auth token for {repo_path}...")
    token_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo_path}:pull"
    req = urllib.request.Request(token_url, headers={"User-Agent": "Docker-Client/20.10.0"})
    with urllib.request.urlopen(req, context=ctx) as resp:
        token = json.loads(resp.read().decode())["token"]

    auth_header = {"Authorization": f"Bearer {token}", "User-Agent": "Docker-Client/20.10.0"}

    print(f"[*] Fetching manifest for {repo_path}:{tag}...")
    manifest_url = f"https://registry-1.docker.io/v2/{repo_path}/manifests/{tag}"
    accept_headers = [
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.index.v1+json"
    ]
    req = urllib.request.Request(manifest_url, headers={**auth_header, "Accept": ", ".join(accept_headers)})
    with urllib.request.urlopen(req, context=ctx) as resp:
        manifest_data = json.loads(resp.read().decode())

    # If manifest list / index, find linux/amd64
    if "manifests" in manifest_data:
        target = None
        for m in manifest_data["manifests"]:
            platform = m.get("platform", {})
            if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
                target = m
                break
        if not target:
            raise RuntimeError("No linux/amd64 manifest found")
        digest = target["digest"]
        print(f"[*] Found linux/amd64 manifest digest: {digest}")
        req = urllib.request.Request(
            f"https://registry-1.docker.io/v2/{repo_path}/manifests/{digest}",
            headers={**auth_header, "Accept": "application/vnd.docker.distribution.manifest.v2+json"}
        )
        with urllib.request.urlopen(req, context=ctx) as resp:
            manifest_data = json.loads(resp.read().decode())

    config_digest = manifest_data["config"]["digest"]
    layers = manifest_data["layers"]
    print(f"[*] Image has {len(layers)} layers. Downloading config {config_digest[:16]}...")

    work_dir = tempfile.mkdtemp(prefix="docker_pull_")
    try:
        # Download config
        config_hash = config_digest.split(":")[-1]
        config_path = os.path.join(work_dir, f"{config_hash}.json")
        blob_url = f"https://registry-1.docker.io/v2/{repo_path}/blobs/{config_digest}"
        req = urllib.request.Request(blob_url, headers=auth_header)
        with urllib.request.urlopen(req, context=ctx) as resp, open(config_path, "wb") as f:
            f.write(resp.read())

        layer_tar_paths = []
        for i, layer in enumerate(layers):
            digest = layer["digest"]
            layer_hash = digest.split(":")[-1]
            layer_dir = os.path.join(work_dir, layer_hash)
            os.makedirs(layer_dir, exist_ok=True)
            layer_tar = os.path.join(layer_dir, "layer.tar")
            
            print(f"[{i+1}/{len(layers)}] Downloading layer {layer_hash[:12]} ({layer.get('size', 0) // 1024} KB)...")
            blob_url = f"https://registry-1.docker.io/v2/{repo_path}/blobs/{digest}"
            req = urllib.request.Request(blob_url, headers=auth_header)
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp, open(layer_tar, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f"    Retry {attempt+1} due to {e}...")
                    time.sleep(2)
            layer_tar_paths.append(f"{layer_hash}/layer.tar")

        manifest_entry = [
            {
                "Config": f"{config_hash}.json",
                "RepoTags": [image_tag],
                "Layers": layer_tar_paths
            }
        ]
        with open(os.path.join(work_dir, "manifest.json"), "w") as f:
            json.dump(manifest_entry, f)

        print(f"[*] Packaging into {output_tar}...")
        with tarfile.open(output_tar, "w") as tar:
            tar.add(os.path.join(work_dir, "manifest.json"), arcname="manifest.json")
            tar.add(config_path, arcname=f"{config_hash}.json")
            for rel in layer_tar_paths:
                full = os.path.join(work_dir, rel)
                tar.add(full, arcname=rel)

        print(f"[+] Successfully saved {image_tag} to {output_tar}!")
    finally:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python pull_image.py <image:tag> <output.tar>")
        sys.exit(1)
    pull_image(sys.argv[1], sys.argv[2])
