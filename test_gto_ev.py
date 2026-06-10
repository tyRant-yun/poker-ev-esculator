import unittest

from gto_ev import calculate, calculate_action_ev, evaluate, parse_cards


class GtoEvTests(unittest.TestCase):
    def test_parse_cards_normalizes_and_rejects_duplicates(self):
        self.assertEqual(parse_cards("as KH"), ["As", "Kh"])
        with self.assertRaises(ValueError):
            parse_cards("As As")

    def test_hand_evaluator_categories(self):
        straight_flush = evaluate(parse_cards("As Ks Qs Js Ts 2d 3c"))
        quads = evaluate(parse_cards("Ah Ad Ac As Kd 2c 3h"))
        full_house = evaluate(parse_cards("Kh Kd Kc 2s 2d 9h 8c"))
        self.assertGreater(straight_flush, quads)
        self.assertGreater(quads, full_house)

    def test_action_ev(self):
        ev = calculate_action_ev(
            equity=0.5, pot=10, to_call=2, raise_size=8, fold_to_raise=0.4
        )
        self.assertAlmostEqual(ev["call"], 4.0)
        self.assertAlmostEqual(ev["raise"], 6.4)

    def test_seeded_calculation_is_repeatable(self):
        kwargs = dict(
            players=2,
            position="BTN",
            hand=parse_cards("As Ah"),
            strategy="balanced",
            simulations=100,
            seed=7,
        )
        first = calculate(**kwargs)
        second = calculate(**kwargs)
        self.assertEqual(first.equity, second.equity)
        self.assertEqual(first.recommended_action, second.recommended_action)

    def test_premium_pair_has_strong_heads_up_equity(self):
        result = calculate(
            players=2,
            position="BTN",
            hand=parse_cards("As Ah"),
            opponent_range=1.0,
            simulations=500,
            seed=11,
        )
        self.assertGreater(result.equity, 0.75)


if __name__ == "__main__":
    unittest.main()
