const adminStatus = document.getElementById('admin-status');
const interactionButtons = document.querySelectorAll('[data-interaction-id]');

function setStatus(message) {
    adminStatus.textContent = message;
}

function setBusy(isBusy) {
    interactionButtons.forEach((button) => {
        button.disabled = isBusy;
    });
}

interactionButtons.forEach((button) => {
    button.addEventListener('click', async () => {
        const interactionId = button.dataset.interactionId;
        setBusy(true);
        setStatus(`Playing ${button.querySelector('.interaction-title').textContent}`);

        try {
            const response = await fetch(`/api/interactions/${encodeURIComponent(interactionId)}/play`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });

            if (!response.ok) {
                setStatus('Could not start interaction.');
                return;
            }

            setStatus('Interaction queued.');
        } catch {
            setStatus('Could not reach local server.');
        } finally {
            setTimeout(() => setBusy(false), 700);
        }
    });
});
