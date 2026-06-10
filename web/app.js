const form = document.querySelector("#hand-create-form");
const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
let currentHand = null;
let pendingBoardCards = [];
let pendingRaiseAction = null;
let selectedRangeSeat = null;
let playerCount = 3;
let showdownHands = {};
let completionPreparedHandId = null;
let trainingTarget = new Set();
let trainingSelected = new Set();
let picker = { mode: "hero", max: 2, selected: [] };
const ranks = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"];
const suits = [
  { code: "s", symbol: "♠", name: "黑桃", color: "black" },
  { code: "h", symbol: "♥", name: "红桃", color: "red" },
  { code: "d", symbol: "♦", name: "方片", color: "red" },
  { code: "c", symbol: "♣", name: "梅花", color: "black" }
];
const actionNames = {
  post_ante: "前注", post_small_blind: "小盲", post_big_blind: "大盲",
  fold: "弃牌", check: "过牌", call: "跟注", bet: "下注", raise: "加注", all_in: "全下"
};
const streetNames = { preflop: "翻牌前", flop: "翻牌", turn: "转牌", river: "河牌" };
const chineseNumbers = { 2: "双", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九" };

function playerSetupValues() {
  return Object.fromEntries(new FormData(form));
}

function renderPlayerSetup(count, preserve = {}) {
  playerCount = Number(count);
  const seats = Array.from({ length: playerCount }, (_, index) => index + 1);
  const buttonSeat = Math.min(Number(preserve.button_seat || playerCount), playerCount);
  const heroSeat = Math.min(Number(preserve.hero_seat || playerCount), playerCount);
  form.elements.button_seat.innerHTML = seats.map(seat => `<option value="${seat}" ${seat === buttonSeat ? "selected" : ""}>座位 ${seat}</option>`).join("");
  form.elements.hero_seat.innerHTML = seats.map(seat => `<option value="${seat}" ${seat === heroSeat ? "selected" : ""}>座位 ${seat}</option>`).join("");
  document.querySelector("#player-config").innerHTML = seats.map(seat => `
    <div class="player-row">
      <strong><i>${seat}</i> 座位 ${seat}<em>${seat === heroSeat ? "HERO" : "VILLAIN"}</em></strong>
      <label>有效筹码<input type="number" name="stack_${seat}" value="${preserve[`stack_${seat}`] || 100}" min="1"></label>
      <label>对手画像<select name="profile_${seat}">
        <option value="balanced" ${preserve[`profile_${seat}`] === "balanced" || !preserve[`profile_${seat}`] ? "selected" : ""}>平衡</option>
        <option value="tight" ${preserve[`profile_${seat}`] === "tight" ? "selected" : ""}>紧手</option>
        <option value="loose_aggressive" ${preserve[`profile_${seat}`] === "loose_aggressive" ? "selected" : ""}>松凶</option>
      </select></label>
    </div>`).join("");
  document.querySelector("#table-description").textContent = `${chineseNumbers[playerCount]}人桌 · 无上限德州扑克`;
  document.querySelector(".create-hand span").textContent = `创建${chineseNumbers[playerCount]}人牌局并开始记录`;
}

form.elements.player_count.addEventListener("change", event => renderPlayerSetup(event.target.value, playerSetupValues()));
form.elements.hero_seat.addEventListener("change", () => renderPlayerSetup(playerCount, playerSetupValues()));

async function api(path, body = {}) {
  let response;
  try {
    response = await fetch(API_BASE + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch (_error) {
    throw new Error("无法连接牌局服务，请运行 python .\\web_app.py 后重试");
  }
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "请求失败");
  return data;
}

async function getApi(path) {
  const response = await fetch(API_BASE + path, { cache: "no-store" });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "请求失败");
  return data;
}

function cardMarkup(card, className = "mini-card") {
  const suit = suits.find(item => item.code === card[1]);
  return `<span class="${className} ${suit?.color || ""}"><strong>${card[0]}</strong><i>${suit?.symbol || ""}</i></span>`;
}

function usedCards(mode = picker.mode) {
  if (mode === "hero" && currentHand?.state.complete) return new Set();
  const hero = form.elements.hero_hand.value ? form.elements.hero_hand.value.split(" ") : [];
  const board = currentHand?.state.board || [];
  return new Set([...hero, ...board, ...Object.values(showdownHands).flat()].filter(Boolean));
}

function openPicker(mode, seat = null) {
  const isHero = mode === "hero";
  const isShowdown = mode === "showdown";
  const max = isHero || isShowdown ? 2 : currentHand?.state.board.length === 0 ? 3 : 1;
  const selected = isHero ? form.elements.hero_hand.value.split(" ").filter(Boolean) : isShowdown ? [...(showdownHands[seat] || [])] : [...pendingBoardCards];
  picker = { mode, seat, max, selected };
  document.querySelector("#picker-kicker").textContent = isHero ? "HOLE CARDS" : isShowdown ? "SHOWDOWN HAND" : "COMMUNITY CARDS";
  document.querySelector("#picker-title").textContent = isHero ? "选择 Hero 手牌" : isShowdown ? `选择座位 ${seat} 手牌` : "选择下一街公共牌";
  renderPicker();
  document.querySelector("#card-picker-dialog").showModal();
}

function renderPicker() {
  const used = usedCards();
  picker.selected.forEach(card => used.delete(card));
  document.querySelector("#picker-help").textContent = `请选择 ${picker.max} 张牌 · 已选 ${picker.selected.length}/${picker.max}`;
  document.querySelector("#picker-selection").innerHTML = Array.from({ length: picker.max }, (_, index) =>
    picker.selected[index] ? cardMarkup(picker.selected[index], "preview-card") : '<span class="preview-card placeholder">?</span>'
  ).join("");
  document.querySelector("#card-deck").innerHTML = suits.map(suit => `
    <div class="suit-row">
      <span class="suit-label ${suit.color}">${suit.symbol}<small>${suit.name}</small></span>
      ${ranks.map(rank => {
        const card = rank + suit.code;
        return `<button type="button" class="deck-card ${suit.color} ${picker.selected.includes(card) ? "selected" : ""}" data-card="${card}" ${used.has(card) ? "disabled" : ""}><strong>${rank}</strong><i>${suit.symbol}</i></button>`;
      }).join("")}
    </div>`).join("");
  document.querySelectorAll(".deck-card:not(:disabled)").forEach(button => button.addEventListener("click", () => {
    const card = button.dataset.card;
    if (picker.selected.includes(card)) picker.selected = picker.selected.filter(item => item !== card);
    else if (picker.selected.length < picker.max) picker.selected.push(card);
    else picker.selected[picker.selected.length - 1] = card;
    renderPicker();
  }));
  document.querySelector("#picker-confirm").disabled = picker.selected.length !== picker.max;
}

function updateCardInputs() {
  const hero = form.elements.hero_hand.value.split(" ").filter(Boolean);
  document.querySelector("#hero-hand-picker").innerHTML = `${hero.length ? hero.map(card => cardMarkup(card)).join("") : '<span class="mini-card placeholder">?</span><span class="mini-card placeholder">?</span>'}<em>${hero.length ? "更换" : "选择"}</em>`;
  const nextHeroPicker = document.querySelector("#next-hero-picker");
  if (nextHeroPicker) nextHeroPicker.innerHTML = `${hero.length ? hero.map(card => cardMarkup(card, "table-card")).join("") : '<span class="table-card placeholder">?</span><span class="table-card placeholder">?</span>'}<em>${hero.length ? "更换下一手 Hero 手牌" : "选择下一手 Hero 手牌"}</em>`;
  document.querySelector("#board-picker").innerHTML = `${pendingBoardCards.length ? pendingBoardCards.map(card => cardMarkup(card)).join("") : '<span class="mini-card placeholder">?</span>'}<em>${pendingBoardCards.length ? "更换选择" : "选择下一街公共牌"}</em>`;
}

document.querySelector("#hero-hand-picker").addEventListener("click", () => openPicker("hero"));
document.querySelector("#next-hero-picker").addEventListener("click", () => openPicker("hero"));
document.querySelector("#board-picker").addEventListener("click", () => currentHand?.state.awaiting_board ? openPicker("board") : showError(new Error("当前无需发公共牌")));
document.querySelector("#picker-close").addEventListener("click", () => document.querySelector("#card-picker-dialog").close());
document.querySelector("#picker-clear").addEventListener("click", () => { picker.selected = []; renderPicker(); });
document.querySelector("#picker-confirm").addEventListener("click", () => {
  if (picker.mode === "hero") form.elements.hero_hand.value = picker.selected.join(" ");
  else if (picker.mode === "showdown") showdownHands[picker.seat] = [...picker.selected];
  else pendingBoardCards = [...picker.selected];
  updateCardInputs();
  renderShowdownControl();
  document.querySelector("#card-picker-dialog").close();
});

function status(text) { document.querySelector("#hand-status").textContent = text; }
function showError(error) { document.querySelector("#hand-error").textContent = error.message || "请求失败"; }

function handClassAt(row, column) {
  if (row === column) return ranks[row] + ranks[column];
  return row < column ? ranks[row] + ranks[column] + "s" : ranks[column] + ranks[row] + "o";
}

function renderRangePanel(hand) {
  const ranges = Object.entries(hand.ranges);
  const tabs = document.querySelector("#range-tabs");
  const container = document.querySelector("#hand-ranges");
  if (!ranges.length) {
    tabs.innerHTML = "";
    container.className = "ranges empty";
    container.textContent = "当前没有未知对手范围";
    return;
  }
  if (!selectedRangeSeat || !hand.ranges[selectedRangeSeat]) selectedRangeSeat = ranges[0][0];
  tabs.innerHTML = ranges.map(([seat]) => `<button type="button" data-range-seat="${seat}" class="${seat === selectedRangeSeat ? "active" : ""}">座位 ${seat} · ${hand.positions[seat] || ""}</button>`).join("");
  tabs.querySelectorAll("[data-range-seat]").forEach(button => button.addEventListener("click", () => {
    selectedRangeSeat = button.dataset.rangeSeat;
    renderRangePanel(hand);
  }));
  const range = hand.ranges[selectedRangeSeat];
  container.className = "ranges";
  container.innerHTML = `<div class="range-overview"><div><span>覆盖率</span><strong>${(range.coverage * 100).toFixed(1)}%</strong></div><div><span>组合数</span><strong>${range.combo_count}</strong></div><div><span>核心牌型</span><strong>${range.top_classes.slice(0, 4).join(" · ")}</strong></div></div>
    <div class="range-matrix">${ranks.flatMap((_, row) => ranks.map((__, column) => {
      const handClass = handClassAt(row, column);
      const density = range.matrix[handClass] || 0;
      return `<span class="${handClass.endsWith("s") ? "suited" : handClass.endsWith("o") ? "offsuit" : "pair"}" style="--density:${density}" title="${handClass} · ${(density * 100).toFixed(0)}%">${handClass}</span>`;
    })).join("")}</div><small class="range-source">${range.source}</small>`;
}

function renderTimeline(actions) {
  const timeline = document.querySelector("#hand-timeline");
  timeline.className = "timeline";
  if (!actions.length) {
    timeline.textContent = "尚无行动";
    return;
  }
  let lastStreet = null;
  timeline.innerHTML = actions.map(action => {
    const heading = action.street !== lastStreet ? `<div class="timeline-street"><span>${streetNames[action.street] || action.street}</span><i></i></div>` : "";
    lastStreet = action.street;
    return `${heading}<div class="timeline-item"><span>${String(action.sequence).padStart(2, "0")}</span><strong>座位 ${action.seat} · ${actionNames[action.type] || action.type}</strong><small>${action.amount ? `+${action.amount}` : ""}${action.raise_to !== null ? ` → ${action.raise_to}` : ""}</small></div>`;
  }).join("");
}

function renderShowdownControl() {
  const control = document.querySelector("#showdown-control");
  if (!currentHand?.state.showdown_ready) {
    control.hidden = true;
    return;
  }
  const unknown = currentHand.state.players.filter(player => !["folded", "out"].includes(player.status) && !player.hole_cards);
  control.hidden = false;
  document.querySelector("#showdown-hands").innerHTML = unknown.map(player => {
    const cards = showdownHands[player.seat] || [];
    return `<button type="button" data-showdown-seat="${player.seat}"><span>座位 ${player.seat}</span><strong>${cards.length ? cards.map(card => cardMarkup(card)).join("") : '<i>选择两张手牌</i>'}</strong></button>`;
  }).join("");
  document.querySelectorAll("[data-showdown-seat]").forEach(button => button.addEventListener("click", () => openPicker("showdown", button.dataset.showdownSeat)));
  document.querySelector("#showdown-submit").disabled = unknown.some(player => (showdownHands[player.seat] || []).length !== 2);
}

function syncCompletedSetup(hand) {
  const preserve = playerSetupValues();
  preserve.hero_seat = hand.hero_seat;
  const activeSeats = hand.state.players.filter(player => player.stack > 0).map(player => player.seat).sort((a, b) => a - b);
  const oldButton = hand.state.config.button_seat;
  preserve.button_seat = activeSeats.find(seat => seat > oldButton) || activeSeats[0] || oldButton;
  hand.state.players.forEach(player => { preserve[`stack_${player.seat}`] = player.stack; });
  form.elements.player_count.value = hand.state.players.length;
  renderPlayerSetup(hand.state.players.length, preserve);
}

function renderCompletionControl(hand) {
  const control = document.querySelector("#completion-control");
  const rebuyControl = document.querySelector("#rebuy-control");
  control.hidden = !hand.state.complete;
  if (!hand.state.complete) {
    completionPreparedHandId = null;
    rebuyControl.hidden = true;
    return;
  }
  if (completionPreparedHandId !== hand.hand_id) {
    completionPreparedHandId = hand.hand_id;
    syncCompletedSetup(hand);
  }
  const busted = hand.state.players.filter(player => player.stack === 0);
  rebuyControl.hidden = !busted.length;
  rebuyControl.innerHTML = busted.length ? `<div class="rebuy-head"><strong>零筹码玩家补筹</strong><span>输入大于 0 的金额后，玩家将在下一手重新入局</span></div><div class="rebuy-players">${busted.map(player => `<label>${player.name}<input type="number" min="0" value="0" data-rebuy-seat="${player.seat}"></label>`).join("")}</div>` : "";
  updateCardInputs();
}

function render(hand) {
  currentHand = hand;
  pendingBoardCards = [];
  pendingRaiseAction = null;
  if (!hand.state.showdown_ready) showdownHands = {};
  updateCardInputs();
  hideRaiseControl();
  const state = hand.state;
  const pot = state.players.reduce((sum, player) => sum + player.total_commitment, 0);
  document.querySelector("#hand-error").textContent = "";
  document.querySelector("#hand-street").textContent = state.street.toUpperCase();
  document.querySelector("#street-caption").textContent = `${streetNames[state.street] || state.street} · 底池 ${pot}`;
  document.querySelector("#hand-pot").textContent = `底池 ${pot}`;
  document.querySelector("#hand-board").innerHTML = state.board.length ? state.board.map(card => cardMarkup(card)).join("") : "公共牌 --";
  document.querySelector("#board-picker").disabled = !state.awaiting_board;
  document.querySelector("#deal-button").disabled = !state.awaiting_board;
  document.querySelector("#analyze-hand-button").disabled = state.acting_seat !== hand.hero_seat;
  document.querySelector("#undo-hand-button").disabled = !hand.history_depth;
  document.querySelector("#branch-hand-button").disabled = false;
  status(state.complete ? "已结束" : state.awaiting_board ? "等待发牌" : state.showdown_ready ? "等待摊牌" : `座位 ${state.acting_seat} 行动`);
  renderShowdownControl();
  renderCompletionControl(hand);
  const order = ["PREFLOP", "FLOP", "TURN", "RIVER"];
  document.querySelectorAll(".street-progress span").forEach(element => {
    const label = element.textContent.trim().replace(/^\d/, "");
    element.classList.toggle("active", order.indexOf(label) <= order.indexOf(state.street.toUpperCase()));
  });

  const table = document.querySelector("#full-hand-table");
  table.querySelectorAll(".seat").forEach(element => element.remove());
  table.classList.toggle("crowded", state.players.length >= 7);
  const heroIndex = state.players.findIndex(player => player.seat === hand.hero_seat);
  state.players.forEach((player, index) => {
    const range = hand.ranges[String(player.seat)];
    const position = hand.positions[String(player.seat)] || "";
    const element = document.createElement("div");
    const angle = (90 + (index - heroIndex) * 360 / state.players.length) * Math.PI / 180;
    const horizontalRadius = state.players.length >= 7 ? 44 : 48;
    element.style.setProperty("--seat-x", `${50 + Math.cos(angle) * horizontalRadius}%`);
    element.style.setProperty("--seat-y", `${50 + Math.sin(angle) * 43}%`);
    const payout = Number(state.payouts[String(player.seat)] || 0);
    const cards = player.hole_cards
      ? player.hole_cards.map(card => cardMarkup(card, "table-card")).join("")
      : '<span class="table-card card-back"></span><span class="table-card card-back"></span>';
    const handLabel = player.seat === hand.hero_seat ? "HERO 手牌" : player.hole_cards ? "已知手牌" : "隐藏手牌";
    element.className = `seat dynamic-seat ${player.seat === state.acting_seat ? "active" : ""} ${player.seat === hand.hero_seat ? "hero" : ""} ${player.status === "folded" ? "folded" : ""} ${payout ? "winner" : ""}`;
    element.innerHTML = `<div class="seat-head"><strong>${player.name} · ${position}</strong>${payout ? `<em>WINNER +${payout}</em>` : ""}</div><div class="seat-hand"><small>${handLabel}</small>${cards}</div><span>筹码 ${player.stack} · 本街投入 ${player.street_commitment}</span><span>${player.status}${range ? ` · 范围 ${(range.coverage * 100).toFixed(1)}%` : ""}</span>`;
    table.appendChild(element);
  });

  const live = state.players.filter(player => !["folded", "out"].includes(player.status)).length;
  document.querySelector("#hand-summary").innerHTML = state.complete
    ? `<div><span>牌局状态</span><strong>完成</strong></div><div><span>派彩玩家</span><strong>${Object.keys(state.payouts).length}</strong></div><div><span>总派彩</span><strong>${Object.values(state.payouts).reduce((sum, value) => sum + value, 0)}</strong></div>`
    : `<div><span>当前街道</span><strong>${state.street}</strong></div><div><span>剩余玩家</span><strong>${live}</strong></div><div><span>行动总数</span><strong>${state.actions.length}</strong></div>`;
  renderRangePanel(hand);
  renderTimeline(state.actions);
  renderActions(hand.legal_actions);
}

function renderActions(legal) {
  const container = document.querySelector("#hand-actions");
  if (!legal) {
    container.className = "action-buttons empty";
    container.textContent = currentHand?.state.awaiting_board ? "请选择下一街公共牌" : "当前没有玩家行动";
    return;
  }
  container.className = "action-buttons";
  container.innerHTML = legal.actions.map(action => {
    const detail = action === "call" ? `<small>投入 ${legal.to_call}</small>` : ["bet", "raise"].includes(action) ? `<small>${legal.min_raise_to} - ${legal.max_raise_to}</small>` : "";
    return `<button type="button" data-action="${action}"><span>${actionNames[action] || action}</span>${detail}</button>`;
  }).join("");
  container.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => {
    const action = button.dataset.action;
    if (["bet", "raise"].includes(action)) showRaiseControl(action, legal);
    else submitAction(action);
  }));
}

function renderReviewNode(review, index) {
  const snapshot = review.snapshots[index];
  const state = snapshot.state;
  const heroSeat = review.final_hand.hero_seat;
  const pot = state.players.reduce((sum, player) => sum + player.total_commitment, 0);
  document.querySelectorAll("[data-review-node]").forEach(button => button.classList.toggle("active", Number(button.dataset.reviewNode) === index));
  document.querySelector("#review-node-content").innerHTML = `
    <div class="review-summary"><div><span>街道</span><strong>${state.street}</strong></div><div><span>底池</span><strong>${pot}</strong></div><div><span>当前行动</span><strong>${state.acting_seat || "--"}</strong></div><div><span>状态</span><strong>${state.complete ? "完成" : state.awaiting_board ? "等待发牌" : "进行中"}</strong></div></div>
    <div class="review-board"><strong>公共牌</strong>${state.board.length ? state.board.map(card => cardMarkup(card, "table-card")).join("") : "<span>--</span>"}</div>
    <div class="review-players">${state.players.map(player => `<div class="review-state-player"><strong>${player.name}${player.seat === heroSeat ? " · HERO" : ""}</strong><div class="seat-hand">${player.hole_cards ? player.hole_cards.map(card => cardMarkup(card, "table-card")).join("") : '<span class="table-card card-back"></span><span class="table-card card-back"></span>'}</div><span>筹码 ${player.stack} · 投入 ${player.total_commitment}</span><small>${player.status}</small></div>`).join("")}</div>
    <div class="review-range-snapshots">${Object.entries(snapshot.ranges).length ? Object.entries(snapshot.ranges).map(([seat, range]) => `<div><span>座位 ${seat} 对手范围</span><strong>${(range.coverage * 100).toFixed(1)}%</strong><small>${range.combo_count} 组合 · ${range.top_classes.slice(0, 5).join(" · ")}</small></div>`).join("") : '<div class="empty">此节点没有未知对手范围</div>'}</div>
    <div class="review-actions">${state.actions.length ? state.actions.map(action => `<div class="timeline-item"><span>${String(action.sequence).padStart(2, "0")}</span><strong>座位 ${action.seat} · ${actionNames[action.type] || action.type}</strong><small>${action.amount ? `+${action.amount}` : ""}</small></div>`).join("") : '<div class="empty">尚无行动</div>'}</div>`;
}

async function openReview(handId) {
  try {
    const review = (await getApi(`/api/reviews/${handId}`)).review;
    const final = review.final_hand.state;
    const hero = final.players.find(player => player.seat === review.final_hand.hero_seat);
    const result = hero.stack - hero.starting_stack;
    const detail = document.querySelector("#review-detail");
    detail.className = "review-detail";
    detail.innerHTML = `<div class="card-head"><div><b>REVIEW</b><span><strong>${(hero.hole_cards || []).join(" ")} · ${final.players.length} 人桌</strong><small>牌局 ${handId.slice(0, 12)}</small></span></div><em class="${result < 0 ? "negative" : ""}">${result >= 0 ? "+" : ""}${result}</em></div><div class="review-node-bar">${review.snapshots.map((snapshot, index) => `<button type="button" data-review-node="${index}">${index === review.snapshots.length - 1 ? "最终" : `节点 ${index + 1}`}</button>`).join("")}</div><div id="review-node-content"></div>`;
    document.querySelectorAll("[data-review-node]").forEach(button => button.addEventListener("click", () => renderReviewNode(review, Number(button.dataset.reviewNode))));
    renderReviewNode(review, review.snapshots.length - 1);
  } catch (error) { showError(error); }
}

async function loadReviews(query = "") {
  const container = document.querySelector("#review-list");
  try {
    const reviews = (await getApi(`/api/reviews${query ? `?q=${encodeURIComponent(query)}` : ""}`)).reviews;
    if (!reviews.length) {
      container.className = "review-list empty";
      container.textContent = "尚无匹配的已归档牌局";
      return;
    }
    container.className = "review-list";
    container.innerHTML = reviews.map(review => `<button type="button" class="review-item" data-review-id="${review.hand_id}"><strong>${review.hero_cards || "Hero 手牌未知"} · ${review.player_count} 人桌</strong><span class="${review.hero_result < 0 ? "negative" : "positive"}">${review.hero_result >= 0 ? "+" : ""}${review.hero_result}</span><small>${new Date(review.completed_at).toLocaleString()} · 底池 ${review.pot} · ${review.action_count} 个行动</small></button>`).join("");
    document.querySelectorAll("[data-review-id]").forEach(button => button.addEventListener("click", () => openReview(button.dataset.reviewId)));
  } catch (error) {
    container.className = "review-list empty";
    container.textContent = error.message;
  }
}

async function loadTraining() {
  const position = document.querySelector("#training-position").value;
  const action = document.querySelector("#training-action").value;
  const training = (await getApi(`/api/training/preflop?position=${position}&action=${action}`)).training;
  trainingTarget = new Set(training.classes);
  trainingSelected = new Set();
  renderTrainingMatrix();
  document.querySelector("#training-result").className = "analysis empty";
  document.querySelector("#training-result").textContent = `目标基础范围覆盖 ${(training.coverage * 100).toFixed(1)}% · ${training.combo_count} 个具体组合`;
}

function renderTrainingMatrix(reveal = false) {
  document.querySelector("#training-matrix").innerHTML = ranks.flatMap((_, row) => ranks.map((__, column) => {
    const handClass = handClassAt(row, column);
    const selected = trainingSelected.has(handClass);
    const target = trainingTarget.has(handClass);
    const resultClass = reveal ? selected && target ? "correct" : selected ? "extra" : target ? "missed" : "" : "";
    return `<button type="button" data-training-class="${handClass}" class="${selected ? "selected" : ""} ${resultClass}">${handClass}</button>`;
  })).join("");
  document.querySelectorAll("[data-training-class]").forEach(button => button.addEventListener("click", () => {
    const handClass = button.dataset.trainingClass;
    if (trainingSelected.has(handClass)) trainingSelected.delete(handClass); else trainingSelected.add(handClass);
    renderTrainingMatrix();
  }));
}

document.querySelector("#training-submit").addEventListener("click", () => {
  const correct = [...trainingSelected].filter(item => trainingTarget.has(item)).length;
  const extra = [...trainingSelected].filter(item => !trainingTarget.has(item)).length;
  const missed = [...trainingTarget].filter(item => !trainingSelected.has(item)).length;
  const precision = trainingSelected.size ? correct / trainingSelected.size : 0;
  const recall = trainingTarget.size ? correct / trainingTarget.size : 0;
  const score = precision + recall ? 2 * precision * recall / (precision + recall) : 0;
  renderTrainingMatrix(true);
  const result = document.querySelector("#training-result");
  result.className = "analysis training-score";
  result.innerHTML = `<div><span>综合得分</span><strong>${(score * 100).toFixed(0)}</strong></div><p>正确 ${correct} · 多选 ${extra} · 漏选 ${missed}</p><small>绿色为正确，红色为多选，金色为漏选。</small>`;
});
document.querySelector("#training-reset").addEventListener("click", () => { trainingSelected = new Set(); renderTrainingMatrix(); });
document.querySelector("#training-position").addEventListener("change", loadTraining);
document.querySelector("#training-action").addEventListener("change", loadTraining);

document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => {
  const reviews = button.dataset.view === "reviews";
  const training = button.dataset.view === "training";
  document.querySelectorAll("[data-view]").forEach(tab => tab.classList.toggle("active", tab === button));
  document.querySelector("#analysis-workspace").hidden = reviews || training;
  document.querySelector(".street-bar").hidden = reviews || training;
  document.querySelector("#review-library").hidden = !reviews;
  document.querySelector("#range-training").hidden = !training;
  if (reviews) loadReviews(document.querySelector("#review-search").value.trim());
  if (training && !trainingTarget.size) loadTraining();
}));
document.querySelector("#review-search").addEventListener("input", event => loadReviews(event.target.value.trim()));

function showRaiseControl(action, legal) {
  pendingRaiseAction = action;
  const control = document.querySelector("#raise-control");
  const slider = document.querySelector("#raise-slider");
  const input = document.querySelector("#raise-input");
  slider.min = input.min = legal.min_raise_to;
  slider.max = input.max = legal.max_raise_to;
  slider.value = input.value = legal.min_raise_to;
  document.querySelector("#raise-value").textContent = legal.min_raise_to;
  document.querySelector("#raise-submit").textContent = `确认${actionNames[action]}`;
  const pot = currentHand.state.players.reduce((sum, player) => sum + player.total_commitment, 0);
  const candidates = currentHand.state.street === "preflop"
    ? [{ label: "2.5x", value: Math.round(currentHand.state.current_bet * 2.5) }, { label: "3x", value: Math.round(currentHand.state.current_bet * 3) }, { label: "4x", value: Math.round(currentHand.state.current_bet * 4) }]
    : [{ label: "33%", value: Math.round(pot * .33) + currentHand.state.current_bet }, { label: "50%", value: Math.round(pot * .5) + currentHand.state.current_bet }, { label: "75%", value: Math.round(pot * .75) + currentHand.state.current_bet }, { label: "底池", value: pot + currentHand.state.current_bet }];
  document.querySelector("#raise-presets").innerHTML = candidates.map(candidate => {
    const value = Math.min(legal.max_raise_to, Math.max(legal.min_raise_to, candidate.value));
    return `<button type="button" data-raise-preset="${value}">${candidate.label}<small>${value}</small></button>`;
  }).join("");
  document.querySelectorAll("[data-raise-preset]").forEach(button => button.addEventListener("click", () => syncRaiseValue(button.dataset.raisePreset)));
  control.hidden = false;
}

function hideRaiseControl() {
  document.querySelector("#raise-control").hidden = true;
}

function syncRaiseValue(value) {
  const slider = document.querySelector("#raise-slider");
  const input = document.querySelector("#raise-input");
  const normalized = Math.min(Number(slider.max), Math.max(Number(slider.min), Number(value)));
  slider.value = input.value = normalized;
  document.querySelector("#raise-value").textContent = normalized;
}

document.querySelector("#raise-slider").addEventListener("input", event => syncRaiseValue(event.target.value));
document.querySelector("#raise-input").addEventListener("input", event => syncRaiseValue(event.target.value));
document.querySelector("#raise-submit").addEventListener("click", () => pendingRaiseAction && submitAction(pendingRaiseAction, Number(document.querySelector("#raise-input").value)));

async function submitAction(action, raiseTo = null) {
  try {
    render((await api(`/api/hands/${currentHand.hand_id}/actions`, { type: action, raise_to: raiseTo })).hand);
    document.querySelector("#hand-analysis").textContent = "状态已变化，请重新运行策略分析";
  } catch (error) { showError(error); }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form));
  if (!values.hero_hand) return showError(new Error("请先选择 Hero 手牌"));
  const heroSeat = Number(values.hero_seat);
  try {
    const data = await api("/api/hands", {
      button_seat: Number(values.button_seat), hero_seat: heroSeat, small_blind: Number(values.small_blind), big_blind: Number(values.big_blind), ante: Number(values.ante),
      players: Array.from({ length: Number(values.player_count) }, (_, index) => index + 1).map(seat => ({ seat, name: seat === heroSeat ? "Hero" : `Villain ${seat}`, stack: Number(values[`stack_${seat}`]), profile: values[`profile_${seat}`], hand: seat === heroSeat ? values.hero_hand : "" }))
    });
    render(data.hand);
    document.querySelector(".setup-panel").open = false;
  } catch (error) { showError(error); }
});

document.querySelector("#deal-button").addEventListener("click", async () => {
  if (!currentHand) return showError(new Error("请先创建牌局"));
  if (!pendingBoardCards.length) return showError(new Error("请先选择公共牌"));
  try { render((await api(`/api/hands/${currentHand.hand_id}/deal`, { cards: pendingBoardCards.join(" ") })).hand); } catch (error) { showError(error); }
});

document.querySelector("#showdown-submit").addEventListener("click", async () => {
  if (!currentHand?.state.showdown_ready) return;
  try {
    render((await api(`/api/hands/${currentHand.hand_id}/showdown`, {
      hands: Object.fromEntries(Object.entries(showdownHands).map(([seat, cards]) => [seat, cards.join(" ")]))
    })).hand);
  } catch (error) { showError(error); }
});

async function continueHand(operation) {
  if (!currentHand) return;
  if (operation !== "reset" && !form.elements.hero_hand.value) return showError(new Error("请先选择下一手 Hero 手牌"));
  try {
    const hand = (await api(`/api/hands/${currentHand.hand_id}/${operation}`, {
      hero_hand: form.elements.hero_hand.value,
      rebuys: operation === "next" ? Object.fromEntries(
        [...document.querySelectorAll("[data-rebuy-seat]")]
          .map(input => [input.dataset.rebuySeat, Number(input.value)])
          .filter(([, amount]) => amount > 0)
      ) : {}
    })).hand;
    render(hand);
    status(operation === "next" ? "下一手已开始" : operation === "restart" ? "已重开本手" : "已回到本手起点");
  } catch (error) { showError(error); }
}

document.querySelector("#next-hand-button").addEventListener("click", () => continueHand("next"));
document.querySelector("#restart-hand-button").addEventListener("click", () => continueHand("restart"));
document.querySelector("#reset-hand-button").addEventListener("click", () => continueHand("reset"));

document.querySelector("#analyze-hand-button").addEventListener("click", async () => {
  if (!currentHand) return showError(new Error("请先创建牌局"));
  const container = document.querySelector("#hand-analysis");
  const analyzeButton = document.querySelector("#analyze-hand-button");
  analyzeButton.disabled = true;
  analyzeButton.classList.add("loading");
  container.className = "analysis empty";
  container.textContent = "正在运行逐范围响应模拟…";
  try {
    const analysis = (await api(`/api/hands/${currentHand.hand_id}/analyze`, { simulations: 500, seed: 42 })).analysis;
    container.className = "analysis";
    const maxAbsEv = Math.max(...analysis.exploit_actions.map(action => Math.abs(action.ev)), 1);
    container.innerHTML = `<div class="recommend"><span>利用性推荐</span><strong>${actionNames[analysis.exploit_action.action_type] || analysis.exploit_action.action_type} · ${analysis.exploit_action.label}</strong><small>基准 ${analysis.baseline_action.label} · 底池 ${analysis.pot} · SPR ${analysis.spr.toFixed(2)}</small></div>
      <div class="analysis-metrics"><div><span>跟注成本</span><strong>${analysis.to_call}</strong></div><div><span>有效筹码</span><strong>${analysis.effective_stack}</strong></div><div><span>候选动作</span><strong>${analysis.exploit_actions.length}</strong></div></div>
      <div class="ev-chart">${analysis.exploit_actions.map(action => {
        const width = Math.max(Math.abs(action.ev) / maxAbsEv * 100, 3);
        return `<div class="ev-row ${action.candidate.label === analysis.exploit_action.label ? "best" : ""}"><div class="ev-label"><strong>${actionNames[action.candidate.action_type] || action.candidate.action_type}</strong><small>${action.candidate.label}</small></div><div class="ev-track"><i class="${action.ev < 0 ? "negative" : ""}" style="width:${width}%"></i></div><strong class="${action.ev < 0 ? "negative" : ""}">${action.ev >= 0 ? "+" : ""}${action.ev.toFixed(2)}</strong></div>`;
      }).join("")}</div>
      <div class="analysis-detail">${analysis.exploit_actions.map(action => `<div><span>${actionNames[action.candidate.action_type] || action.candidate.action_type} · ${action.candidate.label}</span><i><b style="width:${action.heuristic_frequency * 100}%"></b></i><small>推荐 ${(action.heuristic_frequency * 100).toFixed(0)}% · 置信 ${(action.confidence * 100).toFixed(0)}%${action.equity_when_called === null ? "" : ` · 跟注后胜率 ${(action.equity_when_called * 100).toFixed(0)}%`}</small></div>`).join("")}</div>
      <div class="reason-list">${analysis.key_reasons.map(reason => `<p>${reason}</p>`).join("")}</div>`;
  } catch (error) { container.textContent = error.message; showError(error); }
  finally {
    analyzeButton.classList.remove("loading");
    analyzeButton.disabled = currentHand?.state.acting_seat !== currentHand?.hero_seat;
  }
});

document.querySelector("#undo-hand-button").addEventListener("click", async () => { if (currentHand) try { render((await api(`/api/hands/${currentHand.hand_id}/undo`)).hand); } catch (error) { showError(error); } });
document.querySelector("#branch-hand-button").addEventListener("click", async () => {
  if (!currentHand) return;
  try { const hand = (await api(`/api/hands/${currentHand.hand_id}/branch`)).hand; render(hand); status(`分支 ${hand.hand_id.slice(0, 8)}`); } catch (error) { showError(error); }
});
renderPlayerSetup(playerCount);
updateCardInputs();

async function checkService() {
  const banner = document.querySelector("#connection-banner");
  try {
    const response = await fetch(API_BASE + "/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error();
    banner.hidden = true;
  } catch (_error) {
    banner.hidden = false;
  }
}
checkService();
