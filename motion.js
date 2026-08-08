const motionState = document.getElementById('motion-state');
const motionOutput = document.getElementById('motion-output');
const motionButtons = document.querySelectorAll('[data-motion-id]');

function setBusy(isBusy) {
    motionState.textContent = isBusy ? 'Sending' : 'Ready';
    motionButtons.forEach((button) => {
        button.disabled = isBusy;
    });
}

motionButtons.forEach((button) => {
    button.addEventListener('click', async () => {
        const motionId = button.dataset.motionId;
        setBusy(true);
        motionOutput.textContent = `Sending ${button.textContent.trim()} command...`;

        try {
            const response = await fetch(`/api/motion/${encodeURIComponent(motionId)}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });
            const data = await response.json();

            if (!response.ok) {
                motionOutput.textContent = data.error || 'Motion command failed.';
                return;
            }

            motionOutput.textContent = `${data.label}: ${data.command}`;
        } catch {
            motionOutput.textContent = 'Could not reach local motion endpoint.';
        } finally {
            setBusy(false);
        }
    });
});
