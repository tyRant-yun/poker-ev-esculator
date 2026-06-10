import unittest
import tempfile
from pathlib import Path

import web_app
from review_store import get_review, list_reviews
from web_app import (
    HAND_SESSIONS,
    analyze_hand_request,
    apply_hand_action_request,
    branch_hand_request,
    create_hand_request,
    deal_hand_request,
    hand_session_data,
    next_hand_request,
    preflop_training_data,
    reset_hand_request,
    restart_hand_request,
    settle_hand_request,
    undo_hand_request,
)


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        web_app.REVIEW_DB_PATH = Path(self.temp_dir.name) / "reviews.db"

    def tearDown(self):
        HAND_SESSIONS.clear()
        self.temp_dir.cleanup()

    def create_heads_up_hand(self):
        return create_hand_request(
            {
                "small_blind": 1,
                "big_blind": 2,
                "button_seat": 1,
                "hero_seat": 2,
                "players": [
                    {"seat": 1, "stack": 100, "name": "Villain", "profile": "tight"},
                    {"seat": 2, "stack": 100, "name": "Hero", "hand": "As Ah"},
                ],
            }
        )

    def test_complete_hand_session_lifecycle_and_analysis(self):
        hand = self.create_heads_up_hand()
        hand_id = hand["hand_id"]
        self.assertEqual(hand["legal_actions"]["seat"], 1)
        self.assertEqual(hand["history_depth"], 0)
        villain_range = hand["ranges"]["1"]
        self.assertEqual(len(villain_range["matrix"]), 169)
        self.assertIn("AA", villain_range["matrix"])
        self.assertEqual(len(villain_range["top_classes"]), 8)
        hand = apply_hand_action_request(hand_id, {"type": "call"})
        self.assertEqual(hand["history_depth"], 1)
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        self.assertTrue(hand["state"]["awaiting_board"])
        hand = deal_hand_request(hand_id, {"cards": "Kd 7c 2h"})
        self.assertEqual(hand["state"]["acting_seat"], 2)
        analysis = analyze_hand_request(hand_id, {"simulations": 20, "seed": 3})
        self.assertEqual(analysis["hero_seat"], 2)
        self.assertTrue(analysis["baseline_actions"])

    def test_complete_hand_requires_hero_cards(self):
        with self.assertRaisesRegex(ValueError, "Hero 手牌"):
            create_hand_request(
                {
                    "button_seat": 1,
                    "hero_seat": 2,
                    "players": [{"seat": 1, "stack": 100}, {"seat": 2, "stack": 100}],
                }
            )

    def test_nine_player_session_exposes_all_opponent_ranges(self):
        hand = create_hand_request(
            {
                "button_seat": 9,
                "hero_seat": 9,
                "players": [
                    {"seat": seat, "stack": 100, "hand": "As Ah" if seat == 9 else ""}
                    for seat in range(1, 10)
                ],
            }
        )
        self.assertEqual(len(hand["state"]["players"]), 9)
        self.assertEqual(len(hand["positions"]), 9)
        self.assertEqual(len(hand["ranges"]), 8)

    def test_showdown_can_be_completed_with_opponent_cards(self):
        hand = self.create_heads_up_hand()
        hand_id = hand["hand_id"]
        hand = apply_hand_action_request(hand_id, {"type": "call"})
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        hand = deal_hand_request(hand_id, {"cards": "Kd 7c 2h"})
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        hand = deal_hand_request(hand_id, {"cards": "Qs"})
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        hand = deal_hand_request(hand_id, {"cards": "Jd"})
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        hand = apply_hand_action_request(hand_id, {"type": "check"})
        self.assertTrue(hand["state"]["showdown_ready"])
        hand = settle_hand_request(hand_id, {"hands": {"1": "9s 8s"}})
        self.assertTrue(hand["state"]["complete"])
        self.assertEqual(hand["state"]["payouts"], {"2": 4})

    def test_complete_hand_undo_and_branch(self):
        hand = create_hand_request(
            {
                "button_seat": 1,
                "hero_seat": 1,
                "players": [
                    {"seat": 1, "stack": 100, "hand": "As Ah"},
                    {"seat": 2, "stack": 100},
                ],
            }
        )
        original_id = hand["hand_id"]
        hand = apply_hand_action_request(original_id, {"type": "call"})
        self.assertEqual(len(hand["state"]["actions"]), 3)
        restored = undo_hand_request(original_id)
        self.assertEqual(len(restored["state"]["actions"]), 2)
        branch = branch_hand_request(original_id)
        self.assertNotEqual(branch["hand_id"], original_id)
        apply_hand_action_request(branch["hand_id"], {"type": "call"})
        self.assertEqual(len(HAND_SESSIONS[original_id]["state"].actions), 2)

    def test_reset_returns_current_session_to_its_start(self):
        hand = self.create_heads_up_hand()
        hand_id = hand["hand_id"]
        apply_hand_action_request(hand_id, {"type": "call"})
        reset = reset_hand_request(hand_id)
        self.assertEqual(reset["hand_id"], hand_id)
        self.assertEqual(reset["history_depth"], 0)
        self.assertEqual(len(reset["state"]["actions"]), 2)
        self.assertEqual(reset["state"]["players"][0]["stack"], 99)

    def test_restart_creates_fresh_hand_from_original_setup(self):
        hand = self.create_heads_up_hand()
        original_id = hand["hand_id"]
        apply_hand_action_request(original_id, {"type": "call"})
        restarted = restart_hand_request(original_id, {"hero_hand": "Ks Kh"})
        self.assertNotEqual(restarted["hand_id"], original_id)
        self.assertEqual(restarted["state"]["config"]["button_seat"], 1)
        self.assertEqual([player["stack"] for player in restarted["state"]["players"]], [99, 98])
        hero = next(player for player in restarted["state"]["players"] if player["seat"] == 2)
        self.assertEqual(hero["hole_cards"], ["Ks", "Kh"])

    def test_next_hand_inherits_final_stacks_and_rotates_button(self):
        hand = self.create_heads_up_hand()
        original_id = hand["hand_id"]
        complete = apply_hand_action_request(original_id, {"type": "fold"})
        self.assertTrue(complete["state"]["complete"])
        next_hand = next_hand_request(original_id, {"hero_hand": "Ks Kh"})
        self.assertNotEqual(next_hand["hand_id"], original_id)
        self.assertEqual(next_hand["state"]["config"]["button_seat"], 2)
        stacks = {player["seat"]: player["starting_stack"] for player in next_hand["state"]["players"]}
        self.assertEqual(stacks, {1: 99, 2: 101})
        self.assertEqual(next_hand["state"]["board"], [])
        self.assertEqual(len(next_hand["state"]["actions"]), 2)

    def test_next_hand_rejects_incomplete_hand(self):
        hand = self.create_heads_up_hand()
        with self.assertRaisesRegex(ValueError, "尚未结束"):
            next_hand_request(hand["hand_id"], {"hero_hand": "Ks Kh"})

    def test_next_hand_can_rebuy_zero_stack_player(self):
        hand = create_hand_request(
            {
                "button_seat": 1,
                "hero_seat": 1,
                "players": [
                    {"seat": 1, "stack": 100, "hand": "As Ah"},
                    {"seat": 2, "stack": 1},
                    {"seat": 3, "stack": 100},
                ],
            }
        )
        hand_id = hand["hand_id"]
        HAND_SESSIONS[hand_id]["state"].complete = True
        HAND_SESSIONS[hand_id]["state"].players[1].stack = 0
        next_hand = next_hand_request(
            hand_id, {"hero_hand": "Ks Kh", "rebuys": {"2": 80}}
        )
        starting = {player["seat"]: player["starting_stack"] for player in next_hand["state"]["players"]}
        self.assertEqual(starting[2], 80)
        self.assertEqual(len(starting), 3)

    def test_next_hand_rejects_rebuy_for_player_with_chips(self):
        hand = self.create_heads_up_hand()
        apply_hand_action_request(hand["hand_id"], {"type": "fold"})
        with self.assertRaisesRegex(ValueError, "仍有筹码"):
            next_hand_request(
                hand["hand_id"], {"hero_hand": "Ks Kh", "rebuys": {"1": 100}}
            )

    def test_completed_hand_is_archived_with_snapshots(self):
        hand = self.create_heads_up_hand()
        complete = apply_hand_action_request(hand["hand_id"], {"type": "fold"})
        self.assertTrue(complete["state"]["complete"])
        reviews = list_reviews(db_path=web_app.REVIEW_DB_PATH)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["hand_id"], hand["hand_id"])
        archived = get_review(hand["hand_id"], db_path=web_app.REVIEW_DB_PATH)
        self.assertEqual(archived["final_hand"]["state"]["complete"], True)
        self.assertGreaterEqual(len(archived["snapshots"]), 2)

    def test_preflop_training_data_varies_by_position_and_action(self):
        button_rfi = preflop_training_data("BTN", "rfi")
        utg_rfi = preflop_training_data("UTG", "rfi")
        button_three_bet = preflop_training_data("BTN", "three_bet")
        self.assertGreater(button_rfi["coverage"], utg_rfi["coverage"])
        self.assertGreater(button_rfi["combo_count"], button_three_bet["combo_count"])
        self.assertIn("AA", button_rfi["classes"])

    def test_session_data_rejects_unknown_hand(self):
        with self.assertRaisesRegex(ValueError, "牌局不存在"):
            hand_session_data("missing")


if __name__ == "__main__":
    unittest.main()
