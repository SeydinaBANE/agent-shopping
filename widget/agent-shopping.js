class AgentShopping extends HTMLElement {
  static get observedAttributes() {
    return ['tenant-id', 'api-url', 'primary-color', 'position', 'lang', 'token'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });

    this._state = {
      open: false,
      messages: [],
      loading: false,
      tenantId: this.getAttribute('tenant-id') || 'default',
      apiUrl: this.getAttribute('api-url') || 'https://api.agent-shopping.dev',
      primaryColor: this.getAttribute('primary-color') || '#6C5CE7',
      position: this.getAttribute('position') || 'bottom-right',
      lang: this.getAttribute('lang') || 'fr',
      token: this.getAttribute('token') || null,
      pendingConfirmation: null,
    };

    this._render();
    this._bindEvents();
  }

  _render() {
    const styles = `
      :host {
        --primary: ${this._state.primaryColor};
        --primary-hover: ${this._darken(this._state.primaryColor, 0.1)};
        --bg: #ffffff;
        --text: #1a1a2e;
        --text-muted: #6b7280;
        --border: #e5e7eb;
        --shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
        --radius: 16px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }

      * { box-sizing: border-box; margin: 0; padding: 0; }

      .container {
        position: fixed;
        ${this._state.position === 'bottom-right' ? 'right: 20px;' : 'left: 20px;'}
        bottom: 20px;
        z-index: 2147483647;
        direction: ${this._state.lang === 'ar' ? 'rtl' : 'ltr'};
      }

      .chat-button {
        width: 60px;
        height: 60px;
        border-radius: 50%;
        background: var(--primary);
        color: white;
        border: none;
        cursor: pointer;
        box-shadow: var(--shadow);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        transition: transform 0.2s, box-shadow 0.2s;
        margin-left: auto;
      }

      .chat-button:hover {
        transform: scale(1.05);
        box-shadow: 0 6px 32px rgba(0, 0, 0, 0.18);
      }

      .chat-button svg {
        width: 28px;
        height: 28px;
        fill: currentColor;
      }

      .chat-panel {
        display: none;
        position: absolute;
        bottom: 76px;
        ${this._state.position === 'bottom-right' ? 'right: 0;' : 'left: 0;'}
        width: 380px;
        max-width: calc(100vw - 40px);
        height: 560px;
        max-height: calc(100vh - 120px);
        background: var(--bg);
        border-radius: var(--radius);
        box-shadow: var(--shadow);
        overflow: hidden;
        flex-direction: column;
      }

      .chat-panel.open {
        display: flex;
      }

      .header {
        padding: 16px 20px;
        background: var(--primary);
        color: white;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }

      .header h3 {
        font-size: 16px;
        font-weight: 600;
      }

      .header-close {
        background: none;
        border: none;
        color: white;
        cursor: pointer;
        font-size: 20px;
        opacity: 0.8;
      }

      .header-close:hover { opacity: 1; }

      .messages {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .message {
        max-width: 85%;
        padding: 10px 14px;
        border-radius: 12px;
        font-size: 14px;
        line-height: 1.5;
        white-space: pre-wrap;
      }

      .message.user {
        align-self: flex-end;
        background: var(--primary);
        color: white;
        border-bottom-right-radius: 4px;
      }

      .message.assistant {
        align-self: flex-start;
        background: #f3f4f6;
        color: var(--text);
        border-bottom-left-radius: 4px;
      }

      .message.error {
        align-self: center;
        background: #fee2e2;
        color: #dc2626;
        font-size: 13px;
      }

      .typing {
        align-self: flex-start;
        display: flex;
        gap: 4px;
        padding: 12px 16px;
        background: #f3f4f6;
        border-radius: 12px;
        border-bottom-left-radius: 4px;
      }

      .typing span {
        width: 8px;
        height: 8px;
        background: #9ca3af;
        border-radius: 50%;
        animation: typing 1.4s infinite;
      }

      .typing span:nth-child(2) { animation-delay: 0.2s; }
      .typing span:nth-child(3) { animation-delay: 0.4s; }

      @keyframes typing {
        0%, 60%, 100% { opacity: 0.4; transform: translateY(0); }
        30% { opacity: 1; transform: translateY(-4px); }
      }

      .input-area {
        padding: 12px 16px;
        border-top: 1px solid var(--border);
        display: flex;
        gap: 8px;
      }

      .input-area input {
        flex: 1;
        border: 1px solid var(--border);
        border-radius: 24px;
        padding: 10px 16px;
        font-size: 14px;
        outline: none;
        transition: border-color 0.2s;
      }

      .input-area input:focus {
        border-color: var(--primary);
      }

      .input-area button {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--primary);
        color: white;
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
      }

      .input-area button:hover {
        background: var(--primary-hover);
      }

      .input-area button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .confirm-dialog {
        padding: 12px 16px;
        background: #fef3c7;
        border-top: 1px solid #fde68a;
        display: flex;
        gap: 8px;
        align-items: center;
        font-size: 14px;
      }

      .confirm-dialog button {
        padding: 6px 16px;
        border-radius: 8px;
        border: none;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
      }

      .confirm-dialog .confirm-yes {
        background: var(--primary);
        color: white;
      }

      .confirm-dialog .confirm-no {
        background: #e5e7eb;
        color: var(--text);
      }
    `;

    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="container">
        <button class="chat-button" part="button">
          <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/></svg>
        </button>
        <div class="chat-panel">
          <div class="header">
            <h3>Assistant Shopping</h3>
            <button class="header-close" part="close-button">&times;</button>
          </div>
          <div class="messages"></div>
          <div class="confirm-dialog" style="display:none"></div>
          <div class="input-area">
            <input type="text" placeholder="Votre message..." part="input">
            <button part="send-button">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _bindEvents() {
    const root = this.shadowRoot;
    const chatButton = root.querySelector('.chat-button');
    const closeButton = root.querySelector('.header-close');
    const input = root.querySelector('input');
    const sendButton = root.querySelector('.input-area button');

    chatButton.addEventListener('click', () => this._toggle());
    closeButton.addEventListener('click', () => this._toggle(false));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._send();
    });
    sendButton.addEventListener('click', () => this._send());
  }

  _toggle(forceState) {
    this._state.open = forceState !== undefined ? forceState : !this._state.open;
    const panel = this.shadowRoot.querySelector('.chat-panel');
    panel.classList.toggle('open', this._state.open);

    if (this._state.open && this._state.messages.length === 0) {
      this._addMessage(
        'assistant',
        'Bonjour ! Je suis votre assistant shopping. Comment puis-je vous aider aujourd\'hui ?'
      );
    }
  }

  _addMessage(role, content) {
    this._state.messages.push({ role, content });
    const container = this.shadowRoot.querySelector('.messages');
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    msg.textContent = content;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
  }

  async _send() {
    const input = this.shadowRoot.querySelector('input');
    const message = input.value.trim();
    if (!message || this._state.loading) return;

    input.value = '';
    this._addMessage('user', message);

    this._state.loading = true;
    this._showTyping();

    try {
      const response = await this._callAPI(message);
      this._removeTyping();

      if (response.confirmation) {
        this._showConfirmation(response.confirmation);
      } else {
        this._addMessage('assistant', response.response);
      }
    } catch (err) {
      this._removeTyping();
      this._addMessage('error', 'Service momentanément indisponible. Veuillez réessayer.');
    }

    this._state.loading = false;
  }

  _showTyping() {
    const container = this.shadowRoot.querySelector('.messages');
    const typing = document.createElement('div');
    typing.className = 'typing';
    typing.innerHTML = '<span></span><span></span><span></span>';
    typing.id = 'typing-indicator';
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;
  }

  _removeTyping() {
    const typing = this.shadowRoot.getElementById('typing-indicator');
    if (typing) typing.remove();
  }

  async _callAPI(message) {
    const history = this._state.messages.slice(0, -1).map(m => ({
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: m.content,
    }));

    const payload = {
      message,
      history,
      tenant_id: this._state.tenantId,
    };

    const headers = { 'Content-Type': 'application/json' };
    if (this._state.token) {
      headers['Authorization'] = `Bearer ${this._state.token}`;
    }

    const response = await fetch(`${this._state.apiUrl}/assistant/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }

  _showConfirmation(data) {
    const dialog = this.shadowRoot.querySelector('.confirm-dialog');
    dialog.style.display = 'flex';
    dialog.innerHTML = `
      <span>${data.message || 'Confirmez-vous cette action ?'}</span>
      <button class="confirm-yes">Confirmer</button>
      <button class="confirm-no">Annuler</button>
    `;

    dialog.querySelector('.confirm-yes').addEventListener('click', async () => {
      dialog.style.display = 'none';
      this._state.loading = true;
      this._showTyping();

      try {
        const response = await this._callAPI('CONFIRM_COMMAND');
        this._removeTyping();
        this._addMessage('assistant', response.response);
      } catch {
        this._removeTyping();
        this._addMessage('error', 'Erreur lors de la confirmation.');
      }
      this._state.loading = false;
    });

    dialog.querySelector('.confirm-no').addEventListener('click', () => {
      dialog.style.display = 'none';
      this._addMessage('assistant', 'Action annulée. Puis-je vous aider autrement ?');
    });
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue === newValue) return;
    const map = {
      'tenant-id': 'tenantId',
      'api-url': 'apiUrl',
      'primary-color': 'primaryColor',
      'position': 'position',
      'lang': 'lang',
      'token': 'token',
    };
    if (map[name]) {
      this._state[map[name]] = newValue;
      this._render();
      this._bindEvents();
    }
  }

  set token(value) {
    this._state.token = value;
  }

  _darken(hex, amount) {
    const num = parseInt(hex.replace('#', ''), 16);
    const r = Math.min(255, Math.floor((num >> 16) * (1 - amount)));
    const g = Math.min(255, Math.floor(((num >> 8) & 0x00ff) * (1 - amount)));
    const b = Math.min(255, Math.floor((num & 0x0000ff) * (1 - amount)));
    return `#${(r << 16 | g << 8 | b).toString(16).padStart(6, '0')}`;
  }
}

customElements.define('agent-shopping', AgentShopping);
