/* ================================================================
   PFM Chrome Extension — Service Worker
   Minimal: handles viewer tab opening and lifecycle events.
   ================================================================ */

// Open viewer tab when requested
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === 'open_viewer') {
    chrome.tabs.create({
      url: chrome.runtime.getURL('viewer/viewer.html')
    }, (tab) => {
      sendResponse({ tabId: tab.id });
    });
    return true; // keep channel open for async response
  }
});

// Extension install/update lifecycle
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    console.log('[PFM] Extension installed');
  } else if (details.reason === 'update') {
    console.log('[PFM] Extension updated to', chrome.runtime.getManifest().version);
  }
});
