import unittest

from core.uw_fetcher import format_contracts_for_copy, occ_to_copy_token


class ContractCopyFormatTest(unittest.TestCase):
    def test_single_occ_to_copy(self):
        self.assertEqual(
            occ_to_copy_token("SPXW260520C07415000"),
            ".SPXW260520C7415",
        )

    def test_ladder_ignored_single_token_only(self):
        text = format_contracts_for_copy(
            "SPXW260520C07420000",
            {
                "has_ladder": True,
                "ladder_strikes": [7410.0, 7415.0, 7420.0, 7425.0],
            },
        )
        self.assertEqual(text, ".SPXW260520C7420")

    def test_no_ladder_single_token(self):
        self.assertEqual(
            format_contracts_for_copy("NVDA261016C00100000"),
            ".NVDA261016C100",
        )

if __name__ == "__main__":
    unittest.main()
