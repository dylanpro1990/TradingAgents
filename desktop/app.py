from __future__ import annotations

import datetime
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from desktop.runner import (
    DEFAULT_BACKEND_URLS,
    PROVIDER_API_KEY_ENV,
    DesktopSelection,
    run_analysis,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS, get_model_options

ANALYSTS = {
    "market": "Market",
    "social": "Social",
    "news": "News",
    "fundamentals": "Fundamentals",
}
SECTION_TABS = {
    "market_report": "Market",
    "sentiment_report": "Social",
    "news_report": "News",
    "fundamentals_report": "Fundamentals",
    "investment_plan": "Research",
    "trader_investment_plan": "Trader",
    "risk_assessment": "Risk",
    "final_trade_decision": "Final",
}
PROVIDERS = [
    "openai",
    "anthropic",
    "google",
    "deepseek",
    "qwen",
    "glm",
    "xai",
    "openrouter",
    "azure",
    "ollama",
]


class TradingAgentsDesktop(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TradingAgents Desktop")
        self.geometry("1280x820")
        self.minsize(1100, 720)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.event_queue: queue.Queue[dict] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.report_path: Path | None = None
        self.tab_textboxes: dict[str, ctk.CTkTextbox] = {}
        self.analyst_vars: dict[str, tk.BooleanVar] = {}

        self._build_layout()
        self.after(150, self._poll_events)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=300, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(0, weight=1)

        self.sidebar_content = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.sidebar_content.grid(row=0, column=0, sticky="nsew")
        self.sidebar_content.grid_columnconfigure(0, weight=1)

        self.sidebar_actions = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_actions.grid(row=1, column=0, sticky="ew", padx=0, pady=(6, 18))
        self.sidebar_actions.grid_columnconfigure(0, weight=1)

        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        self._build_sidebar()
        self._build_main_panel()

    def _build_sidebar(self) -> None:
        title = ctk.CTkLabel(
            self.sidebar_content,
            text="TradingAgents",
            font=ctk.CTkFont(size=26, weight="bold"),
        )
        title.grid(row=0, column=0, padx=24, pady=(24, 4), sticky="w")
        subtitle = ctk.CTkLabel(
            self.sidebar_content,
            text="A股可直接输 6 位代码，如 002594 / 600519",
            text_color=("gray35", "gray70"),
        )
        subtitle.grid(row=1, column=0, padx=24, pady=(0, 20), sticky="w")

        self.ticker_entry = self._entry("Ticker / 股票代码", "002594", 2)
        self.date_entry = self._entry("Analysis Date", datetime.date.today().isoformat(), 3)

        ctk.CTkLabel(self.sidebar_content, text="Analysts", font=ctk.CTkFont(weight="bold")).grid(
            row=4, column=0, padx=24, pady=(14, 6), sticky="w"
        )
        analyst_frame = ctk.CTkFrame(self.sidebar_content, fg_color="transparent")
        analyst_frame.grid(row=5, column=0, padx=20, sticky="ew")
        for index, (key, label) in enumerate(ANALYSTS.items()):
            var = tk.BooleanVar(value=True)
            self.analyst_vars[key] = var
            checkbox = ctk.CTkCheckBox(analyst_frame, text=label, variable=var)
            checkbox.grid(row=index // 2, column=index % 2, padx=4, pady=6, sticky="w")

        self.language_menu = self._option("Output Language", ["English", "中文"], "English", 6)
        self.provider_menu = self._option("Provider", PROVIDERS, DEFAULT_CONFIG["llm_provider"], 7)
        self.provider_menu.configure(command=self._on_provider_change)

        self.quick_model_entry = self._entry("Quick Model", DEFAULT_CONFIG["quick_think_llm"], 8)
        self.deep_model_entry = self._entry("Deep Model", DEFAULT_CONFIG["deep_think_llm"], 9)
        self.backend_entry = self._entry("Backend URL", DEFAULT_BACKEND_URLS[DEFAULT_CONFIG["llm_provider"]] or "", 10)
        self.depth_menu = self._option("Research Depth", ["1", "3", "5"], "1", 11)

        self.checkpoint_var = tk.BooleanVar(value=False)
        self.checkpoint_checkbox = ctk.CTkCheckBox(
            self.sidebar_content,
            text="Enable checkpoint resume",
            variable=self.checkpoint_var,
        )
        self.checkpoint_checkbox.grid(row=13, column=0, padx=24, pady=(18, 8), sticky="w")

        self.api_key_entry = self._entry(
            self._api_key_label(DEFAULT_CONFIG["llm_provider"]),
            "",
            0,
            show="*",
            parent=self.sidebar_actions,
        )
        self.run_button = ctk.CTkButton(
            self.sidebar_actions,
            text="Start Analysis",
            height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_analysis,
        )
        self.run_button.grid(row=1, column=0, padx=24, pady=(8, 8), sticky="ew")

        self.open_report_button = ctk.CTkButton(
            self.sidebar_actions,
            text="Open Report Folder",
            fg_color="transparent",
            border_width=1,
            command=self._open_report_folder,
            state="disabled",
        )
        self.open_report_button.grid(row=2, column=0, padx=24, pady=(0, 0), sticky="ew")

    def _build_main_panel(self) -> None:
        header = ctk.CTkFrame(self.main, height=120)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        self.decision_label = ctk.CTkLabel(
            header,
            text="Ready",
            font=ctk.CTkFont(size=34, weight="bold"),
        )
        self.decision_label.grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")
        self.status_label = ctk.CTkLabel(
            header,
            text="Configure an analysis and click Start Analysis.",
            text_color=("gray35", "gray72"),
        )
        self.status_label.grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")
        self.progress = ctk.CTkProgressBar(header, width=180, mode="indeterminate")
        self.progress.grid(row=0, column=1, rowspan=2, padx=24, pady=24, sticky="e")
        self.progress.set(0)

        action_bar = ctk.CTkFrame(self.main, fg_color="transparent")
        action_bar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.copy_button = ctk.CTkButton(
            action_bar,
            text="Copy Final Decision",
            width=170,
            command=self._copy_final_decision,
            state="disabled",
        )
        self.copy_button.pack(side="right")

        content = ctk.CTkFrame(self.main)
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(content)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        for tab_name in ["Market", "Social", "News", "Fundamentals", "Research", "Trader", "Risk", "Final"]:
            tab = self.tabs.add(tab_name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            textbox = ctk.CTkTextbox(tab, wrap="word", font=ctk.CTkFont(size=14))
            textbox.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
            textbox.insert("1.0", "Results will appear here during analysis.")
            textbox.configure(state="disabled")
            self.tab_textboxes[tab_name] = textbox

        log_panel = ctk.CTkFrame(content)
        log_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        log_panel.grid_columnconfigure(0, weight=1)
        log_panel.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log_panel, text="Live Log", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, padx=14, pady=(14, 6), sticky="w"
        )
        self.log_text = ctk.CTkTextbox(log_panel, wrap="word", font=ctk.CTkFont(size=12), width=300)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.log_text.configure(state="disabled")

    def _entry(
        self,
        label: str,
        value: str,
        row: int,
        show: str | None = None,
        parent: ctk.CTkFrame | ctk.CTkScrollableFrame | None = None,
    ) -> ctk.CTkEntry:
        container = parent or self.sidebar_content
        frame = ctk.CTkFrame(container, fg_color="transparent")
        frame.grid(row=row, column=0, padx=24, pady=6, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        label_widget = ctk.CTkLabel(frame, text=label)
        label_widget.grid(row=0, column=0, sticky="w")
        entry = ctk.CTkEntry(frame, show=show)
        entry.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        entry.insert(0, value)
        entry._label_widget = label_widget
        return entry

    def _option(self, label: str, values: list[str], value: str, row: int) -> ctk.CTkOptionMenu:
        frame = ctk.CTkFrame(self.sidebar_content, fg_color="transparent")
        frame.grid(row=row, column=0, padx=24, pady=6, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=label).grid(row=0, column=0, sticky="w")
        option = ctk.CTkOptionMenu(frame, values=values)
        option.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        option.set(value)
        return option

    def _api_key_label(self, provider: str) -> str:
        env_var = PROVIDER_API_KEY_ENV.get(provider.lower())
        return f"API Key ({env_var})" if env_var else "API Key (not required)"

    def _on_provider_change(self, provider: str) -> None:
        provider = provider.lower()
        self.api_key_entry._label_widget.configure(text=self._api_key_label(provider))
        self._replace_entry_value(self.api_key_entry, "")
        self._replace_entry_value(self.backend_entry, DEFAULT_BACKEND_URLS.get(provider) or "")
        if provider in MODEL_OPTIONS:
            self._replace_entry_value(self.quick_model_entry, get_model_options(provider, "quick")[0][1])
            self._replace_entry_value(self.deep_model_entry, get_model_options(provider, "deep")[0][1])
        elif provider == "azure":
            self._replace_entry_value(self.quick_model_entry, "your-quick-deployment")
            self._replace_entry_value(self.deep_model_entry, "your-deep-deployment")
        elif provider == "openrouter":
            self._replace_entry_value(self.quick_model_entry, "anthropic/claude-sonnet-4.6")
            self._replace_entry_value(self.deep_model_entry, "anthropic/claude-opus-4.6")

    def _start_analysis(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            selection = self._selection_from_ui()
        except ValueError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            return

        self.report_path = None
        self.open_report_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self._clear_outputs()
        self.decision_label.configure(text="Running")
        self.status_label.configure(text="Starting analysis...")
        self.run_button.configure(state="disabled", text="Running...")
        self.progress.start()

        self.worker = threading.Thread(
            target=run_analysis,
            args=(selection, self.event_queue),
            daemon=True,
        )
        self.worker.start()

    def _selection_from_ui(self) -> DesktopSelection:
        ticker = self.ticker_entry.get().strip()
        analysis_date = self.date_entry.get().strip()
        analysts = [key for key, var in self.analyst_vars.items() if var.get()]
        if not ticker:
            raise ValueError("Ticker is required.")
        try:
            datetime.datetime.strptime(analysis_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Analysis date must use YYYY-MM-DD format.") from exc
        if not analysts:
            raise ValueError("Select at least one analyst.")
        api_key = self.api_key_entry.get().strip()
        required_key = PROVIDER_API_KEY_ENV.get(self.provider_menu.get().lower())
        if required_key and not api_key and not os.environ.get(required_key):
            raise ValueError(f"Please enter {required_key} in the API Key field.")
        return DesktopSelection(
            ticker=ticker,
            analysis_date=analysis_date,
            analysts=analysts,
            llm_provider=self.provider_menu.get(),
            quick_think_llm=self.quick_model_entry.get().strip(),
            deep_think_llm=self.deep_model_entry.get().strip(),
            research_depth=int(self.depth_menu.get()),
            output_language=self.language_menu.get(),
            backend_url=self.backend_entry.get().strip() or None,
            checkpoint_enabled=self.checkpoint_var.get(),
            api_key=api_key or None,
        )

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def _handle_event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "status":
            self.status_label.configure(text=event.get("text", ""))
            self._append_log(event.get("text", ""))
        elif event_type == "message":
            self._append_log(event.get("text", ""))
        elif event_type == "section":
            tab_name = SECTION_TABS.get(event.get("key"))
            if tab_name:
                self._set_tab_text(tab_name, event.get("content", ""))
        elif event_type == "decision":
            self.decision_label.configure(text=event.get("decision", "Decision"))
            self._set_tab_text("Final", event.get("content", ""))
            self.copy_button.configure(state="normal")
        elif event_type == "report":
            self.report_path = Path(event["path"])
            self.open_report_button.configure(state="normal")
        elif event_type == "error":
            self.progress.stop()
            self.progress.set(0)
            self.run_button.configure(state="normal", text="Start Analysis")
            self.decision_label.configure(text="Error")
            self.status_label.configure(text=event.get("text", "Analysis failed."))
            self._append_log(f"Error: {event.get('text', '')}")
        elif event_type == "done":
            self.progress.stop()
            self.progress.set(1)
            self.run_button.configure(state="normal", text="Start Analysis")
            self.status_label.configure(text=event.get("text", "Analysis complete."))
            self._append_log(event.get("text", "Analysis complete."))

    def _clear_outputs(self) -> None:
        for textbox in self.tab_textboxes.values():
            self._replace_textbox(textbox, "Waiting for analysis output...")
        self._replace_textbox(self.log_text, "")

    def _set_tab_text(self, tab_name: str, text: str) -> None:
        textbox = self.tab_textboxes[tab_name]
        self._replace_textbox(textbox, text or "No content yet.")

    def _append_log(self, text: str) -> None:
        if not text:
            return
        self.log_text.configure(state="normal")
        current = self.log_text.get("1.0", "end").strip()
        prefix = "\n\n" if current else ""
        self.log_text.insert("end", f"{prefix}{text[:1600]}")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _replace_textbox(self, textbox: ctk.CTkTextbox, text: str) -> None:
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", text)
        textbox.configure(state="disabled")

    def _replace_entry_value(self, entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    def _copy_final_decision(self) -> None:
        text = self.tab_textboxes["Final"].get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_label.configure(text="Final decision copied to clipboard.")

    def _open_report_folder(self) -> None:
        if not self.report_path:
            return
        folder = self.report_path.parent
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])


def main() -> None:
    app = TradingAgentsDesktop()
    app.mainloop()


if __name__ == "__main__":
    main()
