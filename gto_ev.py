#!/usr/bin/env python3
"""Texas Hold'em single-node GTO/EV approximation calculator."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)
RANK_VALUE = {rank: value for value, rank in enumerate(RANKS, start=2)}

POSITION_DEFAULT_RANGE = {
    "UTG": 0.18,
    "UTG+1": 0.20,
    "MP": 0.25,
    "HJ": 0.29,
    "CO": 0.34,
    "BTN": 0.44,
    "SB": 0.38,
    "BB": 0.42,
}

STRATEGY_PRESETS = {
    "tight": {"range_multiplier": 0.72, "fold_to_raise": 0.55, "temperature": 0.45},
    "balanced": {"range_multiplier": 1.0, "fold_to_raise": 0.42, "temperature": 0.70},
    "loose": {"range_multiplier": 1.30, "fold_to_raise": 0.30, "temperature": 0.95},
}


@dataclass
class Result:
    players: int
    position: str
    hand: list[str]
    board: list[str]
    strategy: str
    opponent_range: float
    fold_to_raise: float
    simulations: int
    equity: float
    win_rate: float
    tie_rate: float
    action_ev: dict[str, float]
    recommended_action: str
    mixed_strategy: dict[str, float]
    raise_recommendation: dict[str, float | str]


def parse_cards(text: str | Iterable[str]) -> list[str]:
    parts = text.split() if isinstance(text, str) else list(text)
    cards = [part.strip() for part in parts if part.strip()]
    normalized = []
    for card in cards:
        if len(card) != 2:
            raise ValueError(f"无效牌面: {card!r}，格式示例: As Kh")
        rank, suit = card[0].upper(), card[1].lower()
        normalized_card = rank + suit
        if rank not in RANKS or suit not in SUITS:
            raise ValueError(f"无效牌面: {card!r}，点数为 2-A，花色为 c/d/h/s")
        normalized.append(normalized_card)
    if len(set(normalized)) != len(normalized):
        raise ValueError("输入中存在重复牌")
    return normalized


def evaluate_five(cards: Sequence[str]) -> tuple[int, ...]:
    values = sorted((RANK_VALUE[card[0]] for card in cards), reverse=True)
    counts = {value: values.count(value) for value in set(values)}
    groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
    flush = len({card[1] for card in cards}) == 1
    unique = sorted(set(values), reverse=True)
    if unique == [14, 5, 4, 3, 2]:
        straight_high = 5
    else:
        straight_high = unique[0] if len(unique) == 5 and unique[0] - unique[-1] == 4 else 0

    if flush and straight_high:
        return (8, straight_high)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if groups[0][0] == 3 and groups[1][0] == 2:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *values)
    if straight_high:
        return (4, straight_high)
    if groups[0][0] == 3:
        kickers = sorted((value for value in values if value != groups[0][1]), reverse=True)
        return (3, groups[0][1], *kickers)
    pairs = sorted((value for value, count in counts.items() if count == 2), reverse=True)
    if len(pairs) == 2:
        kicker = max(value for value in values if value not in pairs)
        return (2, *pairs, kicker)
    if len(pairs) == 1:
        kickers = sorted((value for value in values if value != pairs[0]), reverse=True)
        return (1, pairs[0], *kickers)
    return (0, *values)


def evaluate(cards: Sequence[str]) -> tuple[int, ...]:
    if len(cards) < 5 or len(cards) > 7:
        raise ValueError("牌力计算需要 5 到 7 张牌")
    return max(evaluate_five(combo) for combo in itertools.combinations(cards, 5))


def preflop_score(cards: Sequence[str]) -> float:
    """Return a rough 0-1 preflop strength score used only for range sampling."""
    a, b = sorted((RANK_VALUE[card[0]] for card in cards), reverse=True)
    paired = a == b
    suited = cards[0][1] == cards[1][1]
    gap = a - b
    if paired:
        score = 0.52 + (a - 2) / 12 * 0.48
    else:
        score = (a + b - 4) / 24 * 0.60
        score += 0.10 if suited else 0.0
        score += 0.12 if gap == 1 else 0.06 if gap == 2 else 0.0
        score += 0.08 if a >= 12 and b >= 10 else 0.0
    return min(score, 1.0)


ALL_HOLE_COMBOS = tuple(itertools.combinations(DECK, 2))
SORTED_HOLE_COMBOS = tuple(sorted(ALL_HOLE_COMBOS, key=preflop_score, reverse=True))


def range_combos(range_fraction: float, dead_cards: set[str]) -> list[tuple[str, str]]:
    count = max(1, round(len(SORTED_HOLE_COMBOS) * range_fraction))
    return [combo for combo in SORTED_HOLE_COMBOS[:count] if not dead_cards.intersection(combo)]


def simulate_equity(
    hero: Sequence[str],
    board: Sequence[str],
    players: int,
    opponent_range: float,
    simulations: int,
    rng: random.Random,
) -> tuple[float, float, float, int]:
    dead_initial = set(hero) | set(board)
    candidates = range_combos(opponent_range, dead_initial)
    wins = ties = equity_points = completed = 0.0

    for _ in range(simulations):
        dead = set(dead_initial)
        opponents: list[tuple[str, str]] = []
        for _opponent in range(players - 1):
            chosen = None
            for _attempt in range(1_000):
                candidate = rng.choice(candidates)
                if not dead.intersection(candidate):
                    chosen = candidate
                    break
            if chosen is None:
                break
            opponents.append(chosen)
            dead.update(chosen)
        if len(opponents) != players - 1:
            continue

        remaining = [card for card in DECK if card not in dead]
        runout = rng.sample(remaining, 5 - len(board))
        final_board = list(board) + runout
        hero_rank = evaluate(list(hero) + final_board)
        opponent_ranks = [evaluate(list(hand) + final_board) for hand in opponents]
        best = max([hero_rank, *opponent_ranks])
        winners = (1 if hero_rank == best else 0) + sum(rank == best for rank in opponent_ranks)
        if hero_rank == best:
            equity_points += 1 / winners
            if winners == 1:
                wins += 1
            else:
                ties += 1
        completed += 1

    if not completed:
        raise ValueError("对手范围过窄，无法为所有玩家发牌；请扩大 opponent-range")
    return equity_points / completed, wins / completed, ties / completed, int(completed)


def calculate_action_ev(
    equity: float,
    pot: float,
    to_call: float,
    raise_size: float,
    fold_to_raise: float,
) -> dict[str, float]:
    if to_call > 0:
        passive_action = "call"
        passive_ev = equity * (pot + to_call) - to_call
    else:
        passive_action = "check"
        passive_ev = equity * pot

    action_ev = {"fold": 0.0, passive_action: passive_ev}
    if raise_size > 0:
        opponent_extra_call = max(raise_size - to_call, 0.0)
        called_final_pot = pot + raise_size + opponent_extra_call
        raise_ev = (
            fold_to_raise * pot
            + (1 - fold_to_raise) * (equity * called_final_pot - raise_size)
        )
        action_ev["raise" if to_call > 0 else "bet"] = raise_ev
    return action_ev


def softmax_strategy(action_ev: dict[str, float], temperature: float) -> dict[str, float]:
    scale = max(temperature, 0.01)
    peak = max(action_ev.values())
    weights = {action: math.exp((ev - peak) / scale) for action, ev in action_ev.items()}
    total = sum(weights.values())
    return {action: weight / total for action, weight in weights.items()}


def recommend_raise_range(
    *,
    players: int,
    position: str,
    board: Sequence[str],
    strategy: str,
    opponent_range: float,
    fold_to_raise: float,
    pot: float,
    to_call: float,
) -> dict[str, float | str]:
    """Estimate a practical raise range for the current node.

    This is a transparent heuristic, not a full game-tree GTO solution.
    """
    street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)]
    street_factor = {"preflop": 1.0, "flop": 0.78, "turn": 0.62, "river": 0.52}[street]
    multiway_factor = 1 / math.sqrt(players - 1)
    fold_equity_factor = 0.78 + 0.50 * fold_to_raise
    opponent_factor = 0.82 + 0.38 * opponent_range
    strategy_factor = STRATEGY_PRESETS[strategy]["range_multiplier"]

    total = (
        POSITION_DEFAULT_RANGE[position]
        * street_factor
        * multiway_factor
        * fold_equity_factor
        * opponent_factor
        * strategy_factor
    )
    total = min(max(total, 0.025), 0.70)

    value_share = 0.48 + 0.22 * (1 - fold_to_raise) + 0.04 * max(players - 2, 0)
    value_share = min(max(value_share, 0.50), 0.82)
    value_range = total * value_share
    bluff_range = total - value_range

    pot_fraction = 0.66 if street != "preflop" else 0.55
    pot_fraction += 0.08 * max(players - 2, 0)
    pot_fraction -= 0.18 * fold_to_raise
    pot_fraction = min(max(pot_fraction, 0.33), 1.0)
    recommended_size = to_call + pot * pot_fraction

    return {
        "street": street,
        "total_range": total,
        "value_range": value_range,
        "bluff_range": bluff_range,
        "value_to_bluff_ratio": value_range / max(bluff_range, 0.001),
        "recommended_size": recommended_size,
        "pot_fraction": pot_fraction,
    }


def calculate(
    *,
    players: int,
    position: str,
    hand: Sequence[str],
    board: Sequence[str] = (),
    strategy: str = "balanced",
    opponent_range: float | None = None,
    fold_to_raise: float | None = None,
    pot: float = 1.5,
    to_call: float = 0.0,
    raise_size: float = 3.0,
    simulations: int = 10_000,
    seed: int | None = None,
) -> Result:
    position = position.upper()
    if not 2 <= players <= 9:
        raise ValueError("人数必须在 2 到 9 之间")
    if position not in POSITION_DEFAULT_RANGE:
        raise ValueError(f"未知位置 {position!r}，可用位置: {', '.join(POSITION_DEFAULT_RANGE)}")
    if strategy not in STRATEGY_PRESETS:
        raise ValueError(f"未知策略 {strategy!r}，可用策略: {', '.join(STRATEGY_PRESETS)}")
    if len(hand) != 2 or len(board) not in (0, 3, 4, 5):
        raise ValueError("手牌必须为 2 张；公共牌必须为 0、3、4 或 5 张")
    if len(set(hand) | set(board)) != len(hand) + len(board):
        raise ValueError("手牌和公共牌中存在重复牌")
    if min(pot, to_call, raise_size) < 0:
        raise ValueError("底池、跟注额和加注额不能为负数")
    if simulations < 1:
        raise ValueError("模拟次数必须大于 0")

    preset = STRATEGY_PRESETS[strategy]
    resolved_range = opponent_range
    if resolved_range is None:
        resolved_range = POSITION_DEFAULT_RANGE[position] * preset["range_multiplier"]
    resolved_range = min(max(resolved_range, 0.01), 1.0)
    resolved_fold = preset["fold_to_raise"] if fold_to_raise is None else fold_to_raise
    if not 0 <= resolved_fold <= 1:
        raise ValueError("fold-to-raise 必须在 0 到 1 之间")

    equity, wins, ties, completed = simulate_equity(
        hand, board, players, resolved_range, simulations, random.Random(seed)
    )
    action_ev = calculate_action_ev(equity, pot, to_call, raise_size, resolved_fold)
    mixed = softmax_strategy(action_ev, preset["temperature"])
    best_action = max(action_ev, key=action_ev.get)
    raise_recommendation = recommend_raise_range(
        players=players,
        position=position,
        board=board,
        strategy=strategy,
        opponent_range=resolved_range,
        fold_to_raise=resolved_fold,
        pot=pot,
        to_call=to_call,
    )
    return Result(
        players=players,
        position=position,
        hand=list(hand),
        board=list(board),
        strategy=strategy,
        opponent_range=resolved_range,
        fold_to_raise=resolved_fold,
        simulations=completed,
        equity=equity,
        win_rate=wins,
        tie_rate=ties,
        action_ev=action_ev,
        recommended_action=best_action,
        mixed_strategy=mixed,
        raise_recommendation=raise_recommendation,
    )


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def print_result(result: Result) -> None:
    print(f"人数/位置: {result.players} 人 / {result.position}")
    print(f"手牌/公共牌: {' '.join(result.hand)} / {' '.join(result.board) or '-'}")
    print(
        f"对手策略: {result.strategy}, 入池范围 {percent(result.opponent_range)}, "
        f"面对加注弃牌 {percent(result.fold_to_raise)}"
    )
    print(
        f"权益: {percent(result.equity)} "
        f"(胜 {percent(result.win_rate)}, 平分底池 {percent(result.tie_rate)}, "
        f"{result.simulations} 次模拟)"
    )
    print("动作 EV（净筹码）:")
    for action, ev in result.action_ev.items():
        print(f"  {action:>5}: {ev:+.4f}")
    print(f"推荐动作: {result.recommended_action}")
    print("近似混合策略:")
    for action, frequency in result.mixed_strategy.items():
        print(f"  {action:>5}: {percent(frequency)}")
    raise_range = result.raise_recommendation
    print(
        f"推荐加注范围: 总计 {percent(float(raise_range['total_range']))}, "
        f"价值 {percent(float(raise_range['value_range']))}, "
        f"诈唬 {percent(float(raise_range['bluff_range']))}"
    )
    print(
        f"推荐投入额: {float(raise_range['recommended_size']):.2f} "
        f"({percent(float(raise_range['pot_fraction']))} 底池 + 跟注额)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="德州扑克单节点 GTO/EV 近似计算器（蒙特卡洛权益 + 动作 EV）"
    )
    parser.add_argument("--players", type=int, required=True, help="总人数，2-9")
    parser.add_argument("--position", required=True, help="UTG/UTG+1/MP/HJ/CO/BTN/SB/BB")
    parser.add_argument("--hand", required=True, help='手牌，例如 "As Kh"')
    parser.add_argument("--board", default="", help='公共牌，例如 "Qs Jh 2c"')
    parser.add_argument("--strategy", choices=STRATEGY_PRESETS, default="balanced")
    parser.add_argument("--opponent-range", type=float, help="对手范围比例，例如 0.25")
    parser.add_argument("--fold-to-raise", type=float, help="对手面对加注的弃牌率")
    parser.add_argument("--pot", type=float, default=1.5, help="行动前底池")
    parser.add_argument("--to-call", type=float, default=0.0, help="跟注所需筹码")
    parser.add_argument("--raise-size", type=float, default=3.0, help="加注/下注投入总额")
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = calculate(
            players=args.players,
            position=args.position,
            hand=parse_cards(args.hand),
            board=parse_cards(args.board),
            strategy=args.strategy,
            opponent_range=args.opponent_range,
            fold_to_raise=args.fold_to_raise,
            pot=args.pot,
            to_call=args.to_call,
            raise_size=args.raise_size,
            simulations=args.simulations,
            seed=args.seed,
        )
    except ValueError as exc:
        raise SystemExit(f"输入错误: {exc}") from exc
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
