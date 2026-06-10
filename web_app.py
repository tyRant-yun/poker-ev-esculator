#!/usr/bin/env python3
"""Local web interface for complete Texas Hold'em hand analysis."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from poker import (
    ActionType,
    BALANCED_PROFILE,
    GameConfig,
    LOOSE_AGGRESSIVE_PROFILE,
    TIGHT_PROFILE,
    analyze_strategy,
    apply_action,
    combo_class,
    create_hand,
    deal_board,
    filter_ranges_for_state,
    hand_to_dict,
    initialize_player_ranges,
    legal_actions,
    parse_cards,
    positions_by_seat,
    preflop_range,
    settle_showdown,
    strategy_to_dict,
    update_ranges_after_action,
)
from review_store import DEFAULT_DB_PATH, get_review, list_reviews, save_review


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "web"
HAND_SESSIONS: dict[str, dict] = {}
HAND_SESSIONS_LOCK = threading.RLock()
REVIEW_DB_PATH = DEFAULT_DB_PATH
PROFILE_PRESETS = {
    "balanced": BALANCED_PROFILE,
    "tight": TIGHT_PROFILE,
    "loose_aggressive": LOOSE_AGGRESSIVE_PROFILE,
}


def _legal_actions_data(state) -> dict | None:
    if state.acting_seat is None or state.awaiting_board or state.showdown_ready or state.complete:
        return None
    legal = legal_actions(state)
    return {
        "seat": legal.seat,
        "to_call": legal.to_call,
        "actions": [action.value for action in legal.actions],
        "min_raise_to": legal.min_raise_to,
        "max_raise_to": legal.max_raise_to,
        "full_raise_min_to": legal.full_raise_min_to,
    }


def _range_summary(session: dict) -> dict[str, dict]:
    summaries = {}
    for seat, weighted in session["ranges"].items():
        class_weights: dict[str, float] = {}
        for combo, weight in weighted.combos.items():
            hand_class = combo_class(combo)
            class_weights[hand_class] = class_weights.get(hand_class, 0.0) + weight
        class_density = {
            hand_class: weight / (6 if len(hand_class) == 2 else 4 if hand_class.endswith("s") else 12)
            for hand_class, weight in class_weights.items()
        }
        peak = max(class_density.values(), default=1.0)
        matrix = {
            hand_class: round(density / peak, 4)
            for hand_class, density in class_density.items()
        }
        top_classes = sorted(matrix, key=matrix.get, reverse=True)[:8]
        summaries[str(seat)] = {
            "source": weighted.source,
            "combo_count": weighted.combo_count,
            "coverage": weighted.coverage,
            "matrix": matrix,
            "top_classes": top_classes,
        }
    return summaries


def preflop_training_data(position: str, action: str) -> dict:
    weighted = preflop_range(position, action)
    classes = sorted({combo_class(combo) for combo in weighted.combos})
    return {
        "position": position.upper(),
        "action": action,
        "coverage": weighted.coverage,
        "combo_count": weighted.combo_count,
        "classes": classes,
    }


def hand_session_data(hand_id: str) -> dict:
    with HAND_SESSIONS_LOCK:
        if hand_id not in HAND_SESSIONS:
            raise ValueError("牌局不存在或服务已重启")
        session = HAND_SESSIONS[hand_id]
        state = session["state"]
        return {
            "hand_id": hand_id,
            "hero_seat": session["hero_seat"],
            "state": hand_to_dict(state),
            "positions": {str(seat): position for seat, position in positions_by_seat(state).items()},
            "legal_actions": _legal_actions_data(state),
            "ranges": _range_summary(session),
            "history_depth": len(session["history"]),
        }


def _archive_completed_hand(hand_id: str, session: dict) -> None:
    if not session["state"].complete:
        return
    final_hand = hand_session_data(hand_id)
    snapshots = [
        {
            "index": index,
            "state": hand_to_dict(snapshot["state"]),
            "ranges": _range_summary({"ranges": snapshot["ranges"]}),
        }
        for index, snapshot in enumerate(session["history"])
    ]
    snapshots.append(
        {
            "index": len(snapshots),
            "state": final_hand["state"],
            "ranges": final_hand["ranges"],
        }
    )
    save_review(hand_id, {"final_hand": final_hand, "snapshots": snapshots}, REVIEW_DB_PATH)


def _store_hand_session(
    state,
    hero_seat: int,
    profiles: dict[int, object],
    *,
    setup: dict | None = None,
) -> str:
    hand_id = uuid.uuid4().hex
    ranges = initialize_player_ranges(state, hero_seat=hero_seat)
    setup = setup or {
        "config": state.config,
        "hero_seat": hero_seat,
        "names": {player.seat: player.name for player in state.players},
        "profiles": dict(profiles),
        "starting_stacks": {player.seat: player.starting_stack for player in state.players},
    }
    HAND_SESSIONS[hand_id] = {
        "state": state,
        "hero_seat": hero_seat,
        "ranges": ranges,
        "profiles": dict(profiles),
        "history": [],
        "initial_state": state.clone(),
        "initial_ranges": dict(ranges),
        "setup": setup,
    }
    return hand_id


def _new_hand_from_setup(setup: dict, stacks: dict[int, int], hero_hand: str, button_seat: int):
    hero_seat = setup["hero_seat"]
    if hero_seat not in stacks or stacks[hero_seat] <= 0:
        raise ValueError("Hero 已无筹码，无法继续下一手")
    active_stacks = {seat: stack for seat, stack in stacks.items() if stack > 0}
    if len(active_stacks) < 2:
        raise ValueError("至少需要两位仍有筹码的玩家才能开始下一手")
    cards = parse_cards(str(hero_hand).strip())
    if len(cards) != 2:
        raise ValueError("请为新牌局选择两张 Hero 手牌")
    config = setup["config"]
    state = create_hand(
        GameConfig(
            small_blind=config.small_blind,
            big_blind=config.big_blind,
            ante=config.ante,
            button_seat=button_seat,
        ),
        active_stacks,
        names={seat: setup["names"][seat] for seat in active_stacks},
        hole_cards={hero_seat: cards},
    )
    profiles = {seat: setup["profiles"][seat] for seat in active_stacks}
    return state, profiles


def create_hand_request(payload: dict) -> dict:
    raw_players = payload.get("players")
    if not isinstance(raw_players, list) or not 2 <= len(raw_players) <= 9:
        raise ValueError("players 必须是包含 2 至 9 位玩家的数组")
    stacks: dict[int, int] = {}
    names: dict[int, str] = {}
    hole_cards: dict[int, list[str]] = {}
    profiles: dict[int, object] = {}
    hero_seat = int(payload.get("hero_seat", 0))
    for raw in raw_players:
        if not isinstance(raw, dict):
            raise ValueError("每位玩家必须是 JSON 对象")
        seat = int(raw["seat"])
        stacks[seat] = int(raw["stack"])
        names[seat] = str(raw.get("name", f"Seat {seat}"))
        hand = str(raw.get("hand", "")).strip()
        if hand:
            hole_cards[seat] = parse_cards(hand)
        profile_name = str(raw.get("profile", "balanced"))
        if profile_name not in PROFILE_PRESETS:
            raise ValueError(f"未知对手画像: {profile_name}")
        profiles[seat] = PROFILE_PRESETS[profile_name]
    if hero_seat not in stacks:
        raise ValueError("hero_seat 必须属于牌局")
    if hero_seat not in hole_cards:
        raise ValueError("必须提供 Hero 手牌")

    state = create_hand(
        GameConfig(
            small_blind=int(payload.get("small_blind", 1)),
            big_blind=int(payload.get("big_blind", 2)),
            ante=int(payload.get("ante", 0)),
            button_seat=int(payload["button_seat"]),
        ),
        stacks,
        names=names,
        hole_cards=hole_cards,
    )
    with HAND_SESSIONS_LOCK:
        hand_id = _store_hand_session(state, hero_seat, profiles)
    return hand_session_data(hand_id)


def _save_hand_snapshot(session: dict) -> None:
    session["history"].append({"state": session["state"].clone(), "ranges": dict(session["ranges"])})


def apply_hand_action_request(hand_id: str, payload: dict) -> dict:
    with HAND_SESSIONS_LOCK:
        session = _session(hand_id)
        before = session["state"]
        after = apply_action(
            before,
            ActionType(str(payload["type"])),
            raise_to=int(payload["raise_to"]) if payload.get("raise_to") not in (None, "") else None,
        )
        _save_hand_snapshot(session)
        session["state"] = after
        session["ranges"] = update_ranges_after_action(
            before, after, session["ranges"], profiles=session["profiles"]
        )
        _archive_completed_hand(hand_id, session)
    return hand_session_data(hand_id)


def deal_hand_request(hand_id: str, payload: dict) -> dict:
    with HAND_SESSIONS_LOCK:
        session = _session(hand_id)
        after = deal_board(session["state"], parse_cards(str(payload.get("cards", ""))))
        _save_hand_snapshot(session)
        session["state"] = after
        session["ranges"] = filter_ranges_for_state(after, session["ranges"])
    return hand_session_data(hand_id)


def undo_hand_request(hand_id: str) -> dict:
    with HAND_SESSIONS_LOCK:
        session = _session(hand_id)
        if not session["history"]:
            raise ValueError("当前没有可撤销的牌局步骤")
        snapshot = session["history"].pop()
        session["state"] = snapshot["state"]
        session["ranges"] = snapshot["ranges"]
    return hand_session_data(hand_id)


def branch_hand_request(hand_id: str) -> dict:
    with HAND_SESSIONS_LOCK:
        source = _session(hand_id)
        branch_id = _store_hand_session(
            source["state"].clone(),
            source["hero_seat"],
            source["profiles"],
            setup=source["setup"],
        )
    return hand_session_data(branch_id)


def reset_hand_request(hand_id: str) -> dict:
    with HAND_SESSIONS_LOCK:
        session = _session(hand_id)
        session["state"] = session["initial_state"].clone()
        session["ranges"] = dict(session["initial_ranges"])
        session["history"] = []
    return hand_session_data(hand_id)


def restart_hand_request(hand_id: str, payload: dict) -> dict:
    with HAND_SESSIONS_LOCK:
        source = _session(hand_id)
        setup = source["setup"]
        state, profiles = _new_hand_from_setup(
            setup,
            setup["starting_stacks"],
            payload.get("hero_hand", ""),
            setup["config"].button_seat,
        )
        new_id = _store_hand_session(state, setup["hero_seat"], profiles, setup=setup)
    return hand_session_data(new_id)


def next_hand_request(hand_id: str, payload: dict) -> dict:
    with HAND_SESSIONS_LOCK:
        source = _session(hand_id)
        if not source["state"].complete:
            raise ValueError("当前牌局尚未结束，无法开始下一手")
        setup = source["setup"]
        stacks = {seat: 0 for seat in setup["names"]}
        stacks.update({player.seat: player.stack for player in source["state"].players})
        raw_rebuys = payload.get("rebuys", {})
        if not isinstance(raw_rebuys, dict):
            raise ValueError("rebuys 必须是座位到补筹金额的对象")
        for raw_seat, raw_amount in raw_rebuys.items():
            seat = int(raw_seat)
            amount = int(raw_amount)
            if seat not in stacks:
                raise ValueError(f"未知补筹座位: {seat}")
            if stacks[seat] > 0:
                raise ValueError(f"座位 {seat} 仍有筹码，无需补筹")
            if amount <= 0:
                raise ValueError(f"座位 {seat} 的补筹金额必须大于 0")
            stacks[seat] = amount
        active_seats = sorted(seat for seat, stack in stacks.items() if stack > 0)
        if len(active_seats) < 2:
            raise ValueError("至少需要两位仍有筹码的玩家才能开始下一手")
        old_button = source["state"].config.button_seat
        next_button = next((seat for seat in active_seats if seat > old_button), active_seats[0])
        state, profiles = _new_hand_from_setup(
            setup,
            stacks,
            payload.get("hero_hand", ""),
            next_button,
        )
        next_setup = {
            **setup,
            "config": state.config,
            "starting_stacks": {seat: stack for seat, stack in stacks.items() if stack > 0},
        }
        new_id = _store_hand_session(state, setup["hero_seat"], profiles, setup=next_setup)
    return hand_session_data(new_id)


def settle_hand_request(hand_id: str, payload: dict) -> dict:
    with HAND_SESSIONS_LOCK:
        session = _session(hand_id)
        state = session["state"]
        if not state.showdown_ready:
            raise ValueError("当前牌局尚未进入摊牌阶段")
        raw_hands = payload.get("hands", {})
        if not isinstance(raw_hands, dict):
            raise ValueError("hands 必须是座位到手牌的对象")
        result = state.clone()
        for player in result.players:
            if player.status.value in ("folded", "out") or player.hole_cards:
                continue
            cards = parse_cards(str(raw_hands.get(str(player.seat), "")))
            if len(cards) != 2:
                raise ValueError(f"必须提供座位 {player.seat} 的两张摊牌手牌")
            player.hole_cards = cards
        _save_hand_snapshot(session)
        session["state"] = settle_showdown(result)
        session["ranges"] = {}
        _archive_completed_hand(hand_id, session)
    return hand_session_data(hand_id)


def analyze_hand_request(hand_id: str, payload: dict) -> dict:
    with HAND_SESSIONS_LOCK:
        session = _session(hand_id)
        result = analyze_strategy(
            session["state"],
            session["hero_seat"],
            session["ranges"],
            profiles=session["profiles"],
            simulations=int(payload.get("simulations", 500)),
            seed=int(payload.get("seed", 1)),
        )
    return strategy_to_dict(result)


def _session(hand_id: str) -> dict:
    if hand_id not in HAND_SESSIONS:
        raise ValueError("牌局不存在或服务已重启")
    return HAND_SESSIONS[hand_id]


class AppHandler(BaseHTTPRequestHandler):
    server_version = "PokerWorkbench/2.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("请求内容过大")
        payload = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象")
        return payload

    def do_POST(self) -> None:
        request_path = urlparse(self.path).path
        hand_match = re.fullmatch(
            r"/api/hands/([0-9a-f]+)/(?P<operation>actions|deal|analyze|undo|branch|showdown|reset|restart|next)",
            request_path,
        )
        if request_path != "/api/hands" and not hand_match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_payload()
            if request_path == "/api/hands":
                self.send_json({"ok": True, "hand": create_hand_request(payload)}, HTTPStatus.CREATED)
                return
            hand_id = hand_match.group(1)
            operation = hand_match.group("operation")
            handlers = {
                "actions": lambda: apply_hand_action_request(hand_id, payload),
                "deal": lambda: deal_hand_request(hand_id, payload),
                "undo": lambda: undo_hand_request(hand_id),
                "branch": lambda: branch_hand_request(hand_id),
                "showdown": lambda: settle_hand_request(hand_id, payload),
                "reset": lambda: reset_hand_request(hand_id),
                "restart": lambda: restart_hand_request(hand_id, payload),
                "next": lambda: next_hand_request(hand_id, payload),
            }
            if operation == "analyze":
                self.send_json({"ok": True, "analysis": analyze_hand_request(hand_id, payload)})
            else:
                status = HTTPStatus.CREATED if operation in ("branch", "restart", "next") else HTTPStatus.OK
                self.send_json({"ok": True, "hand": handlers[operation]()}, status)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self.send_json({"ok": False, "error": "请求处理失败，请检查输入后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        if request_path == "/api/health":
            self.send_json({"ok": True, "service": "complete-hand-workbench", "version": 2})
            return
        if request_path == "/api/reviews":
            search = parse_qs(urlparse(self.path).query).get("q", [""])[0]
            self.send_json({"ok": True, "reviews": list_reviews(search, REVIEW_DB_PATH)})
            return
        if request_path == "/api/training/preflop":
            query = parse_qs(urlparse(self.path).query)
            try:
                self.send_json(
                    {
                        "ok": True,
                        "training": preflop_training_data(
                            query.get("position", ["BTN"])[0],
                            query.get("action", ["rfi"])[0],
                        ),
                    }
                )
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        review_match = re.fullmatch(r"/api/reviews/([0-9a-f]+)", request_path)
        if review_match:
            try:
                self.send_json({"ok": True, "review": get_review(review_match.group(1), REVIEW_DB_PATH)})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        hand_match = re.fullmatch(r"/api/hands/([0-9a-f]+)", request_path)
        if hand_match:
            try:
                self.send_json({"ok": True, "hand": hand_session_data(hand_match.group(1))})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in candidate.parents or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="启动德州扑克完整手牌策略工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Poker Strategy Workbench: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
