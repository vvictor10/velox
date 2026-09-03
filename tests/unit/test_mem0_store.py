from __future__ import annotations

from pathlib import Path

from velox.config import AppSettings
from velox.models.company import CompanyIdentity
from velox.models.report import EarningsBrief, PriorReportMemory, PriorReportStatus, ReportSection
from velox.models.telemetry import FailureCategory
from velox.models.tool_result import ToolStatus
from velox.providers.mem0_store import MAX_SAVED_COMPANIES, Mem0ReportStore


class FakeMemoryClient:
    def __init__(self, *, search_response=None, fail_search: bool = False) -> None:
        self.search_response = search_response or {"results": []}
        self.fail_search = fail_search
        self.add_calls = []
        self.update_calls = []
        self.get_calls = []

    def get(self, memory_id):
        self.get_calls.append(memory_id)
        return {
            "id": memory_id,
            "memory": "Verified saved report",
            "metadata": {"report_timestamp": "2026-09-01T12:00:00+00:00"},
        }

    def search(self, query, **kwargs):
        if self.fail_search:
            raise RuntimeError("Mem0 unavailable")
        return self.search_response

    def add(self, messages, **kwargs):
        self.add_calls.append((messages, kwargs))
        return {"id": "mem-new", "status": "created"}

    def update(self, memory_id, **kwargs):
        self.update_calls.append((memory_id, kwargs))
        return {"id": memory_id, "status": "updated"}


def test_lookup_prior_report_missing_when_mem0_has_no_match(tmp_path: Path) -> None:
    company = _company()
    store = Mem0ReportStore(
        AppSettings(mem0_api_key="test-key"),
        client=FakeMemoryClient(search_response={"results": []}),
        snapshot_dir=tmp_path,
    )

    memory, result = store.lookup_prior_report(company)

    assert memory.status == PriorReportStatus.MISSING
    assert result.status == ToolStatus.SUCCESS
    assert result.error is None
    assert result.source == "Mem0 not_found"


def test_lookup_prior_report_failure_is_lookup_failed_not_missing(tmp_path: Path) -> None:
    company = _company()
    store = Mem0ReportStore(
        AppSettings(mem0_api_key="test-key"),
        client=FakeMemoryClient(fail_search=True),
        snapshot_dir=tmp_path,
    )

    memory, result = store.lookup_prior_report(company)

    assert memory.status == PriorReportStatus.LOOKUP_FAILED
    assert result.status == ToolStatus.LOOKUP_FAILED
    assert result.failure_category == FailureCategory.DEGRADED_CONTINUABLE
    assert "continuing without claiming no prior report exists" in memory.warnings[0].message


def test_lookup_prior_report_uses_local_memory_id_first(tmp_path: Path) -> None:
    company = _company()
    (tmp_path / "AAPL.json").write_text(
        (
            "{"
            '"ticker":"AAPL",'
            '"cik":"320193",'
            '"status":"found",'
            '"memory_id":"mem-existing",'
            '"summary":"Existing local mirror"'
            "}"
        ),
        encoding="utf-8",
    )
    client = FakeMemoryClient(search_response={"results": []})
    store = Mem0ReportStore(AppSettings(mem0_api_key="test-key"), client=client, snapshot_dir=tmp_path)

    memory, result = store.lookup_prior_report(company)

    assert memory.status == PriorReportStatus.FOUND
    assert memory.memory_id == "mem-existing"
    assert result.source == "Mem0 get_by_memory_id"
    assert client.get_calls == ["mem-existing"]
    assert client.search_response == {"results": []}


def test_save_requires_approval(tmp_path: Path) -> None:
    store = Mem0ReportStore(AppSettings(mem0_api_key="test-key"), client=FakeMemoryClient(), snapshot_dir=tmp_path)

    result = store.save_approved_report(company=_company(), brief=_brief(), approved=False)

    assert result.tool_result.status == ToolStatus.SKIPPED
    assert result.tool_result.failure_category == FailureCategory.NON_RECOVERABLE
    assert list(tmp_path.glob("*.json")) == []


def test_approved_save_writes_one_snapshot_per_ticker(tmp_path: Path) -> None:
    client = FakeMemoryClient()
    store = Mem0ReportStore(AppSettings(mem0_api_key="test-key"), client=client, snapshot_dir=tmp_path)

    first = store.save_approved_report(company=_company(), brief=_brief("First"), approved=True)
    second = store.save_approved_report(company=_company(), brief=_brief("Second"), approved=True)

    assert first.saved_snapshot_path == second.saved_snapshot_path
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert first.memory.memory_id == "mem-new"
    assert "mem-new" in first.saved_snapshot_path.read_text(encoding="utf-8")
    assert client.add_calls and len(client.add_calls) == 2
    assert client.add_calls[0][1]["user_id"] == "velox-public-demo"
    assert client.add_calls[0][1]["agent_id"] == "velox"
    assert client.add_calls[0][1]["app_id"] == "velox"
    assert client.get_calls == ["mem-new", "mem-new"]
    assert second.memory.summary and "Second" in second.memory.summary
    assert "VELOX_APPROVED_BRIEF_SNAPSHOT_JSON:" in client.add_calls[0][0]


def test_approved_save_updates_existing_mem0_memory_when_id_is_known(tmp_path: Path) -> None:
    client = FakeMemoryClient()
    store = Mem0ReportStore(AppSettings(mem0_api_key="test-key"), client=client, snapshot_dir=tmp_path)

    result = store.save_approved_report(
        company=_company(),
        brief=_brief("Updated"),
        approved=True,
        existing_memory_id="mem-existing",
    )

    assert result.tool_result.status == ToolStatus.SUCCESS
    assert result.memory.memory_id == "mem-existing"
    assert client.add_calls == []
    assert len(client.update_calls) == 1
    assert client.update_calls[0][0] == "mem-existing"


def test_approved_save_retains_previous_approved_snapshot_history(tmp_path: Path) -> None:
    client = FakeMemoryClient()
    store = Mem0ReportStore(AppSettings(mem0_api_key="test-key"), client=client, snapshot_dir=tmp_path)
    previous = PriorReportMemory(
        ticker="AAPL",
        cik="320193",
        status=PriorReportStatus.FOUND,
        memory_id="mem-existing",
        summary="Prior summary",
        payload={
            "headline": "Prior report",
            "sections": [
                {
                    "title": "Prior Risks",
                    "body": "Prior risk body",
                    "citation_ids": ["E1"],
                }
            ],
            "warnings": [],
        },
    )

    result = store.save_approved_report(
        company=_company(),
        brief=_brief("Updated with missing live data warning"),
        approved=True,
        existing_memory_id="mem-existing",
        previous_memory=previous,
    )

    history = result.memory.payload["prior_approved_snapshots"]
    assert history[0]["headline"] == "Prior report"
    assert history[0]["sections"][0]["title"] == "Prior Risks"
    assert "prior_approved_snapshots" in result.saved_snapshot_path.read_text(encoding="utf-8")
    assert "Prior Risks" in client.update_calls[0][1]["options"].text


def test_approved_save_extracts_nested_mem0_memory_id(tmp_path: Path) -> None:
    client = FakeMemoryClient()
    client.add = lambda messages, **kwargs: {"results": [{"memory_id": "mem-nested"}]}
    store = Mem0ReportStore(AppSettings(mem0_api_key="test-key"), client=client, snapshot_dir=tmp_path)

    result = store.save_approved_report(company=_company(), brief=_brief(), approved=True)

    assert result.memory.memory_id == "mem-nested"
    assert "mem-nested" in result.saved_snapshot_path.read_text(encoding="utf-8")


def test_save_blocks_new_ticker_when_memory_cap_reached(tmp_path: Path) -> None:
    for index in range(MAX_SAVED_COMPANIES):
        ticker = f"T{index}"
        (tmp_path / f"{ticker}.json").write_text(
            _memory_json(ticker=ticker, cik=str(index)),
            encoding="utf-8",
        )
    store = Mem0ReportStore(AppSettings(mem0_api_key="test-key"), client=FakeMemoryClient(), snapshot_dir=tmp_path)

    result = store.save_approved_report(
        company=CompanyIdentity(ticker="NEW", company_name="New Co", cik="999"),
        brief=_brief(ticker="NEW", company_name="New Co"),
        approved=True,
    )

    assert result.tool_result.status == ToolStatus.SKIPPED
    assert "Memory limit reached" in (result.tool_result.error or "")


def test_lookup_prior_report_parses_mem0_result(tmp_path: Path) -> None:
    company = _company()
    memory_text = (
        'Earnings Setup: Prior brief summary\n\n'
        'VELOX_APPROVED_BRIEF_SNAPSHOT_JSON:\n'
        '{"headline":"Prior headline","sections":[{"title":"Earnings Setup","body":"Prior brief summary","citation_ids":["E1"]}]}'
    )
    store = Mem0ReportStore(
        AppSettings(mem0_api_key="test-key"),
        client=FakeMemoryClient(
            search_response={
                "results": [
                    {
                        "id": "mem-1",
                        "memory": memory_text,
                        "metadata": {"report_timestamp": "2026-09-01T12:00:00+00:00"},
                    }
                ]
            }
        ),
        snapshot_dir=tmp_path,
    )

    memory, _ = store.lookup_prior_report(company)

    assert memory.status == PriorReportStatus.FOUND
    assert memory.memory_id == "mem-1"
    assert memory.summary == memory_text
    assert memory.payload["approved_brief_snapshot"]["headline"] == "Prior headline"


def _company() -> CompanyIdentity:
    return CompanyIdentity(ticker="AAPL", company_name="Apple Inc.", exchange="Nasdaq", cik="320193")


def _brief(body: str = "Brief body", *, ticker: str = "AAPL", company_name: str = "Apple Inc.") -> EarningsBrief:
    return EarningsBrief(
        ticker=ticker,
        company_name=company_name,
        sections=[ReportSection(title="Earnings Setup", body=body, citation_ids=["E1"])],
    )


def _memory_json(*, ticker: str, cik: str) -> str:
    return (
        "{"
        f'"ticker":"{ticker}",'
        f'"cik":"{cik}",'
        '"status":"found",'
        '"summary":"Existing report"'
        "}"
    )
