import os
import unittest

import pytest

from desktop.reporting import assemble_report, extract_sections
from desktop.runner import (
    DesktopSelection,
    _apply_api_key,
    _localized,
    build_config,
    normalize_analysts,
    normalize_ticker_input,
)


@pytest.mark.unit
class DesktopRunnerTests(unittest.TestCase):
    def test_build_config_overlays_desktop_selection(self):
        selection = DesktopSelection(
            ticker="nvda",
            analysis_date="2026-01-15",
            analysts=["market"],
            llm_provider="Anthropic",
            quick_think_llm="claude-sonnet-4-6",
            deep_think_llm="claude-opus-4-6",
            research_depth=3,
            output_language="中文",
            backend_url="https://example.test",
            checkpoint_enabled=True,
            anthropic_effort="medium",
            api_key="secret-key",
        )

        config = build_config(selection)

        self.assertEqual(config["llm_provider"], "anthropic")
        self.assertEqual(config["quick_think_llm"], "claude-sonnet-4-6")
        self.assertEqual(config["deep_think_llm"], "claude-opus-4-6")
        self.assertEqual(config["max_debate_rounds"], 3)
        self.assertEqual(config["max_risk_discuss_rounds"], 3)
        self.assertEqual(config["output_language"], "中文")
        self.assertEqual(config["backend_url"], "https://example.test")
        self.assertTrue(config["checkpoint_enabled"])
        self.assertEqual(config["anthropic_effort"], "medium")
        self.assertEqual(config["api_key"], "secret-key")

    def test_build_config_prefers_akshare_for_a_share_tickers(self):
        selection = DesktopSelection(
            ticker="002594",
            analysis_date="2026-01-15",
            analysts=["market"],
            llm_provider="deepseek",
            quick_think_llm="deepseek-chat",
            deep_think_llm="deepseek-reasoner",
        )

        config = build_config(selection)

        self.assertEqual(config["tool_vendors"]["get_stock_data"], "akshare,yfinance")
        self.assertEqual(config["tool_vendors"]["get_indicators"], "akshare,yfinance")

    def test_apply_api_key_sets_provider_environment_variable(self):
        os.environ.pop("DEEPSEEK_API_KEY", None)
        selection = DesktopSelection(
            ticker="nvda",
            analysis_date="2026-01-15",
            analysts=["market"],
            llm_provider="deepseek",
            quick_think_llm="deepseek-chat",
            deep_think_llm="deepseek-reasoner",
            api_key="secret-key",
        )

        _apply_api_key(selection)

        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "secret-key")

    def test_localized_returns_chinese_when_selected(self):
        selection = DesktopSelection(
            ticker="002594",
            analysis_date="2026-01-15",
            analysts=["market"],
            llm_provider="deepseek",
            quick_think_llm="deepseek-chat",
            deep_think_llm="deepseek-reasoner",
            output_language="中文",
        )

        self.assertEqual(_localized(selection, "Analysis complete.", "分析完成。"), "分析完成。")

        self.assertEqual(normalize_ticker_input("比亚迪"), "002594.SZ")
        self.assertEqual(normalize_ticker_input("腾讯"), "0700.HK")
        self.assertEqual(normalize_ticker_input("nvda"), "NVDA")

    def test_normalize_ticker_input_expands_a_share_codes(self):
        self.assertEqual(normalize_ticker_input("002594"), "002594.SZ")
        self.assertEqual(normalize_ticker_input("300750"), "300750.SZ")
        self.assertEqual(normalize_ticker_input("600519"), "600519.SS")

    def test_normalize_analysts_keeps_graph_order(self):
        self.assertEqual(
            normalize_analysts(["fundamentals", "market", "news"]),
            ["market", "news", "fundamentals"],
        )

    def test_normalize_analysts_rejects_empty_selection(self):
        with self.assertRaises(ValueError):
            normalize_analysts([])

    def test_extract_sections_combines_nested_debate_state(self):
        sections = extract_sections(
            {
                "market_report": "Market content",
                "investment_debate_state": {
                    "bull_history": "Bull case",
                    "bear_history": "Bear case",
                    "judge_decision": "Manager call",
                },
                "risk_debate_state": {
                    "aggressive_history": "Aggressive view",
                    "conservative_history": "Conservative view",
                    "neutral_history": "Neutral view",
                    "judge_decision": "Risk decision",
                },
                "final_trade_decision": "Hold",
            }
        )

        self.assertEqual(sections["market_report"], "Market content")
        self.assertIn("### 多方研究员", sections["investment_plan"])
        self.assertIn("Manager call", sections["investment_plan"])
        self.assertIn("### 组合经理", sections["risk_assessment"])
        self.assertEqual(sections["final_trade_decision"], "Hold")

    def test_assemble_report_includes_core_metadata_and_sections(self):
        report = assemble_report(
            "NVDA",
            "2026-01-15",
            {
                "market_report": "Market content",
                "risk_debate_state": {"judge_decision": "Risk decision"},
                "final_trade_decision": "Buy",
            },
        )

        self.assertIn("# 交易分析报告：NVDA", report)
        self.assertIn("分析日期：2026-01-15", report)
        self.assertIn("## 市场分析", report)
        self.assertIn("## 风险管理", report)
        self.assertIn("## 组合经理决策", report)
