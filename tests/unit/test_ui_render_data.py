from __future__ import annotations

from datetime import UTC, date, datetime

from velox.models.company import CompanyIdentity
from velox.models.earnings import EarningsEvent, EarningsSnapshot, HistoricalEarningsQuarter
from velox.models.evidence import EvidencePack, EvidenceRecord, EvidenceType
from velox.models.failures import FallbackRecord, RetryRecord
from velox.models.state import RunState, RunStatus
from velox.models.telemetry import FailureCategory, RunTelemetry, SpanKind, TelemetrySpan
from velox.ui import render_data


def test_format_date_uses_readable_ordinal_format() -> None:
    assert render_data.format_date(date(2026, 3, 30)) == "30th March 2026"
    assert render_data.format_date(datetime(2026, 9, 1, 8, 24, 43, tzinfo=UTC)) == "1st September 2026"
    assert render_data.format_short_date(date(2026, 10, 27)) == "27th October"


def test_format_money_millions_uses_dollars_and_m_suffix() -> None:
    assert render_data.format_money(115_060_000_000) == "$115.1B"
    assert render_data.format_money(206_371_200) == "$206.4M"
    assert render_data.format_money(-1_250_000) == "-$1.2M"
    assert render_data.format_eps(2.543) == "$2.54"
    assert render_data.format_eps(-0.071) == "-$0.07"


def test_display_company_name_removes_sec_jurisdiction_suffix() -> None:
    assert render_data.display_company_name("APPLIED MATERIALS INC /DE") == "Applied Materials Inc."
    assert render_data.display_company_name("NVIDIA CORP") == "Nvidia Corp."


def test_ticker_options_use_ticker_aware_display_name() -> None:
    companies = [
        CompanyIdentity(ticker="AMZN", company_name="AMAZON COM INC", exchange="Nasdaq", cik="1018724"),
        CompanyIdentity(ticker="NVDA", company_name="NVIDIA CORP", exchange="Nasdaq", cik="1045810"),
    ]

    assert render_data.ticker_options(companies) == ["AMZN | Amazon.com, Inc.", "NVDA | NVIDIA Corp."]


def test_latest_earnings_summary_uses_most_recent_history() -> None:
    state = RunState(
        earnings=EarningsSnapshot(
            ticker="AMZN",
            history=[
                HistoricalEarningsQuarter(
                    period=date(2026, 3, 31),
                    eps_actual=1.25,
                    eps_estimate=1.10,
                    surprise_percent=13.6,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2026, 6, 30),
                    eps_actual=1.68,
                    eps_estimate=1.32,
                    surprise_percent=27.3,
                    source_provider="fixture",
                ),
            ],
        )
    )

    assert render_data.latest_earnings_summary(state) == {
        "Period": "30th June",
        "EPS Actual": "$1.68",
        "EPS Estimate": "$1.32",
        "EPS Surprise %": "27.30%",
    }


def test_summary_metric_items_do_not_show_missing_next_report_card() -> None:
    state = RunState(
        earnings=EarningsSnapshot(
            ticker="AMZN",
            history=[
                HistoricalEarningsQuarter(
                    period=date(2026, 6, 30),
                    eps_actual=1.68,
                    surprise_percent=27.3,
                    source_provider="fixture",
                ),
            ],
        )
    )

    items = render_data.summary_metric_items(state)

    assert ("Next Report", "n/a", None) not in items
    assert items[:3] == [
        ("Latest Quarter", "30th June", None),
        ("Latest EPS Actual", "$1.68", None),
        ("EPS Surprise", "27.30%", None),
    ]


def test_summary_metric_items_prefer_forward_earnings_values() -> None:
    state = RunState(
        earnings=EarningsSnapshot(
            ticker="AMZN",
            next_event=EarningsEvent(
                report_date=date(2026, 10, 30),
                eps_estimate=1.42,
                revenue_estimate=100_000_000_000,
                source_provider="fixture",
            ),
            history=[
                HistoricalEarningsQuarter(
                    period=date(2026, 6, 30),
                    eps_actual=1.68,
                    surprise_percent=27.3,
                    source_provider="fixture",
                ),
            ],
        )
    )

    items = render_data.summary_metric_items(state)

    assert items[:3] == [
        ("Next Report", "30th October", None),
        ("EPS Estimate", "$1.42", None),
        ("Revenue Estimate", "$100.0B", None),
    ]


def test_earnings_rows_and_charts_use_latest_four_quarters() -> None:
    state = RunState(
        earnings=EarningsSnapshot(
            ticker="META",
            history=[
                HistoricalEarningsQuarter(
                    period=date(2025, 9, 30),
                    eps_actual=7.25,
                    eps_estimate=6.70,
                    surprise_percent=8.05,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2025, 12, 31),
                    eps_actual=8.90,
                    eps_estimate=8.25,
                    surprise_percent=8.03,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2026, 3, 31),
                    eps_actual=7.30,
                    eps_estimate=6.80,
                    surprise_percent=7.18,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2026, 6, 30),
                    eps_actual=6.20,
                    eps_estimate=7.30,
                    surprise_percent=-12.96,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2024, 9, 30),
                    eps_actual=6.00,
                    eps_estimate=5.30,
                    surprise_percent=13.77,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2024, 12, 31),
                    eps_actual=8.00,
                    eps_estimate=6.65,
                    surprise_percent=20.06,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2025, 3, 31),
                    eps_actual=6.40,
                    eps_estimate=5.20,
                    surprise_percent=23.42,
                    source_provider="fixture",
                ),
                HistoricalEarningsQuarter(
                    period=date(2025, 6, 30),
                    eps_actual=7.10,
                    eps_estimate=5.85,
                    surprise_percent=21.84,
                    source_provider="fixture",
                ),
            ],
        )
    )

    table_rows = render_data.earnings_history_rows(state)
    chart_rows = render_data.earnings_surprise_chart_rows(state)

    assert [row["Period"] for row in table_rows] == [
        "30th June 2026",
        "31st March 2026",
        "31st December 2025",
        "30th September 2025",
    ]
    assert [row["Period"] for row in chart_rows] == [
        "30th September 2025",
        "31st December 2025",
        "31st March 2026",
        "30th June 2026",
    ]


def test_source_rows_drop_blank_source_date_column() -> None:
    state = RunState(
        evidence_pack=EvidencePack(
            records=[
                EvidenceRecord(
                    evidence_id="E1",
                    evidence_type=EvidenceType.EARNINGS,
                    provider="fixture",
                    title="Earnings calendar",
                )
            ]
        )
    )

    rows = render_data.source_rows(state)

    assert "Source Date" not in rows[0]
    assert rows[0]["Captured"]


def test_telemetry_rows_use_seconds() -> None:
    state = RunState(
        telemetry=RunTelemetry(
            run_id="run-1",
            spans=[
                TelemetrySpan(name="llm.brief_drafter", kind=SpanKind.LLM).model_copy(
                    update={"duration_ms": 8118}
                )
            ],
        )
    )

    rows = render_data.telemetry_rows(state)

    assert rows[0]["Duration"] == "8.12s"


def test_telemetry_summary_separates_tool_and_llm_recovery_counts() -> None:
    state = RunState(
        retry_records=[
            RetryRecord(
                tool_name="alpha_vantage.news_sentiment",
                attempt_count=1,
                reason="Alpha Vantage news was unavailable.",
                failure_category=FailureCategory.RECOVERABLE,
                user_message="Retrying Alpha Vantage news fetch.",
            )
        ],
        fallback_records=[
            FallbackRecord(
                primary_tool_name="alpha_vantage.news_sentiment",
                fallback_tool_name="finnhub.company_news",
                reason="Alpha Vantage news was unavailable.",
                user_message="Alpha Vantage news was unavailable; using Finnhub company news.",
            )
        ],
        telemetry=RunTelemetry(
            run_id="run-1",
            spans=[
                TelemetrySpan(name="llm.risk", kind=SpanKind.LLM).model_copy(
                    update={"retry_count": 1}
                )
            ],
        ).finish(final_status="waiting_for_approval"),
    )

    rows = render_data.telemetry_summary_rows(state)

    assert rows[0]["Tool Retries"] == 1
    assert rows[0]["Tool Fallbacks"] == 1
    assert rows[0]["LLM Retries"] == 1


def test_recovery_event_rows_show_retry_and_fallback_records() -> None:
    state = RunState(
        retry_records=[
            RetryRecord(
                tool_name="alpha_vantage.news_sentiment",
                attempt_count=1,
                reason="Alpha Vantage news was unavailable.",
                failure_category=FailureCategory.RECOVERABLE,
                user_message="Retrying Alpha Vantage news fetch.",
            )
        ],
        fallback_records=[
            FallbackRecord(
                primary_tool_name="alpha_vantage.news_sentiment",
                fallback_tool_name="finnhub.company_news",
                reason="Alpha Vantage news was unavailable.",
                user_message="Alpha Vantage news was unavailable; using Finnhub company news.",
            )
        ],
    )

    rows = render_data.recovery_event_rows(state)

    assert [row["Event"] for row in rows] == ["Retry", "Fallback"]
    assert rows[0]["Primary Tool"] == "alpha_vantage.news_sentiment"
    assert rows[1]["Fallback Tool"] == "finnhub.company_news"
    assert rows[1]["Message"] == "Alpha Vantage news was unavailable; using Finnhub company news."


def test_news_theme_rows_use_readable_headers() -> None:
    state = RunState(
        news_themes=[
            {
                "theme": "Competitive pressure",
                "summary": "Cloud and AI competition is present.",
                "supporting_evidence_ids": ["E5"],
                "confidence": 0.4,
            }
        ]
    )

    rows = render_data.news_theme_rows(state)

    assert "Supporting Evidence IDs" in rows[0]
    assert "supporting_evidence_ids" not in rows[0]
    assert rows[0]["Confidence"] == "0.40"


def test_prior_memory_rows_hide_missing_empty_memory() -> None:
    from velox.models.report import PriorReportMemory, PriorReportStatus

    state = RunState(
        prior_memory=PriorReportMemory(
            ticker="GOOG",
            cik="1652044",
            status=PriorReportStatus.MISSING,
        )
    )

    assert render_data.prior_memory_rows(state) == []


def test_eval_checklist_rows_expose_system_eval_results() -> None:
    state = RunState(
        status=RunStatus.STOPPED,
        telemetry=RunTelemetry(run_id="run-1"),
    )

    rows = render_data.eval_checklist_rows(state)

    assert rows
    assert rows[0]["Check"] == "Final Status Known"
    assert "Result" in rows[0]
    assert "Gate Score" in rows[0]
