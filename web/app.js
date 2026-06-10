const form = document.querySelector("#solver-form");
const submitButton = form.querySelector(".solve-button");
const rangeInput = form.elements.opponent_range;
let rangeIsAuto = true;

const actionNames = { fold: "弃牌", check: "过牌", call: "跟注", bet: "下注", raise: "加注" };
const pct = value => `${(value * 100).toFixed(1)}%`;
const ev = value => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;

function renderCards(inputId, previewId, slots) {
  const cards = document.querySelector(inputId).value.trim().split(/\s+/).filter(Boolean);
  const preview = document.querySelector(previewId);
  preview.innerHTML = "";
  cards.slice(0, slots).forEach(card => {
    const suit = { s: "♠", h: "♥", d: "♦", c: "♣" }[card.slice(-1).toLowerCase()] || "?";
    const rank = card.slice(0, -1).toUpperCase();
    const el = document.createElement("div");
    el.className = `playing-card ${["h", "d"].includes(card.slice(-1).toLowerCase()) ? "red" : ""}`;
    el.innerHTML = `<span>${rank}</span><span>${suit}</span>`;
    preview.appendChild(el);
  });
  for (let i = cards.length; i < slots; i++) {
    const empty = document.createElement("div");
    empty.className = "empty-card";
    preview.appendChild(empty);
  }
}

function updateCardPreviews() {
  renderCards("#hand-input", "#hand-preview", 2);
  renderCards("#board-input", "#board-preview", 5);
}

function formPayload() {
  const data = Object.fromEntries(new FormData(form));
  ["players", "simulations"].forEach(key => data[key] = Number(data[key]));
  ["pot", "to_call", "raise_size", "fold_to_raise"].forEach(key => data[key] = Number(data[key]));
  data.opponent_range = rangeIsAuto ? null : Number(data.opponent_range);
  return data;
}

function renderBars(containerId, values, kind, bestAction) {
  const container = document.querySelector(containerId);
  container.className = kind === "ev" ? "ev-chart" : "strategy-chart";
  container.innerHTML = "";
  const magnitude = Math.max(...Object.values(values).map(Math.abs), 0.001);
  Object.entries(values).forEach(([action, value]) => {
    const row = document.createElement("div");
    row.className = kind === "ev" ? "ev-row" : "strategy-row";
    const width = kind === "ev" ? Math.abs(value) / magnitude * 100 : value * 100;
    row.innerHTML = `
      <span>${actionNames[action] || action}</span>
      <div class="bar-track"><div class="bar ${value < 0 ? "negative" : ""} ${action === bestAction ? "best" : ""}" style="width:${width}%"></div></div>
      <span class="bar-value">${kind === "ev" ? ev(value) : pct(value)}</span>`;
    container.appendChild(row);
  });
}

function renderResult(result) {
  const bestEv = result.action_ev[result.recommended_action];
  document.querySelector("#recommended").textContent = actionNames[result.recommended_action] || result.recommended_action;
  document.querySelector("#recommend-meta").textContent =
    `最高净 EV ${ev(bestEv)} BB · ${result.simulations.toLocaleString()} 次模拟`;
  document.querySelector("#equity").textContent = pct(result.equity);
  document.querySelector("#equity-ring").style.setProperty("--equity", `${result.equity * 360}deg`);
  document.querySelector("#win-rate").textContent = pct(result.win_rate);
  document.querySelector("#tie-rate").textContent = pct(result.tie_rate);
  document.querySelector("#resolved-range").textContent = pct(result.opponent_range);
  renderBars("#ev-chart", result.action_ev, "ev", result.recommended_action);
  renderBars("#strategy-chart", result.mixed_strategy, "strategy", result.recommended_action);
  document.querySelector("#strategy-script").textContent = result.strategy_script || "未生成策略脚本。";
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const error = document.querySelector("#error-message");
  error.textContent = "";
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "正在运行模拟…";
  try {
    const response = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formPayload())
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error);
    renderResult(data.result);
  } catch (err) {
    error.textContent = err.message || "计算失败，请稍后重试。";
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "运行决策分析";
  }
});

document.querySelector("#advanced-toggle").addEventListener("click", () => {
  const advanced = document.querySelector(".advanced");
  advanced.classList.toggle("open");
  document.querySelector("#advanced-toggle span").textContent = advanced.classList.contains("open") ? "−" : "+";
});
document.querySelector("#range-auto").addEventListener("click", () => {
  rangeIsAuto = true;
  document.querySelector("#range-value").textContent = "自动";
});
rangeInput.addEventListener("input", () => {
  rangeIsAuto = false;
  document.querySelector("#range-value").textContent = pct(Number(rangeInput.value));
});
form.elements.fold_to_raise.addEventListener("input", event => {
  document.querySelector("#fold-value").textContent = pct(Number(event.target.value));
});
["#hand-input", "#board-input"].forEach(id => document.querySelector(id).addEventListener("input", updateCardPreviews));
document.querySelector("#load-example").addEventListener("click", () => {
  form.elements.players.value = "2";
  form.elements.position.value = "CO";
  form.elements.strategy.value = "balanced";
  form.elements.hand.value = "Ah Qh";
  form.elements.board.value = "Jh 8h 2c";
  form.elements.pot.value = "12";
  form.elements.to_call.value = "4";
  form.elements.raise_size.value = "14";
  rangeIsAuto = false;
  rangeInput.value = ".25";
  form.elements.fold_to_raise.value = ".38";
  document.querySelector("#range-value").textContent = "25.0%";
  document.querySelector("#fold-value").textContent = "38.0%";
  updateCardPreviews();
});

updateCardPreviews();

const captureVideo = document.querySelector("#capture-video");
const captureCanvas = document.querySelector("#capture-canvas");
const detectedText = document.querySelector("#detected-text");
let captureStream = null;
let aiAvailable = false;
let windowsOcrAvailable = false;
const offlineFields = {
  players: "#offline-players",
  position: "#offline-position",
  hand: "#offline-hand",
  board: "#offline-board",
  pot: "#offline-pot",
  to_call: "#offline-call",
  raise_size: "#offline-raise"
};

function setVisionStatus(text, active = false) {
  const status = document.querySelector("#vision-status");
  status.textContent = text;
  status.classList.toggle("active", active);
}

function showCapture(element) {
  document.querySelector("#capture-placeholder").style.display = "none";
  captureVideo.style.display = element === captureVideo ? "block" : "none";
  captureCanvas.style.display = element === captureCanvas ? "block" : "none";
}

function parseDetectedState(text) {
  const state = {};
  const normalized = text.replace(/[♠]/g, "s").replace(/[♥]/g, "h").replace(/[♦]/g, "d").replace(/[♣]/g, "c");
  const patterns = {
    players: /(?:players?|人数)\s*[:=]?\s*(\d)/i,
    position: /(?:position|位置)\s*[:=]?\s*(UTG\+1|UTG|MP|HJ|CO|BTN|SB|BB)/i,
    hand: /(?:hand|手牌)\s*[:=]?\s*((?:[2-9TJQKA][cdhs]\s*){2})/i,
    board: /(?:board|公共牌)\s*[:=]?\s*((?:[2-9TJQKA][cdhs]\s*){3,5})/i,
    pot: /(?:pot|底池)\s*[:=]?\s*(\d+(?:\.\d+)?)/i,
    to_call: /(?:to.?call|call|跟注)\s*[:=]?\s*(\d+(?:\.\d+)?)/i,
    raise_size: /(?:raise|bet|加注|下注)\s*[:=]?\s*(\d+(?:\.\d+)?)/i
  };
  Object.entries(patterns).forEach(([key, pattern]) => {
    const match = normalized.match(pattern);
    if (match) state[key] = match[1].trim();
  });
  return state;
}

function renderDetectedTags(state) {
  const tags = document.querySelector("#detected-tags");
  const entries = Object.entries(state);
  tags.innerHTML = entries.length
    ? entries.map(([key, value]) => `<span class="detected-tag">${key}: ${value}</span>`).join("")
    : "未识别到标准字段，请校准识别文本。";
}

function stateToText(state) {
  return Object.entries(state)
    .filter(([, value]) => value !== "" && value !== null && value !== undefined)
    .map(([key, value]) => `${key} ${value}`)
    .join("\n");
}

function syncOfflineFields(state) {
  Object.entries(offlineFields).forEach(([key, selector]) => {
    document.querySelector(selector).value = state[key] ?? "";
  });
}

function stateFromOfflineFields() {
  const state = {};
  Object.entries(offlineFields).forEach(([key, selector]) => {
    const value = document.querySelector(selector).value.trim();
    if (value) state[key] = value;
  });
  return state;
}

function publishDetectedState(state, status = "离线状态已就绪") {
  detectedText.value = stateToText(state);
  syncOfflineFields(state);
  renderDetectedTags(state);
  setVisionStatus(status, true);
}

async function aiScanCanvas() {
  const error = document.querySelector("#vision-error");
  error.textContent = "";
  if (!aiAvailable) throw new Error("AI API 不可用，请使用离线模式。");
  setVisionStatus("AI 正在检测...");
  const image = captureCanvas.toDataURL("image/jpeg", .82);
  const response = await fetch("/api/vision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image })
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error);
  publishDetectedState(data.state, `AI 已识别 ${Object.keys(data.state).length} 个字段`);
}

async function offlineScanCanvas() {
  const error = document.querySelector("#vision-error");
  error.textContent = "";
  if (!captureCanvas.width) throw new Error("请先选择桌面窗口或导入截图。");
  if (windowsOcrAvailable) {
    setVisionStatus("Windows 本地 OCR 正在检测...");
    const response = await fetch("/api/ocr", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: captureCanvas.toDataURL("image/png") })
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error);
    detectedText.value = data.text;
    const state = parseDetectedState(data.text);
    syncOfflineFields(state);
    renderDetectedTags(state);
    setVisionStatus(`Windows OCR 已识别 ${Object.keys(state).length} 个字段`, true);
    return;
  }
  if (!window.TextDetector) {
    const current = stateFromOfflineFields();
    publishDetectedState(current, "离线快速校准");
    error.textContent = "当前浏览器没有本地 OCR。请在离线字段中校准牌局状态，截图不会上传。";
    return;
  }
  setVisionStatus("本地 OCR 正在检测...");
  const detector = new TextDetector();
  const blocks = await detector.detect(captureCanvas);
  detectedText.value = blocks.map(block => block.rawValue).join("\n");
  const state = parseDetectedState(detectedText.value);
  syncOfflineFields(state);
  renderDetectedTags(state);
  setVisionStatus(`本地 OCR 识别到 ${Object.keys(state).length} 个字段`, true);
}

document.querySelector("#start-capture").addEventListener("click", async () => {
  const error = document.querySelector("#vision-error");
  error.textContent = "";
  try {
    captureStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    captureVideo.srcObject = captureStream;
    showCapture(captureVideo);
    setVisionStatus("桌面画面已连接", true);
    captureStream.getVideoTracks()[0].addEventListener("ended", () => setVisionStatus("画面共享已停止"));
  } catch (err) {
    error.textContent = "未能连接桌面画面，请允许浏览器共享目标窗口。";
  }
});

document.querySelector("#scan-frame").addEventListener("click", async () => {
  const error = document.querySelector("#vision-error");
  error.textContent = "";
  if (captureVideo.srcObject && captureVideo.videoWidth) {
    captureCanvas.width = captureVideo.videoWidth;
    captureCanvas.height = captureVideo.videoHeight;
    captureCanvas.getContext("2d").drawImage(captureVideo, 0, 0);
    showCapture(captureCanvas);
  }
  if (!captureCanvas.width) {
    error.textContent = "请先选择桌面窗口或导入截图。";
    return;
  }
  try { await offlineScanCanvas(); } catch (err) { error.textContent = `离线检测失败：${err.message}`; }
});

document.querySelector("#ai-scan-frame").addEventListener("click", async () => {
  const error = document.querySelector("#vision-error");
  error.textContent = "";
  if (captureVideo.srcObject && captureVideo.videoWidth) {
    captureCanvas.width = captureVideo.videoWidth;
    captureCanvas.height = captureVideo.videoHeight;
    captureCanvas.getContext("2d").drawImage(captureVideo, 0, 0);
    showCapture(captureCanvas);
  }
  if (!captureCanvas.width) {
    error.textContent = "请先选择桌面窗口或导入截图。";
    return;
  }
  try {
    await aiScanCanvas();
  } catch (err) {
    aiAvailable = false;
    document.querySelector("#ai-scan-frame").disabled = true;
    setVisionStatus("AI 调用失败 · 已切换离线模式", true);
    error.textContent = `AI 检测失败：${err.message}`;
  }
});

document.querySelector("#image-upload").addEventListener("change", event => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.name.toLowerCase().endsWith(".json") || file.name.toLowerCase().endsWith(".txt")) {
    file.text().then(text => {
      try {
        const state = file.name.toLowerCase().endsWith(".json")
          ? JSON.parse(text)
          : parseDetectedState(text);
        publishDetectedState(state, "离线状态文件已导入");
      } catch (err) {
        document.querySelector("#vision-error").textContent = `状态文件无效：${err.message}`;
      }
    });
    return;
  }
  const image = new Image();
  image.onload = () => {
    captureCanvas.width = image.naturalWidth;
    captureCanvas.height = image.naturalHeight;
    captureCanvas.getContext("2d").drawImage(image, 0, 0);
    showCapture(captureCanvas);
    setVisionStatus("截图已导入 · 等待离线校准", true);
    URL.revokeObjectURL(image.src);
  };
  image.src = URL.createObjectURL(file);
});

detectedText.addEventListener("input", () => renderDetectedTags(parseDetectedState(detectedText.value)));
Object.values(offlineFields).forEach(selector => {
  document.querySelector(selector).addEventListener("input", () => {
    const state = stateFromOfflineFields();
    detectedText.value = stateToText(state);
    renderDetectedTags(state);
  });
});
document.querySelector("#state-from-form").addEventListener("click", () => {
  publishDetectedState(formPayload(), "已从当前参数生成离线状态");
});
document.querySelector("#load-offline-example").addEventListener("click", () => {
  publishDetectedState(
    { players: 2, position: "BTN", hand: "As Kh", board: "Qs Jh 2c", pot: 10, to_call: 2, raise_size: 8 },
    "离线示例已载入"
  );
});
document.querySelector("#apply-detection").addEventListener("click", async () => {
  const state = { ...parseDetectedState(detectedText.value), ...stateFromOfflineFields() };
  const error = document.querySelector("#vision-error");
  error.textContent = "";
  if (!state.hand) {
    error.textContent = "至少需要识别或填写 hand，例如：hand As Kh";
    return;
  }
  Object.entries(state).forEach(([key, value]) => {
    if (form.elements[key]) form.elements[key].value = value;
  });
  updateCardPreviews();
  setVisionStatus("状态已应用，正在分析", true);
  form.requestSubmit();
});
document.querySelector("#copy-script").addEventListener("click", async () => {
  await navigator.clipboard.writeText(document.querySelector("#strategy-script").textContent);
  document.querySelector("#copy-script").textContent = "已复制";
  setTimeout(() => document.querySelector("#copy-script").textContent = "复制脚本", 1200);
});

fetch("/api/health").then(response => response.json()).then(data => {
  aiAvailable = data.ai_configured && !data.ai?.warnings?.length;
  windowsOcrAvailable = data.windows_ocr_available;
  document.querySelector("#ai-scan-frame").disabled = !aiAvailable;
  if (aiAvailable) {
    setVisionStatus(`AI 已配置 · ${data.ai.model}`, true);
  } else if (data.ai_configured) {
    setVisionStatus(`离线模式 · ${data.ai.warnings.join("；")}`, true);
  } else {
    setVisionStatus(
      windowsOcrAvailable ? "Windows 本地 OCR 可用 · AI API 不可用" : "离线校准可用 · OCR 不可用",
      true
    );
  }
});
