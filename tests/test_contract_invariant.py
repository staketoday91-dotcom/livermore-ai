import unittest

from core.scanner import LivermoreScanner


class FakeUW:
    async def get_ticker_data(self, ticker):
        return {"prev_close": 900.0, "iv_rank": 50}

    async def get_ticker_flow(self, ticker):
        return [
            {
                "option_chain": "MU261016C01000000",
                "nominal_value": 5_000_000,
                "volume": 100,
                "open_interest": 1000,
                "volume_oi_ratio": 1.0,
                "total_ask_side_prem": 4_000_000,
                "delta": 0.45,
                "has_sweep": True,
                "has_floor": False,
                "repeated_flow": False,
                "flow_count": 1,
                "accumulated_nominal": 5_000_000,
                "is_single_leg": True,
            }
        ]

    async def get_oi_change(self, ticker):
        return {"oi_growing": False, "oi_change_pct": 0, "days_growing": 0}

    async def analyze_dark_pool(self, ticker, current_price):
        return None

    async def get_net_premium(self, ticker):
        return {
            "net_call_premium": 250_000,
            "net_put_premium": 0,
            "call_trend": 1,
            "bearish_pressure": False,
        }

    async def get_gex(self, ticker):
        return {"gex_positive": True}

    async def get_option_chain_map(self, ticker):
        return {}

    async def get_earnings_dte(self, ticker):
        return 99


class ContractInvariantTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_cross_ticker_contamination(self):
        scanner = LivermoreScanner()
        scanner.uw = FakeUW()

        result = await scanner._analyze_ticker(
            "NVDA",
            "REGULAR",
            {"market_direction": "NEUTRAL"},
            {"has_event_today": False, "has_event_tomorrow": False, "events": []},
        )

        self.assertTrue(result is None or result["contract"].startswith("NVDA"))

    async def test_accepts_matching_contract_from_option_symbol_field(self):
        class OptionSymbolUW(FakeUW):
            async def get_ticker_flow(self, ticker):
                rows = await super().get_ticker_flow(ticker)
                rows[0].pop("option_chain")
                rows[0]["option_symbol"] = "NVDA261016C01000000"
                return rows

        scanner = LivermoreScanner()
        scanner.uw = OptionSymbolUW()

        result = await scanner._analyze_ticker(
            "NVDA",
            "REGULAR",
            {"market_direction": "NEUTRAL"},
            {"has_event_today": False, "has_event_tomorrow": False, "events": []},
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["contract"], "NVDA261016C01000000")


if __name__ == "__main__":
    unittest.main()
