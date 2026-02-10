"""Multi-agent dashboard for Orchestack."""

DASHBOARD_HTML: str = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Orchestack Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface-hover: #232634;
    --border: #2e3241;
    --text: #e2e4ea;
    --text-muted: #8b8fa3;
    --primary: #6c72cb;
    --primary-hover: #7f84d4;
    --user-bubble: #2d3152;
    --bot-bubble: #1e2133;
    --danger: #e05252;
    --success: #4caf50;
    --radius: 10px;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             "Helvetica Neue", Arial, sans-serif;
    --mono: "SF Mono", "Fira Code", "Fira Mono", "Roboto Mono", monospace;
  }

  html, body {
    height: 100%; width: 100%;
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
  }

  #grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    grid-template-rows: repeat(2, 1fr);
    gap: 3px;
    height: 100vh;
    width: 100vw;
    background: var(--bg);
  }

  .pane {
    display: flex;
    flex-direction: column;
    background: var(--surface);
    overflow: hidden;
    border: 1px solid var(--border);
  }

  .pane-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    flex-shrink: 0;
    border-bottom: 2px solid var(--border);
    min-height: 40px;
  }

  .pane-header .emoji {
    font-size: 16px;
    flex-shrink: 0;
  }

  .pane-header .agent-name {
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .pane-header .agent-role {
    font-size: 10px;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-left: auto;
  }

  .pane-header .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--danger);
    flex-shrink: 0;
    transition: background 0.3s;
  }

  .pane-header .status-dot.connected {
    background: var(--success);
  }

  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .msg {
    max-width: 85%;
    padding: 6px 10px;
    border-radius: var(--radius);
    line-height: 1.4;
    font-size: 12px;
    word-wrap: break-word;
    white-space: pre-wrap;
  }

  .msg.user {
    align-self: flex-end;
    background: var(--user-bubble);
    border-bottom-right-radius: 3px;
  }

  .msg.bot {
    align-self: flex-start;
    background: var(--bot-bubble);
    border: 1px solid var(--border);
    border-bottom-left-radius: 3px;
  }

  .msg.system {
    align-self: center;
    font-size: 10px;
    color: var(--text-muted);
    background: transparent;
    padding: 2px 6px;
  }

  .msg .ts {
    display: block;
    font-size: 9px;
    color: var(--text-muted);
    margin-top: 2px;
    text-align: right;
  }

  .typing-indicator {
    align-self: flex-start;
    display: none;
    padding: 8px 12px;
    background: var(--bot-bubble);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    border-bottom-left-radius: 3px;
  }

  .typing-indicator.visible {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .typing-indicator .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--text-muted);
    animation: typingPulse 1.4s infinite ease-in-out;
  }

  .typing-indicator .dot:nth-child(2) { animation-delay: 0.2s; }
  .typing-indicator .dot:nth-child(3) { animation-delay: 0.4s; }

  @keyframes typingPulse {
    0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
    30% { opacity: 1; transform: scale(1); }
  }

  .input-area {
    display: flex;
    align-items: flex-end;
    gap: 4px;
    padding: 6px 8px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
    background: var(--surface);
  }

  .input-area textarea {
    flex: 1;
    resize: none;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg);
    color: var(--text);
    padding: 6px 10px;
    font-size: 12px;
    font-family: var(--font);
    line-height: 1.3;
    max-height: 60px;
    overflow-y: auto;
    rows: 1;
  }

  .input-area textarea:focus {
    outline: none;
    border-color: var(--primary);
  }

  .input-area textarea::placeholder {
    color: var(--text-muted);
  }

  .send-btn {
    width: 32px;
    height: 32px;
    border: none;
    border-radius: var(--radius);
    background: var(--primary);
    color: #fff;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: background 0.15s;
  }

  .send-btn:hover {
    background: var(--primary-hover);
  }

  .send-btn svg {
    width: 14px;
    height: 14px;
  }

  /* Control panel styles */
  .control-panel {
    display: flex;
    flex-direction: column;
    background: var(--surface);
    overflow: hidden;
    border: 1px solid var(--border);
  }

  .control-panel .pane-header {
    border-bottom: 2px solid var(--border);
  }

  .control-content {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .control-section h3 {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }

  .health-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px;
  }

  .health-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    background: var(--bg);
    border-radius: 6px;
    font-size: 11px;
  }

  .health-item .h-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .health-item .h-dot.up { background: var(--success); }
  .health-item .h-dot.down { background: var(--danger); }
  .health-item .h-dot.unknown { background: var(--text-muted); }

  .agent-status-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .agent-status-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 8px;
    background: var(--bg);
    border-radius: 6px;
    font-size: 11px;
  }

  .agent-status-row .a-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .agent-status-row .a-dot.connected { background: var(--success); }
  .agent-status-row .a-dot.disconnected { background: var(--danger); }

  .agent-status-row .a-name {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .agent-status-row .a-count {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--text-muted);
    flex-shrink: 0;
  }

  /* Scrollbar styling */
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 2px;
  }
  ::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
  }

  /* Per-agent accent colors applied to the header bottom border */
  .accent-homarus .pane-header { border-bottom-color: #e06c75; }
  .accent-ken .pane-header { border-bottom-color: #61afef; }
  .accent-mercer .pane-header { border-bottom-color: #e5c07b; }
  .accent-rory .pane-header { border-bottom-color: #56b6c2; }
  .accent-scarlet .pane-header { border-bottom-color: #c678dd; }
  .accent-ive .pane-header { border-bottom-color: #98c379; }
  .accent-mark .pane-header { border-bottom-color: #d19a66; }
</style>
</head>
<body>

<div id="grid"></div>

<script>
(function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* Agent definitions                                                   */
  /* ------------------------------------------------------------------ */

  var AGENTS = [
    {
      name: "Homarus",
      slug: "homarus",
      role: "Chief of Staff",
      uuid: "00000000-0000-0000-0000-00000000a001",
      emoji: "\\u{1F99E}",
      accent: "accent-homarus"
    },
    {
      name: "Ken",
      slug: "ken",
      role: "Software Engineering",
      uuid: "00000000-0000-0000-0000-00000000a002",
      emoji: "\\u{1F4BB}",
      accent: "accent-ken"
    },
    {
      name: "Mercer",
      slug: "mercer",
      role: "Finance",
      uuid: "00000000-0000-0000-0000-00000000a003",
      emoji: "\\u{1F4B0}",
      accent: "accent-mercer"
    },
    {
      name: "Rory",
      slug: "rory",
      role: "Revenue Operations",
      uuid: "00000000-0000-0000-0000-00000000a004",
      emoji: "\\u{1F4C8}",
      accent: "accent-rory"
    },
    {
      name: "Scarlet",
      slug: "scarlet",
      role: "Red Hat / DevOps",
      uuid: "00000000-0000-0000-0000-00000000a005",
      emoji: "\\u{1F9E2}",
      accent: "accent-scarlet"
    },
    {
      name: "Ive",
      slug: "ive",
      role: "UI/UX Design",
      uuid: "00000000-0000-0000-0000-00000000a006",
      emoji: "\\u{1F3A8}",
      accent: "accent-ive"
    },
    {
      name: "Mark",
      slug: "mark",
      role: "Creative Director",
      uuid: "00000000-0000-0000-0000-00000000a007",
      emoji: "\\u{1F3AC}",
      accent: "accent-mark"
    }
  ];

  /* ------------------------------------------------------------------ */
  /* State tracking                                                      */
  /* ------------------------------------------------------------------ */

  var agentState = {};
  AGENTS.forEach(function (a) {
    agentState[a.slug] = {
      ws: null,
      sessionId: null,
      reconnectDelay: 1000,
      reconnectTimer: null,
      connected: false,
      messageCount: 0,
      streamingEls: {},
      waiting: false
    };
  });

  var MAX_RECONNECT = 30000;

  /* ------------------------------------------------------------------ */
  /* Utility helpers                                                      */
  /* ------------------------------------------------------------------ */

  function ts() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function storageKey(slug) {
    return "orchestack_dashboard_" + slug;
  }

  function scrollBottom(el) {
    el.scrollTop = el.scrollHeight;
  }

  /* ------------------------------------------------------------------ */
  /* DOM creation helpers                                                 */
  /* ------------------------------------------------------------------ */

  function createAgentPane(agent) {
    var pane = document.createElement("div");
    pane.className = "pane " + agent.accent;
    pane.id = "pane-" + agent.slug;

    /* Header */
    var header = document.createElement("div");
    header.className = "pane-header";

    var emoji = document.createElement("span");
    emoji.className = "emoji";
    emoji.textContent = agent.emoji;
    header.appendChild(emoji);

    var name = document.createElement("span");
    name.className = "agent-name";
    name.textContent = agent.name;
    header.appendChild(name);

    var role = document.createElement("span");
    role.className = "agent-role";
    role.textContent = agent.role;
    header.appendChild(role);

    var dot = document.createElement("span");
    dot.className = "status-dot";
    dot.id = "dot-" + agent.slug;
    header.appendChild(dot);

    pane.appendChild(header);

    /* Messages area */
    var messages = document.createElement("div");
    messages.className = "messages";
    messages.id = "messages-" + agent.slug;

    /* Typing indicator */
    var typing = document.createElement("div");
    typing.className = "typing-indicator";
    typing.id = "typing-" + agent.slug;
    for (var i = 0; i < 3; i++) {
      var d = document.createElement("span");
      d.className = "dot";
      typing.appendChild(d);
    }
    messages.appendChild(typing);

    pane.appendChild(messages);

    /* Input area */
    var inputArea = document.createElement("div");
    inputArea.className = "input-area";

    var textarea = document.createElement("textarea");
    textarea.rows = 1;
    textarea.placeholder = "Message " + agent.name + "...";
    textarea.id = "input-" + agent.slug;
    inputArea.appendChild(textarea);

    var sendBtn = document.createElement("button");
    sendBtn.className = "send-btn";
    sendBtn.title = "Send";
    sendBtn.id = "send-" + agent.slug;
    sendBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
    inputArea.appendChild(sendBtn);

    pane.appendChild(inputArea);

    return pane;
  }

  function createControlPanel() {
    var pane = document.createElement("div");
    pane.className = "control-panel";

    /* Header */
    var header = document.createElement("div");
    header.className = "pane-header";
    header.style.borderBottomColor = "var(--primary)";

    var gearIcon = document.createElement("span");
    gearIcon.className = "emoji";
    gearIcon.textContent = "\\u2699\\uFE0F";
    header.appendChild(gearIcon);

    var title = document.createElement("span");
    title.className = "agent-name";
    title.textContent = "Control Panel";
    header.appendChild(title);

    pane.appendChild(header);

    /* Content */
    var content = document.createElement("div");
    content.className = "control-content";

    /* Service health section */
    var healthSection = document.createElement("div");
    healthSection.className = "control-section";
    var healthTitle = document.createElement("h3");
    healthTitle.textContent = "Service Health";
    healthSection.appendChild(healthTitle);
    var healthGrid = document.createElement("div");
    healthGrid.className = "health-grid";
    healthGrid.id = "health-grid";
    healthSection.appendChild(healthGrid);
    content.appendChild(healthSection);

    /* Agent connections section */
    var agentSection = document.createElement("div");
    agentSection.className = "control-section";
    var agentTitle = document.createElement("h3");
    agentTitle.textContent = "Agent Connections";
    agentSection.appendChild(agentTitle);
    var agentList = document.createElement("div");
    agentList.className = "agent-status-list";
    agentList.id = "agent-status-list";
    agentSection.appendChild(agentList);
    content.appendChild(agentSection);

    pane.appendChild(content);
    return pane;
  }

  /* ------------------------------------------------------------------ */
  /* Message display                                                      */
  /* ------------------------------------------------------------------ */

  function addMessage(slug, text, cls) {
    var container = document.getElementById("messages-" + slug);
    var typing = document.getElementById("typing-" + slug);
    var div = document.createElement("div");
    div.className = "msg " + cls;

    var span = document.createElement("span");
    span.textContent = text;
    div.appendChild(span);

    if (cls !== "system") {
      var t = document.createElement("span");
      t.className = "ts";
      t.textContent = ts();
      div.appendChild(t);
    }

    container.insertBefore(div, typing);
    scrollBottom(container);
    return div;
  }

  function getOrCreateStreamEl(slug, key) {
    var state = agentState[slug];
    if (!state.streamingEls[key]) {
      var container = document.getElementById("messages-" + slug);
      var typing = document.getElementById("typing-" + slug);
      var div = document.createElement("div");
      div.className = "msg bot";
      var span = document.createElement("span");
      span.textContent = "";
      div.appendChild(span);
      container.insertBefore(div, typing);
      state.streamingEls[key] = div;
    }
    return state.streamingEls[key];
  }

  function showTyping(slug, show) {
    var typing = document.getElementById("typing-" + slug);
    if (typing) {
      typing.className = show ? "typing-indicator visible" : "typing-indicator";
      if (show) {
        var container = document.getElementById("messages-" + slug);
        scrollBottom(container);
      }
    }
    agentState[slug].waiting = show;
  }

  /* ------------------------------------------------------------------ */
  /* Session management                                                   */
  /* ------------------------------------------------------------------ */

  function getBaseUrl() {
    return window.location.protocol + "//" + window.location.host;
  }

  function createSession(agent, callback) {
    var url = getBaseUrl() + "/v1/chat/sessions";
    var body = JSON.stringify({
      display_name: "Dashboard",
      agent_id: agent.uuid
    });

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body
    })
    .then(function (res) {
      if (!res.ok) throw new Error("Session creation failed: " + res.status);
      return res.json();
    })
    .then(function (data) {
      var sessionId = data.session_id;
      localStorage.setItem(storageKey(agent.slug), sessionId);
      agentState[agent.slug].sessionId = sessionId;
      callback(sessionId);
    })
    .catch(function (err) {
      addMessage(agent.slug, "Session error: " + err.message, "system");
      /* Retry after delay */
      setTimeout(function () { createSession(agent, callback); }, 3000);
    });
  }

  function ensureSession(agent, callback) {
    var existing = localStorage.getItem(storageKey(agent.slug));
    if (existing) {
      /* Validate the existing session still works */
      var url = getBaseUrl() + "/v1/chat/sessions/" + existing;
      fetch(url)
        .then(function (res) {
          if (res.ok) {
            agentState[agent.slug].sessionId = existing;
            callback(existing);
          } else {
            /* Session expired or invalid, create new */
            localStorage.removeItem(storageKey(agent.slug));
            createSession(agent, callback);
          }
        })
        .catch(function () {
          /* Server unreachable, try with stored session anyway */
          agentState[agent.slug].sessionId = existing;
          callback(existing);
        });
    } else {
      createSession(agent, callback);
    }
  }

  /* ------------------------------------------------------------------ */
  /* WebSocket connection                                                 */
  /* ------------------------------------------------------------------ */

  function connectAgent(agent) {
    var state = agentState[agent.slug];
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    ensureSession(agent, function (sessionId) {
      var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      var wsUrl = proto + "//" + window.location.host + "/ws/" + sessionId;

      var ws = new WebSocket(wsUrl);
      state.ws = ws;

      ws.onopen = function () {
        state.connected = true;
        state.reconnectDelay = 1000;
        if (state.reconnectTimer) {
          clearTimeout(state.reconnectTimer);
          state.reconnectTimer = null;
        }
        updateDot(agent.slug, true);
        addMessage(agent.slug, "Connected", "system");
        updateControlPanel();
      };

      ws.onclose = function () {
        state.connected = false;
        state.ws = null;
        updateDot(agent.slug, false);
        showTyping(agent.slug, false);
        updateControlPanel();
        scheduleReconnect(agent);
      };

      ws.onerror = function () {
        state.connected = false;
        updateDot(agent.slug, false);
        updateControlPanel();
      };

      ws.onmessage = function (evt) {
        var data;
        try { data = JSON.parse(evt.data); } catch (_) { return; }

        if (data.type === "session") {
          /* Server may reassign session ID */
          state.sessionId = data.session_id;
          localStorage.setItem(storageKey(agent.slug), data.session_id);
          return;
        }

        if (data.type === "pong") return;

        if (data.type === "ack") {
          /* Message acknowledged -- keep typing indicator visible */
          return;
        }

        if (data.type === "error") {
          showTyping(agent.slug, false);
          addMessage(agent.slug, "Error: " + (data.detail || "unknown"), "system");
          return;
        }

        if (data.type === "stream") {
          var key = data.message_id || "__default__";
          var el = getOrCreateStreamEl(agent.slug, key);
          el.firstChild.textContent += data.chunk;
          var container = document.getElementById("messages-" + agent.slug);
          scrollBottom(container);

          if (data.done) {
            showTyping(agent.slug, false);
            var t = document.createElement("span");
            t.className = "ts";
            t.textContent = ts();
            el.appendChild(t);
            delete state.streamingEls[key];
            state.messageCount++;
            updateControlPanel();
          }
          return;
        }

        /* Regular message */
        showTyping(agent.slug, false);
        var content = data.content || data.message || JSON.stringify(data);
        addMessage(agent.slug, content, "bot");
        state.messageCount++;
        updateControlPanel();
      };
    });
  }

  function scheduleReconnect(agent) {
    var state = agentState[agent.slug];
    if (state.reconnectTimer) return;

    addMessage(agent.slug, "Disconnected. Reconnecting...", "system");
    state.reconnectTimer = setTimeout(function () {
      state.reconnectTimer = null;
      state.reconnectDelay = Math.min(state.reconnectDelay * 1.5, MAX_RECONNECT);
      connectAgent(agent);
    }, state.reconnectDelay);
  }

  function updateDot(slug, connected) {
    var dot = document.getElementById("dot-" + slug);
    if (dot) {
      dot.className = connected ? "status-dot connected" : "status-dot";
    }
  }

  /* ------------------------------------------------------------------ */
  /* Send message                                                         */
  /* ------------------------------------------------------------------ */

  function sendMessage(agent) {
    var state = agentState[agent.slug];
    var input = document.getElementById("input-" + agent.slug);
    var text = input.value.trim();
    if (!text || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;

    state.ws.send(JSON.stringify({ type: "message", content: text }));
    addMessage(agent.slug, text, "user");
    state.messageCount++;
    showTyping(agent.slug, true);
    input.value = "";
    input.style.height = "auto";
    updateControlPanel();
  }

  /* ------------------------------------------------------------------ */
  /* Ping keep-alive                                                      */
  /* ------------------------------------------------------------------ */

  setInterval(function () {
    AGENTS.forEach(function (agent) {
      var state = agentState[agent.slug];
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: "ping" }));
      }
    });
  }, 25000);

  /* ------------------------------------------------------------------ */
  /* Control panel                                                        */
  /* ------------------------------------------------------------------ */

  var healthData = {};

  function pollHealth() {
    var url = getBaseUrl() + "/v1/system/status";
    fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("Status " + res.status);
        return res.json();
      })
      .then(function (data) {
        healthData = data;
        renderHealthGrid();
      })
      .catch(function () {
        healthData = { _error: true };
        renderHealthGrid();
      });
  }

  function renderHealthGrid() {
    var grid = document.getElementById("health-grid");
    if (!grid) return;
    grid.innerHTML = "";

    if (healthData._error) {
      var item = document.createElement("div");
      item.className = "health-item";
      item.style.gridColumn = "1 / -1";
      var dot = document.createElement("span");
      dot.className = "h-dot down";
      item.appendChild(dot);
      var label = document.createElement("span");
      label.textContent = "Status endpoint unreachable";
      item.appendChild(label);
      grid.appendChild(item);
      return;
    }

    /* Render whatever keys the status endpoint returns */
    var services = healthData.services || healthData;
    var keys = Object.keys(services);
    if (keys.length === 0) {
      var emptyItem = document.createElement("div");
      emptyItem.className = "health-item";
      emptyItem.style.gridColumn = "1 / -1";
      var emptyDot = document.createElement("span");
      emptyDot.className = "h-dot unknown";
      emptyItem.appendChild(emptyDot);
      var emptyLabel = document.createElement("span");
      emptyLabel.textContent = "No services reported";
      emptyItem.appendChild(emptyLabel);
      grid.appendChild(emptyItem);
      return;
    }

    keys.forEach(function (key) {
      var val = services[key];
      var item = document.createElement("div");
      item.className = "health-item";

      var dot = document.createElement("span");
      var isUp = false;
      if (typeof val === "boolean") {
        isUp = val;
      } else if (typeof val === "string") {
        isUp = val === "ok" || val === "up" || val === "healthy" || val === "ready";
      } else if (typeof val === "object" && val !== null) {
        isUp = val.status === "ok" || val.status === "up" || val.status === "healthy" || val.healthy === true;
      }
      dot.className = "h-dot " + (isUp ? "up" : "down");
      item.appendChild(dot);

      var label = document.createElement("span");
      label.textContent = key;
      label.style.overflow = "hidden";
      label.style.textOverflow = "ellipsis";
      label.style.whiteSpace = "nowrap";
      item.appendChild(label);

      grid.appendChild(item);
    });
  }

  function updateControlPanel() {
    var list = document.getElementById("agent-status-list");
    if (!list) return;
    list.innerHTML = "";

    AGENTS.forEach(function (agent) {
      var state = agentState[agent.slug];
      var row = document.createElement("div");
      row.className = "agent-status-row";

      var dot = document.createElement("span");
      dot.className = "a-dot " + (state.connected ? "connected" : "disconnected");
      row.appendChild(dot);

      var name = document.createElement("span");
      name.className = "a-name";
      name.textContent = agent.emoji + " " + agent.name;
      row.appendChild(name);

      var count = document.createElement("span");
      count.className = "a-count";
      count.textContent = state.messageCount + " msgs";
      row.appendChild(count);

      list.appendChild(row);
    });
  }

  /* ------------------------------------------------------------------ */
  /* Build the grid                                                       */
  /* ------------------------------------------------------------------ */

  function init() {
    var grid = document.getElementById("grid");

    /* Row 1: Homarus, Ken, Mercer, Rory */
    /* Row 2: Scarlet, Ive, Mark, Control Panel */
    AGENTS.forEach(function (agent) {
      grid.appendChild(createAgentPane(agent));
    });
    grid.appendChild(createControlPanel());

    /* Wire up input events */
    AGENTS.forEach(function (agent) {
      var input = document.getElementById("input-" + agent.slug);
      var sendBtn = document.getElementById("send-" + agent.slug);

      sendBtn.addEventListener("click", function () {
        sendMessage(agent);
      });

      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage(agent);
        }
      });

      input.addEventListener("input", function () {
        this.style.height = "auto";
        this.style.height = Math.min(this.scrollHeight, 60) + "px";
      });
    });

    /* Connect all agents */
    AGENTS.forEach(function (agent) {
      connectAgent(agent);
    });

    /* Start control panel updates */
    updateControlPanel();
    pollHealth();
    setInterval(pollHealth, 10000);
  }

  /* ------------------------------------------------------------------ */
  /* Launch                                                               */
  /* ------------------------------------------------------------------ */

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
</script>
</body>
</html>
"""
