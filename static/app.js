const COLORS = [
  "#4A90D9", "#E74C3C", "#2ECC71", "#F39C12",
  "#9B59B6", "#1ABC9C", "#E67E22", "#3498DB",
];

const DEFAULT_AGENTS = [
  {
    name: "张明",
    provider: "openai",
    base_url: "",
    api_key: "",
    model: "",
    prompt: "你是张明，35岁，科技公司产品经理。你对新技术持开放和乐观的态度，善于从商业和实际应用的角度思考问题。说话直接，喜欢用具体案例来支持自己的观点。",
  },
  {
    name: "李华",
    provider: "openai",
    base_url: "",
    api_key: "",
    model: "",
    prompt: "你是李华，42岁，大学哲学教授。你善于从人文、伦理和社会学角度思考问题，观点深刻。说话温和但有力，喜欢反问和类比。",
  },
  {
    name: "王芳",
    provider: "openai",
    base_url: "",
    api_key: "",
    model: "",
    prompt: "你是王芳，28岁，自由撰稿人。你思维活跃，善于从普通人的角度提出实际的担忧和期望。说话活泼，偶尔带点幽默。",
  },
];

class AgentdTalking {
  constructor() {
    this.ws = null;
    this.agents = [];
    this.isRunning = false;
    this.currentStreamEl = null;
    this.agentColorMap = {};

    this._bindUI();
    DEFAULT_AGENTS.forEach((a) => this.addAgent(a));
  }

  _bindUI() {
    document.getElementById("addAgent").addEventListener("click", () => this.addAgent());
    document.getElementById("startBtn").addEventListener("click", () => this.toggle());
    document.getElementById("toggleSidebar").addEventListener("click", () => {
      document.getElementById("sidebar").classList.toggle("collapsed");
    });
  }

  /* ── Agent Cards ── */

  addAgent(defaults = {}) {
    const id = "agent_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6);
    const color = COLORS[this.agents.length % COLORS.length];
    const agent = {
      id,
      name: defaults.name || `参与者${this.agents.length + 1}`,
      provider: defaults.provider || "openai",
      base_url: defaults.base_url || "",
      api_key: defaults.api_key || "",
      model: defaults.model || "",
      prompt: defaults.prompt || "",
      color,
    };
    this.agents.push(agent);
    this.agentColorMap[agent.name] = color;
    this._renderCard(agent);
  }

  removeAgent(id) {
    const idx = this.agents.findIndex((a) => a.id === id);
    if (idx < 0) return;
    this.agents.splice(idx, 1);
    document.getElementById(id)?.remove();
  }

  _renderCard(agent) {
    const list = document.getElementById("agentsList");
    const card = document.createElement("div");
    card.className = "agent-card expanded";
    card.id = agent.id;
    card.innerHTML = `
      <div class="agent-card-header">
        <span class="agent-color-dot" style="background:${agent.color}"></span>
        <span class="agent-card-name">${agent.name}</span>
        <span class="agent-collapse-icon">&#9654;</span>
        <button class="remove-btn" title="删除">&times;</button>
      </div>
      <div class="agent-card-body">
        <div class="agent-field">
          <label>名称</label>
          <input type="text" data-field="name" value="${agent.name}">
        </div>
        <div class="agent-field">
          <label>Provider</label>
          <select data-field="provider">
            <option value="openai" ${agent.provider === "openai" ? "selected" : ""}>OpenAI 兼容</option>
            <option value="anthropic" ${agent.provider === "anthropic" ? "selected" : ""}>Anthropic</option>
          </select>
        </div>
        <div class="agent-field">
          <label>Base URL（留空使用默认，填到 /v1 即可）</label>
          <input type="text" data-field="base_url" value="${agent.base_url}" placeholder="https://api.openai.com/v1">
        </div>
        <div class="agent-field">
          <label>API Key</label>
          <input type="password" data-field="api_key" value="${agent.api_key}" placeholder="sk-...">
        </div>
        <div class="agent-field">
          <label>Model</label>
          <input type="text" data-field="model" value="${agent.model}" placeholder="gpt-4o / claude-sonnet-4-6">
        </div>
        <div class="agent-field">
          <label>人设 Prompt</label>
          <textarea data-field="prompt" rows="3" placeholder="描述这个角色的背景、性格、观点倾向...">${agent.prompt}</textarea>
        </div>
        <button class="test-btn" data-agent-id="${agent.id}">测试连接</button>
        <div class="test-result" data-result-for="${agent.id}"></div>
      </div>
    `;

    const header = card.querySelector(".agent-card-header");
    header.addEventListener("click", (e) => {
      if (e.target.closest(".remove-btn")) return;
      card.classList.toggle("expanded");
    });

    card.querySelector(".remove-btn").addEventListener("click", () => this.removeAgent(agent.id));

    card.querySelectorAll("[data-field]").forEach((el) => {
      el.addEventListener("input", () => {
        agent[el.dataset.field] = el.value;
        if (el.dataset.field === "name") {
          card.querySelector(".agent-card-name").textContent = el.value;
          this.agentColorMap[el.value] = agent.color;
        }
      });
    });

    card.querySelector(".test-btn").addEventListener("click", () => this.testAgent(agent));

    list.appendChild(card);
  }

  async testAgent(agent) {
    const card = document.getElementById(agent.id);
    const btn = card.querySelector(".test-btn");
    const resultEl = card.querySelector(".test-result");

    btn.disabled = true;
    btn.textContent = "测试中...";
    resultEl.className = "test-result";
    resultEl.textContent = "";

    try {
      const resp = await fetch("/api/test-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: agent.name,
          provider: agent.provider,
          base_url: agent.base_url,
          api_key: agent.api_key,
          model: agent.model,
          prompt: agent.prompt,
        }),
      });
      const data = await resp.json();
      resultEl.textContent = data.message;
      resultEl.classList.add(data.success ? "success" : "fail");
    } catch (e) {
      resultEl.textContent = "请求失败: " + e.message;
      resultEl.classList.add("fail");
    } finally {
      btn.disabled = false;
      btn.textContent = "测试连接";
    }
  }

  _collectConfig() {
    return {
      topic: document.getElementById("topic").value.trim(),
      mode: document.getElementById("mode").value,
      max_rounds: parseInt(document.getElementById("maxRounds").value) || 10,
      agents: this.agents.map((a) => ({
        name: a.name,
        provider: a.provider,
        base_url: a.base_url,
        api_key: a.api_key,
        model: a.model,
        prompt: a.prompt,
      })),
    };
  }

  /* ── Discussion Control ── */

  toggle() {
    if (this.isRunning) {
      this.stop();
    } else {
      this.start();
    }
  }

  start() {
    const config = this._collectConfig();
    if (!config.topic) return alert("请输入讨论话题");
    if (config.agents.length < 2) return alert("至少需要2个参与者");

    for (const a of config.agents) {
      if (!a.api_key) return alert(`请填写 ${a.name} 的 API Key`);
      if (!a.model) return alert(`请填写 ${a.name} 的 Model`);
    }

    this.agentColorMap = {};
    this.agents.forEach((a) => {
      this.agentColorMap[a.name] = a.color;
    });

    this._clearMessages();
    document.getElementById("chatTopic").textContent = config.topic;

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${location.host}/ws`);

    this.ws.onopen = () => {
      this.ws.send(JSON.stringify({ type: "start", config }));
      this._setRunning(true);
    };

    this.ws.onmessage = (e) => this._handleEvent(JSON.parse(e.data));

    this.ws.onclose = () => {
      this._setRunning(false);
    };

    this.ws.onerror = () => {
      alert("WebSocket 连接失败");
      this._setRunning(false);
    };
  }

  stop() {
    if (this.ws) {
      this.ws.send(JSON.stringify({ type: "stop" }));
    }
    this._setRunning(false);
  }

  _setRunning(running) {
    this.isRunning = running;
    const btn = document.getElementById("startBtn");
    if (running) {
      btn.textContent = "停止讨论";
      btn.classList.add("stop");
    } else {
      btn.textContent = "开始讨论";
      btn.classList.remove("stop");
    }
  }

  _clearMessages() {
    const container = document.getElementById("messages");
    container.innerHTML = "";
    this.currentStreamEl = null;
  }

  /* ── Event Handling ── */

  _handleEvent(evt) {
    const container = document.getElementById("messages");

    switch (evt.type) {
      case "moderator":
        this._appendSystem(evt.content);
        break;

      case "round":
        this._appendRound(evt.number);
        break;

      case "thinking":
        this._appendThinking(evt.agent);
        break;

      case "token":
        this._appendToken(evt.agent, evt.content);
        break;

      case "message_done":
        this._finishMessage();
        break;

      case "consensus":
        this._finishMessage();
        this._appendConsensus(evt.message);
        break;

      case "max_rounds":
        this._finishMessage();
        this._appendSystem(evt.message);
        break;

      case "error":
        this._finishMessage();
        this._appendSystem(`${evt.agent} 出错: ${evt.message}`);
        break;

      case "finished":
        this._finishMessage();
        this._setRunning(false);
        document.getElementById("chatStatus").textContent = "已结束";
        break;
    }

    container.scrollTop = container.scrollHeight;
  }

  _getColor(agentName) {
    return this.agentColorMap[agentName] || "#999";
  }

  _appendSystem(text) {
    const container = document.getElementById("messages");
    const el = document.createElement("div");
    el.className = "system-message";
    el.innerHTML = `<span>${this._escapeHtml(text)}</span>`;
    container.appendChild(el);
  }

  _appendRound(number) {
    const container = document.getElementById("messages");
    const el = document.createElement("div");
    el.className = "round-indicator";
    el.innerHTML = `<span>第 ${number} 轮</span>`;
    container.appendChild(el);
    document.getElementById("chatStatus").textContent = `第 ${number} 轮`;
  }

  _appendConsensus(text) {
    const container = document.getElementById("messages");
    const el = document.createElement("div");
    el.className = "consensus-message";
    el.innerHTML = `<span>${this._escapeHtml(text)}</span>`;
    container.appendChild(el);
  }

  _appendThinking(agentName) {
    this._finishMessage();

    const container = document.getElementById("messages");
    const color = this._getColor(agentName);
    const initial = agentName.charAt(0);

    const el = document.createElement("div");
    el.className = "message";
    el.setAttribute("data-agent", agentName);
    el.innerHTML = `
      <div class="message-avatar" style="background-color:${color}">${initial}</div>
      <div class="message-body">
        <div class="message-name" style="color:${color}">${this._escapeHtml(agentName)}</div>
        <div class="message-content">
          <div class="typing-indicator"><span></span><span></span><span></span></div>
        </div>
      </div>
    `;
    container.appendChild(el);
    this.currentStreamEl = el;
  }

  _appendToken(agentName, token) {
    if (!this.currentStreamEl) {
      this._appendThinking(agentName);
    }

    const contentEl = this.currentStreamEl.querySelector(".message-content");
    const typing = contentEl.querySelector(".typing-indicator");
    if (typing) {
      typing.remove();
      contentEl.textContent = "";
    }
    contentEl.textContent += token;
  }

  _finishMessage() {
    if (this.currentStreamEl) {
      const typing = this.currentStreamEl.querySelector(".typing-indicator");
      if (typing) typing.remove();
      this.currentStreamEl = null;
    }
  }

  _escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  window.app = new AgentdTalking();
});
