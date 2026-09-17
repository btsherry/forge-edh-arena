#!/usr/bin/env python3
"""ship-release-s3.py — upload a built forge-light-llm tarball to the public Cloudflare R2 bucket over the
S3 API and verify it. The sibling ship-release.sh uses the Cloudflare REST API, which (like wrangler) stops
at 300 MiB; a tarball with the voices bundled is ~480 MiB (v4.2 Experimental, 2026-09-17), so it ships here:
multipart upload, then the public object is downloaded back and compared by sha256.

Usage:  forge-arena/packaging/ship-release-s3.py <tarball> <dated-key> [--latest]
  e.g.  forge-arena/packaging/ship-release-s3.py ~/Claude/personal/forge-light-llm-20260917.tar.gz forge-light-llm-20260917.tar.gz
  --latest   also point forge-light-llm-latest.tar.gz at the same bytes (server-side copy). Ben's naming rule:
             the DATED object is the version and is never overwritten; -latest is the alias.

Credentials: ~/Claude/hello/cloudflare-hello — line 1 the account id, line 3 an R2 S3 Access Key ID, line 4 its
Secret Access Key (an Account API token with Object Read & Write on the bucket). Read into variables only;
never printed, never on a command line, never committed. Needs boto3 (pip install --user boto3)."""
import hashlib
import sys
import urllib.request
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig

BUCKET = "forge-light-llm-dist"
PUB = "https://pub-6a4e610a9fd04c94b51eb95344c3013f.r2.dev"


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--latest"]
    if len(args) != 2:
        print(__doc__); return 2
    tar, key = Path(args[0]), args[1]
    latest = "--latest" in sys.argv
    if not key.startswith("forge-light-llm-") or not key.endswith(".tar.gz"):
        print("ship-s3: key must look like forge-light-llm-YYYYMMDD.tar.gz"); return 1
    if not tar.is_file() or tar.stat().st_size == 0:
        print(f"ship-s3: tarball missing: {tar}"); return 1
    lines = Path.home().joinpath("Claude/hello/cloudflare-hello").read_text().splitlines()
    if len(lines) < 4 or not lines[2].strip() or not lines[3].strip():
        print("ship-s3: credentials file needs the S3 Access Key ID on line 3 and the Secret Access Key on line 4"); return 1
    s3 = boto3.client("s3", endpoint_url=f"https://{lines[0].strip()}.r2.cloudflarestorage.com",
                      aws_access_key_id=lines[2].strip(), aws_secret_access_key=lines[3].strip(), region_name="auto")
    local = hashlib.sha256(tar.read_bytes()).hexdigest()
    print(f"ship-s3: {tar} — {tar.stat().st_size} bytes, sha256 {local}")
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        print(f"ship-s3: {key} already exists in the bucket — dated objects are never overwritten (use a b-suffixed key for a same-day re-cut)")
        return 1
    except s3.exceptions.ClientError:
        pass
    cfg = TransferConfig(multipart_threshold=64 * 1024 * 1024, multipart_chunksize=64 * 1024 * 1024, max_concurrency=4)
    s3.upload_file(str(tar), BUCKET, key, ExtraArgs={"ContentType": "application/gzip"}, Config=cfg)
    print(f"ship-s3: PUT {key} -> done")
    keys = [key]
    if latest:
        s3.copy_object(Bucket=BUCKET, Key="forge-light-llm-latest.tar.gz", CopySource={"Bucket": BUCKET, "Key": key},
                       ContentType="application/gzip", MetadataDirective="REPLACE")
        print("ship-s3: COPY -> forge-light-llm-latest.tar.gz")
        keys.append("forge-light-llm-latest.tar.gz")
    for k in keys:                                          # the public URL, read back whole, like ship-release.sh
        h, n = hashlib.sha256(), 0
        req = urllib.request.Request(f"{PUB}/{k}", headers={"User-Agent": "curl/8"})   # the dev URL 403s python's default agent
        with urllib.request.urlopen(req, timeout=900) as r:
            while chunk := r.read(8 * 1024 * 1024):
                h.update(chunk); n += len(chunk)
        if h.hexdigest() != local:
            print(f"ship-s3: verify {k} -> MISMATCH remote sha256 {h.hexdigest()} ({n} bytes)"); return 1
        print(f"ship-s3: verify {k} -> byte-exact ({n} bytes)")
    print("ship-s3: done — " + " and ".join(f"{PUB}/{k}" for k in keys))
    return 0


if __name__ == "__main__":
    sys.exit(main())
