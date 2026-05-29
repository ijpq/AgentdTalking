const COLORS = [
  "#5c6bc0", "#e53935", "#43a047", "#fb8c00",
  "#8e24aa", "#00897b", "#d81b60", "#1e88e5",
];
const USER_COLOR = "#6d4c41";

class AgentdTalking {
  constructor() {
    this.ws             = null;
    this.agents         = [];
    this.isRunning      = false;
    this.isViewer       = false;
    this.sessionId      = null;
    this.userAlias      = "你";
    this.currentTopic   = "";
    this.chatHistory    = [];          // [{type, agent?, content, number?}]
    this.currentStreamEl      = null;
    this.currentStreamAgent   = null;
    this.currentDeepThinkingEl = null;
    this.reportEl       = null;
    this.reportText     = "";
    this.agentColorMap  = { "你": USER_COLOR };

    this._bindUI();
    this._checkForSession();
    if (!new URLSearchParams(location.search).get("session")) {
      this._checkSavedState();
    }
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

    // Advanced settings collapsible
    document.getElementById("advHeader").addEventListener("click", () => {
      const body  = document.getElementById("advBody");
      const arrow = document.getElementById("advArrow");
      body.classList.toggle("hidden");
      arrow.innerHTML = body.classList.contains("hidden") ? "&#9654;" : "&#9660;";
    });
    // Toggle switch clicks for advanced settings
    ["phasesToggle", "thinkToggle", "moderatorToggle"].forEach((id) => {
      document.getElementById(id).addEventListener("click", () => {
        const cb = document.getElementById(id).querySelector("input[type=checkbox]");
        cb.checked = !cb.checked;
      });
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

    // Share / Export
    document.getElementById("shareBtn").addEventListener("click",  () => this.shareDiscussion());
    document.getElementById("exportBtn").addEventListener("click", () => this.exportDiscussion());
  }

  // ── Session / viewer mode ───────────────────────────────────────────────────

  _checkForSession() {
    const sid = new URLSearchParams(location.search).get("session");
    if (sid) this._joinAsViewer(sid);
  }

  _joinAsViewer(sid) {
    this.isViewer = true;

    // Disable owner controls
    const startBtn = document.getElementById("startBtn");
    startBtn.textContent = "观看模式";
    startBtn.disabled = true;

    document.getElementById("viewerBanner").classList.remove("hidden");
    document.getElementById("exportBtn").classList.remove("hidden");

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${location.host}/ws?session=${encodeURIComponent(sid)}`);
    this.ws.onmessage = (e) => this._handleEvent(JSON.parse(e.data));
    this.ws.onerror   = () => { this._appendSystem("WebSocket 连接失败"); };
    this.ws.onclose   = () => {
      const banner = document.getElementById("viewerBanner");
      banner.textContent = "👁 观看已结束";
      banner.classList.add("ended");
    };
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
    const searchEnabled = document.getElementById("searchEnabled").checked;
    const tavilyKey = document.getElementById("tavilyApiKey").value.trim();
    btn.textContent = searchEnabled && tavilyKey ? "检索+生成中…" : "生成中…";

    try {
      const resp = await fetch("/api/generate-roster", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic, mode: document.getElementById("mode").value, ...llm,
          tavily_api_key: searchEnabled && tavilyKey ? tavilyKey : "",
        }),
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
      topic:            document.getElementById("topic").value.trim(),
      mode:             document.getElementById("mode").value,
      max_rounds:       parseInt(document.getElementById("maxRounds").value) || 10,
      enable_phases:    document.getElementById("enablePhases").checked,
      enable_think:     document.getElementById("enableThink").checked,
      enable_moderator: document.getElementById("enableModerator").checked,
      summary_interval: parseInt(document.getElementById("summaryInterval").value) || 0,
      agents:           this.agents.map((a) => ({
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

    this.userAlias = "你";
    this.agentColorMap = { "你": USER_COLOR };
    this.agents.forEach((a) => { this.agentColorMap[a.name] = a.color; });
    this.currentTopic = config.topic;

    this._clearMessages();
    document.getElementById("chatTopic").textContent = config.topic;
    document.getElementById("chatStatus").classList.remove("hidden");
    document.getElementById("exportBtn").classList.add("hidden");
    document.getElementById("shareBtn").classList.add("hidden");

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
    if (this.isViewer) return;
    const btn = document.getElementById("startBtn");
    const bar = document.getElementById("userInputBar");
    btn.textContent = running ? "停止讨论" : "开始讨论";
    btn.classList.toggle("stop", running);
    bar.classList.toggle("hidden", !running);
    if (running) document.getElementById("userInput").focus();
  }

  _clearMessages() {
    document.getElementById("messages").innerHTML = "";
    this.chatHistory           = [];
    this.currentStreamEl       = null;
    this.currentStreamAgent    = null;
    this.currentDeepThinkingEl = null;
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
      // ── Sharing ──
      case "session_id":
        this.sessionId = evt.id;
        history.pushState({}, "", `?session=${evt.id}`);
        document.getElementById("shareBtn").classList.remove("hidden");
        break;

      case "user_alias":
        this.userAlias = evt.alias;
        this.agentColorMap[evt.alias] = USER_COLOR;
        if (!this.isViewer) {
          document.getElementById("userInput").placeholder = `加入讨论…（你是 ${evt.alias}）`;
        }
        break;

      case "session_not_found":
        this._appendSystem("❌ 会话不存在或已结束，请检查链接");
        break;

      case "history_replay":
        this._clearMessages();
        this.currentTopic = evt.topic;
        this.userAlias = "你";
        document.getElementById("chatTopic").textContent = evt.topic;
        this.agentColorMap = { "你": USER_COLOR };
        evt.events.forEach((e) => this._handleEvent(e));
        if (!evt.active) {
          const banner = document.getElementById("viewerBanner");
          if (banner) { banner.textContent = "👁 讨论已结束"; banner.classList.add("ended"); }
        }
        break;

      // ── Discussion events ──
      case "moderator":    this._appendSystem(evt.content);               break;
      case "round":        this._appendRound(evt.number);                 break;
      case "thinking":     this._appendThinking(evt.agent);               break;
      case "token":        this._appendToken(evt.agent, evt.content);     break;
      case "message_done": this._finishMessage();                          break;
      case "user_spoke":
        if (this.isViewer) this._appendUserMessage(evt.content, evt.agent);
        break;

      case "phase_change":
        this._appendPhaseChange(evt.label || evt.phase);
        break;

      case "deep_thinking":
        this._appendDeepThinking(evt.agent);
        break;

      case "moderator_question":
        this._finishMessage();
        this._appendModeratorQuestion(evt.content);
        break;

      case "summary":
        this._appendSummary(evt.round, evt.content);
        break;

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

      case "report_start":
        this._finishMessage();
        this._startReport();
        break;
      case "report_token":
        this._appendReportToken(evt.content);
        break;
      case "report_done":
        this._finishReport();
        break;
      case "report_failed":
        this._appendSystem(`⚠️ 结论报告生成失败: ${evt.message}`);
        break;

      case "error":
        this._finishMessage();
        this._appendSystem(`${evt.agent} 出错: ${evt.message}`);
        break;

      case "finished":
        this._finishMessage();
        this._setRunning(false);
        document.getElementById("chatStatus").textContent = "已结束";
        if (this.chatHistory.length > 0) {
          document.getElementById("exportBtn").classList.remove("hidden");
          this._appendQualityDashboard();
          this._saveToStorage();
        }
        break;
    }
    document.getElementById("messages").scrollTop = 9999;
  }

  // ── DOM builders ────────────────────────────────────────────────────────────

  _getColor(name) {
    if (!this.agentColorMap[name]) {
      this.agentColorMap[name] = COLORS[Object.keys(this.agentColorMap).length % COLORS.length];
    }
    return this.agentColorMap[name];
  }

  _appendSystemDOM(text) {
    const el = document.createElement("div");
    el.className = "system-message";
    el.innerHTML = `<span>${this._escapeHtml(text)}</span>`;
    document.getElementById("messages").appendChild(el);
  }
  _appendSystem(text) {
    this.chatHistory.push({ type: "system", content: text });
    this._appendSystemDOM(text);
  }

  _appendRoundDOM(n) {
    const el = document.createElement("div");
    el.className = "round-indicator";
    el.innerHTML = `<span>第 ${n} 轮</span>`;
    document.getElementById("messages").appendChild(el);
  }
  _appendRound(n) {
    this.chatHistory.push({ type: "round", number: n });
    this._appendRoundDOM(n);
    if (!this.isViewer) document.getElementById("chatStatus").textContent = `第 ${n} 轮`;
  }

  _appendConsensusDOM(text) {
    const el = document.createElement("div");
    el.className = "consensus-message";
    el.innerHTML = `<span>${this._escapeHtml(text)}</span>`;
    document.getElementById("messages").appendChild(el);
  }
  _appendConsensus(text) {
    this.chatHistory.push({ type: "consensus", content: text });
    this._appendConsensusDOM(text);
  }

  _appendToken(name, token) {
    if (!this.currentStreamEl) this._appendThinking(name);
    const contentEl = this.currentStreamEl.querySelector(".message-content");
    const typing    = contentEl.querySelector(".typing-indicator");
    if (typing) { typing.remove(); contentEl.textContent = ""; }
    contentEl.textContent += token;
  }

  _appendUserMessage(content, displayName = null) {
    const name = displayName || this.userAlias;
    this.chatHistory.push({ type: "user", agent: name, content });
    this._appendUserMessageDOM(content, name);
  }

  _finishMessage() {
    if (this.currentStreamEl) {
      const contentEl = this.currentStreamEl.querySelector(".message-content");
      const typing    = contentEl?.querySelector(".typing-indicator");
      if (typing) typing.remove();
      const text = contentEl?.textContent || "";
      if (text && this.currentStreamAgent) {
        this.chatHistory.push({ type: "message", agent: this.currentStreamAgent, content: text });
      }
      this.currentStreamEl    = null;
      this.currentStreamAgent = null;
    }
  }

  // ── Conclusions report ────────────────────────────────────────────────────────

  _startReport() {
    this.reportText = "";
    const el = document.createElement("div");
    el.className = "report-card";
    el.innerHTML = `
      <div class="report-header">📊 结论报告</div>
      <div class="report-body"><div class="typing-indicator"><span></span><span></span><span></span></div></div>`;
    document.getElementById("messages").appendChild(el);
    this.reportEl = el;
  }

  _appendReportToken(token) {
    if (!this.reportEl) this._startReport();
    this.reportText += token;
    const body = this.reportEl.querySelector(".report-body");
    body.innerHTML = this._renderMarkdown(this.reportText);
    document.getElementById("messages").scrollTop = 9999;
  }

  _finishReport() {
    if (!this.reportEl) return;
    const body = this.reportEl.querySelector(".report-body");
    body.innerHTML = this._renderMarkdown(this.reportText);
    if (this.reportText.trim()) {
      this.chatHistory.push({ type: "report", content: this.reportText });
    }
    this.reportEl = null;
    document.getElementById("exportBtn").classList.remove("hidden");
  }

  _renderMarkdown(md) {
    const lines = md.split("\n");
    let html = "", inList = false;
    for (const line of lines) {
      if (/^\s*[-*]\s+/.test(line)) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += "<li>" + this._inlineMarkdown(this._escapeHtml(line.replace(/^\s*[-*]\s+/, ""))) + "</li>";
        continue;
      }
      if (inList) { html += "</ul>"; inList = false; }
      const h = line.match(/^(#{1,4})\s+(.*)/);
      if (h) {
        const lvl = Math.min(h[1].length + 2, 6);
        html += `<h${lvl}>${this._inlineMarkdown(this._escapeHtml(h[2]))}</h${lvl}>`;
      } else if (line.trim() === "") {
        // blank line — paragraph break handled by block spacing
      } else {
        html += `<p>${this._inlineMarkdown(this._escapeHtml(line))}</p>`;
      }
    }
    if (inList) html += "</ul>";
    return html;
  }

  _inlineMarkdown(s) {
    return s
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }

  // ── Phase / moderator / summary / dashboard DOM builders ─────────────────────

  _appendPhaseChangeDOM(label) {
    const el = document.createElement("div");
    el.className = "phase-indicator";
    el.innerHTML = `<span class="phase-pill">▶ 阶段切换：${this._escapeHtml(label)}</span>`;
    document.getElementById("messages").appendChild(el);
  }
  _appendPhaseChange(label) {
    this.chatHistory.push({ type: "phase", content: label });
    this._appendPhaseChangeDOM(label);
  }

  _appendDeepThinking(name) {
    // Transient "deep thinking" indicator that resolves into the normal thinking bubble
    const existing = document.querySelector(".deep-thinking-row");
    if (existing) existing.remove();
    const el = document.createElement("div");
    el.className = "deep-thinking-row";
    el.innerHTML = `<span class="deep-thinking-pill">🧠 ${this._escapeHtml(name)} 私下推理中…</span>`;
    document.getElementById("messages").appendChild(el);
    this.currentDeepThinkingEl = el;
  }

  _appendThinking(name) {
    // Remove deep-thinking banner if present
    if (this.currentDeepThinkingEl) {
      this.currentDeepThinkingEl.remove();
      this.currentDeepThinkingEl = null;
    }
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
    this.currentStreamEl    = el;
    this.currentStreamAgent = name;
  }

  _appendModeratorQuestionDOM(content) {
    const el = document.createElement("div");
    el.className = "moderator-question";
    el.innerHTML = `<span class="mq-badge">🎙 主持人</span><span class="mq-text">${this._escapeHtml(content)}</span>`;
    document.getElementById("messages").appendChild(el);
  }
  _appendModeratorQuestion(content) {
    this.chatHistory.push({ type: "moderator_q", content });
    this._appendModeratorQuestionDOM(content);
  }

  _appendSummaryDOM(round, content) {
    const el = document.createElement("div");
    el.className = "summary-card";
    el.innerHTML = `
      <div class="summary-header" data-open="false">
        📋 第 ${round} 轮进展快照 <span class="summary-toggle">▼ 展开</span>
      </div>
      <div class="summary-body hidden">${this._renderMarkdown(this._escapeHtml(content))}</div>`;
    el.querySelector(".summary-header").addEventListener("click", function() {
      const body  = el.querySelector(".summary-body");
      const tog   = el.querySelector(".summary-toggle");
      const open  = this.dataset.open === "true";
      body.classList.toggle("hidden", open);
      tog.textContent = open ? "▼ 展开" : "▲ 收起";
      this.dataset.open = String(!open);
    });
    document.getElementById("messages").appendChild(el);
  }
  _appendSummary(round, content) {
    this.chatHistory.push({ type: "summary", round, content });
    this._appendSummaryDOM(round, content);
  }

  _appendCompletedMessage(name, content) {
    const color = this._getColor(name);
    const el = document.createElement("div");
    el.className = "message";
    el.innerHTML = `
      <div class="message-avatar" style="background:${color}">${name.charAt(0)}</div>
      <div class="message-body">
        <div class="message-name" style="color:${color}">${this._escapeHtml(name)}</div>
        <div class="message-content">${this._escapeHtml(content)}</div>
      </div>`;
    document.getElementById("messages").appendChild(el);
  }

  _appendUserMessageDOM(content, displayName) {
    const name = displayName || this.userAlias;
    const el = document.createElement("div");
    el.className = "message message-user";
    el.innerHTML = `
      <div class="message-avatar" style="background:${USER_COLOR}">${this._escapeHtml(name.charAt(0))}</div>
      <div class="message-body">
        <div class="message-name" style="color:${USER_COLOR}">${this._escapeHtml(name)}</div>
        <div class="message-content">${this._escapeHtml(content)}</div>
      </div>`;
    document.getElementById("messages").appendChild(el);
  }

  _appendQualityDashboard() {
    const metrics = this._computeQuality();
    if (!metrics) return;
    const el = document.createElement("div");
    el.className = "quality-dashboard";
    const bars = Object.entries(metrics.byAgent)
      .sort((a, b) => b[1].msgs - a[1].msgs)
      .map(([name, d]) => {
        const color = this._getColor(name);
        const pct   = Math.round((d.msgs / metrics.totalAgentMsgs) * 100);
        return `<div class="qd-agent-row">
          <div class="qd-name" style="color:${color}">${this._escapeHtml(name)}</div>
          <div class="qd-bar-wrap"><div class="qd-bar" style="width:${pct}%;background:${color}"></div></div>
          <div class="qd-stat">${d.msgs} 条</div>
        </div>`;
      }).join("");
    el.innerHTML = `
      <div class="qd-header">📊 讨论质量指标</div>
      <div class="qd-body">
        <div class="qd-grid">
          <div class="qd-kpi"><div class="qd-kpi-val">${metrics.rounds}</div><div class="qd-kpi-label">完成轮数</div></div>
          <div class="qd-kpi"><div class="qd-kpi-val">${metrics.totalAgentMsgs}</div><div class="qd-kpi-label">AI 发言数</div></div>
          <div class="qd-kpi"><div class="qd-kpi-val">${metrics.disagreeRate}%</div><div class="qd-kpi-label">分歧密度</div></div>
          <div class="qd-kpi"><div class="qd-kpi-val">${metrics.moderatorCount}</div><div class="qd-kpi-label">主持人干预</div></div>
        </div>
        <div class="qd-section-label">发言分布</div>
        ${bars}
      </div>`;
    document.getElementById("messages").appendChild(el);
  }

  _computeQuality() {
    if (!this.chatHistory.length) return null;
    const agentMsgs = this.chatHistory.filter(h => h.type === "message");
    if (!agentMsgs.length) return null;
    const byAgent = {};
    for (const h of agentMsgs) {
      if (!byAgent[h.agent]) byAgent[h.agent] = { msgs: 0, chars: 0 };
      byAgent[h.agent].msgs++;
      byAgent[h.agent].chars += (h.content || "").length;
    }
    const allText = agentMsgs.map(h => h.content || "").join(" ");
    const disagree = (allText.match(/不对|不是|但是|然而|相反|错误|漏洞|问题|反对|质疑|等等|不认为|不成立|站不住脚|这个逻辑|这个前提/g) || []).length;
    const agree    = (allText.match(/对对|同意|确实|说得对|有道理|我也|没错|是的|赞同|完全正确/g) || []).length;
    const total = disagree + agree;
    return {
      byAgent,
      rounds:         this.chatHistory.filter(h => h.type === "round").length,
      totalAgentMsgs: agentMsgs.length,
      disagreeRate:   total > 0 ? Math.round(disagree / total * 100) : 0,
      moderatorCount: this.chatHistory.filter(h => h.type === "moderator_q").length,
    };
  }

  // ── LocalStorage save / restore ───────────────────────────────────────────────

  _saveToStorage() {
    try {
      const state = {
        savedAt:      Date.now(),
        currentTopic: this.currentTopic,
        chatHistory:  this.chatHistory,
        agentColorMap: this.agentColorMap,
      };
      localStorage.setItem("agentdtalking_history", JSON.stringify(state));
    } catch (e) {}
  }

  _checkSavedState() {
    try {
      const raw = localStorage.getItem("agentdtalking_history");
      if (!raw) return;
      const state = JSON.parse(raw);
      if (!state.chatHistory?.length || !state.currentTopic) return;
      const age = Math.round((Date.now() - state.savedAt) / 60000);
      const label = age < 60 ? `${age} 分钟前` : `${Math.round(age / 60)} 小时前`;
      this._showRestoreBanner(state, label);
    } catch (e) {}
  }

  _showRestoreBanner(state, label) {
    const banner = document.createElement("div");
    banner.className = "restore-banner";
    banner.id = "restoreBanner";
    banner.innerHTML = `
      <span>💾 发现上次讨论记录（${this._escapeHtml(state.currentTopic.slice(0, 30))}…，${label}）</span>
      <button id="restoreYes">恢复</button>
      <button id="restoreNo">忽略</button>`;
    document.body.prepend(banner);
    document.getElementById("restoreYes").addEventListener("click", () => {
      this._restoreHistory(state);
      banner.remove();
    });
    document.getElementById("restoreNo").addEventListener("click", () => {
      localStorage.removeItem("agentdtalking_history");
      banner.remove();
    });
  }

  _restoreHistory(state) {
    const saved = state.chatHistory || [];
    this.currentTopic  = state.currentTopic;
    this.agentColorMap = { ...{ "你": USER_COLOR }, ...(state.agentColorMap || {}) };
    document.getElementById("chatTopic").textContent = state.currentTopic;
    document.getElementById("chatStatus").classList.remove("hidden");
    document.getElementById("chatStatus").textContent = "已恢复";
    document.getElementById("exportBtn").classList.remove("hidden");
    this._clearMessages();
    // Replay saved history into DOM without re-pushing to chatHistory
    for (const h of saved) {
      if (h.type === "round")         { this._appendRoundDOM(h.number); }
      else if (h.type === "system")   { this._appendSystemDOM(h.content); }
      else if (h.type === "consensus"){ this._appendConsensusDOM(h.content); }
      else if (h.type === "phase")    { this._appendPhaseChangeDOM(h.content); }
      else if (h.type === "moderator_q") { this._appendModeratorQuestionDOM(h.content); }
      else if (h.type === "summary")  { this._appendSummaryDOM(h.round, h.content); }
      else if (h.type === "report")   { this._appendRestoredReport(h.content); }
      else if (h.type === "message")  { this._appendCompletedMessage(h.agent, h.content); }
      else if (h.type === "user")     { this._appendUserMessageDOM(h.content, h.agent); }
    }
    this.chatHistory = saved;
    this._appendQualityDashboard();
  }

  _appendRestoredReport(content) {
    const el = document.createElement("div");
    el.className = "report-card";
    el.innerHTML = `
      <div class="report-header">📊 结论报告</div>
      <div class="report-body">${this._renderMarkdown(this._escapeHtml(content))}</div>`;
    document.getElementById("messages").appendChild(el);
  }

  // ── Export ──────────────────────────────────────────────────────────────────

  exportDiscussion() {
    if (!this.chatHistory.length) return;
    const topic = this.currentTopic || "讨论";
    const lines = [
      `# 讨论记录\n\n`,
      `**话题：** ${topic}\n\n`,
      `**时间：** ${new Date().toLocaleString("zh-CN")}\n\n`,
      `---\n\n`,
    ];
    for (const h of this.chatHistory) {
      if (h.type === "round") {
        lines.push(`\n---\n\n**第 ${h.number} 轮**\n\n`);
      } else if (h.type === "phase") {
        lines.push(`\n> 🔄 阶段：${h.content}\n\n`);
      } else if (h.type === "system") {
        lines.push(`> ${h.content}\n\n`);
      } else if (h.type === "moderator_q") {
        lines.push(`> 🎙 **主持人插问：** ${h.content}\n\n`);
      } else if (h.type === "summary") {
        lines.push(`\n### 📋 第 ${h.round} 轮进展快照\n\n${h.content}\n\n`);
      } else if (h.type === "consensus") {
        lines.push(`\n✅ **${h.content}**\n\n`);
      } else if (h.type === "report") {
        lines.push(`\n---\n\n# 📊 结论报告\n\n${h.content}\n\n`);
      } else if (h.type === "message" || h.type === "user") {
        lines.push(`**${h.agent || "你"}：**\n\n${h.content}\n\n`);
      }
    }
    const blob = new Blob([lines.join("")], { type: "text/markdown;charset=utf-8" });
    const url  = URL.createObjectURL(blob);
    const safe = topic.replace(/[^一-龥\w]/g, "").slice(0, 12) || "discussion";
    const a    = Object.assign(document.createElement("a"), {
      href: url, download: `讨论_${safe}_${Date.now()}.md`,
    });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ── Share ───────────────────────────────────────────────────────────────────

  shareDiscussion() {
    const url  = location.href;
    const btn  = document.getElementById("shareBtn");
    const orig = btn.textContent;
    const done = () => { btn.textContent = "✓ 已复制"; setTimeout(() => { btn.textContent = orig; }, 2200); };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(done).catch(() => prompt("复制此链接：", url));
    } else {
      prompt("复制此链接：", url);
    }
  }

  // ── Util ────────────────────────────────────────────────────────────────────

  _escapeHtml(str = "") {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }
}

document.addEventListener("DOMContentLoaded", () => { window.app = new AgentdTalking(); });
