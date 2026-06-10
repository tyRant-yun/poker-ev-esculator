import math
import json
import unittest

from poker import (
    ActionType,
    GameConfig,
    TIGHT_PROFILE,
    WeightedRange,
    analyze_strategy,
    apply_action,
    create_hand,
    deal_board,
    generate_candidate_actions,
    initialize_player_ranges,
    strategy_to_dict,
)


def heads_up_flop_state():
    state = create_hand(
        GameConfig(small_blind=1, big_blind=2, button_seat=1),
        {1: 100, 2: 100},
        hole_cards={2: ["As", "Ah"]},
    )
    state = apply_action(state, ActionType.CALL)
    state = apply_action(state, ActionType.CHECK)
    return deal_board(state, ["Kd", "7c", "2h"])


class CandidateActionTests(unittest.TestCase):
    def test_preflop_candidates_are_legal_and_include_multiple_sizes(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=3),
            {1: 100, 2: 100, 3: 100},
            hole_cards={3: ["As", "Ah"]},
        )
        candidates = generate_candidate_actions(state)
        self.assertEqual(candidates[0].action_type, ActionType.FOLD)
        self.assertIn(ActionType.CALL, [candidate.action_type for candidate in candidates])
        raises = [candidate for candidate in candidates if candidate.action_type == ActionType.RAISE]
        self.assertGreaterEqual(len(raises), 2)
        self.assertTrue(all(candidate.raise_to >= 4 for candidate in raises))
        aggressive = [
            candidate
            for candidate in candidates
            if candidate.action_type in (ActionType.RAISE, ActionType.ALL_IN)
        ]
        self.assertEqual(
            len({candidate.raise_to for candidate in aggressive}),
            len(aggressive),
        )
        self.assertNotIn(ActionType.ALL_IN, [candidate.action_type for candidate in candidates])

    def test_short_preflop_stack_includes_all_in(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=3),
            {1: 30, 2: 30, 3: 30},
            hole_cards={3: ["As", "Ah"]},
        )
        self.assertIn(
            ActionType.ALL_IN,
            [candidate.action_type for candidate in generate_candidate_actions(state)],
        )

    def test_deep_postflop_candidates_include_pot_fractions_but_not_all_in(self):
        candidates = generate_candidate_actions(heads_up_flop_state())
        bets = [candidate for candidate in candidates if candidate.action_type == ActionType.BET]
        self.assertGreaterEqual(len(bets), 4)
        self.assertTrue(any(candidate.pot_fraction is not None for candidate in bets))
        self.assertNotIn(ActionType.ALL_IN, [candidate.action_type for candidate in candidates])

    def test_low_spr_postflop_candidates_include_all_in(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=1),
            {1: 12, 2: 12},
            hole_cards={2: ["As", "Ah"]},
        )
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.CHECK)
        state = deal_board(state, ["Kd", "7c", "2h"])
        self.assertIn(
            ActionType.ALL_IN,
            [candidate.action_type for candidate in generate_candidate_actions(state)],
        )

    def test_facing_bet_candidates_include_fold_call_and_raise(self):
        state = heads_up_flop_state()
        state = apply_action(state, ActionType.CHECK)
        state = apply_action(state, ActionType.BET, raise_to=4)
        actions = {candidate.action_type for candidate in generate_candidate_actions(state)}
        self.assertTrue({ActionType.FOLD, ActionType.CALL, ActionType.RAISE}.issubset(actions))


class StrategyAnalysisTests(unittest.TestCase):
    def test_strategy_analysis_returns_ev_frequencies_and_explanations(self):
        state = heads_up_flop_state()
        ranges = initialize_player_ranges(state, hero_seat=2)
        result = analyze_strategy(state, 2, ranges, simulations=250, seed=7)
        self.assertEqual(result.hero_seat, 2)
        self.assertEqual(result.model, "finite-depth heuristic rollout")
        self.assertIn(result.baseline_action, [item.candidate for item in result.baseline_actions])
        self.assertAlmostEqual(
            sum(item.heuristic_frequency for item in result.baseline_actions),
            1.0,
        )
        self.assertTrue(all(math.isfinite(item.ev) for item in result.baseline_actions))
        self.assertGreaterEqual(len(result.key_reasons), 2)
        payload = json.loads(json.dumps(strategy_to_dict(result)))
        self.assertEqual(payload["street"], "flop")
        self.assertEqual(payload["model"], "finite-depth heuristic rollout")

    def test_fold_ev_is_zero_when_facing_bet(self):
        state = heads_up_flop_state()
        state = apply_action(state, ActionType.CHECK)
        state = apply_action(state, ActionType.BET, raise_to=4)
        ranges = initialize_player_ranges(state, hero_seat=2)
        result = analyze_strategy(state, 2, ranges, simulations=150, seed=11)
        fold = next(
            item for item in result.exploit_actions if item.candidate.action_type == ActionType.FOLD
        )
        self.assertEqual(fold.ev, 0)
        self.assertEqual(result.to_call, 4)

    def test_tight_profile_increases_fold_probability(self):
        state = heads_up_flop_state()
        ranges = {
            1: WeightedRange(
                {
                    ("Kc", "Qc"): 1.0,
                    ("Qd", "Jd"): 1.0,
                    ("6s", "5s"): 1.0,
                    ("3c", "3d"): 1.0,
                }
            )
        }
        result = analyze_strategy(
            state,
            2,
            ranges,
            profiles={1: TIGHT_PROFILE},
            simulations=1200,
            seed=19,
        )
        baseline_bet = next(
            item for item in result.baseline_actions if item.candidate.action_type == ActionType.BET
        )
        exploit_bet = next(
            item
            for item in result.exploit_actions
            if item.candidate.raise_to == baseline_bet.candidate.raise_to
        )
        self.assertGreater(exploit_bet.all_fold_probability, baseline_bet.all_fold_probability)

    def test_strategy_requires_current_actor_and_known_hero_hand(self):
        state = heads_up_flop_state()
        ranges = initialize_player_ranges(state, hero_seat=2)
        with self.assertRaisesRegex(ValueError, "当前行动玩家"):
            analyze_strategy(state, 1, ranges, simulations=10)

    def test_river_known_nuts_check_ev_equals_current_pot(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=1),
            {1: 100, 2: 100},
            hole_cards={1: ["2c", "3d"], 2: ["As", "Ah"]},
        )
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.CHECK)
        for cards in (["Ad", "7c", "7h"], ["Ks"], ["Qd"]):
            state = deal_board(state, cards)
            if len(state.board) < 5:
                state = apply_action(state, ActionType.CHECK)
                state = apply_action(state, ActionType.CHECK)
        result = analyze_strategy(state, 2, {}, simulations=20, seed=3)
        check = next(
            item for item in result.baseline_actions if item.candidate.action_type == ActionType.CHECK
        )
        self.assertEqual(check.ev, state.pot_total)


if __name__ == "__main__":
    unittest.main()
