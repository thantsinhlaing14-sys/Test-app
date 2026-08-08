const form = document.getElementById('local-ai-form');
const input = document.getElementById('local-ai-input');
const output = document.getElementById('local-ai-output');
const cursor = document.getElementById('local-ai-cursor');
const state = document.getElementById('local-ai-state');
const sendButton = document.querySelector('.local-ai-send-btn');
const speakerToggle = document.getElementById('speaker-toggle');

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

function b64ToWavBlob(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: 'audio/wav' });
}

function playStreamAudio(srcOrB64) {
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
    const audio = new Audio(typeof srcOrB64 === 'string' && srcOrB64.startsWith('/') ? srcOrB64 : URL.createObjectURL(b64ToWavBlob(srcOrB64)));
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
    state.textContent = isBusy ? 'Thinking' : 'Ready';
    sendButton.disabled = isBusy;
    input.disabled = isBusy;
}

function startTyping() {
    if (typeInterval) return;
    typeInterval = setInterval(drainQueue, CHAR_DELAY_MS);
}

function drainQueue() {
    if (charQueue.length === 0) {
        clearInterval(typeInterval);
        typeInterval = null;
        cursor.classList.remove('active');
        return;
    }

    const ch = charQueue.shift();
    if (!currentSpan || ch === '\n') {
        currentSpan = document.createElement('span');
        currentSpan.className = 'stream-line';
        output.appendChild(currentSpan);
        if (ch === '\n') return;
    }
    currentSpan.textContent += ch;
    output.parentElement.scrollTop = output.parentElement.scrollHeight;
}

function enqueueText(text) {
    for (const ch of text) charQueue.push(ch);
    cursor.classList.add('active');
    startTyping();
}

function resetOutput() {
    clearInterval(typeInterval);
    typeInterval = null;
    charQueue = [];
    currentSpan = null;
    output.innerHTML = '';
    cursor.classList.remove('active');
}

async function sendPrompt(prompt) {
    setBusy(true);
    resetOutput();

    try {
        const response = await fetch('/api/local-ai/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt }),
        });

        if (!response.ok || !response.body) {
            enqueueText('Local AI request failed.');
            return;
        }

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
                const event = JSON.parse(line);

                if (event.type === 'reset') resetOutput();
                if (event.type === 'text') enqueueText(event.data);
                if (event.type === 'status') state.textContent = 'Speaking';
                if (event.type === 'audio') playStreamAudio(event.data?.b64 || event.data?.src);
                if (event.type === 'done') {
                    stopStreamAudio();
                    setBusy(false);
                }
            }
        }
    } catch {
        enqueueText('Could not reach local AI endpoint.');
    } finally {
        setBusy(false);
    }
}

form.addEventListener('submit', (event) => {
    event.preventDefault();
    const prompt = input.value.trim();
    if (!prompt) return;
    sendPrompt(prompt);
});
