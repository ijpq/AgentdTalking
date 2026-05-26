const COLORS = [
  "#5c6bc0", "#e53935", "#43a047", "#fb8c00",
  "#8e24aa", "#00897b", "#d81b60", "#1e88e5",
];
const USER_COLOR = "#6d4c41";

class AgentdTalking {
  constructor() {
    this.ws          = null;
    this.agents      = [];
    this.isRunning   = false;
    this.currentStreamEl = null;
    this.agentColorMap   = { "你": USER_COLOR };

    this._bindUI();
  }

  // ── UI binding ──────────────────────────────────────────────────────────────

  _bindUI() {
    document.getElementById("addAgent").addEventListener("click", () => this.addAgent());
    document.getElementById("startBtn").addEventListener("click", () => this.toggle());
    document.getElementById("toggleSidebar").addEventListener("click", () => {
      document.getElementById("sidebar").classList.toggle("collapsed");
    });
    document.getElementById("aiGenBtn").addEventListener("click", () => this.generateRoster());

    // Global LLM collapsible
    document.getElementById("globalLlmHeader").addEventListener("click", () => {
      const body  = document.getElementById("globalLlmBody");
      const arrow = document.getElementById("globalLlmArrow");
      body.classList.toggle("hidden");
      arrow.innerHTML = body.classList.contains("hidden") ? "&#9654;" : "&#9660;";
    });

    // Global LLM test button
    document.getElementById("testGlobalBtn").addEventListener("click", () => this.testGlobalLlm());

    // Tavily toggle
    document.getElementById("searchToggle").addEventListener("click", () => {
      const cb = document.getElementById("searchEnabled");
      cb.checked = !cb.checked;
      document.getElementById("searchConfig").classList.toggle("hidden", !cb.checked);
    });

    // User input
    document.getElementById("userSendBtn").addEventListener("click",  () => this.sendUserMessage());
    document.getElementById("userInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.sendUserMessage(); }
    });
  }

  // ── Global LLM helpers ──────────────────────────────────────────────────────

  _globalLlmConfig() {
    return {
      provider: document.getElementById("globalProvider").value,
      base_url: document.getElementById("globalBaseUrl").value.trim(),
      api_key:  document.getElementById("globalApiKey").value.trim(),
      model:    document.getElementById("globalModel").value.trim(),
    };
  }

  async testGlobalLlm() {
    const llm = this._globalLlmConfig();
    const btn = document.getElementById("testGlobalBtn");
    const resultEl = document.getElementById("globalTestResult");
    const dot = document.getElementById("globalLlmDot");

    btn.disabled = true;
    btn.textContent = "测试中…";
    resultEl.textContent = "";
    resultEl.className = "global-test-result";
    dot.className = "dot";

    try {
      const resp = await fetch("/api/test-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "global-test", ...llm, prompt: "" }),
      });
      const data = await resp.json();
      resultEl.textContent = data.message;
      resultEl.classList.add(data.success ? "ok" : "err");
      dot.classList.add(data.success ? "ok" : "err");
    } catch (e) {
      resultEl.textContent = "请求失败: " + e.message;
      resultEl.classList.add("err");
      dot.classList.add("err");
    } finally {
      btn.disabled = false;
      btn.textContent = "测试连接";
    }
  }

  // ── AI roster generation ────────────────────────────────────────────────────

  async generateRoster() {
    const topic = document.getElementById("topic").value.trim();
    if (!topic) return alert("请先输入话题");

    const llm = this._globalLlmConfig();
    if (!llm.api_key || !llm.model) {
      document.getElementById("globalLlmBody").classList.remove("hidden");
      document.getElementById("globalLlmArrow").innerHTML = "&#9660;";
      return alert("请先在「全局 LLM 配置」中填写 API Key 和 Model");
    }

    const btn = document.getElementById("aiGenBtn");
    btn.disabled = true;
    btn.textContent = "生成中…";

    try {
      const resp = await fetch("/api/generate-roster", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, mode: document.getElementById("mode").value, ...llm }),
      });
      const data = await resp.json();
      if (!data.success) { alert("生成失败：" + data.message); return; }
      [...this.agents].forEach((a) => this.removeAgent(a.id));
      data.agents.forEach((a) => this.addAgent({ ...a, ...llm }));
    } catch (e) {
      alert("请求失败：" + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "✦ AI 生成";
    }
  }

  // ── Agent cards ─────────────────────────────────────────────────────────────

  _updateSearchCount() {
    const el = document.getElementById("searchCount");
    if (el) el.textContent = this.agents.length;
  }

  addAgent(defaults = {}) {
    const llm   = this._globalLlmConfig();
    const id    = "agent_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6);
    const color = COLORS[this.agents.length % COLORS.length];
    const agent = {
      id,
      name:     defaults.name     || `参与者${this.agents.length + 1}`,
      provider: defaults.provider || llm.provider || "openai",
      base_url: defaults.base_url ?? llm.base_url,
      api_key:  defaults.api_key  ?? llm.api_key,
      model:    defaults.model    ?? llm.model,
      prompt:   defaults.prompt   || "",
      color,
    };
    this.agents.push(agent);
    this.agentColorMap[agent.name] = color;
    this._renderCard(agent);
    this._updateSearchCount();
  }

  removeAgent(id) {
    const idx = this.agents.findIndex((a) => a.id === id);
    if (idx < 0) return;
    this.agents.splice(idx, 1);
    document.getElementById(id)?.remove();
    this._updateSearchCount();
  }

  _renderCard(agent) {
    const list = document.getElementById("agentsList");
    const card = document.createElement("div");
    card.className = "agent-card expanded";
    card.id = agent.id;
    card.innerHTML = `
      <div class="agent-card-header">
        <div class="agent-color-bar" style="background:${agent.color}"></div>
        <span class="agent-card-name">${this._escapeHtml(agent.name)}</span>
        <span class="agent-collapse-icon">&#9654;</span>
        <button class="remove-btn" title="删除">&times;</button>
      </div>
      <div class="agent-card-body">
        <div class="agent-field">
          <label>名称</label>
          <input type="text" data-field="name" value="${this._escapeHtml(agent.name)}">
        </div>
        <div class="agent-field">
          <label>Provider</label>
          <select data-field="provider">
            <option value="openai"     ${agent.provider === "openai"     ? "selected" : ""}>OpenAI 兼容</option>
            <option value="anthropic"  ${agent.provider === "anthropic"  ? "selected" : ""}>Anthropic</option>
          </select>
        </div>
        <div class="agent-field">
          <label>Base URL</label>
          <input type="text"     data-field="base_url" value="${this._escapeHtml(agent.base_url)}" placeholder="https://api.openai.com/v1">
        </div>
        <div class="agent-field">
          <label>API Key</label>
          <input type="password" data-field="api_key"  value="${this._escapeHtml(agent.api_key)}"  placeholder="sk-...">
        </div>
        <div class="agent-field">
          <label>Model</label>
          <input type="text"     data-field="model"    value="${this._escapeHtml(agent.model)}"    placeholder="gpt-4o">
        </div>
        <div class="agent-field">
          <label>人设 Prompt</label>
          <textarea data-field="prompt" rows="3" placeholder="描述这个角色的背景、性格、观点倾向…">${this._escapeHtml(agent.prompt)}</textarea>
        </div>
        <button class="test-btn">测试连接</button>
        <div class="test-result"></div>
      </div>`;

    card.querySelector(".agent-card-header").addEventListener("click", (e) => {
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
    card.querySelector(".test-btn").addEventListener("click", () => this.testAgent(agent, card));
    list.appendChild(card);
  }

  async testAgent(agent, card) {
    const btn      = card.querySelector(".test-btn");
    const resultEl = card.querySelector(".test-result");
    btn.disabled = true;
    btn.textContent = "测试中…";
    resultEl.className = "test-result";
    resultEl.textContent = "";
    try {
      const resp = await fetch("/api/test-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: agent.name, provider: agent.provider,
          base_url: agent.base_url, api_key: agent.api_key,
          model: agent.model, prompt: agent.prompt }),
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

  // ── Config ──────────────────────────────────────────────────────────────────

  _collectConfig() {
    const searchEnabled = document.getElementById("searchEnabled").checked;
    const tavilyKey     = document.getElementById("tavilyApiKey").value.trim();
    return {
      topic:      document.getElementById("topic").value.trim(),
      mode:       document.getElementById("mode").value,
      max_rounds: parseInt(document.getElementById("maxRounds").value) || 10,
      agents:     this.agents.map((a) => ({
        name: a.name, provider: a.provider, base_url: a.base_url,
        api_key: a.api_key, model: a.model, prompt: a.prompt,
      })),
      search: searchEnabled && tavilyKey ? { provider: "tavily", api_key: tavilyKey } : null,
    };
  }

  // ── Discussion ──────────────────────────────────────────────────────────────

  toggle() { this.isRunning ? this.stop() : this.start(); }

  start() {
    const config = this._collectConfig();
    if (!config.topic)              return alert("请输入讨论话题");
    if (config.agents.length < 2)  return alert("至少需要 2 个参与者");
    for (const a of config.agents) {
      if (!a.api_key) return alert(`请填写「${a.name}」的 API Key`);
      if (!a.model)   return alert(`请填写「${a.name}」的 Model`);
    }

    this.agentColorMap = { "你": USER_COLOR };
    this.agents.forEach((a) => { this.agentColorMap[a.name] = a.color; });

    this._clearMessages();
    document.getElementById("chatTopic").textContent = config.topic;
    document.getElementById("chatStatus").classList.remove("hidden");

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws.onopen    = () => { this.ws.send(JSON.stringify({ type: "start", config })); this._setRunning(true); };
    this.ws.onmessage = (e) => this._handleEvent(JSON.parse(e.data));
    this.ws.onclose   = () => this._setRunning(false);
    this.ws.onerror   = () => { alert("WebSocket 连接失败"); this._setRunning(false); };
  }

  stop() {
    if (this.ws) this.ws.send(JSON.stringify({ type: "stop" }));
    this._setRunning(false);
  }

  _setRunning(running) {
    this.isRunning = running;
    const btn = document.getElementById("startBtn");
    const bar = document.getElementById("userInputBar");
    btn.textContent = running ? "停止讨论" : "开始讨论";
    btn.classList.toggle("stop", running);
    bar.classList.toggle("hidden", !running);
    if (running) document.getElementById("userInput").focus();
  }

  _clearMessages() {
    document.getElementById("messages").innerHTML = "";
    this.currentStreamEl = null;
  }

  // ── User message ────────────────────────────────────────────────────────────

  sendUserMessage() {
    const input   = document.getElementById("userInput");
    const content = input.value.trim();
    if (!content || !this.isRunning) return;
    input.value = "";
    this._finishMessage();
    this._appendUserMessage(content);
    if (this.ws) this.ws.send(JSON.stringify({ type: "user_message", content }));
  }

  // ── Event handling ──────────────────────────────────────────────────────────

  _handleEvent(evt) {
    switch (evt.type) {
      case "moderator":    this._appendSystem(evt.content);               break;
      case "round":        this._appendRound(evt.number);                 break;
      case "thinking":     this._appendThinking(evt.agent);               break;
      case "token":        this._appendToken(evt.agent, evt.content);     break;
      case "message_done": this._finishMessage();                          break;
      case "user_spoke":                                                   break;
      case "consensus":
        this._finishMessage();
        this._appendConsensus(evt.message);
        break;
      case "max_rounds":
        this._finishMessage();
        this._appendSystem(evt.message);
        break;
      case "searching":
        this._appendSystem(`🔍 ${evt.agent} 正在检索最新资料…`);
        break;
      case "search_done":   break;
      case "search_failed":
        this._appendSystem(`⚠️ ${evt.agent} 检索失败: ${evt.message}`);
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
    document.getElementById("messages").scrollTop = 9999;
  }

  // ── DOM builders ────────────────────────────────────────────────────────────

  _getColor(name) { return this.agentColorMap[name] || "#90a4ae"; }

  _appendSystem(text) {
    const el = document.createElement("div");
    el.className = "system-message";
    el.innerHTML = `<span>${this._escapeHtml(text)}</span>`;
    document.getElementById("messages").appendChild(el);
  }

  _appendRound(n) {
    const el = document.createElement("div");
    el.className = "round-indicator";
    el.innerHTML = `<span>第 ${n} 轮</span>`;
    document.getElementById("messages").appendChild(el);
    document.getElementById("chatStatus").textContent = `第 ${n} 轮`;
  }

  _appendConsensus(text) {
    const el = document.createElement("div");
    el.className = "consensus-message";
    el.innerHTML = `<span>${this._escapeHtml(text)}</span>`;
    document.getElementById("messages").appendChild(el);
  }

  _appendThinking(name) {
    this._finishMessage();
    const color = this._getColor(name);
    const el = document.createElement("div");
    el.className = "message";
    el.setAttribute("data-agent", name);
    el.innerHTML = `
      <div class="message-avatar" style="background:${color}">${name.charAt(0)}</div>
      <div class="message-body">
        <div class="message-name" style="color:${color}">${this._escapeHtml(name)}</div>
        <div class="message-content">
          <div class="typing-indicator"><span></span><span></span><span></span></div>
        </div>
      </div>`;
    document.getElementById("messages").appendChild(el);
    this.currentStreamEl = el;
  }

  _appendToken(name, token) {
    if (!this.currentStreamEl) this._appendThinking(name);
    const contentEl = this.currentStreamEl.querySelector(".message-content");
    const typing    = contentEl.querySelector(".typing-indicator");
    if (typing) { typing.remove(); contentEl.textContent = ""; }
    contentEl.textContent += token;
  }

  _appendUserMessage(content) {
    const el = document.createElement("div");
    el.className = "message message-user";
    el.innerHTML = `
      <div class="message-avatar" style="background:${USER_COLOR}">你</div>
      <div class="message-body">
        <div class="message-name" style="color:${USER_COLOR}">你</div>
        <div class="message-content">${this._escapeHtml(content)}</div>
      </div>`;
    document.getElementById("messages").appendChild(el);
  }

  _finishMessage() {
    if (this.currentStreamEl) {
      this.currentStreamEl.querySelector(".typing-indicator")?.remove();
      this.currentStreamEl = null;
    }
  }

  _escapeHtml(str = "") {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }
}

document.addEventListener("DOMContentLoaded", () => { window.app = new AgentdTalking(); });
