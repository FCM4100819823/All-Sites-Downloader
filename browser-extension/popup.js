// ...popup.js...
document.addEventListener('DOMContentLoaded', () => {
  const backendInput = document.getElementById('backendUrl');
  const sendBtn = document.getElementById('sendBtn');
  const status = document.getElementById('status');

  // Load backend URL from storage
  chrome.storage && chrome.storage.local.get(['downloaderBackend'], (result) => {
    if (result.downloaderBackend) backendInput.value = result.downloaderBackend;
  });

  sendBtn.onclick = async () => {
    status.textContent = '';
    const backend = backendInput.value.trim().replace(/\/$/, '');
    if (!backend) {
      status.textContent = 'Please enter your backend URL.';
      return;
    }
    // Save backend URL
    chrome.storage && chrome.storage.local.set({downloaderBackend: backend});
    // Get current tab URL
    chrome.tabs && chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
      const tab = tabs[0];
      if (!tab || !tab.url) {
        status.textContent = 'Could not get current tab URL.';
        return;
      }
      // Send to backend
      fetch(backend + '/api/start_download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: tab.url})
      })
      .then(r => r.json())
      .then(data => {
        if (data.download_id) {
          status.textContent = 'Sent! Check your downloader app.';
        } else {
          status.textContent = 'Failed: ' + (data.error || 'Unknown error');
        }
      })
      .catch(e => {
        status.textContent = 'Error: ' + e.message;
      });
    });
  };
});
// ...popup.js...
