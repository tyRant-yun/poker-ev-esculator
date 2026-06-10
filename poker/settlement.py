"""Pot construction and showdown settlement."""

from __future__ import annotations

from collections.abc import Mapping

from .models import HandState, PlayerStatus, Pot, validate_state


def build_pots(state: HandState) -> list[Pot]:
    """Build main and side pots from total player commitments."""
    levels = sorted(
        {player.total_commitment for player in state.players if player.total_commitment > 0}
    )
    pots: list[Pot] = []
    previous = 0
    for level in levels:
        contributors = [
            player for player in state.players if player.total_commitment >= level
        ]
        amount = (level - previous) * len(contributors)
        eligible = tuple(
            player.seat
            for player in contributors
            if player.status not in (PlayerStatus.FOLDED, PlayerStatus.OUT)
        )
        if amount:
            pots.append(Pot(amount=amount, eligible_seats=eligible))
        previous = level
    return pots


def _odd_chip_order(state: HandState, winners: set[int]) -> list[int]:
    seats = sorted(player.seat for player in state.players)
    button_index = seats.index(state.config.button_seat)
    clockwise = seats[button_index + 1 :] + seats[: button_index + 1]
    return [seat for seat in clockwise if seat in winners]


def award_uncontested(state: HandState) -> None:
    """Award all committed chips to the only player that has not folded."""
    live = state.live_seats
    if len(live) != 1:
        raise ValueError("无争议底池必须只有一位未弃牌玩家")
    winner = state.player(live[0])
    amount = state.pot_total
    winner.stack += amount
    state.payouts = {winner.seat: amount}
    state.pots = build_pots(state)
    state.acting_seat = None
    state.pending_to_act.clear()
    state.awaiting_board = False
    state.showdown_ready = False
    state.complete = True
    validate_state(state)


def settle_showdown(
    state: HandState,
    ranks: Mapping[int, tuple[int, ...]] | None = None,
) -> HandState:
    """Settle every pot using comparable hand-rank tuples."""
    if not state.showdown_ready:
        raise ValueError("当前牌局尚未到摊牌结算阶段")
    result = state.clone()
    if ranks is None:
        from .cards import evaluate

        ranks = {
            player.seat: evaluate((player.hole_cards or []) + result.board)
            for player in result.players
            if player.status not in (PlayerStatus.FOLDED, PlayerStatus.OUT)
        }

    result.pots = build_pots(result)
    payouts: dict[int, int] = {}
    for pot in result.pots:
        missing = [seat for seat in pot.eligible_seats if seat not in ranks]
        if missing:
            raise ValueError(f"缺少摊牌牌力: {missing}")
        best = max(ranks[seat] for seat in pot.eligible_seats)
        winners = {seat for seat in pot.eligible_seats if ranks[seat] == best}
        share, remainder = divmod(pot.amount, len(winners))
        for seat in winners:
            payouts[seat] = payouts.get(seat, 0) + share
        for seat in _odd_chip_order(result, winners)[:remainder]:
            payouts[seat] = payouts.get(seat, 0) + 1

    for seat, amount in payouts.items():
        result.player(seat).stack += amount
    result.payouts = payouts
    result.acting_seat = None
    result.pending_to_act.clear()
    result.awaiting_board = False
    result.showdown_ready = False
    result.complete = True
    validate_state(result)
    return result
