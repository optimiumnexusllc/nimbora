export const HEADLESS_CHAT_EXAMPLE = `let chatState = 'idle';

function withNimboraWidget(callback) {
  if (window.NimboraWidget) {
    callback(window.NimboraWidget);
    return;
  }

  const script = document.getElementById('nimbora-widget');
  if (!script) {
    console.error('NIMBORA embed script not found');
    return;
  }

  script.addEventListener('load', () => {
    if (window.NimboraWidget) callback(window.NimboraWidget);
  }, { once: true });
}

withNimboraWidget((widget) => {
  widget.onChatStateChange((state) => {
    chatState = state; // idle | starting | ready | waiting | ended | expired | error
  });

  widget.onMessage((text, turn) => {
    appendAgentBubble(text); // render however you want
  });

  document.getElementById('open-chat').addEventListener('click', () => {
    widget.startChat();
  });

  document.getElementById('send-btn').addEventListener('click', async () => {
    const input = document.getElementById('chat-input');
    appendVisitorBubble(input.value);
    const transcript = await widget.sendMessage(input.value);
    if (transcript !== null) input.value = '';
  });

  document.getElementById('end-chat')?.addEventListener('click', async () => {
    await widget.endChat();
  });
});`;
