const form = document.getElementById('local-ai-form');
const input = document.getElementById('local-ai-input');
const output = document.getElementById('local-ai-output');
const cursor = document.getElementById('local-ai-cursor');
const state = document.getElementById('local-ai-state');
const sendButton = document.querySelector('.local-ai-send-btn');

let charQueue = [];
let typeInterval = null;
let currentSpan = null;
const CHAR_DELAY_MS = 18;

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
                if (event.type === 'done') setBusy(false);
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
