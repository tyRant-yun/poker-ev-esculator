"""Equity simulation against independent per-player weighted ranges."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from .cards import DECK, evaluate
from .ranges import Combo, WeightedRange


@dataclass(frozen=True)
class EquityResult:
    equity: float
    win_rate: float
    tie_rate: float
    simulations: int
    opponent_equity: dict[int, float]


def sample_opponent_hands(
    ranges: Mapping[int, WeightedRange],
    rng: random.Random,
    *,
    dead_cards: Sequence[str] = (),
) -> dict[int, Combo]:
    """Sample one mutually exclusive hand for each player range."""
    known_dead = set(dead_cards)
    for _attempt in range(1_000):
        sampled = {
            seat: weighted_range.sample(rng, dead_cards=known_dead)
            for seat, weighted_range in ranges.items()
        }
        cards = [card for combo in sampled.values() for card in combo]
        if len(cards) == len(set(cards)):
            return sampled
    raise ValueError("各对手范围牌张冲突过多，无法完成互斥抽样")


def simulate_weighted_equity(
    hero: Sequence[str],
    board: Sequence[str],
    opponent_ranges: Mapping[int, WeightedRange],
    *,
    simulations: int = 10_000,
    seed: int | None = None,
) -> EquityResult:
    """Calculate Hero equity against different weighted ranges per opponent."""
    if len(hero) != 2 or len(board) not in (0, 3, 4, 5):
        raise ValueError("Hero 手牌必须为 2 张，公共牌必须为 0、3、4 或 5 张")
    known = list(hero) + list(board)
    if any(card not in DECK for card in known):
        raise ValueError("Hero 手牌或公共牌包含无效牌面")
    if len(known) != len(set(known)):
        raise ValueError("Hero 手牌和公共牌存在重复牌")
    if not opponent_ranges:
        raise ValueError("至少需要一位对手范围")
    if simulations < 1:
        raise ValueError("模拟次数必须大于 0")

    rng = random.Random(seed)
    wins = ties = equity_points = 0.0
    opponent_points = {seat: 0.0 for seat in opponent_ranges}
    completed = 0
    for _ in range(simulations):
        try:
            opponents = sample_opponent_hands(opponent_ranges, rng, dead_cards=known)
        except ValueError:
            continue
        dead = set(known)
        for combo in opponents.values():
            dead.update(combo)
        remaining = [card for card in DECK if card not in dead]
        final_board = list(board) + rng.sample(remaining, 5 - len(board))
        ranks = {"hero": evaluate(list(hero) + final_board)}
        ranks.update(
            {seat: evaluate(list(combo) + final_board) for seat, combo in opponents.items()}
        )
        best = max(ranks.values())
        winners = [seat for seat, rank in ranks.items() if rank == best]
        share = 1 / len(winners)
        if "hero" in winners:
            equity_points += share
            if len(winners) == 1:
                wins += 1
            else:
                ties += 1
        for seat in opponent_points:
            if seat in winners:
                opponent_points[seat] += share
        completed += 1

    if not completed:
        raise ValueError("各对手范围互相冲突，无法完成权益模拟")
    return EquityResult(
        equity=equity_points / completed,
        win_rate=wins / completed,
        tie_rate=ties / completed,
        simulations=completed,
        opponent_equity={
            seat: points / completed for seat, points in opponent_points.items()
        },
    )
