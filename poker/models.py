"""Domain models for a complete no-limit Texas Hold'em hand."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"


class PlayerStatus(str, Enum):
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"
    OUT = "out"


class ActionType(str, Enum):
    POST_ANTE = "post_ante"
    POST_SMALL_BLIND = "post_small_blind"
    POST_BIG_BLIND = "post_big_blind"
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"


@dataclass(frozen=True)
class GameConfig:
    small_blind: int
    big_blind: int
    button_seat: int
    ante: int = 0

    def __post_init__(self) -> None:
        if self.small_blind < 0 or self.big_blind <= 0 or self.ante < 0:
            raise ValueError("盲注和前注必须使用非负整数筹码单位，且大盲必须大于 0")
        if self.small_blind > self.big_blind:
            raise ValueError("小盲不能大于大盲")


@dataclass
class PlayerState:
    seat: int
    name: str
    starting_stack: int
    stack: int
    street_commitment: int = 0
    total_commitment: int = 0
    status: PlayerStatus = PlayerStatus.ACTIVE
    hole_cards: list[str] | None = None
    range_id: str | None = None
    profile_id: str | None = None

    def __post_init__(self) -> None:
        if self.starting_stack < 0 or self.stack < 0:
            raise ValueError("玩家筹码不能为负数")


@dataclass(frozen=True)
class ActionRecord:
    sequence: int
    street: Street
    seat: int
    type: ActionType
    amount: int
    raise_to: int | None
    pot_before: int
    stack_before: int
    full_raise: bool = False


@dataclass(frozen=True)
class Pot:
    amount: int
    eligible_seats: tuple[int, ...]


@dataclass(frozen=True)
class LegalActions:
    seat: int
    to_call: int
    actions: tuple[ActionType, ...]
    min_raise_to: int | None = None
    max_raise_to: int | None = None
    full_raise_min_to: int | None = None


@dataclass
class HandState:
    config: GameConfig
    players: list[PlayerState]
    street: Street = Street.PREFLOP
    board: list[str] = field(default_factory=list)
    acting_seat: int | None = None
    current_bet: int = 0
    last_full_raise: int = 0
    pending_to_act: set[int] = field(default_factory=set)
    acted_since_full_raise: set[int] = field(default_factory=set)
    actions: list[ActionRecord] = field(default_factory=list)
    pots: list[Pot] = field(default_factory=list)
    awaiting_board: bool = False
    showdown_ready: bool = False
    complete: bool = False
    payouts: dict[int, int] = field(default_factory=dict)

    def clone(self) -> HandState:
        return copy.deepcopy(self)

    def player(self, seat: int) -> PlayerState:
        for player in self.players:
            if player.seat == seat:
                return player
        raise ValueError(f"未知座位: {seat}")

    @property
    def pot_total(self) -> int:
        return sum(player.total_commitment for player in self.players)

    @property
    def live_seats(self) -> list[int]:
        return [
            player.seat
            for player in self.players
            if player.status not in (PlayerStatus.FOLDED, PlayerStatus.OUT)
        ]


def _enum_values(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _enum_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_enum_values(item) for item in value]
    return value


def hand_to_dict(state: HandState) -> dict[str, Any]:
    """Return a JSON-compatible complete hand snapshot."""
    return _enum_values(asdict(state))


def hand_from_dict(data: dict[str, Any]) -> HandState:
    """Restore a hand snapshot produced by :func:`hand_to_dict`."""
    config = GameConfig(**data["config"])
    players = [
        PlayerState(
            **{
                **player,
                "status": PlayerStatus(player.get("status", PlayerStatus.ACTIVE.value)),
            }
        )
        for player in data["players"]
    ]
    actions = [
        ActionRecord(
            **{
                **action,
                "street": Street(action["street"]),
                "type": ActionType(action["type"]),
            }
        )
        for action in data.get("actions", [])
    ]
    pots = [
        Pot(amount=pot["amount"], eligible_seats=tuple(pot["eligible_seats"]))
        for pot in data.get("pots", [])
    ]
    state = HandState(
        config=config,
        players=players,
        street=Street(data.get("street", Street.PREFLOP.value)),
        board=list(data.get("board", [])),
        acting_seat=data.get("acting_seat"),
        current_bet=data.get("current_bet", 0),
        last_full_raise=data.get("last_full_raise", config.big_blind),
        pending_to_act=set(data.get("pending_to_act", [])),
        acted_since_full_raise=set(data.get("acted_since_full_raise", [])),
        actions=actions,
        pots=pots,
        awaiting_board=data.get("awaiting_board", False),
        showdown_ready=data.get("showdown_ready", False),
        complete=data.get("complete", False),
        payouts={int(seat): amount for seat, amount in data.get("payouts", {}).items()},
    )
    validate_state(state)
    return state


def validate_state(state: HandState) -> None:
    """Raise when a hand snapshot violates core accounting or turn invariants."""
    seats = [player.seat for player in state.players]
    if len(seats) != len(set(seats)):
        raise ValueError("牌局状态包含重复座位")
    if state.config.button_seat not in seats:
        raise ValueError("按钮座位不在牌局中")
    if any(
        player.stack < 0
        or player.street_commitment < 0
        or player.total_commitment < player.street_commitment
        for player in state.players
    ):
        raise ValueError("牌局状态包含无效筹码投入")
    if any(
        player.status == PlayerStatus.ALL_IN and player.stack != 0 and not state.complete
        for player in state.players
    ):
        raise ValueError("全下玩家的剩余筹码必须为 0")
    if any(
        state.player(seat).status != PlayerStatus.ACTIVE for seat in state.pending_to_act
    ):
        raise ValueError("待行动列表只能包含仍可行动的玩家")
    if state.acting_seat is not None:
        if state.acting_seat not in state.pending_to_act:
            raise ValueError("当前行动玩家必须位于待行动列表")
        if state.player(state.acting_seat).status != PlayerStatus.ACTIVE:
            raise ValueError("当前行动玩家必须处于 active 状态")
    known_cards = list(state.board)
    for player in state.players:
        known_cards.extend(player.hole_cards or [])
    if len(known_cards) != len(set(known_cards)):
        raise ValueError("牌局状态包含重复已知牌")
    starting_total = sum(player.starting_stack for player in state.players)
    accounted_total = (
        sum(player.stack for player in state.players)
        + state.pot_total
        - sum(state.payouts.values())
    )
    if starting_total != accounted_total:
        raise ValueError("牌局状态不满足筹码守恒")
