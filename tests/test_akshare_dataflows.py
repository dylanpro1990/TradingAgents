import unittest
from http.client import RemoteDisconnected
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tradingagents.dataflows.akshare_utils import (
    AkShareConnectionError,
    AkShareUnsupportedSymbolError,
    get_indicators,
    get_stock_data,
    normalize_a_share_symbol,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.interface import VENDOR_METHODS, route_to_vendor


@pytest.mark.unit
class AkShareDataflowTests(unittest.TestCase):
    def setUp(self):
        self.sample_data = pd.DataFrame(
            {
                "日期": ["2026-04-28", "2026-04-29", "2026-04-30"],
                "开盘": [100.123, 101.0, 102.0],
                "最高": [103.0, 104.0, 105.0],
                "最低": [99.0, 100.0, 101.0],
                "收盘": [102.345, 103.0, 104.0],
                "成交量": [10000, 12000, 13000],
            }
        )

    def test_normalize_a_share_symbol_variants(self):
        self.assertEqual(normalize_a_share_symbol("002594"), "002594")
        self.assertEqual(normalize_a_share_symbol("002594.SZ"), "002594")
        self.assertEqual(normalize_a_share_symbol("SZ002594"), "002594")
        self.assertEqual(normalize_a_share_symbol("600519.SS"), "600519")
        self.assertEqual(normalize_a_share_symbol("SH600519"), "600519")

    def test_normalize_a_share_symbol_rejects_non_a_share(self):
        with self.assertRaises(AkShareUnsupportedSymbolError):
            normalize_a_share_symbol("NVDA")

    @patch("akshare.stock_zh_a_hist")
    def test_get_stock_data_formats_akshare_dataframe(self, stock_hist):
        stock_hist.return_value = self.sample_data

        result = get_stock_data("002594.SZ", "2026-04-28", "2026-04-30")

        stock_hist.assert_called_once_with(
            symbol="002594",
            period="daily",
            start_date="20260428",
            end_date="20260430",
            adjust="qfq",
        )
        self.assertIn("# Stock data for 002594 from 2026-04-28 to 2026-04-30", result)
        self.assertIn("# Total records: 3", result)
        self.assertIn("Date,Open,High,Low,Close,Volume", result)
        self.assertIn("2026-04-28,100.12,103.0,99.0,102.34,10000", result)

    @patch("akshare.stock_zh_a_hist")
    def test_get_stock_data_returns_clear_no_data_message(self, stock_hist):
        stock_hist.return_value = pd.DataFrame()

        result = get_stock_data("002594", "2026-04-28", "2026-04-30")

        self.assertEqual(result, "No data found for symbol '002594' between 2026-04-28 and 2026-04-30")

    @patch("akshare.stock_zh_a_hist")
    def test_get_indicators_formats_markdown_output(self, stock_hist):
        stock_hist.return_value = self.sample_data

        result = get_indicators("002594", "close_10_ema", "2026-04-30", look_back_days=2)

        self.assertIn("## close_10_ema values from 2026-04-28 to 2026-04-30", result)
        self.assertIn("2026-04-30:", result)
        self.assertIn("10 EMA", result)

    @patch("akshare.stock_zh_a_hist")
    def test_get_stock_data_wraps_akshare_connection_errors(self, stock_hist):
        stock_hist.side_effect = RemoteDisconnected("Remote end closed connection without response")

        with self.assertRaises(AkShareConnectionError):
            get_stock_data("002594", "2026-04-28", "2026-04-30")

    def test_route_to_vendor_falls_back_when_akshare_connection_fails(self):
        akshare_stock = Mock(side_effect=AkShareConnectionError("akshare failed"))
        yfinance_stock = Mock(return_value="yf result")
        original_akshare = VENDOR_METHODS["get_stock_data"]["akshare"]
        original_yfinance = VENDOR_METHODS["get_stock_data"]["yfinance"]
        VENDOR_METHODS["get_stock_data"]["akshare"] = akshare_stock
        VENDOR_METHODS["get_stock_data"]["yfinance"] = yfinance_stock
        set_config(
            {
                "data_vendors": {"core_stock_apis": "akshare,yfinance"},
                "tool_vendors": {},
            }
        )

        try:
            result = route_to_vendor("get_stock_data", "002594.SZ", "2026-04-28", "2026-04-30")
        finally:
            VENDOR_METHODS["get_stock_data"]["akshare"] = original_akshare
            VENDOR_METHODS["get_stock_data"]["yfinance"] = original_yfinance

        self.assertEqual(result, "yf result")

        yfinance_stock = Mock(return_value="yf result")
        original_yfinance = VENDOR_METHODS["get_stock_data"]["yfinance"]
        VENDOR_METHODS["get_stock_data"]["yfinance"] = yfinance_stock
        set_config(
            {
                "data_vendors": {"core_stock_apis": "akshare,yfinance"},
                "tool_vendors": {},
            }
        )

        try:
            result = route_to_vendor("get_stock_data", "NVDA", "2026-04-28", "2026-04-30")
        finally:
            VENDOR_METHODS["get_stock_data"]["yfinance"] = original_yfinance

        self.assertEqual(result, "yf result")


if __name__ == "__main__":
    unittest.main()
