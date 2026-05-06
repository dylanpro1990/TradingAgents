from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any, Literal

from cli.utils import normalize_ticker_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpointer import clear_checkpoint, get_checkpointer, thread_id
from tradingagents.graph.trading_graph import TradingAgentsGraph

from desktop.reporting import extract_sections, save_report

ANALYST_ORDER = ("market", "social", "news", "fundamentals")
DEFAULT_BACKEND_URLS = {
    "openai": "https://api.openai.com/v1",
    "google": None,
    "anthropic": "https://api.anthropic.com/",
    "xai": "https://api.x.ai/v1",
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4/",
    "openrouter": "https://openrouter.ai/api/v1",
    "azure": None,
    "ollama": "http://localhost:11434/v1",
}
PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
}

TICKER_ALIASES = {
    "比亚迪": "002594.SZ",
    "比亚迪股份": "002594.SZ",
    "BYD": "002594.SZ",
    "宁德时代": "300750.SZ",
    "贵州茅台": "600519.SS",
    "东方财富": "300059.SZ",
    "五粮液": "000858.SZ",
    "平安银行": "000001.SZ",
    "中国平安": "601318.SS",
    "招商银行": "600036.SS",
    "中信证券": "600030.SS",
    "隆基绿能": "601012.SS",
    "腾讯": "0700.HK",
    "腾讯控股": "0700.HK",
    "阿里巴巴": "9988.HK",
    "小米": "1810.HK",
    "美团": "3690.HK",
}

EventType = Literal["status", "message", "section", "decision", "report", "error", "done"]


@dataclass(frozen=True)
class DesktopSelection:
    ticker: str
    analysis_date: str
    analysts: list[str]
    llm_provider: str
    quick_think_llm: str
    deep_think_llm: str
    research_depth: int = 1
    output_language: str = "English"
    backend_url: str | None = None
    checkpoint_enabled: bool = False
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    api_key: str | None = None


def build_config(selection: DesktopSelection) -> dict[str, Any]:
    provider = selection.llm_provider.lower()
    ticker = normalize_ticker_input(selection.ticker)
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selection.research_depth
    config["max_risk_discuss_rounds"] = selection.research_depth
    config["quick_think_llm"] = selection.quick_think_llm.strip()
    config["deep_think_llm"] = selection.deep_think_llm.strip()
    config["backend_url"] = selection.backend_url or DEFAULT_BACKEND_URLS.get(provider)
    config["llm_provider"] = provider
    config["google_thinking_level"] = selection.google_thinking_level
    config["openai_reasoning_effort"] = selection.openai_reasoning_effort
    config["anthropic_effort"] = selection.anthropic_effort
    config["output_language"] = selection.output_language
    config["checkpoint_enabled"] = selection.checkpoint_enabled
    if is_a_share_ticker(ticker):
        tool_vendors = config.get("tool_vendors", {}).copy()
        tool_vendors["get_stock_data"] = "akshare,yfinance"
        tool_vendors["get_indicators"] = "akshare,yfinance"
        config["tool_vendors"] = tool_vendors
    if selection.api_key:
        config["api_key"] = selection.api_key.strip()
    return config


def normalize_ticker_input(ticker: str) -> str:
    raw = ticker.strip()
    alias = TICKER_ALIASES.get(raw) or TICKER_ALIASES.get(raw.upper())
    if alias:
        return alias
    if raw.isdigit() and len(raw) == 6:
        suffix = ".SS" if raw.startswith(("6", "9")) else ".SZ"
        return f"{raw}{suffix}"
    return normalize_ticker_symbol(raw)


def is_a_share_ticker(ticker: str) -> bool:
    normalized = ticker.strip().upper()
    return normalized.endswith((".SZ", ".SS"))


def normalize_analysts(analysts: list[str]) -> list[str]:
    selected = {analyst.lower() for analyst in analysts}
    ordered = [analyst for analyst in ANALYST_ORDER if analyst in selected]
    if not ordered:
        raise ValueError("Select at least one analyst.")
    return ordered


def run_analysis(selection: DesktopSelection, event_queue: Queue[dict[str, Any]]) -> None:
    try:
        ticker = normalize_ticker_input(selection.ticker)
        selected_analysts = normalize_analysts(selection.analysts)
        config = build_config(selection)
        _apply_api_key(selection)

        if ticker != selection.ticker.strip():
            _emit(event_queue, "status", text=f"Mapped {selection.ticker.strip()} to ticker {ticker}.")
        if is_a_share_ticker(ticker):
            _emit(event_queue, "status", text="Using AkShare first for A-share price and indicator data.")
        _emit(event_queue, "status", text="Initializing analysis graph...")
        graph = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            config=config,
            debug=False,
        )
        graph.ticker = ticker

        if config.get("checkpoint_enabled"):
            graph._checkpointer_ctx = get_checkpointer(config["data_cache_dir"], ticker)
            saver = graph._checkpointer_ctx.__enter__()
            graph.graph = graph.workflow.compile(checkpointer=saver)

        try:
            _emit(event_queue, "status", text=f"Analyzing {ticker} on {selection.analysis_date}...")
            graph._resolve_pending_entries(ticker)
            past_context = graph.memory_log.get_past_context(ticker)
            init_state = graph.propagator.create_initial_state(
                ticker, selection.analysis_date, past_context=past_context
            )
            args = graph.propagator.get_graph_args()
            if config.get("checkpoint_enabled"):
                args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = thread_id(
                    ticker, selection.analysis_date
                )

            trace: list[dict[str, Any]] = []
            for chunk in graph.graph.stream(init_state, **args):
                trace.append(chunk)
                _publish_chunk(event_queue, graph, chunk)

            if not trace:
                raise RuntimeError("Analysis finished without returning any graph state.")

            final_state = trace[-1]
            graph.curr_state = final_state
            graph._log_state(selection.analysis_date, final_state)
            graph.memory_log.store_decision(
                ticker=ticker,
                trade_date=selection.analysis_date,
                final_trade_decision=final_state["final_trade_decision"],
            )
            if config.get("checkpoint_enabled"):
                clear_checkpoint(config["data_cache_dir"], ticker, selection.analysis_date)

            decision = graph.process_signal(final_state["final_trade_decision"])
            report_path = save_report(Path(config["results_dir"]), ticker, selection.analysis_date, final_state)
            _emit(event_queue, "decision", decision=decision, content=final_state["final_trade_decision"])
            _emit(event_queue, "report", path=str(report_path))
            _emit(event_queue, "done", text="Analysis complete.")
        finally:
            if graph._checkpointer_ctx is not None:
                graph._checkpointer_ctx.__exit__(None, None, None)
                graph._checkpointer_ctx = None
                graph.graph = graph.workflow.compile()
    except Exception as exc:
        _emit(event_queue, "error", text=str(exc))


def _apply_api_key(selection: DesktopSelection) -> None:
    api_key = (selection.api_key or "").strip()
    if not api_key:
        return
    env_var = PROVIDER_API_KEY_ENV.get(selection.llm_provider.lower())
    if env_var:
        os.environ[env_var] = api_key


def _publish_chunk(event_queue: Queue[dict[str, Any]], graph: TradingAgentsGraph, chunk: dict[str, Any]) -> None:
    for message in chunk.get("messages", []):
        content = getattr(message, "content", None)
        if content and str(content).strip():
            _emit(event_queue, "message", text=str(content).strip())

    for key, content in extract_sections(chunk).items():
        _emit(event_queue, "section", key=key, content=content)

    final_decision = chunk.get("final_trade_decision")
    if final_decision:
        _emit(
            event_queue,
            "decision",
            decision=graph.process_signal(final_decision),
            content=final_decision,
        )


def _emit(event_queue: Queue[dict[str, Any]], event_type: EventType, **payload: Any) -> None:
    event_queue.put({"type": event_type, **payload})
