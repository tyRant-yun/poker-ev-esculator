"""Candidate action generation and finite-depth strategy roll-outs."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any
from typing import Mapping

from .cards import DECK, evaluate
from .engine import legal_actions
from .models import ActionType, HandState, PlayerStatus, Street
from .ranges import (
    BALANCED_PROFILE,
    Combo,
    OpponentProfile,
    WeightedRange,
    combo_strength,
)
from .equity import sample_opponent_hands


@dataclass(frozen=True)
class CandidateAction:
    action_type: ActionType
    raise_to: int | None
    amount: int
    label: str
    pot_fraction: float | None = None


@dataclass(frozen=True)
class ResponseSummary:
    fold_probability: float
    call_probability: float
    raise_probability: float


@dataclass(frozen=True)
class ActionAnalysis:
    candidate: CandidateAction
    ev: float
    equity_when_called: float | None
    all_fold_probability: float
    any_raise_probability: float
    response_by_seat: dict[int, ResponseSummary]
    heuristic_frequency: float
    simulations: int
    confidence: float


@dataclass(frozen=True)
class StrategyAnalysis:
    hero_seat: int
    street: Street
    pot: int
    to_call: int
    effective_stack: int
    spr: float
    baseline_actions: tuple[ActionAnalysis, ...]
    exploit_actions: tuple[ActionAnalysis, ...]
    baseline_action: CandidateAction
    exploit_action: CandidateAction
    key_reasons: tuple[str, ...]
    model: str = "finite-depth heuristic rollout"


def _json_values(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_values(item) for item in value]
    return value


def strategy_to_dict(analysis: StrategyAnalysis) -> dict[str, Any]:
    """Return a JSON-compatible strategy analysis payload."""
    return _json_values(asdict(analysis))


DEFAULT_POSTFLOP_FRACTIONS = (0.33, 0.50, 0.75, 1.00, 1.50)
DEFAULT_PREFLOP_OPEN_BB = (2.0, 2.5, 3.0)
DEFAULT_PREFLOP_RAISE_MULTIPLIERS = (2.5, 3.0, 4.0)


def _bounded_targets(targets: list[tuple[int, str, float | None]], minimum: int, maximum: int):
    result: list[tuple[int, str, float | None]] = []
    seen: set[int] = set()
    for target, label, fraction in targets:
        bounded = min(max(target, minimum), maximum)
        if bounded not in seen:
            result.append((bounded, label, fraction))
            seen.add(bounded)
    return result


def generate_candidate_actions(
    state: HandState,
    *,
    custom_raise_to: tuple[int, ...] = (),
) -> tuple[CandidateAction, ...]:
    """Generate legal passive actions and practical bet/raise sizes."""
    legal = legal_actions(state)
    player = state.player(legal.seat)
    candidates: list[CandidateAction] = []
    if ActionType.FOLD in legal.actions:
        candidates.append(CandidateAction(ActionType.FOLD, None, 0, "fold"))
    if ActionType.CHECK in legal.actions:
        candidates.append(CandidateAction(ActionType.CHECK, None, 0, "check"))
    if ActionType.CALL in legal.actions:
        amount = min(legal.to_call, player.stack)
        candidates.append(CandidateAction(ActionType.CALL, None, amount, "call"))

    aggressive_type = ActionType.BET if ActionType.BET in legal.actions else ActionType.RAISE
    if aggressive_type in legal.actions:
        assert legal.min_raise_to is not None and legal.max_raise_to is not None
        targets: list[tuple[int, str, float | None]] = []
        if custom_raise_to:
            targets.extend((target, f"to {target}", None) for target in custom_raise_to)
        elif state.street == Street.PREFLOP:
            if state.current_bet <= state.config.big_blind:
                targets.extend(
                    (
                        round(state.config.big_blind * multiple),
                        f"{multiple:g} BB",
                        None,
                    )
                    for multiple in DEFAULT_PREFLOP_OPEN_BB
                )
            else:
                targets.extend(
                    (
                        round(state.current_bet * multiple),
                        f"{multiple:g}x raise",
                        None,
                    )
                    for multiple in DEFAULT_PREFLOP_RAISE_MULTIPLIERS
                )
        else:
            pot_after_call = state.pot_total + legal.to_call
            targets.extend(
                (
                    state.current_bet + round(pot_after_call * fraction),
                    f"{fraction:.0%} pot",
                    fraction,
                )
                for fraction in DEFAULT_POSTFLOP_FRACTIONS
            )
        for target, label, fraction in _bounded_targets(
            targets, legal.min_raise_to, legal.max_raise_to
        ):
            candidates.append(
                CandidateAction(
                    aggressive_type,
                    target,
                    target - player.street_commitment,
                    label,
                    fraction,
                )
            )

    if ActionType.ALL_IN in legal.actions:
        target = player.street_commitment + player.stack
        all_in_is_call = player.stack <= legal.to_call
        effective_stack = min(
            player.stack,
            max(
                (
                    other.stack
                    for other in state.players
                    if other.seat != player.seat
                    and other.status not in (PlayerStatus.FOLDED, PlayerStatus.OUT)
                ),
                default=player.stack,
            ),
        )
        short_preflop = effective_stack <= state.config.big_blind * 25
        low_spr_postflop = (
            state.street != Street.PREFLOP
            and (
                effective_stack <= state.pot_total * 4
                or legal.to_call >= effective_stack * 0.35
            )
        )
        include_all_in = short_preflop if state.street == Street.PREFLOP else low_spr_postflop
        if (
            include_all_in
            and not all_in_is_call
            and not any(candidate.raise_to == target for candidate in candidates)
        ):
            candidates.append(
                CandidateAction(ActionType.ALL_IN, target, player.stack, "all-in")
            )
    return tuple(candidates)


def _response_probabilities(
    combo: Combo,
    state: HandState,
    candidate: CandidateAction,
    seat: int,
    profile: OpponentProfile,
) -> ResponseSummary:
    opponent = state.player(seat)
    target = candidate.raise_to or state.current_bet
    to_call = max(target - opponent.street_commitment, 0)
    pressure = min(to_call / max(state.pot_total + candidate.amount, 1), 2.0)
    strength = combo_strength(combo, state.board)
    fold = max((1 - strength) * (0.48 + 0.45 * pressure) / profile.calling, 0.01)
    call = max((0.25 + 0.75 * (1 - abs(strength - 0.60))) * profile.calling, 0.01)
    can_raise = (
        candidate.action_type != ActionType.ALL_IN
        and opponent.stack > to_call
        and opponent.status == PlayerStatus.ACTIVE
    )
    raise_weight = (
        max(
            strength**2 * profile.aggression
            + (1 - strength) * 0.08 * profile.bluffing,
            0.01,
        )
        if can_raise
        else 0.0
    )
    total = fold + call + raise_weight
    return ResponseSummary(fold / total, call / total, raise_weight / total)


def _known_and_unknown_ranges(
    state: HandState,
    hero_seat: int,
    opponent_ranges: Mapping[int, WeightedRange],
) -> dict[int, WeightedRange]:
    result: dict[int, WeightedRange] = {}
    for player in state.players:
        if player.seat == hero_seat or player.status in (PlayerStatus.FOLDED, PlayerStatus.OUT):
            continue
        if player.hole_cards:
            result[player.seat] = WeightedRange({tuple(player.hole_cards): 1.0}, "known hand")
        elif player.seat in opponent_ranges:
            result[player.seat] = opponent_ranges[player.seat]
        else:
            raise ValueError(f"缺少玩家 {player.seat} 的范围")
    return result


def _showdown_share(hero: list[str], opponents: dict[int, Combo], board: list[str]) -> float:
    ranks = {"hero": evaluate(hero + board)}
    ranks.update({seat: evaluate(list(combo) + board) for seat, combo in opponents.items()})
    best = max(ranks.values())
    winners = [seat for seat, rank in ranks.items() if rank == best]
    return 1 / len(winners) if "hero" in winners else 0.0


def _hero_terminal_payout(
    state: HandState,
    hero_seat: int,
    hero: list[str],
    opponents: dict[int, Combo],
    board: list[str],
    extra_commitments: Mapping[int, int],
) -> float:
    """Return Hero's gross payout across main and side pots."""
    commitments = {
        player.seat: player.total_commitment + extra_commitments.get(player.seat, 0)
        for player in state.players
    }
    eligible = {hero_seat, *opponents}
    ranks = {hero_seat: evaluate(hero + board)}
    ranks.update({seat: evaluate(list(combo) + board) for seat, combo in opponents.items()})
    payout = 0.0
    previous = 0
    for level in sorted({amount for amount in commitments.values() if amount > 0}):
        contributors = [seat for seat, amount in commitments.items() if amount >= level]
        amount = (level - previous) * len(contributors)
        pot_eligible = [seat for seat in contributors if seat in eligible]
        if hero_seat in pot_eligible:
            best = max(ranks[seat] for seat in pot_eligible)
            winners = [seat for seat in pot_eligible if ranks[seat] == best]
            if hero_seat in winners:
                payout += amount / len(winners)
        previous = level
    return payout


def _runout(
    hero: list[str],
    board: list[str],
    opponents: Mapping[int, Combo],
    rng: random.Random,
) -> list[str]:
    dead = set(hero) | set(board)
    for combo in opponents.values():
        dead.update(combo)
    remaining = [card for card in DECK if card not in dead]
    return board + rng.sample(remaining, 5 - len(board))


def _analyze_candidate(
    state: HandState,
    hero_seat: int,
    hero: list[str],
    ranges: Mapping[int, WeightedRange],
    candidate: CandidateAction,
    profiles: Mapping[int, OpponentProfile],
    *,
    simulations: int,
    seed: int,
) -> ActionAnalysis:
    if candidate.action_type == ActionType.FOLD:
        return ActionAnalysis(
            candidate, 0.0, None, 0.0, 0.0, {}, 0.0, simulations, 1.0
        )

    rng = random.Random(seed)
    pot = state.pot_total
    payoffs: list[float] = []
    all_folds = raises = called_equity = called_count = 0.0
    response_counts = {
        seat: {"fold": 0.0, "call": 0.0, "raise": 0.0} for seat in ranges
    }
    aggressive = candidate.action_type in (
        ActionType.BET,
        ActionType.RAISE,
        ActionType.ALL_IN,
    ) and (candidate.raise_to or 0) > state.current_bet

    for _ in range(simulations):
        sampled = sample_opponent_hands(ranges, rng, dead_cards=hero + state.board)
        if not aggressive:
            final_board = _runout(hero, state.board, sampled, rng)
            share = _showdown_share(hero, sampled, final_board)
            payout = _hero_terminal_payout(
                state,
                hero_seat,
                hero,
                sampled,
                final_board,
                {hero_seat: candidate.amount},
            )
            payoffs.append(payout - candidate.amount)
            continue

        callers: dict[int, Combo] = {}
        extra_commitments = {hero_seat: candidate.amount}
        any_raise = False
        for seat, combo in sampled.items():
            opponent = state.player(seat)
            if opponent.status == PlayerStatus.ALL_IN:
                callers[seat] = combo
                response_counts[seat]["call"] += 1
                continue
            response = _response_probabilities(
                combo,
                state,
                candidate,
                seat,
                profiles.get(seat, BALANCED_PROFILE),
            )
            choice = rng.choices(
                ("fold", "call", "raise"),
                weights=(
                    response.fold_probability,
                    response.call_probability,
                    response.raise_probability,
                ),
                k=1,
            )[0]
            response_counts[seat][choice] += 1
            if choice == "raise":
                any_raise = True
            elif choice == "call":
                callers[seat] = combo
                target = candidate.raise_to or state.current_bet
                extra_commitments[seat] = min(
                    max(target - opponent.street_commitment, 0), opponent.stack
                )
        if any_raise:
            raises += 1
            payoffs.append(-candidate.amount)
        elif not callers:
            all_folds += 1
            payoffs.append(float(pot))
        else:
            final_board = _runout(hero, state.board, callers, rng)
            share = _showdown_share(hero, callers, final_board)
            called_equity += share
            called_count += 1
            payout = _hero_terminal_payout(
                state,
                hero_seat,
                hero,
                callers,
                final_board,
                extra_commitments,
            )
            payoffs.append(payout - candidate.amount)

    mean = sum(payoffs) / len(payoffs)
    variance = sum((payoff - mean) ** 2 for payoff in payoffs) / max(len(payoffs) - 1, 1)
    stderr = math.sqrt(variance / len(payoffs))
    confidence = max(0.0, min(1.0, 1 - stderr / max(abs(mean) + pot * 0.10, 1)))
    responses = {
        seat: ResponseSummary(
            counts["fold"] / simulations,
            counts["call"] / simulations,
            counts["raise"] / simulations,
        )
        for seat, counts in response_counts.items()
    }
    return ActionAnalysis(
        candidate=candidate,
        ev=mean,
        equity_when_called=called_equity / called_count if called_count else None,
        all_fold_probability=all_folds / simulations,
        any_raise_probability=raises / simulations,
        response_by_seat=responses,
        heuristic_frequency=0.0,
        simulations=simulations,
        confidence=confidence,
    )


def _with_frequencies(actions: list[ActionAnalysis], pot: int) -> tuple[ActionAnalysis, ...]:
    peak = max(action.ev for action in actions)
    temperature = max(pot * 0.20, 1.0)
    weights = [math.exp((action.ev - peak) / temperature) for action in actions]
    total = sum(weights)
    return tuple(
        ActionAnalysis(
            candidate=action.candidate,
            ev=action.ev,
            equity_when_called=action.equity_when_called,
            all_fold_probability=action.all_fold_probability,
            any_raise_probability=action.any_raise_probability,
            response_by_seat=action.response_by_seat,
            heuristic_frequency=weight / total,
            simulations=action.simulations,
            confidence=action.confidence,
        )
        for action, weight in zip(actions, weights)
    )


def _analyze_with_profiles(
    state: HandState,
    hero_seat: int,
    hero: list[str],
    ranges: Mapping[int, WeightedRange],
    candidates: tuple[CandidateAction, ...],
    profiles: Mapping[int, OpponentProfile],
    *,
    simulations: int,
    seed: int,
) -> tuple[ActionAnalysis, ...]:
    actions = [
        _analyze_candidate(
            state,
            hero_seat,
            hero,
            ranges,
            candidate,
            profiles,
            simulations=simulations,
            seed=seed + index * 1009,
        )
        for index, candidate in enumerate(candidates)
    ]
    return _with_frequencies(actions, state.pot_total)


def analyze_strategy(
    state: HandState,
    hero_seat: int,
    opponent_ranges: Mapping[int, WeightedRange],
    *,
    profiles: Mapping[int, OpponentProfile] | None = None,
    custom_raise_to: tuple[int, ...] = (),
    simulations: int = 2_000,
    seed: int = 1,
) -> StrategyAnalysis:
    """Compare legal Hero actions with a finite-depth response roll-out."""
    if state.acting_seat != hero_seat:
        raise ValueError("只能分析当前行动玩家")
    hero_player = state.player(hero_seat)
    if not hero_player.hole_cards:
        raise ValueError("策略分析需要 Hero 已知手牌")
    if simulations < 1:
        raise ValueError("模拟次数必须大于 0")

    ranges = _known_and_unknown_ranges(state, hero_seat, opponent_ranges)
    candidates = generate_candidate_actions(state, custom_raise_to=custom_raise_to)
    balanced_profiles = {seat: BALANCED_PROFILE for seat in ranges}
    baseline = _analyze_with_profiles(
        state,
        hero_seat,
        hero_player.hole_cards,
        ranges,
        candidates,
        balanced_profiles,
        simulations=simulations,
        seed=seed,
    )
    exploit = _analyze_with_profiles(
        state,
        hero_seat,
        hero_player.hole_cards,
        ranges,
        candidates,
        profiles or balanced_profiles,
        simulations=simulations,
        seed=seed,
    )
    baseline_best = max(baseline, key=lambda action: action.ev)
    exploit_best = max(exploit, key=lambda action: action.ev)
    legal = legal_actions(state)
    opponents = [
        player
        for player in state.players
        if player.seat != hero_seat
        and player.status not in (PlayerStatus.FOLDED, PlayerStatus.OUT)
    ]
    effective_stack = min(
        hero_player.stack,
        max((player.stack for player in opponents), default=hero_player.stack),
    )
    reasons = [
        f"当前底池 {state.pot_total}，跟注成本 {legal.to_call}，SPR {effective_stack / max(state.pot_total, 1):.2f}",
        (
            f"利用性最佳动作相对基准最佳动作 EV 变化 "
            f"{exploit_best.ev - baseline_best.ev:+.2f}"
        ),
    ]
    if exploit_best.all_fold_probability:
        reasons.append(
            f"最佳主动动作预计所有对手弃牌概率 {exploit_best.all_fold_probability:.1%}"
        )
    if exploit_best.any_raise_probability:
        reasons.append(
            f"最佳主动动作预计遭遇加注概率 {exploit_best.any_raise_probability:.1%}"
        )
    return StrategyAnalysis(
        hero_seat=hero_seat,
        street=state.street,
        pot=state.pot_total,
        to_call=legal.to_call,
        effective_stack=effective_stack,
        spr=effective_stack / max(state.pot_total, 1),
        baseline_actions=baseline,
        exploit_actions=exploit,
        baseline_action=baseline_best.candidate,
        exploit_action=exploit_best.candidate,
        key_reasons=tuple(reasons),
    )
