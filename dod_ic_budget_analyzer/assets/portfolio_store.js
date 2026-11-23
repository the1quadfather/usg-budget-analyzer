// Only trusted code lives here. Collection JSON travels as data, never HTML.
export default function(component) {
    const { data, parentElement, setStateValue } = component;
    const label = parentElement.querySelector('[role="status"]');
    if (!data || label.dataset.command === data.id) return;
    label.dataset.command = data.id;
    const key = 'dod-budget-explorer.collections.v1';
    let response;
    try {
        const current = localStorage.getItem(key);
        if (data.action === 'load' && current && new TextEncoder().encode(current).length > 1000000) {
            throw new Error('Saved data exceeds the supported size');
        }
        if (data.action === 'load') {
            response = {id: data.id, status: 'loaded', payload: current};
        } else if (data.action === 'save') {
            if (new TextEncoder().encode(data.payload).length > 1000000) {
                throw new Error('Backup too large');
            }
            let revision = null;
            try { revision = current ? JSON.parse(current).revision : null; } catch (_) {}
            // A repeated acknowledgement is harmless; an old tab may not
            // overwrite a newer save without explicit backup-restore consent.
            if (current !== data.payload && !data.replace && revision !== data.expected_revision) {
                response = {id: data.id, status: 'conflict'};
            } else {
                localStorage.setItem(key, data.payload);
                response = {id: data.id, status: 'saved'};
            }
        } else {
            throw new Error('Unknown operation');
        }
    } catch (_) {
        response = {id: data.id, status: 'unavailable'};
    }
    const labels = {
        loaded: 'Saved work loaded from this browser.',
        saved: 'Saved in this browser. Download a backup to move devices.',
        conflict: 'Another tab changed your saved work. Reload before saving.',
        unavailable: 'Browser saving is unavailable. Download a backup to keep your work.'
    };
    label.textContent = labels[response.status];
    setStateValue('response', response);
}
