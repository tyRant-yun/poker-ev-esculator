import json
import unittest

from poker import (
    ActionType,
    GameConfig,
    PlayerStatus,
    Street,
    apply_action,
    build_pots,
    create_hand,
    deal_board,
    hand_from_dict,
    hand_to_dict,
    legal_actions,
    settle_showdown,
)


class HandStateTests(unittest.TestCase):
    def setUp(self):
        self.config = GameConfig(small_blind=1, big_blind=2, button_seat=3)

    def test_three_handed_action_order_and_street_progression(self):
        state = create_hand(self.config, {1: 100, 2: 100, 3: 100})
        self.assertEqual(state.acting_seat, 3)
        self.assertEqual(state.pot_total, 3)
        self.assertEqual(legal_actions(state).to_call, 2)

        state = apply_action(state, ActionType.CALL)
        self.assertEqual(state.acting_seat, 1)
        state = apply_action(state, ActionType.CALL)
        self.assertEqual(state.acting_seat, 2)
        self.assertEqual(legal_actions(state).actions, (ActionType.CHECK, ActionType.RAISE, ActionType.ALL_IN))
        state = apply_action(state, ActionType.CHECK)
        self.assertTrue(state.awaiting_board)

        state = deal_board(state, ["As", "Kh", "2c"])
        self.assertEqual(state.street, Street.FLOP)
        self.assertEqual(state.acting_seat, 1)
        self.assertTrue(all(player.street_commitment == 0 for player in state.players))

    def test_heads_up_button_acts_first_preflop_and_last_postflop(self):
        config = GameConfig(small_blind=1, big_blind=2, button_seat=1)
        state = create_hand(config, {1: 100, 2: 100})
        self.assertEqual(state.acting_seat, 1)
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.CHECK)
        state = deal_board(state, ["As", "Kh", "2c"])
        self.assertEqual(state.acting_seat, 2)

    def test_ante_does_not_change_preflop_call_amount(self):
        config = GameConfig(small_blind=1, big_blind=2, button_seat=3, ante=1)
        state = create_hand(config, {1: 100, 2: 100, 3: 100})
        self.assertEqual(state.pot_total, 6)
        self.assertEqual(state.current_bet, 2)
        self.assertEqual(legal_actions(state).to_call, 2)

    def test_short_all_in_does_not_reopen_raise_for_players_who_acted(self):
        config = GameConfig(small_blind=1, big_blind=2, button_seat=4)
        state = create_hand(config, {1: 100, 2: 100, 3: 100, 4: 8})
        state = apply_action(state, ActionType.CALL)  # seat 3
        state = apply_action(state, ActionType.CALL)  # seat 4
        state = apply_action(state, ActionType.CALL)  # seat 1
        state = apply_action(state, ActionType.RAISE, raise_to=6)  # seat 2, full raise
        state = apply_action(state, ActionType.CALL)  # seat 3
        state = apply_action(state, ActionType.ALL_IN)  # seat 4, raises to 8
        state = apply_action(state, ActionType.CALL)  # seat 1 had not acted after full raise

        self.assertEqual(state.acting_seat, 2)
        legal = legal_actions(state)
        self.assertEqual(legal.to_call, 2)
        self.assertNotIn(ActionType.RAISE, legal.actions)
        self.assertNotIn(ActionType.ALL_IN, legal.actions)

    def test_full_raise_reopens_action(self):
        state = create_hand(self.config, {1: 100, 2: 100, 3: 100})
        state = apply_action(state, ActionType.RAISE, raise_to=6)
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.RAISE, raise_to=18)
        self.assertEqual(state.acting_seat, 3)
        self.assertIn(ActionType.RAISE, legal_actions(state).actions)

    def test_short_opening_all_in_reopens_action_for_prior_checker(self):
        config = GameConfig(small_blind=1, big_blind=2, button_seat=3)
        state = create_hand(config, {1: 100, 2: 3, 3: 100})
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.CHECK)
        state = deal_board(state, ["As", "Kh", "2c"])
        state = apply_action(state, ActionType.CHECK)  # seat 1
        state = apply_action(state, ActionType.ALL_IN)  # seat 2 bets 1
        state = apply_action(state, ActionType.CALL)  # seat 3
        self.assertEqual(state.acting_seat, 1)
        self.assertIn(ActionType.RAISE, legal_actions(state).actions)

    def test_cannot_raise_when_all_other_players_are_all_in(self):
        config = GameConfig(small_blind=1, big_blind=2, button_seat=1)
        state = create_hand(config, {1: 100, 2: 20})
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.ALL_IN)
        self.assertEqual(state.acting_seat, 1)
        legal = legal_actions(state)
        self.assertNotIn(ActionType.RAISE, legal.actions)
        self.assertNotIn(ActionType.ALL_IN, legal.actions)

    def test_uncontested_pot_is_awarded_immediately(self):
        state = create_hand(self.config, {1: 100, 2: 100, 3: 100})
        state = apply_action(state, ActionType.FOLD)
        state = apply_action(state, ActionType.FOLD)
        self.assertTrue(state.complete)
        self.assertEqual(state.payouts, {2: 3})
        self.assertEqual(sum(player.stack for player in state.players), 300)

    def test_all_in_side_pots_and_showdown_settlement(self):
        state = create_hand(self.config, {1: 100, 2: 60, 3: 20})
        state = apply_action(state, ActionType.ALL_IN)  # seat 3 to 20
        state = apply_action(state, ActionType.ALL_IN)  # seat 1 to 100
        state = apply_action(state, ActionType.ALL_IN)  # seat 2 calls for 60
        self.assertTrue(state.awaiting_board)
        self.assertEqual(
            [(pot.amount, pot.eligible_seats) for pot in build_pots(state)],
            [(60, (1, 2, 3)), (80, (1, 2)), (40, (1,))],
        )

        state = deal_board(state, ["As", "Kh", "2c"])
        state = deal_board(state, ["3d"])
        state = deal_board(state, ["4h"])
        self.assertTrue(state.showdown_ready)
        state = settle_showdown(state, {1: (0,), 2: (1,), 3: (2,)})
        self.assertTrue(state.complete)
        self.assertEqual(state.payouts, {3: 60, 2: 80, 1: 40})
        self.assertEqual(sum(player.stack for player in state.players), 180)

    def test_folded_player_contributes_but_cannot_win(self):
        state = create_hand(self.config, {1: 100, 2: 100, 3: 100})
        state = apply_action(state, ActionType.RAISE, raise_to=10)
        state = apply_action(state, ActionType.CALL)
        state = apply_action(state, ActionType.FOLD)
        state = deal_board(state, ["As", "Kh", "2c"])
        state = apply_action(state, ActionType.CHECK)
        state = apply_action(state, ActionType.CHECK)
        state = deal_board(state, ["3d"])
        state = apply_action(state, ActionType.CHECK)
        state = apply_action(state, ActionType.CHECK)
        state = deal_board(state, ["4h"])
        state = apply_action(state, ActionType.CHECK)
        state = apply_action(state, ActionType.CHECK)
        self.assertTrue(state.showdown_ready)
        state = settle_showdown(state, {1: (1,), 3: (2,)})
        self.assertNotIn(2, state.payouts)
        self.assertEqual(sum(state.payouts.values()), 22)

    def test_complete_state_json_round_trip(self):
        state = create_hand(
            self.config,
            {1: 100, 2: 100, 3: 100},
            hole_cards={3: ["As", "Ah"]},
        )
        state = apply_action(state, ActionType.RAISE, raise_to=6)
        payload = json.loads(json.dumps(hand_to_dict(state)))
        restored = hand_from_dict(payload)
        self.assertEqual(hand_to_dict(restored), payload)
        self.assertEqual(restored.player(3).hole_cards, ["As", "Ah"])
        self.assertEqual(restored.player(1).status, PlayerStatus.ACTIVE)

    def test_illegal_raise_is_rejected(self):
        state = create_hand(self.config, {1: 100, 2: 100, 3: 100})
        with self.assertRaisesRegex(ValueError, "下注总额"):
            apply_action(state, ActionType.RAISE, raise_to=3)


if __name__ == "__main__":
    unittest.main()
