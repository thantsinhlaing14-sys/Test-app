const output = document.getElementById('stream-output');
const streamCursor = document.getElementById('stream-cursor');
const demoState = document.getElementById('demo-state');
const actionButtons = document.querySelectorAll('[data-interaction-id]');
const streamContainer = document.querySelector('.stream-container');
const speakerToggle = document.getElementById('speaker-toggle');

let isNewResponse = true;
let isResponding = false;
let charQueue = [];
let typeInterval = null;
let currentSpan = null;
let currentAudio = null;
const CHAR_DELAY_MS = 18;

async function refreshSpeakerToggle() {
    try {
        const response = await fetch('/api/output-mode');
        const data = await response.json();
        speakerToggle.textContent = data.mode === 'phone' ? 'Speaker: Phone' : 'Speaker: Laptop';
    } catch {
        speakerToggle.textContent = 'Speaker: Laptop';
    }
}

async function setSpeakerMode(mode) {
    speakerToggle.textContent = mode === 'phone' ? 'Speaker: Phone' : 'Speaker: Laptop';
    try {
        await fetch('/api/output-mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode }),
        });
    } catch {
        // ignore
    }
}

function playStreamAudio(src) {
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
    const audio = new Audio(src);
    currentAudio = audio;
    audio.play().catch(() => {});
}

function stopStreamAudio() {
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
}

if (speakerToggle) {
    speakerToggle.addEventListener('click', () => {
        const isPhone = speakerToggle.textContent.includes('Phone');
        setSpeakerMode(isPhone ? 'laptop' : 'phone');
    });
    refreshSpeakerToggle();
}

function setBusy(isBusy) {
    isResponding = isBusy;
    demoState.textContent = isBusy ? 'Playing' : 'Ready';
    actionButtons.forEach((button) => {
        button.disabled = isBusy;
    });
}

async function playInteraction(interactionId) {
    if (isResponding) return;
    setBusy(true);

    try {
        const response = await fetch(`/api/interactions/${encodeURIComponent(interactionId)}/play`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });

        if (!response.ok) {
            setBusy(false);
        }
    } catch {
        setBusy(false);
    }
}

actionButtons.forEach((button) => {
    button.addEventListener('click', () => {
        playInteraction(button.dataset.interactionId);
    });
});

function startTyping() {
    if (typeInterval) return;
    typeInterval = setInterval(drainQueue, CHAR_DELAY_MS);
}

function drainQueue() {
    if (charQueue.length === 0) {
        clearInterval(typeInterval);
        typeInterval = null;
        streamCursor.classList.remove('active');
        return;
    }

    const ch = charQueue.shift();

    if (ch === '\n') {
        currentSpan = null;
    } else {
        if (!currentSpan) {
            currentSpan = document.createElement('span');
            currentSpan.className = 'stream-line';
            output.appendChild(currentSpan);
        }
        currentSpan.textContent += ch;
    }

    streamContainer.scrollTop = streamContainer.scrollHeight;
}

function enqueueText(text) {
    if (!currentSpan) {
        currentSpan = document.createElement('span');
        currentSpan.className = 'stream-line';
        output.appendChild(currentSpan);
    }

    for (const ch of text) {
        charQueue.push(ch);
    }

    streamCursor.classList.add('active');
    startTyping();
}

function flushQueue() {
    clearInterval(typeInterval);
    typeInterval = null;
    charQueue = [];
    currentSpan = null;
    streamCursor.classList.remove('active');
}

async function listenToStream() {
    try {
        const response = await fetch('/stream');
        if (!response.body) throw new Error('No response body');

        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += value;
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.trim()) continue;

                let event;
                try {
                    event = JSON.parse(line);
                } catch (error) {
                    console.error('Stream parse error:', error, line);
                    continue;
                }

                if (event.type === 'reset') {
                    isNewResponse = true;
                    setBusy(true);
                    flushQueue();
                    continue;
                }

                if (event.type === 'interaction') {
                    demoState.textContent = event.data?.label || 'Playing';
                    continue;
                }

                if (event.type === 'audio') {
                    if (event.data?.src) {
                        playStreamAudio(event.data.src);
                    }
                    continue;
                }

                if (event.type === 'audio-stop') {
                    stopStreamAudio();
                    continue;
                }

                if (event.type === 'text') {
                    if (isNewResponse) {
                        output.innerHTML = '';
                        currentSpan = null;
                        isNewResponse = false;
                    }
                    enqueueText(event.data);
                    continue;
                }

                if (event.type === 'done') {
                    stopStreamAudio();
                    setBusy(false);
                }
            }
        }
    } catch {
        demoState.textContent = 'Reconnecting';
        setTimeout(listenToStream, 2000);
    }
}

listenToStream();
