document.addEventListener('DOMContentLoaded', async () => {
    const grid = document.getElementById('game-grid');
    const loader = document.getElementById('loader-overlay');
    const theater = document.getElementById('theater-view');
    const iframe = document.getElementById('game-iframe');
    const theaterTitle = document.getElementById('theater-game-title');
    const backToLibraryBtn = document.getElementById('btn-back-to-library');

    let currentSessionId = null;
    let monitorInterval = null;
    let allRoms = {};
    let currentPlatform = 'ps1';

    // --- Client Identification ---
    let clientId = localStorage.getItem('duckstation_client_id');
    if (!clientId) {
        clientId = (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID()
            : 'user-' + Math.random().toString(36).substring(2, 15);
        localStorage.setItem('duckstation_client_id', clientId);
    }

    // --- UI Listeners ---
    backToLibraryBtn.addEventListener('click', exitTheater);

    // Initial Load
    loadLibrary();
    refreshActiveSessions();

    // Tab Synchronization Event Listener
    window.addEventListener('storage', (e) => {
        if (e.key === 'app_sync_game_launched') {
            if (!theater.classList.contains('hidden') || isLaunching) {
                console.log("Cross-tab action detected. Halting this game.");
                exitTheater();
                loader.classList.add('hidden');
                grid.style.pointerEvents = 'auto';
                isLaunching = false;

                const Toast = Swal.mixin({
                    toast: true,
                    position: 'top-end',
                    showConfirmButton: false,
                    timer: 5000,
                    timerProgressBar: true,
                    background: '#1e1e2e',
                    color: '#cdd6f4'
                });
                Toast.fire({
                    icon: 'warning',
                    title: 'Game paused! You started a session in another tab.'
                });
            }
        }
    });

    // Tab Bar Logic
    const tabs = document.querySelectorAll('.platform-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            tabs.forEach(t => t.classList.remove('active'));
            e.target.classList.add('active');
            currentPlatform = e.target.getAttribute('data-platform');
            renderGrid();
        });
    });

    // Periodically sync library state without flickering
    setInterval(() => {
        if (document.visibilityState === 'hidden') return;
        if (theater.classList.contains('hidden')) {
            refreshActiveSessions();
        }
    }, 5000);

    let lastSessionsData = null;

    async function loadLibrary() {
        try {
            const response = await fetch('/api/roms');
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            allRoms = await response.json();
            renderGrid();
        } catch (error) {
            grid.innerHTML = '<div style="color: #ff4d4d; grid-column: 1/-1; text-align: center;">Error connecting to server</div>';
        }
    }

    function renderGrid() {
        grid.innerHTML = '';
        const roms = allRoms[currentPlatform] || [];

        if (roms.length === 0) {
            grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-secondary);">No ROMs found in library for this platform</div>';
            return;
        }

        roms.forEach(rom => {
            const card = document.createElement('div');
            card.className = 'game-card';

            card.innerHTML = `
                <div class="game-poster-container">
                    <img src="${rom.poster_url}" class="game-poster" alt="${rom.display_name}" loading="lazy">
                    <div class="game-poster-overlay">
                        <i class="fas fa-play"></i>
                    </div>
                </div>
                <div class="game-title">${rom.display_name}</div>
            `;

            const img = card.querySelector('img');
            img.onerror = () => {
                img.onerror = null;
                const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400" viewBox="0 0 300 400"><rect width="100%" height="100%" fill="#1e1e2e"/><text x="50%" y="50%" font-family="sans-serif" font-size="24" fill="#cdd6f4" text-anchor="middle" dominant-baseline="middle" font-weight="bold">${currentPlatform.toUpperCase()}</text></svg>`;
                img.src = 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg);
            };

            card.addEventListener('click', () => startGame(rom.filename, rom.platform));
            grid.appendChild(card);
        });
    }

    async function refreshActiveSessions() {
        const container = document.getElementById('active-sessions-container');
        const list = document.getElementById('session-list');

        try {
            const response = await fetch(`/api/active-sessions/${clientId}`);
            if (!response.ok) return;
            const sessions = await response.json();

            const currentData = JSON.stringify(sessions);
            if (currentData === lastSessionsData) return; // Prevent unnecessary DOM recreation/flickering
            lastSessionsData = currentData;

            if (sessions.length > 0) {
                container.classList.remove('hidden');
                list.innerHTML = '';
                sessions.forEach(session => {
                    const card = document.createElement('div');
                    card.className = 'session-card';
                    card.innerHTML = `
                        <div class="session-info">
                            <span class="session-game-name">${session.game_name}</span>
                            <span class="session-status">● ${session.status}</span>
                        </div>
                        <div class="session-actions">
                            <button class="btn btn-resume">Resume</button>
                            <button class="btn btn-stop">End Session</button>
                        </div>
                    `;

                    card.querySelector('.btn-resume').addEventListener('click', () => {
                        enterTheater(session.session_id, session.url_path, session.game_name);
                    });

                    card.querySelector('.btn-stop').addEventListener('click', async (e) => {
                        const btn = e.target;
                        btn.innerText = 'Stopping...';
                        btn.disabled = true;
                        await apiStopSession(session.session_id);
                    });

                    list.appendChild(card);
                });
            } else {
                container.classList.add('hidden');
            }
        } catch (error) {
            console.error('Error fetching active sessions:', error);
        }
    }

    let isLaunching = false;
    let launchAborted = false;
    const btnCancelLaunch = document.getElementById('btn-cancel-launch');

    if (btnCancelLaunch) {
        btnCancelLaunch.addEventListener('click', () => {
            launchAborted = true;
            isLaunching = false;
            loader.classList.add('hidden');
            grid.style.pointerEvents = 'auto';
        });
    }

    async function startGame(filename, platform) {
        if (isLaunching) return;
        isLaunching = true;
        launchAborted = false;
        loader.classList.remove('hidden');

        const loaderStatus = document.getElementById('loader-status');
        const loaderMsg = document.getElementById('loader-message');
        if (loaderStatus) loaderStatus.innerText = 'Initializing System';
        if (loaderMsg) loaderMsg.innerText = 'Connecting to server...';

        grid.style.pointerEvents = 'none';

        try {
            const response = await fetch('/api/start-session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ game_filename: filename, client_id: clientId, platform: platform })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to start session');
            }
            const data = await response.json();
            const sessionId = data.session_id;

            if (launchAborted) {
                console.log("Launch aborted during allocation. Cleaning up ghost session:", sessionId);
                if (data.platform === 'ps1') apiStopSession(sessionId);
                return;
            }

            // WASM Quick-Boot bypass
            if (data.platform && data.platform !== 'ps1') {
                loader.classList.add('hidden');
                isLaunching = false;
                grid.style.pointerEvents = 'auto';
                enterTheater(sessionId, data.url_path, filename, data.platform);
                return;
            }

            // Docker Boot Polling for PS1...
            const startTime = Date.now();
            const TIMEOUT_MS = 90000; // 90 seconds max

            const MILESTONES = {
                'initializing': 'Preparing system components...',
                'waiting_for_x': 'Setting up graphics engine...',
                'waiting_for_wm': 'Handshaking with window manager...',
                'extracting': 'Unpacking game files...',
                'running_game': 'Starting game theater...'
            };

            const pollStatus = async () => {
                if (launchAborted) {
                    apiStopSession(sessionId);
                    return;
                }

                if (Date.now() - startTime > TIMEOUT_MS) {
                    throw new Error('Launch timeout. The server might be under heavy load.');
                }

                const statusRes = await fetch(`/api/session-status/${sessionId}?client_id=${clientId}`);
                const statusData = await statusRes.json();

                if (statusData.status === 'running_game') {
                    loader.classList.add('hidden');
                    isLaunching = false;
                    grid.style.pointerEvents = 'auto';
                    enterTheater(sessionId, data.url_path, filename);
                } else if (['error', 'stopped', 'stuck', 'not_found'].includes(statusData.status)) {
                    throw new Error(statusData.message || 'Emulator failed to initialize');
                } else {
                    // Map internal status to user-friendly milestone
                    const rawStatus = (statusData.status || 'initializing').toLowerCase();
                    const friendlyMsg = MILESTONES[rawStatus] || 'Booting emulator...';

                    if (loaderStatus) loaderStatus.innerText = 'Synchronizing';
                    if (loaderMsg) loaderMsg.innerText = friendlyMsg;

                    setTimeout(pollStatus, 1500);
                }
            };
            pollStatus();
        } catch (error) {
            if (!launchAborted) {
                alert('Launch failed: ' + error.message);
                loader.classList.add('hidden');
                grid.style.pointerEvents = 'auto';
                isLaunching = false;
            }
        }
    }

    function enterTheater(sessionId, urlPath, title, platform = 'ps1') {
        currentSessionId = sessionId;
        const cleanTitle = title.replace(/\s*\(Disc\s*\d+\)/gi, '').replace(/\.(zip|bin|cue|iso|smc|sfc|gba)$/i, '');
        theaterTitle.innerText = cleanTitle;
        iframe.src = urlPath;
        theater.classList.remove('hidden');
        document.body.style.overflow = 'hidden';

        // Broadcast to all other tabs to shut down their active iframes
        localStorage.setItem('app_sync_game_launched', Date.now().toString());

        if (platform !== 'ps1') return; // WASM platforms do not need remote heartbeat monitoring

        // Start High-Efficiency Heartbeat for PS1 Docker Containers
        if (monitorInterval) clearInterval(monitorInterval);
        monitorInterval = setInterval(async () => {
            // Skip if tab hidden to save server resources
            if (document.visibilityState === 'hidden') return;

            try {
                const res = await fetch(`/api/session-status/${sessionId}?client_id=${clientId}`);
                if (!res.ok) return;
                const data = await res.json();

                if (['stopped', 'not_found', 'error'].includes(data.status)) {
                    console.log("Session ended remotely. Exiting theater.");
                    exitTheater();
                }
            } catch (e) {
                console.error("Heartbeat failed", e);
            }
        }, 4000); // 4 second check is plenty for 50+ users
    }

    function exitTheater() {
        if (monitorInterval) clearInterval(monitorInterval);
        monitorInterval = null;
        currentSessionId = null;
        theater.classList.add('hidden');
        iframe.src = 'about:blank';
        document.body.style.overflow = 'auto';
        refreshActiveSessions();
    }

    async function apiStopSession(sessionId) {
        try {
            const res = await fetch(`/api/stop-session/${sessionId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ client_id: clientId })
            });
            // Refresh regardless of success/fail to synchronize UI with reality
            await refreshActiveSessions();
        } catch (e) {
            console.error("Stop failed", e);
            await refreshActiveSessions();
        }
    }
});
