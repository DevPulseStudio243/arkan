const { app, BrowserWindow, shell, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const child_process = require('child_process');

// Root directory of the ARKAN project (parent of electron-app/)
const ROOT_DIR = path.join(__dirname, '..');

let mainWindow = null;
let pyProc = null;
let nuextractProc = null;

// Log file configuration with automatic rotation (> 10MB)
const logPath = path.join(__dirname, 'backend.log');
try {
    if (fs.existsSync(logPath) && fs.statSync(logPath).size > 10 * 1024 * 1024) {
        const oldLog = path.join(__dirname, 'backend.log.old');
        if (fs.existsSync(oldLog)) fs.unlinkSync(oldLog);
        fs.renameSync(logPath, oldLog);
    }
} catch(e) {}
const logStream = fs.createWriteStream(logPath, { flags: 'a' });

function log(msg) {
    const formatted = `[${new Date().toISOString()}] ${msg}\n`;
    // Filter repetitive polling spam from terminal to prevent console freeze
    const isPolling = msg.includes('/api/dots/') || msg.includes('/api/training/') || msg.includes('/api/share/');
    if (!isPolling) {
        console.log(formatted.trim());
    }
    try {
        logStream.write(formatted);
    } catch(e) {}
}

function getPythonPath() {
    const venvPaths = [
        path.join(__dirname, '..', 'venv', 'Scripts', 'python.exe'),
        path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
    ];
    for (const venvPath of venvPaths) {
        try {
            if (fs.existsSync(venvPath)) {
                // Test python version AND essential modules (fastapi, uvicorn)
                child_process.execSync(`"${venvPath}" -c "import sys, fastapi, uvicorn; sys.exit(0)"`, { stdio: 'ignore' });
                log(`Using local virtual environment python: ${venvPath}`);
                return venvPath;
            }
        } catch (e) {
            log(`Venv python at ${venvPath} failed validation (missing modules or corrupted): ${e.message}`);
        }
    }
    log("Warning: Using system default python binary");
    return 'python';
}

function startBackend() {
    const pythonBin = getPythonPath();
    const cwd = path.join(__dirname, '..');
    
    log(`Spawning backend: "${pythonBin}" -m uvicorn api_enhanced:app --host 127.0.0.1 --port 8000`);
    
    try {
        child_process.execSync('powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"', { stdio: 'ignore' });
    } catch(e) {}

    const uvicornArgs = ['-m', 'uvicorn', 'api_enhanced:app', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'info', '--no-access-log'];
    if (process.env.ARKAN_DEV === '1') {
        uvicornArgs.push('--reload');
    }
    pyProc = child_process.spawn(pythonBin, uvicornArgs, {
        cwd: cwd,
        env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' }
    });
    
    pyProc.stdout.on('data', (data) => {
        log(`[BACKEND STDOUT] ${data.toString().trim()}`);
    });
    
    pyProc.stderr.on('data', (data) => {
        log(`[BACKEND STDERR] ${data.toString().trim()}`);
    });
    
    pyProc.on('close', (code) => {
        log(`Backend process closed with exit code ${code}`);
    });
}

function stopBackend() {
    if (pyProc) {
        log(`Stopping backend process (PID: ${pyProc.pid})...`);
        try {
            child_process.execSync(`taskkill /pid ${pyProc.pid} /T /F`, { stdio: 'ignore' });
            log("Backend process tree terminated successfully.");
        } catch (e) {
            try { pyProc.kill(); } catch(err) {}
        }
        pyProc = null;
    }
}

function getNuExtractServer() {
    const localAppData = process.env.LOCALAPPDATA || '';
    const programFiles = process.env.ProgramFiles || 'C:\\Program Files';
    const possiblePaths = [
        path.join(localAppData, 'Programs', 'Ollama', 'lib', 'ollama', 'llama-server.exe'),
        path.join(programFiles, 'Ollama', 'lib', 'ollama', 'llama-server.exe'),
        'C:\\Program Files\\Ollama\\lib\\ollama\\llama-server.exe'
    ];
    for (const p of possiblePaths) {
        if (p && fs.existsSync(p)) return p;
    }
    return null;
}

function checkNuExtract(callback) {
    const req = http.get('http://127.0.0.1:11435/health', (res) => {
        callback(res.statusCode === 200);
    });
    req.on('error', () => callback(false));
    req.setTimeout(1500, () => {
        req.destroy();
        callback(false);
    });
}

function startNuExtract() {
    checkNuExtract((isRunning) => {
        if (isRunning) {
            log("NuExtract-3 server is already active on http://127.0.0.1:11435");
            return;
        }
        const serverBin = getNuExtractServer();
        const modelPath = path.join(__dirname, '..', 'models', 'nuextract3', 'NuExtract3-Q4_K_M.gguf');
        if (!serverBin || !fs.existsSync(modelPath)) {
            log(`[NuExtract] Missing binary or model: bin=${serverBin}, model=${modelPath}`);
            return;
        }
        log(`Spawning NuExtract-3 server: "${serverBin}" --model "${modelPath}" --port 11435 -c 8192 -np 1 --threads 6 --no-webui`);
        try {
            nuextractProc = child_process.spawn(serverBin, [
                '--model', modelPath,
                '--port', '11435',
                '-c', '8192',
                '-np', '1',
                '--threads', '6',
                '--no-webui'
            ], {
                windowsHide: true,
                detached: false
            });
            nuextractProc.on('close', (code) => {
                log(`NuExtract-3 process closed with exit code ${code}`);
                nuextractProc = null;
            });
        } catch (err) {
            log(`Failed to spawn NuExtract-3: ${err.message}`);
        }
    });
}

function stopNuExtract() {
    if (nuextractProc) {
        log(`Stopping NuExtract-3 process (PID: ${nuextractProc.pid})...`);
        try {
            child_process.execSync(`taskkill /pid ${nuextractProc.pid} /T /F`, { stdio: 'ignore' });
        } catch (e) {
            try { nuextractProc.kill(); } catch(err) {}
        }
        nuextractProc = null;
    }
}

function checkBackend(callback, retries = 0) {
    http.get('http://127.0.0.1:8000/health', (res) => {
        if (res.statusCode === 200) {
            log("Backend server /health responded 200 OK - Backend is ready!");
            callback(true);
        } else {
            if (retries % 10 === 0) {
                log(`Backend responded with status code: ${res.statusCode}. Retrying (${retries}/120)...`);
            }
            if (retries < 120) {
                setTimeout(() => checkBackend(callback, retries + 1), 500);
            } else {
                log("Backend health check timed out after 60s.");
                callback(false);
            }
        }
    }).on('error', (err) => {
        if (retries % 10 === 0 && retries > 0) {
            log(`Waiting for backend server to start... (${retries * 0.5}s elapsed)`);
        }
        if (retries < 120) {
            setTimeout(() => checkBackend(callback, retries + 1), 500);
        } else {
            log(`Waiting for backend server to start timed out (${err.message}) after 60s`);
            callback(false);
        }
    });
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1360,
        height: 880,
        minWidth: 1000,
        minHeight: 650,
        title: "ARKAN — Intelligence EPC Oil & Gas",
        backgroundColor: '#0F172A',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            webSecurity: true // Safe same-origin loading via http://127.0.0.1:8000/ui
        }
    });

    // Remove default menu bar
    mainWindow.removeMenu();

    // Allow target=_blank links to open in Electron:
    // - Procurement PDF/contract links → new BrowserWindow (shows PDF inline)
    // - External URLs → system default browser
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        const isSameOrigin = url.startsWith('http://127.0.0.1:8000');
        if (isSameOrigin) {
            // Open procurement PDFs / same-origin pages in a new Electron window
            const popup = new BrowserWindow({
                width: 1100,
                height: 860,
                title: 'ARKAN — Document',
                backgroundColor: '#0F172A',
                webPreferences: {
                    contextIsolation: true,
                    nodeIntegration: false
                }
            });
            popup.removeMenu();
            popup.loadURL(url);
            return { action: 'deny' }; // we opened it manually
        } else {
            // External links → open in system default browser
            shell.openExternal(url);
            return { action: 'deny' };
        }
    });

    // Load Arkan UI directly from backend HTTP server (same origin)
    const targetUrl = 'http://127.0.0.1:8000/ui';
    log(`Loading frontend URL: ${targetUrl}`);
    mainWindow.loadURL(targetUrl);

    let isRetrying = false;
    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
        log(`Failed to load ${validatedURL}: ${errorDescription} (${errorCode}).`);
        if (!isRetrying && targetUrl.startsWith('http://127.0.0.1:8000')) {
            isRetrying = true;
            log('Backend may still be initializing. Retrying connection in 2 seconds...');
            setTimeout(() => {
                isRetrying = false;
                if (mainWindow && !mainWindow.isDestroyed()) {
                    log(`Retrying to load: ${targetUrl}`);
                    mainWindow.loadURL(targetUrl);
                }
            }, 2000);
        }
    });

    mainWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
        if (level >= 2) {
            log(`[RENDERER CONSOLE] [Level ${level}] ${message} (at ${path.basename(sourceId)}:${line})`);
        }
    });

    // Ctrl+Shift+I shortcut for DevTools, F5 / Ctrl+R for Reload
    mainWindow.webContents.on('before-input-event', (event, input) => {
        if (input.control && input.shift && input.key.toLowerCase() === 'i') {
            mainWindow.webContents.toggleDevTools();
            event.preventDefault();
        } else if (input.key === 'F5' || (input.control && input.key.toLowerCase() === 'r')) {
            mainWindow.webContents.reloadIgnoringCache();
            event.preventDefault();
        }
    });

    // Auto-reload UI when arkan-ui.html is updated on disk
    try {
        const uiHtmlPath = path.join(ROOT_DIR, 'arkan-ui.html');
        let reloadDebounce = null;
        fs.watch(uiHtmlPath, () => {
            if (reloadDebounce) clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(() => {
                if (mainWindow && !mainWindow.isDestroyed()) {
                    log('arkan-ui.html modified on disk — auto-reloading renderer...');
                    mainWindow.webContents.reloadIgnoringCache();
                }
            }, 600);
        });
    } catch (watchErr) {
        log(`Warning: Could not watch arkan-ui.html: ${watchErr.message}`);
    }

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// Native Electron File Dialog for Technical Drawings & Documents
ipcMain.handle('dialog:openPlanFile', async () => {
    if (!mainWindow || mainWindow.isDestroyed()) return null;
    try {
        const result = await dialog.showOpenDialog(mainWindow, {
            title: 'Sélectionner des documents ARKAN (DWG, DXF, PDF, Excel, ZIP)',
            properties: ['openFile', 'multiSelections'],
            filters: [
                { name: 'Tous les fichiers (*.*)', extensions: ['*'] },
                { name: 'Plans & Documents Techniques', extensions: ['dwg', 'dxf', 'pdf', 'xlsx', 'xlsm', 'xls', 'csv', 'zip'] },
                { name: 'Plans DWG / DXF', extensions: ['dwg', 'dxf'] },
                { name: 'Plans PDF', extensions: ['pdf'] },
                { name: 'Carnets & Notes (Excel/CSV)', extensions: ['xlsx', 'xlsm', 'xls', 'csv'] }
            ]
        });
        if (!result.canceled && result.filePaths && result.filePaths.length > 0) {
            log(`[NATIVE_DIALOG] Fichiers sélectionnés (${result.filePaths.length}) : ${result.filePaths.join(', ')}`);
            return result.filePaths;
        }
        return null;
    } catch (err) {
        log(`[NATIVE_DIALOG_ERROR] ${err.message}`);
        return null;
    }
});

app.whenReady().then(() => {
    startNuExtract();
    startBackend();
    
    checkBackend((success) => {
        if (success) {
            createWindow();
        } else {
            log("Backend failed to start in time. Launching window fallback...");
            createWindow();
        }
    });
});

app.on('window-all-closed', () => {
    stopBackend();
    stopNuExtract();
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});

process.on('exit', () => {
    stopBackend();
    stopNuExtract();
});
