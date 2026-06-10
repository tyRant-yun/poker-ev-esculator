"""Cards, hand evaluation, and preflop strength helpers."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence


RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)
RANK_VALUE = {rank: value for value, rank in enumerate(RANKS, start=2)}


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
    """Return a rough 0-1 preflop score used for baseline range ordering."""
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
