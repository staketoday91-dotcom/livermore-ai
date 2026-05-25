import unittest

from core.flash_feed import filter_directional_universe, infer_direction_from_flows


class TestFlashDirectional(unittest.TestCase):
    def test_discards_ticker_with_calls_and_puts(self):
        rows = [
            {"ticker": "NVDA", "option_chain": "NVDA260620C00120000"},
            {"ticker": "NVDA", "option_chain": "NVDA260620P00110000"},
            {"ticker": "AAPL", "option_chain": "AAPL260620C00200000"},
        ]
        out = filter_directional_universe(rows)
        tickers = {r["ticker"] for r in out}
        self.assertNotIn("NVDA", tickers)
        self.assertIn("AAPL", tickers)

    def test_infer_bullish_bearish(self):
        calls = [{"option_chain": "TSLA260620C00300000"}]
        puts = [{"option_chain": "TSLA260620P00280000"}]
        self.assertEqual(infer_direction_from_flows(calls), "BULLISH")
        self.assertEqual(infer_direction_from_flows(puts), "BEARISH")


if __name__ == "__main__":
    unittest.main()
