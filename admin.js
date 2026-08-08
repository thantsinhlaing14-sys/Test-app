const modeButtons = document.querySelectorAll('.mode-button');
const promptForm = document.getElementById('prompt-form');
const promptInput = document.getElementById('prompt-input');
const adminStatus = document.getElementById('admin-status');

let currentMode = 'en';

function setStatus(message) {
    adminStatus.textContent = message;
}

function renderMode(mode) {
    currentMode = mode;
    modeButtons.forEach((button) => {
        button.classList.toggle('active', button.dataset.mode === mode);
    });
}

async function loadMode() {
    const response = await fetch('/api/mode');
    const data = await response.json();
    renderMode(data.language || 'en');
}

modeButtons.forEach((button) => {
    button.addEventListener('click', async () => {
        const language = button.dataset.mode;
        renderMode(language);
        setStatus('Switching mode...');

        const response = await fetch('/api/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language }),
        });

        if (!response.ok) {
            setStatus('Could not switch mode.');
            return;
        }

        setStatus(language === 'mm' ? 'Myanmar mode active.' : 'English mode active.');
    });
});

promptForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    const prompt = promptInput.value.trim();
    if (!prompt) {
        setStatus('Type a prompt first.');
        return;
    }

    setStatus('Sending...');
    const response = await fetch('/api/prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
    });

    if (!response.ok) {
        setStatus('Could not send prompt.');
        return;
    }

    promptInput.value = '';
    setStatus(`Queued in ${currentMode === 'mm' ? 'Myanmar' : 'English'} mode.`);
});

loadMode().catch(() => setStatus('Could not load mode.'));
