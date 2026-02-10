"""Embeddable webchat widget served as a self-contained HTML page.

The widget provides a minimalist chat interface with:
- WebSocket connection management with auto-reconnect
- Streaming response display
- File upload support (metadata only -- actual bytes go via S3 presign)
- Session persistence via localStorage
- Responsive, modern UI
"""

from __future__ import annotations

WIDGET_HTML: str = (
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta charset="utf-8" />\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
    "<title>Orchestack Chat</title>\n"
    "<style>\n"
    "  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n"
    "\n"
    "  :root {\n"
    "    --bg: #0f1117;\n"
    "    --surface: #1a1d27;\n"
    "    --surface-hover: #232634;\n"
    "    --border: #2e3241;\n"
    "    --text: #e2e4ea;\n"
    "    --text-muted: #8b8fa3;\n"
    "    --primary: #6c72cb;\n"
    "    --primary-hover: #7f84d4;\n"
    "    --user-bubble: #2d3152;\n"
    "    --bot-bubble: #1e2133;\n"
    "    --danger: #e05252;\n"
    "    --radius: 12px;\n"
    '    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,\n'
    '             "Helvetica Neue", Arial, sans-serif;\n'
    "  }\n"
    "\n"
    "  html, body {\n"
    "    height: 100%; width: 100%;\n"
    "    font-family: var(--font);\n"
    "    background: var(--bg);\n"
    "    color: var(--text);\n"
    "  }\n"
    "\n"
    "  body {\n"
    "    display: flex;\n"
    "    flex-direction: column;\n"
    "  }\n"
    "\n"
    "  #header {\n"
    "    display: flex;\n"
    "    align-items: center;\n"
    "    gap: 10px;\n"
    "    padding: 14px 20px;\n"
    "    background: var(--surface);\n"
    "    border-bottom: 1px solid var(--border);\n"
    "    flex-shrink: 0;\n"
    "  }\n"
    "  #header .dot {\n"
    "    width: 10px; height: 10px;\n"
    "    border-radius: 50%;\n"
    "    background: #4caf50;\n"
    "    flex-shrink: 0;\n"
    "  }\n"
    "  #header .dot.disconnected { background: var(--danger); }\n"
    "  #header h1 { font-size: 16px; font-weight: 600; }\n"
    "  #header .session-id {\n"
    "    margin-left: auto;\n"
    "    font-size: 11px;\n"
    "    color: var(--text-muted);\n"
    "    font-family: monospace;\n"
    "  }\n"
    "\n"
    "  #messages {\n"
    "    flex: 1;\n"
    "    overflow-y: auto;\n"
    "    padding: 20px;\n"
    "    display: flex;\n"
    "    flex-direction: column;\n"
    "    gap: 10px;\n"
    "  }\n"
    "\n"
    "  .msg {\n"
    "    max-width: 75%;\n"
    "    padding: 10px 14px;\n"
    "    border-radius: var(--radius);\n"
    "    line-height: 1.5;\n"
    "    font-size: 14px;\n"
    "    word-wrap: break-word;\n"
    "    white-space: pre-wrap;\n"
    "  }\n"
    "  .msg.user {\n"
    "    align-self: flex-end;\n"
    "    background: var(--user-bubble);\n"
    "    border-bottom-right-radius: 4px;\n"
    "  }\n"
    "  .msg.bot {\n"
    "    align-self: flex-start;\n"
    "    background: var(--bot-bubble);\n"
    "    border: 1px solid var(--border);\n"
    "    border-bottom-left-radius: 4px;\n"
    "  }\n"
    "  .msg.system {\n"
    "    align-self: center;\n"
    "    font-size: 12px;\n"
    "    color: var(--text-muted);\n"
    "    background: transparent;\n"
    "  }\n"
    "  .msg .ts {\n"
    "    display: block;\n"
    "    font-size: 10px;\n"
    "    color: var(--text-muted);\n"
    "    margin-top: 4px;\n"
    "    text-align: right;\n"
    "  }\n"
    "\n"
    "  #input-area {\n"
    "    display: flex;\n"
    "    align-items: flex-end;\n"
    "    gap: 8px;\n"
    "    padding: 14px 20px;\n"
    "    background: var(--surface);\n"
    "    border-top: 1px solid var(--border);\n"
    "    flex-shrink: 0;\n"
    "  }\n"
    "\n"
    "  #msg-input {\n"
    "    flex: 1;\n"
    "    resize: none;\n"
    "    border: 1px solid var(--border);\n"
    "    border-radius: var(--radius);\n"
    "    background: var(--bg);\n"
    "    color: var(--text);\n"
    "    padding: 10px 14px;\n"
    "    font-size: 14px;\n"
    "    font-family: var(--font);\n"
    "    line-height: 1.4;\n"
    "    max-height: 120px;\n"
    "    overflow-y: auto;\n"
    "  }\n"
    "  #msg-input:focus { outline: none; border-color: var(--primary); }\n"
    "  #msg-input::placeholder { color: var(--text-muted); }\n"
    "\n"
    "  .icon-btn {\n"
    "    width: 40px; height: 40px;\n"
    "    border: none;\n"
    "    border-radius: var(--radius);\n"
    "    background: var(--surface-hover);\n"
    "    color: var(--text-muted);\n"
    "    cursor: pointer;\n"
    "    display: flex;\n"
    "    align-items: center;\n"
    "    justify-content: center;\n"
    "    flex-shrink: 0;\n"
    "    transition: background 0.15s, color 0.15s;\n"
    "  }\n"
    "  .icon-btn:hover { background: var(--primary); color: #fff; }\n"
    "\n"
    "  #send-btn { background: var(--primary); color: #fff; }\n"
    "  #send-btn:hover { background: var(--primary-hover); }\n"
    "\n"
    "  #file-input { display: none; }\n"
    "\n"
    "  ::-webkit-scrollbar { width: 6px; }\n"
    "  ::-webkit-scrollbar-track { background: transparent; }\n"
    "  ::-webkit-scrollbar-thumb {\n"
    "    background: var(--border);\n"
    "    border-radius: 3px;\n"
    "  }\n"
    "</style>\n"
    "</head>\n"
    "<body>\n"
    "\n"
    '<div id="header">\n'
    '  <span class="dot" id="status-dot"></span>\n'
    "  <h1>Orchestack Chat</h1>\n"
    '  <span class="session-id" id="session-label"></span>\n'
    "</div>\n"
    "\n"
    '<div id="messages"></div>\n'
    "\n"
    '<div id="input-area">\n'
    '  <button class="icon-btn" id="file-btn" title="Attach file">\n'
    '    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none"\n'
    '         stroke="currentColor" stroke-width="2" stroke-linecap="round"\n'
    '         stroke-linejoin="round" viewBox="0 0 24 24">\n'
    '      <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19\n'
    '               a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>\n'
    "    </svg>\n"
    "  </button>\n"
    '  <input type="file" id="file-input" multiple />\n'
    '  <textarea id="msg-input" rows="1" placeholder="Type a message..."></textarea>\n'
    '  <button class="icon-btn" id="send-btn" title="Send">\n'
    '    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none"\n'
    '         stroke="currentColor" stroke-width="2" stroke-linecap="round"\n'
    '         stroke-linejoin="round" viewBox="0 0 24 24">\n'
    '      <line x1="22" y1="2" x2="11" y2="13"/>\n'
    '      <polygon points="22 2 15 22 11 13 2 9 22 2"/>\n'
    "    </svg>\n"
    "  </button>\n"
    "</div>\n"
    "\n"
    "<script>\n"
    "(function () {\n"
    '  "use strict";\n'
    "\n"
    '  var messagesEl  = document.getElementById("messages");\n'
    '  var inputEl     = document.getElementById("msg-input");\n'
    '  var sendBtn     = document.getElementById("send-btn");\n'
    '  var fileBtn     = document.getElementById("file-btn");\n'
    '  var fileInput   = document.getElementById("file-input");\n'
    '  var statusDot   = document.getElementById("status-dot");\n'
    '  var sessionLabel = document.getElementById("session-label");\n'
    "\n"
    '  var STORAGE_KEY = "orchestack_webchat_session";\n'
    '  var sessionId = localStorage.getItem(STORAGE_KEY) || "";\n'
    "  var ws = null;\n"
    "  var reconnectDelay = 1000;\n"
    "  var MAX_RECONNECT = 30000;\n"
    "  var streamingEls = {};\n"
    "\n"
    "  function scrollBottom() {\n"
    "    messagesEl.scrollTop = messagesEl.scrollHeight;\n"
    "  }\n"
    "\n"
    "  function ts() {\n"
    '    return new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});\n'
    "  }\n"
    "\n"
    "  function addMessage(text, cls) {\n"
    '    var div = document.createElement("div");\n'
    '    div.className = "msg " + cls;\n'
    '    var span = document.createElement("span");\n'
    "    span.textContent = text;\n"
    "    div.appendChild(span);\n"
    '    if (cls !== "system") {\n'
    '      var t = document.createElement("span");\n'
    '      t.className = "ts";\n'
    "      t.textContent = ts();\n"
    "      div.appendChild(t);\n"
    "    }\n"
    "    messagesEl.appendChild(div);\n"
    "    scrollBottom();\n"
    "    return div;\n"
    "  }\n"
    "\n"
    "  function getOrCreateStreamEl(key) {\n"
    "    if (!streamingEls[key]) {\n"
    '      var div = document.createElement("div");\n'
    '      div.className = "msg bot";\n'
    '      var span = document.createElement("span");\n'
    '      span.textContent = "";\n'
    "      div.appendChild(span);\n"
    "      messagesEl.appendChild(div);\n"
    "      streamingEls[key] = div;\n"
    "    }\n"
    "    return streamingEls[key];\n"
    "  }\n"
    "\n"
    "  function updateSessionLabel() {\n"
    '    sessionLabel.textContent = sessionId ? sessionId.slice(0, 12) + "..." : "";\n'
    "  }\n"
    "\n"
    "  function buildWsUrl() {\n"
    '    var proto = location.protocol === "https:" ? "wss:" : "ws:";\n'
    '    var base  = proto + "//" + location.host;\n'
    '    return sessionId ? base + "/ws/" + sessionId : base + "/ws";\n'
    "  }\n"
    "\n"
    "  function connect() {\n"
    "    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {\n"
    "      return;\n"
    "    }\n"
    "    ws = new WebSocket(buildWsUrl());\n"
    "\n"
    "    ws.onopen = function () {\n"
    '      statusDot.classList.remove("disconnected");\n'
    "      reconnectDelay = 1000;\n"
    '      addMessage("Connected", "system");\n'
    "    };\n"
    "\n"
    "    ws.onclose = function () {\n"
    '      statusDot.classList.add("disconnected");\n'
    "      scheduleReconnect();\n"
    "    };\n"
    "\n"
    "    ws.onerror = function () {\n"
    '      statusDot.classList.add("disconnected");\n'
    "    };\n"
    "\n"
    "    ws.onmessage = function (evt) {\n"
    "      var data;\n"
    "      try { data = JSON.parse(evt.data); } catch (_) { return; }\n"
    "\n"
    '      if (data.type === "session") {\n'
    "        sessionId = data.session_id;\n"
    "        localStorage.setItem(STORAGE_KEY, sessionId);\n"
    "        updateSessionLabel();\n"
    "        return;\n"
    "      }\n"
    "\n"
    '      if (data.type === "pong") return;\n'
    '      if (data.type === "ack") return;\n'
    "\n"
    '      if (data.type === "error") {\n'
    '        addMessage("Error: " + (data.detail || "unknown"), "system");\n'
    "        return;\n"
    "      }\n"
    "\n"
    '      if (data.type === "stream") {\n'
    '        var key = data.message_id || "__default__";\n'
    "        var el = getOrCreateStreamEl(key);\n"
    "        el.firstChild.textContent += data.chunk;\n"
    "        scrollBottom();\n"
    "        if (data.done) {\n"
    '          var t = document.createElement("span");\n'
    '          t.className = "ts";\n'
    "          t.textContent = ts();\n"
    "          el.appendChild(t);\n"
    "          delete streamingEls[key];\n"
    "        }\n"
    "        return;\n"
    "      }\n"
    "\n"
    "      var content = data.content || data.message || JSON.stringify(data);\n"
    '      addMessage(content, "bot");\n'
    "    };\n"
    "  }\n"
    "\n"
    "  function scheduleReconnect() {\n"
    '    addMessage("Disconnected. Reconnecting...", "system");\n'
    "    setTimeout(function () {\n"
    "      reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT);\n"
    "      connect();\n"
    "    }, reconnectDelay);\n"
    "  }\n"
    "\n"
    "  setInterval(function () {\n"
    "    if (ws && ws.readyState === WebSocket.OPEN) {\n"
    '      ws.send(JSON.stringify({type: "ping"}));\n'
    "    }\n"
    "  }, 25000);\n"
    "\n"
    "  function sendMessage() {\n"
    "    var text = inputEl.value.trim();\n"
    "    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;\n"
    '    ws.send(JSON.stringify({type: "message", content: text}));\n'
    '    addMessage(text, "user");\n'
    '    inputEl.value = "";\n'
    '    inputEl.style.height = "auto";\n'
    "  }\n"
    "\n"
    '  sendBtn.addEventListener("click", sendMessage);\n'
    '  inputEl.addEventListener("keydown", function (e) {\n'
    '    if (e.key === "Enter" && !e.shiftKey) {\n'
    "      e.preventDefault();\n"
    "      sendMessage();\n"
    "    }\n"
    "  });\n"
    "\n"
    '  inputEl.addEventListener("input", function () {\n'
    '    this.style.height = "auto";\n'
    '    this.style.height = Math.min(this.scrollHeight, 120) + "px";\n'
    "  });\n"
    "\n"
    '  fileBtn.addEventListener("click", function () { fileInput.click(); });\n'
    '  fileInput.addEventListener("change", function () {\n'
    "    if (!ws || ws.readyState !== WebSocket.OPEN) return;\n"
    "    var files = Array.from(fileInput.files || []);\n"
    "    files.forEach(function (f) {\n"
    "      var attachments = [{\n"
    "        filename: f.name,\n"
    '        content_type: f.type || "application/octet-stream",\n'
    "        size_bytes: f.size,\n"
    '        payload_ref: ""\n'
    "      }];\n"
    "      ws.send(JSON.stringify({\n"
    '        type: "message",\n'
    '        content: "Uploaded: " + f.name,\n'
    "        attachments: attachments\n"
    "      }));\n"
    '      addMessage("Uploaded: " + f.name, "user");\n'
    "    });\n"
    '    fileInput.value = "";\n'
    "  });\n"
    "\n"
    "  updateSessionLabel();\n"
    "  connect();\n"
    "})();\n"
    "</script>\n"
    "</body>\n"
    "</html>\n"
)
