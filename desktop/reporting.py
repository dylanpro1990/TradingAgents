from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any


REPORT_SECTIONS = {
    "market_report": ("市场分析", "market.md"),
    "sentiment_report": ("社交情绪分析", "social.md"),
    "news_report": ("新闻分析", "news.md"),
    "fundamentals_report": ("基本面分析", "fundamentals.md"),
    "investment_plan": ("研究辩论", "research.md"),
    "trader_investment_plan": ("交易计划", "trader.md"),
    "risk_assessment": ("风险管理", "risk.md"),
    "final_trade_decision": ("组合经理决策", "decision.md"),
}


def extract_sections(state: dict[str, Any]) -> dict[str, str]:
    investment_debate = state.get("investment_debate_state") or {}
    risk_debate = state.get("risk_debate_state") or {}

    sections = {
        "market_report": state.get("market_report", ""),
        "sentiment_report": state.get("sentiment_report", ""),
        "news_report": state.get("news_report", ""),
        "fundamentals_report": state.get("fundamentals_report", ""),
        "investment_plan": "\n\n".join(
            part
            for part in (
                _section_text("多方研究员", investment_debate.get("bull_history")),
                _section_text("空方研究员", investment_debate.get("bear_history")),
                _section_text("研究经理", investment_debate.get("judge_decision")),
            )
            if part
        ),
        "trader_investment_plan": state.get("trader_investment_plan", ""),
        "risk_assessment": "\n\n".join(
            part
            for part in (
                _section_text("激进风险分析师", risk_debate.get("aggressive_history")),
                _section_text("保守风险分析师", risk_debate.get("conservative_history")),
                _section_text("中性风险分析师", risk_debate.get("neutral_history")),
                _section_text("组合经理", risk_debate.get("judge_decision")),
            )
            if part
        ),
        "final_trade_decision": state.get("final_trade_decision", ""),
    }
    return {key: value.strip() for key, value in sections.items() if value and value.strip()}


def assemble_report(ticker: str, trade_date: str, state: dict[str, Any]) -> str:
    title = f"# 交易分析报告：{ticker}\n\n"
    metadata = (
        f"- 分析日期：{trade_date}\n"
        f"- 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    sections = []
    for key, (heading, _) in REPORT_SECTIONS.items():
        content = extract_sections(state).get(key)
        if content:
            sections.append(f"## {heading}\n\n{content}")
    return title + metadata + "\n\n".join(sections)


def save_report(base_dir: Path | str, ticker: str, trade_date: str, state: dict[str, Any]) -> Path:
    report_dir = Path(base_dir) / ticker.upper() / trade_date / "desktop_reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    for key, (_, filename) in REPORT_SECTIONS.items():
        content = extract_sections(state).get(key)
        if content:
            (report_dir / filename).write_text(content, encoding="utf-8")

    complete_report = report_dir / "complete_report.md"
    complete_report.write_text(assemble_report(ticker, trade_date, state), encoding="utf-8")
    return complete_report


def _section_text(title: str, content: Any) -> str:
    if not content or not str(content).strip():
        return ""
    return f"### {title}\n{str(content).strip()}"
