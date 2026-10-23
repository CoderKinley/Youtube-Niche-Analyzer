"use strict";

function renderKeyStatus(ready) {
  $("connection").textContent = ready ? "Key saved" : "Not connected";
  $("connection").classList.toggle("ready", ready);
  $("key-status").textContent = ready
    ? "Your saved key is ready to use. Paste another to replace it."
    : "Add a key to start searching.";
  $("api-key").placeholder = ready ? "Paste a replacement key" : "Paste your API key";
}

$("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = $("api-key").value.trim();
  $("key-message").hidden = false;
  $("key-message").className = "key-message";
  if (!/^[A-Za-z0-9_-]{20,200}$/.test(key)) {
    $("key-message").textContent = "Paste the key without quotes or spaces.";
    $("key-message").classList.add("error");
    return;
  }
  $("save-key").disabled = true;
  $("save-key").textContent = "Saving…";
  $("key-message").textContent = "Saving…";
  try {
    await api("/api/settings/youtube-key", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key }),
    });
    $("api-key").value = "";
    renderKeyStatus(true);
    $("key-message").textContent = "Saved. You’re ready to search.";
  } catch (error) {
    $("key-message").textContent = error.message || "Could not save the key. Try again.";
    $("key-message").classList.add("error");
  } finally {
    $("save-key").disabled = false;
    $("save-key").textContent = "Save key";
  }
});

async function initializeSettings() {
  try { renderKeyStatus((await api("/api/health")).youtube_key_configured); }
  catch {
    $("connection").textContent = "Offline";
    $("key-status").textContent = "Could not reach the server. Try refreshing.";
  }
}
initializeSettings();
