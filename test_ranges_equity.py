import random
import json
import unittest

from poker import (
    ActionType,
    GameConfig,
    LOOSE_AGGRESSIVE_PROFILE,
    TIGHT_PROFILE,
    WeightedRange,
    apply_action,
    create_hand,
    deal_board,
    filter_ranges_for_state,
    initialize_player_ranges,
    positions_by_seat,
    preflop_range,
    sample_opponent_hands,
    simulate_weighted_equity,
    update_range_for_action,
    update_ranges_after_action,
)


class WeightedRangeTests(unittest.TestCase):
    def test_full_range_dead_cards_and_normalization(self):
        weighted = WeightedRange.full(dead_cards=["As", "Kh"])
        self.assertEqual(weighted.combo_count, 1225)
        self.assertTrue(all("As" not in combo and "Kh" not in combo for combo in weighted.combos))
        normalized = weighted.normalized()
        self.assertAlmostEqual(normalized.total_weight, 1.0)

    def test_range_json_round_trip(self):
        weighted = WeightedRange({("As", "Ah"): 0.7, ("Kd", "Kc"): 0.3}, "manual")
        payload = json.loads(json.dumps(weighted.to_dict()))
        restored = WeightedRange.from_dict(payload)
        self.assertEqual(restored.source, "manual")
        self.assertEqual(restored.combos, weighted.combos)

    def test_preflop_range_depends_on_position_and_action(self):
        utg_open = preflop_range("UTG", "rfi")
        button_open = preflop_range("BTN", "rfi")
        button_three_bet = preflop_range("BTN", "three_bet")
        self.assertLess(utg_open.combo_count, button_open.combo_count)
        self.assertLess(button_three_bet.combo_count, button_open.combo_count)
        self.assertGreater(button_three_bet.hand_class_weight("AA"), 0)

    def test_opponent_profile_changes_range_width(self):
        tight = preflop_range("CO", "rfi", profile=TIGHT_PROFILE)
        loose = preflop_range("CO", "rfi", profile=LOOSE_AGGRESSIVE_PROFILE)
        self.assertLess(tight.combo_count, loose.combo_count)

    def test_position_mapping_uses_button_and_occupied_seats(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=5),
            {1: 100, 2: 100, 3: 100, 4: 100, 5: 100, 6: 100},
        )
        self.assertEqual(
            positions_by_seat(state),
            {5: "BTN", 6: "SB", 1: "BB", 2: "UTG", 3: "HJ", 4: "CO"},
        )

    def test_initialize_ranges_are_independent_and_remove_known_cards(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=3),
            {1: 100, 2: 100, 3: 100},
            hole_cards={3: ["As", "Ah"]},
        )
        ranges = initialize_player_ranges(state, hero_seat=3)
        self.assertEqual(set(ranges), {1, 2})
        self.assertIsNot(ranges[1], ranges[2])
        self.assertTrue(all("As" not in combo and "Ah" not in combo for combo in ranges[1].combos))

    def test_preflop_raise_reweights_toward_strong_hands(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=3),
            {1: 100, 2: 100, 3: 100},
        )
        prior = WeightedRange.full()
        after = apply_action(state, ActionType.RAISE, raise_to=6)
        updated = update_range_for_action(prior, state, after.actions[-1])
        self.assertGreater(updated.hand_class_weight("AA"), updated.hand_class_weight("72o"))
        self.assertIn("rfi", updated.source)

    def test_postflop_bet_increases_value_hand_weight(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=1),
            {1: 100, 2: 100},
        )
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.CHECK)
        state = deal_board(state, ["As", "Kd", "2c"])
        prior = WeightedRange(
            {
                ("Ah", "Ad"): 1.0,
                ("7h", "6h"): 1.0,
            }
        ).normalized()
        after = apply_action(state, ActionType.BET, raise_to=4)
        updated = update_range_for_action(prior, state, after.actions[-1])
        self.assertGreater(updated.combos[("Ad", "Ah")], updated.combos[("6h", "7h")])

    def test_folded_player_is_removed_from_range_mapping(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=3),
            {1: 100, 2: 100, 3: 100},
        )
        ranges = initialize_player_ranges(state)
        after = apply_action(state, ActionType.FOLD)
        updated = update_ranges_after_action(state, after, ranges)
        self.assertNotIn(3, updated)
        self.assertIn(1, updated)
        self.assertIn(2, updated)

    def test_new_board_cards_are_removed_from_every_range(self):
        state = create_hand(
            GameConfig(small_blind=1, big_blind=2, button_seat=1),
            {1: 100, 2: 100},
            hole_cards={1: ["As", "Ah"]},
        )
        ranges = initialize_player_ranges(state, hero_seat=1)
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.CHECK)
        state = deal_board(state, ["Kd", "Qc", "2h"])
        filtered = filter_ranges_for_state(state, ranges)
        self.assertTrue(
            all(
                not {"As", "Ah", "Kd", "Qc", "2h"}.intersection(combo)
                for combo in filtered[2].combos
            )
        )


class WeightedEquityTests(unittest.TestCase):
    def test_multi_player_sampling_never_repeats_cards(self):
        ranges = {
            1: WeightedRange.full(),
            2: WeightedRange.full(),
            3: WeightedRange.full(),
        }
        rng = random.Random(17)
        for _ in range(100):
            hands = sample_opponent_hands(ranges, rng, dead_cards=["As", "Ah"])
            cards = [card for combo in hands.values() for card in combo]
            self.assertEqual(len(cards), len(set(cards)))
            self.assertNotIn("As", cards)
            self.assertNotIn("Ah", cards)

    def test_weighted_equity_accepts_different_ranges_per_opponent(self):
        result = simulate_weighted_equity(
            ["As", "Ah"],
            [],
            {
                1: preflop_range("UTG", "rfi", dead_cards=["As", "Ah"]),
                2: preflop_range("BB", "call_open", dead_cards=["As", "Ah"]),
            },
            simulations=500,
            seed=9,
        )
        self.assertEqual(result.simulations, 500)
        self.assertGreater(result.equity, 0.55)
        self.assertEqual(set(result.opponent_equity), {1, 2})
        self.assertAlmostEqual(
            result.equity + sum(result.opponent_equity.values()),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
