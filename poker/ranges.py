"""Per-player weighted ranges and action-based range updates."""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass
from typing import Iterable

from .cards import DECK, RANK_VALUE, evaluate, preflop_score
from .models import ActionRecord, ActionType, HandState, PlayerStatus, Street


Combo = tuple[str, str]
ALL_COMBOS: tuple[Combo, ...] = tuple(itertools.combinations(DECK, 2))
SORTED_COMBOS: tuple[Combo, ...] = tuple(
    sorted(ALL_COMBOS, key=preflop_score, reverse=True)
)

POSITION_ORDER = {
    2: ("BTN", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("BTN", "SB", "BB", "CO"),
    5: ("BTN", "SB", "BB", "HJ", "CO"),
    6: ("BTN", "SB", "BB", "UTG", "HJ", "CO"),
    7: ("BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"),
    8: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"),
    9: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "MP+1", "HJ", "CO"),
}

RFI_FRACTIONS = {
    "UTG": 0.17,
    "UTG+1": 0.19,
    "MP": 0.23,
    "MP+1": 0.26,
    "HJ": 0.30,
    "CO": 0.38,
    "BTN": 0.50,
    "SB": 0.42,
    "BB": 0.12,
}
CALL_OPEN_FRACTIONS = {
    "UTG": 0.06,
    "UTG+1": 0.07,
    "MP": 0.09,
    "MP+1": 0.10,
    "HJ": 0.12,
    "CO": 0.15,
    "BTN": 0.20,
    "SB": 0.16,
    "BB": 0.34,
}
THREE_BET_FRACTIONS = {
    "UTG": 0.045,
    "UTG+1": 0.05,
    "MP": 0.06,
    "MP+1": 0.065,
    "HJ": 0.075,
    "CO": 0.09,
    "BTN": 0.11,
    "SB": 0.12,
    "BB": 0.10,
}


def canonical_combo(cards: Iterable[str]) -> Combo:
    combo = tuple(cards)
    if len(combo) != 2 or combo[0] == combo[1] or any(card not in DECK for card in combo):
        raise ValueError(f"无效手牌组合: {combo!r}")
    return tuple(sorted(combo, key=DECK.index))  # type: ignore[return-value]


@dataclass
class WeightedRange:
    """A concrete two-card combination range with non-negative weights."""

    combos: dict[Combo, float]
    source: str = "custom"

    def __post_init__(self) -> None:
        normalized: dict[Combo, float] = {}
        for cards, weight in self.combos.items():
            combo = canonical_combo(cards)
            if not math.isfinite(weight) or weight < 0:
                raise ValueError("范围权重必须是有限非负数")
            if weight > 0:
                normalized[combo] = normalized.get(combo, 0.0) + float(weight)
        if not normalized:
            raise ValueError("范围必须至少包含一个正权重组合")
        self.combos = normalized

    @classmethod
    def full(cls, *, dead_cards: Iterable[str] = (), source: str = "all hands") -> WeightedRange:
        dead = set(dead_cards)
        return cls({combo: 1.0 for combo in ALL_COMBOS if not dead.intersection(combo)}, source)

    @classmethod
    def top_fraction(
        cls,
        fraction: float,
        *,
        dead_cards: Iterable[str] = (),
        source: str | None = None,
    ) -> WeightedRange:
        if not 0 < fraction <= 1:
            raise ValueError("范围比例必须在 0 到 1 之间")
        dead = set(dead_cards)
        count = max(1, round(len(SORTED_COMBOS) * fraction))
        return cls(
            {combo: 1.0 for combo in SORTED_COMBOS[:count] if not dead.intersection(combo)},
            source or f"top {fraction:.1%}",
        )

    @property
    def total_weight(self) -> float:
        return sum(self.combos.values())

    @property
    def combo_count(self) -> int:
        return len(self.combos)

    @property
    def coverage(self) -> float:
        return self.combo_count / len(ALL_COMBOS)

    def normalized(self) -> WeightedRange:
        total = self.total_weight
        return WeightedRange(
            {combo: weight / total for combo, weight in self.combos.items()},
            self.source,
        )

    def without_cards(self, dead_cards: Iterable[str]) -> WeightedRange:
        dead = set(dead_cards)
        return WeightedRange(
            {combo: weight for combo, weight in self.combos.items() if not dead.intersection(combo)},
            self.source,
        )

    def reweight(self, likelihoods: dict[Combo, float], *, source: str) -> WeightedRange:
        updated = {
            combo: prior * max(likelihoods.get(combo, 0.0), 0.0)
            for combo, prior in self.combos.items()
        }
        return WeightedRange(updated, source).normalized()

    def sample(self, rng: random.Random, *, dead_cards: Iterable[str] = ()) -> Combo:
        dead = set(dead_cards)
        candidates = [
            (combo, weight)
            for combo, weight in self.combos.items()
            if not dead.intersection(combo)
        ]
        if not candidates:
            raise ValueError("范围与已知牌冲突，无法抽样")
        return rng.choices(
            [combo for combo, _weight in candidates],
            weights=[weight for _combo, weight in candidates],
            k=1,
        )[0]

    def hand_class_weight(self, hand_class: str) -> float:
        return sum(
            weight for combo, weight in self.combos.items() if combo_class(combo) == hand_class
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "combos": {"".join(combo): weight for combo, weight in self.combos.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> WeightedRange:
        raw_combos = data.get("combos")
        if not isinstance(raw_combos, dict):
            raise ValueError("范围快照缺少 combos")
        combos: dict[Combo, float] = {}
        for key, weight in raw_combos.items():
            if not isinstance(key, str) or len(key) != 4:
                raise ValueError(f"无效范围组合键: {key!r}")
            combos[canonical_combo((key[:2], key[2:]))] = float(weight)
        return cls(combos, str(data.get("source", "snapshot")))


@dataclass(frozen=True)
class OpponentProfile:
    name: str = "balanced"
    range_multiplier: float = 1.0
    aggression: float = 1.0
    calling: float = 1.0
    bluffing: float = 1.0


BALANCED_PROFILE = OpponentProfile()
TIGHT_PROFILE = OpponentProfile(
    name="tight", range_multiplier=0.75, aggression=0.85, calling=0.78, bluffing=0.70
)
LOOSE_AGGRESSIVE_PROFILE = OpponentProfile(
    name="loose_aggressive",
    range_multiplier=1.30,
    aggression=1.25,
    calling=1.15,
    bluffing=1.35,
)


def combo_class(combo: Combo) -> str:
    a, b = sorted(combo, key=lambda card: RANK_VALUE[card[0]], reverse=True)
    if a[0] == b[0]:
        return a[0] + b[0]
    return a[0] + b[0] + ("s" if a[1] == b[1] else "o")


def positions_by_seat(state: HandState) -> dict[int, str]:
    """Map occupied seats to standard position labels."""
    seats = sorted(player.seat for player in state.players)
    button_index = seats.index(state.config.button_seat)
    button_first = seats[button_index:] + seats[:button_index]
    labels = POSITION_ORDER[len(seats)]
    return dict(zip(button_first, labels))


def preflop_range(
    position: str,
    action: str,
    *,
    profile: OpponentProfile = BALANCED_PROFILE,
    dead_cards: Iterable[str] = (),
) -> WeightedRange:
    """Return a baseline range for a common preflop action."""
    position = position.upper()
    tables = {
        "rfi": RFI_FRACTIONS,
        "call_open": CALL_OPEN_FRACTIONS,
        "three_bet": THREE_BET_FRACTIONS,
    }
    if action not in tables:
        raise ValueError(f"未知翻牌前范围场景: {action}")
    if position not in tables[action]:
        raise ValueError(f"未知位置: {position}")
    fraction = min(max(tables[action][position] * profile.range_multiplier, 0.01), 1.0)
    return WeightedRange.top_fraction(
        fraction,
        dead_cards=dead_cards,
        source=f"{profile.name}:{position}:{action}",
    )


def initialize_player_ranges(
    state: HandState,
    *,
    hero_seat: int | None = None,
) -> dict[int, WeightedRange]:
    """Create independent full ranges for every unknown, live opponent."""
    dead = set(state.board)
    for player in state.players:
        dead.update(player.hole_cards or [])
    return {
        player.seat: WeightedRange.full(dead_cards=dead, source="initial unknown range")
        for player in state.players
        if player.seat != hero_seat
        and player.hole_cards is None
        and player.status not in (PlayerStatus.FOLDED, PlayerStatus.OUT)
    }


def _preflop_scenario(state_before: HandState, action: ActionRecord) -> str | None:
    voluntary_raises = [
        item
        for item in state_before.actions
        if item.street == Street.PREFLOP and item.type in (ActionType.RAISE, ActionType.ALL_IN)
    ]
    facing_raise = bool(voluntary_raises)
    raises_current_bet = (action.raise_to or 0) > state_before.current_bet
    if action.type == ActionType.RAISE or (
        action.type == ActionType.ALL_IN and raises_current_bet
    ):
        return "three_bet" if facing_raise else "rfi"
    if action.type == ActionType.CALL or (
        action.type == ActionType.ALL_IN and not raises_current_bet
    ):
        if not facing_raise:
            return None
        return "call_open"
    return None


def _draw_bonus(combo: Combo, board: list[str]) -> float:
    cards = list(combo) + board
    suit_counts = {suit: sum(card[1] == suit for card in cards) for suit in "cdhs"}
    flush_draw = any(count == 4 for count in suit_counts.values())
    ranks = {RANK_VALUE[card[0]] for card in cards}
    if 14 in ranks:
        ranks.add(1)
    straight_draw = any(len(ranks.intersection(range(start, start + 5))) >= 4 for start in range(1, 11))
    return min(0.12 * flush_draw + 0.09 * straight_draw, 0.18)


def combo_strength(combo: Combo, board: list[str]) -> float:
    """Return a transparent 0-1 strength feature for action likelihoods."""
    if not board:
        return preflop_score(combo)
    rank = evaluate(list(combo) + board)
    made = rank[0] / 8
    kicker = (rank[1] - 2) / 12 if len(rank) > 1 else 0
    return min(0.78 * made + 0.12 * kicker + _draw_bonus(combo, board), 1.0)


def _action_likelihood(
    strength: float,
    action: ActionRecord,
    profile: OpponentProfile,
) -> float:
    pressure = min(action.amount / max(action.pot_before, 1), 2.0)
    if action.type == ActionType.FOLD:
        return max((1.05 - strength) * (0.80 + 0.20 * pressure), 0.01)
    if action.type == ActionType.CHECK:
        return max(0.28 + 0.72 * (1 - strength), 0.03)
    if action.type == ActionType.CALL:
        middle = 1 - abs(strength - 0.58) * 1.45
        return max((0.18 + 0.82 * middle) * profile.calling, 0.02)
    if action.type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
        value = strength ** (1.20 + 0.30 * pressure)
        bluff = (1 - strength) * 0.16 * profile.bluffing
        return max((value + bluff) * profile.aggression, 0.02)
    return 1.0


def update_range_for_action(
    prior: WeightedRange,
    state_before: HandState,
    action: ActionRecord,
    *,
    profile: OpponentProfile = BALANCED_PROFILE,
) -> WeightedRange:
    """Bayesian-style reweighting after one visible player action."""
    if state_before.street == Street.PREFLOP:
        scenario = _preflop_scenario(state_before, action)
        if scenario:
            position = positions_by_seat(state_before)[action.seat]
            baseline = preflop_range(position, scenario, profile=profile)
            likelihoods = {
                combo: baseline.combos.get(combo, 0.015)
                for combo in prior.combos
            }
            return prior.reweight(
                likelihoods,
                source=f"{prior.source} -> {position} {scenario}",
            )

    effective_action = action
    if action.type == ActionType.ALL_IN and (action.raise_to or 0) <= state_before.current_bet:
        effective_action = ActionRecord(
            sequence=action.sequence,
            street=action.street,
            seat=action.seat,
            type=ActionType.CALL,
            amount=action.amount,
            raise_to=action.raise_to,
            pot_before=action.pot_before,
            stack_before=action.stack_before,
            full_raise=action.full_raise,
        )
    likelihoods = {
        combo: _action_likelihood(
            combo_strength(combo, state_before.board), effective_action, profile
        )
        for combo in prior.combos
        if not set(combo).intersection(state_before.board)
    }
    return prior.reweight(
        likelihoods,
        source=f"{prior.source} -> {state_before.street.value} {action.type.value}",
    )


def filter_ranges_for_state(
    state: HandState,
    ranges: dict[int, WeightedRange],
) -> dict[int, WeightedRange]:
    """Remove folded players and every currently known dead card."""
    dead = set(state.board)
    for player in state.players:
        dead.update(player.hole_cards or [])
    return {
        seat: weighted.without_cards(dead)
        for seat, weighted in ranges.items()
        if state.player(seat).status not in (PlayerStatus.FOLDED, PlayerStatus.OUT)
    }


def update_ranges_after_action(
    state_before: HandState,
    state_after: HandState,
    ranges: dict[int, WeightedRange],
    *,
    profiles: dict[int, OpponentProfile] | None = None,
) -> dict[int, WeightedRange]:
    """Update only the acting player's range and remove folded players."""
    if len(state_after.actions) != len(state_before.actions) + 1:
        raise ValueError("范围更新要求前后状态恰好相差一个动作")
    action = state_after.actions[-1]
    result = dict(ranges)
    if action.seat in result:
        if action.type == ActionType.FOLD:
            result.pop(action.seat)
        else:
            result[action.seat] = update_range_for_action(
                result[action.seat],
                state_before,
                action,
                profile=(profiles or {}).get(action.seat, BALANCED_PROFILE),
            )
    return filter_ranges_for_state(state_after, result)
