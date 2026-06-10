"""Legal action generation and deterministic hand state transitions."""

from __future__ import annotations

from .models import (
    ActionRecord,
    ActionType,
    GameConfig,
    HandState,
    LegalActions,
    PlayerState,
    PlayerStatus,
    Street,
    validate_state,
)
from .settlement import award_uncontested, build_pots


STREET_BOARD_COUNTS = {
    Street.PREFLOP: 0,
    Street.FLOP: 3,
    Street.TURN: 4,
    Street.RIVER: 5,
}
NEXT_STREET = {
    Street.PREFLOP: Street.FLOP,
    Street.FLOP: Street.TURN,
    Street.TURN: Street.RIVER,
}
RANKS = set("23456789TJQKA")
SUITS = set("cdhs")


def _normalize_cards(cards: list[str], *, expected: int | None = None) -> list[str]:
    if expected is not None and len(cards) != expected:
        raise ValueError(f"必须提供 {expected} 张牌")
    normalized: list[str] = []
    for card in cards:
        if len(card) != 2:
            raise ValueError(f"无效牌面: {card!r}")
        normalized_card = card[0].upper() + card[1].lower()
        if normalized_card[0] not in RANKS or normalized_card[1] not in SUITS:
            raise ValueError(f"无效牌面: {card!r}")
        normalized.append(normalized_card)
    if len(normalized) != len(set(normalized)):
        raise ValueError("输入中存在重复牌")
    return normalized


def _ordered_seats(state: HandState, after_seat: int) -> list[int]:
    seats = sorted(player.seat for player in state.players)
    if after_seat not in seats:
        raise ValueError(f"未知座位: {after_seat}")
    index = seats.index(after_seat)
    return seats[index + 1 :] + seats[: index + 1]


def _next_matching(state: HandState, after_seat: int, candidates: set[int]) -> int | None:
    return next((seat for seat in _ordered_seats(state, after_seat) if seat in candidates), None)


def _commit(player: PlayerState, amount: int) -> int:
    paid = min(amount, player.stack)
    player.stack -= paid
    player.street_commitment += paid
    player.total_commitment += paid
    if player.stack == 0:
        player.status = PlayerStatus.ALL_IN
    return paid


def _record_forced_bet(state: HandState, seat: int, action_type: ActionType, amount: int) -> None:
    player = state.player(seat)
    stack_before = player.stack
    pot_before = state.pot_total
    if action_type == ActionType.POST_ANTE:
        paid = min(amount, player.stack)
        player.stack -= paid
        player.total_commitment += paid
        if player.stack == 0:
            player.status = PlayerStatus.ALL_IN
    else:
        paid = _commit(player, amount)
    state.actions.append(
        ActionRecord(
            sequence=len(state.actions) + 1,
            street=Street.PREFLOP,
            seat=seat,
            type=action_type,
            amount=paid,
            raise_to=player.street_commitment if action_type != ActionType.POST_ANTE else None,
            pot_before=pot_before,
            stack_before=stack_before,
        )
    )


def create_hand(
    config: GameConfig,
    stacks: dict[int, int],
    *,
    names: dict[int, str] | None = None,
    hole_cards: dict[int, list[str]] | None = None,
) -> HandState:
    """Create a hand, post forced bets, and select the first preflop actor."""
    if not 2 <= len(stacks) <= 9:
        raise ValueError("牌局人数必须在 2 到 9 之间")
    if config.button_seat not in stacks:
        raise ValueError("按钮座位必须属于当前牌局")
    if len(set(stacks)) != len(stacks):
        raise ValueError("座位不能重复")
    if any(stack <= 0 or not isinstance(stack, int) for stack in stacks.values()):
        raise ValueError("起始筹码必须是正整数筹码单位")

    names = names or {}
    hole_cards = {
        seat: _normalize_cards(cards, expected=2)
        for seat, cards in (hole_cards or {}).items()
    }
    if any(seat not in stacks for seat in hole_cards):
        raise ValueError("手牌所属座位不在当前牌局")
    known_hole_cards = [card for cards in hole_cards.values() for card in cards]
    if len(known_hole_cards) != len(set(known_hole_cards)):
        raise ValueError("不同玩家的已知手牌存在重复牌")
    players = [
        PlayerState(
            seat=seat,
            name=names.get(seat, f"Seat {seat}"),
            starting_stack=stack,
            stack=stack,
            hole_cards=hole_cards.get(seat),
        )
        for seat, stack in sorted(stacks.items())
    ]
    state = HandState(config=config, players=players, last_full_raise=config.big_blind)
    seats_after_button = _ordered_seats(state, config.button_seat)
    if len(players) == 2:
        small_blind_seat = config.button_seat
        big_blind_seat = seats_after_button[0]
    else:
        small_blind_seat, big_blind_seat = seats_after_button[:2]

    if config.ante:
        for player in state.players:
            _record_forced_bet(state, player.seat, ActionType.POST_ANTE, config.ante)
    _record_forced_bet(state, small_blind_seat, ActionType.POST_SMALL_BLIND, config.small_blind)
    _record_forced_bet(state, big_blind_seat, ActionType.POST_BIG_BLIND, config.big_blind)

    state.current_bet = max(
        config.big_blind,
        max(player.street_commitment for player in state.players),
    )
    state.pending_to_act = {
        player.seat for player in state.players if player.status == PlayerStatus.ACTIVE
    }
    state.acting_seat = _next_matching(state, big_blind_seat, state.pending_to_act)
    if state.acting_seat is None:
        _finish_betting_round(state)
    validate_state(state)
    return state


def legal_actions(state: HandState) -> LegalActions:
    """Return all legal actions for the current actor."""
    if state.complete:
        raise ValueError("牌局已经结束")
    if state.awaiting_board:
        raise ValueError("当前等待发出下一街公共牌")
    if state.showdown_ready:
        raise ValueError("当前等待摊牌结算")
    if state.acting_seat is None:
        raise ValueError("当前没有行动玩家")

    player = state.player(state.acting_seat)
    to_call = max(state.current_bet - player.street_commitment, 0)
    actions: list[ActionType] = [ActionType.FOLD, ActionType.CALL] if to_call else [ActionType.CHECK]
    max_raise_to = player.street_commitment + player.stack
    raising_reopened = player.seat not in state.acted_since_full_raise
    can_be_called_or_raised = any(
        other.seat != player.seat and other.status == PlayerStatus.ACTIVE
        for other in state.players
    )
    min_raise_to = full_raise_min_to = None

    if player.stack > to_call and raising_reopened and can_be_called_or_raised:
        full_raise_min_to = (
            state.config.big_blind
            if state.current_bet == 0
            else state.current_bet + state.last_full_raise
        )
        min_raise_to = min(full_raise_min_to, max_raise_to)
        if max_raise_to > state.current_bet:
            actions.append(ActionType.BET if state.current_bet == 0 else ActionType.RAISE)
    if player.stack > 0 and (
        player.stack <= to_call or (raising_reopened and can_be_called_or_raised)
    ):
        actions.append(ActionType.ALL_IN)

    return LegalActions(
        seat=player.seat,
        to_call=to_call,
        actions=tuple(actions),
        min_raise_to=min_raise_to,
        max_raise_to=max_raise_to if min_raise_to is not None else None,
        full_raise_min_to=full_raise_min_to,
    )


def apply_action(
    state: HandState,
    action_type: ActionType | str,
    *,
    raise_to: int | None = None,
) -> HandState:
    """Apply one legal player action and return a new state."""
    result = state.clone()
    legal = legal_actions(result)
    action_type = ActionType(action_type)
    if action_type not in legal.actions:
        raise ValueError(f"当前不能执行动作: {action_type.value}")

    player = result.player(legal.seat)
    old_current_bet = result.current_bet
    pot_before = result.pot_total
    stack_before = player.stack
    paid = 0
    target = player.street_commitment
    full_raise = False

    if action_type == ActionType.FOLD:
        player.status = PlayerStatus.FOLDED
    elif action_type == ActionType.CHECK:
        pass
    elif action_type == ActionType.CALL:
        paid = _commit(player, legal.to_call)
        target = player.street_commitment
    else:
        if action_type == ActionType.ALL_IN:
            target = player.street_commitment + player.stack
        else:
            if raise_to is None:
                raise ValueError("下注或加注必须提供 raise_to")
            target = raise_to
        if target > old_current_bet:
            if legal.min_raise_to is None or legal.max_raise_to is None:
                raise ValueError("当前不能下注或加注")
            if not legal.min_raise_to <= target <= legal.max_raise_to:
                raise ValueError(
                    f"下注总额必须在 {legal.min_raise_to} 到 {legal.max_raise_to} 之间"
                )
        paid = _commit(player, target - player.street_commitment)
        target = player.street_commitment
        if target > old_current_bet:
            raise_amount = target - old_current_bet
            full_raise = raise_amount >= result.last_full_raise
            result.current_bet = target
            if full_raise:
                result.last_full_raise = raise_amount

    result.actions.append(
        ActionRecord(
            sequence=len(result.actions) + 1,
            street=result.street,
            seat=player.seat,
            type=action_type,
            amount=paid,
            raise_to=target if action_type not in (ActionType.FOLD, ActionType.CHECK) else None,
            pot_before=pot_before,
            stack_before=stack_before,
            full_raise=full_raise,
        )
    )
    result.pending_to_act.discard(player.seat)

    if target > old_current_bet:
        if full_raise or old_current_bet == 0:
            result.acted_since_full_raise = {player.seat}
        else:
            result.acted_since_full_raise.add(player.seat)
        result.pending_to_act.update(
            other.seat
            for other in result.players
            if other.seat != player.seat
            and other.status == PlayerStatus.ACTIVE
            and other.street_commitment < result.current_bet
        )
    else:
        result.acted_since_full_raise.add(player.seat)

    result.pending_to_act = {
        seat
        for seat in result.pending_to_act
        if result.player(seat).status == PlayerStatus.ACTIVE
    }
    if len(result.live_seats) == 1:
        award_uncontested(result)
    elif not result.pending_to_act:
        _finish_betting_round(result)
    else:
        result.acting_seat = _next_matching(result, player.seat, result.pending_to_act)
    result.pots = build_pots(result)
    validate_state(result)
    return result


def _finish_betting_round(state: HandState) -> None:
    state.acting_seat = None
    state.pending_to_act.clear()
    state.acted_since_full_raise.clear()
    if state.street == Street.RIVER:
        state.showdown_ready = True
    else:
        state.awaiting_board = True


def deal_board(state: HandState, cards: list[str]) -> HandState:
    """Deal the next street and start its betting round when action is possible."""
    if state.complete:
        raise ValueError("牌局已经结束")
    if not state.awaiting_board:
        raise ValueError("当前不能发出公共牌")
    next_street = NEXT_STREET[state.street]
    expected_new_cards = STREET_BOARD_COUNTS[next_street] - len(state.board)
    if len(cards) != expected_new_cards:
        raise ValueError(f"{next_street.value} 必须发出 {expected_new_cards} 张公共牌")
    normalized = _normalize_cards(cards)
    known_cards = set(state.board)
    for player in state.players:
        known_cards.update(player.hole_cards or [])
    if known_cards.intersection(normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("公共牌与已知牌重复")

    result = state.clone()
    result.street = next_street
    result.board.extend(normalized)
    result.awaiting_board = False
    result.current_bet = 0
    result.last_full_raise = result.config.big_blind
    for player in result.players:
        player.street_commitment = 0

    active = {
        player.seat for player in result.players if player.status == PlayerStatus.ACTIVE
    }
    if len(active) <= 1:
        if result.street == Street.RIVER:
            result.showdown_ready = True
        else:
            result.awaiting_board = True
        validate_state(result)
        return result
    result.pending_to_act = active
    result.acting_seat = _next_matching(result, result.config.button_seat, active)
    validate_state(result)
    return result
