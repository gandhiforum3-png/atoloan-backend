"""
Unit tests for app.services.bank_finder.get_term_options_for_offer — the
query used to build the "rates by term" table for the applicant summary
email. Uses a mocked AsyncConnection (no DB needed); live-DB scenarios are
covered separately under tests/integration/test_bank_finder.py.
"""
from unittest.mock import AsyncMock, MagicMock

import app.services.bank_finder as bank_finder_module
from app.services.bank_finder import find_best_bank, find_matching_banks, get_term_options_for_offer


def _mock_conn(rows: list[dict]) -> AsyncMock:
    conn = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [MagicMock(_mapping=row) for row in rows]
    conn.execute = AsyncMock(return_value=result)
    return conn


class TestGetTermOptionsForOffer:
    async def test_applies_rate_delta_uniformly_across_terms(self) -> None:
        conn = _mock_conn([
            {"term_in_months": 36, "rate": "5.25%", "rate_value": 5.25},
            {"term_in_months": 60, "rate": "5.75%", "rate_value": 5.75},
        ])

        options = await get_term_options_for_offer(
            conn,
            bank_id=1,
            program_name="New Auto",
            tier_name="Tier 1",
            credit_score=700,
            loan_amount=20000.0,
            rate_delta=-0.25,
        )

        assert options == [
            {"term_in_months": 36, "interest_rate": "5.25%", "rate_value": 5.25, "effective_rate": 5.0},
            {"term_in_months": 60, "interest_rate": "5.75%", "rate_value": 5.75, "effective_rate": 5.5},
        ]

    async def test_falls_back_to_parsing_rate_text_when_rate_value_missing(self) -> None:
        """Legacy rows ingested before rate_value existed."""
        conn = _mock_conn([{"term_in_months": 48, "rate": "6.00%", "rate_value": None}])

        options = await get_term_options_for_offer(
            conn, bank_id=1, program_name="New Auto", tier_name="Tier 1",
            credit_score=700, loan_amount=20000.0,
        )

        assert options == [
            {"term_in_months": 48, "interest_rate": "6.00%", "rate_value": 6.0, "effective_rate": 6.0}
        ]

    async def test_skips_rows_with_unparseable_rate(self) -> None:
        conn = _mock_conn([
            {"term_in_months": 36, "rate": "n/a", "rate_value": None},
            {"term_in_months": 48, "rate": "5.00%", "rate_value": 5.0},
        ])

        options = await get_term_options_for_offer(
            conn, bank_id=1, program_name="New Auto", tier_name="Tier 1",
            credit_score=700, loan_amount=20000.0,
        )

        assert len(options) == 1
        assert options[0]["term_in_months"] == 48

    async def test_query_filters_by_bank_program_tier_and_credit_score(self) -> None:
        conn = _mock_conn([])

        await get_term_options_for_offer(
            conn, bank_id=42, program_name="New Auto", tier_name="Tier 1",
            credit_score=700, loan_amount=20000.0,
        )

        params = conn.execute.call_args.args[1]
        assert params["bank_id"] == 42
        assert params["program_name"] == "New Auto"
        assert params["tier_name"] == "Tier 1"
        assert params["credit_score"] == 700
        assert params["loan_amount"] == 20000.0


class TestFindBestBankDealerNetworkFilter:
    """bank_ids restricts find_best_bank() to a dealer's mapped bank
    network — intersected with (not instead of) geographic eligibility."""

    def _stub_lookups(self, monkeypatch, eligible_banks: list[dict]):
        monkeypatch.setattr(
            bank_finder_module, "_get_county_from_zipcode", AsyncMock(return_value="Santa Clara")
        )
        monkeypatch.setattr(
            bank_finder_module, "_get_eligible_banks", AsyncMock(return_value=eligible_banks)
        )
        find_best_rate_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(bank_finder_module, "_find_best_rate", find_best_rate_mock)
        return find_best_rate_mock

    async def test_none_bank_ids_searches_every_eligible_bank(self, monkeypatch) -> None:
        banks = [{"bank_id": 1, "name": "A"}, {"bank_id": 2, "name": "B"}]
        find_best_rate_mock = self._stub_lookups(monkeypatch, banks)

        await find_best_bank(AsyncMock(), zipcode="94102", loan_amount=20000.0, credit_score=700, bank_ids=None)

        assert find_best_rate_mock.call_args.args[1] == banks

    async def test_bank_ids_restricts_to_dealer_network(self, monkeypatch) -> None:
        banks = [{"bank_id": 1, "name": "A"}, {"bank_id": 2, "name": "B"}, {"bank_id": 3, "name": "C"}]
        find_best_rate_mock = self._stub_lookups(monkeypatch, banks)

        await find_best_bank(AsyncMock(), zipcode="94102", loan_amount=20000.0, credit_score=700, bank_ids=[2, 3])

        passed_banks = find_best_rate_mock.call_args.args[1]
        assert {b["bank_id"] for b in passed_banks} == {2, 3}

    async def test_empty_dealer_network_returns_none_without_searching(self, monkeypatch) -> None:
        banks = [{"bank_id": 1, "name": "A"}]
        find_best_rate_mock = self._stub_lookups(monkeypatch, banks)

        result = await find_best_bank(
            AsyncMock(), zipcode="94102", loan_amount=20000.0, credit_score=700, bank_ids=[]
        )

        assert result is None
        find_best_rate_mock.assert_not_awaited()

    async def test_bank_ids_with_no_geographic_overlap_returns_none(self, monkeypatch) -> None:
        """Dealer's network exists but none of those banks are geographically
        eligible for this zipcode — must not fall through to searching
        every eligible bank instead."""
        banks = [{"bank_id": 1, "name": "A"}]
        find_best_rate_mock = self._stub_lookups(monkeypatch, banks)

        result = await find_best_bank(
            AsyncMock(), zipcode="94102", loan_amount=20000.0, credit_score=700, bank_ids=[999]
        )

        assert result is None
        find_best_rate_mock.assert_not_awaited()


class TestFindMatchingBanks:
    """find_matching_banks() shares find_best_bank()'s eligibility filtering
    but returns every eligible bank's own offer instead of just the single
    cheapest one."""

    def _stub_lookups(self, monkeypatch, eligible_banks: list[dict], offers: list[dict]):
        monkeypatch.setattr(
            bank_finder_module, "_get_county_from_zipcode", AsyncMock(return_value="Santa Clara")
        )
        monkeypatch.setattr(
            bank_finder_module, "_get_eligible_banks", AsyncMock(return_value=eligible_banks)
        )
        find_all_rates_mock = AsyncMock(return_value=offers)
        monkeypatch.setattr(bank_finder_module, "_find_all_rates", find_all_rates_mock)
        return find_all_rates_mock

    async def test_returns_offers_sorted_cheapest_first(self, monkeypatch) -> None:
        banks = [{"bank_id": 1, "name": "A"}, {"bank_id": 2, "name": "B"}]
        offers = [
            {"bank_id": 1, "bank_name": "A", "effective_rate": 6.5},
            {"bank_id": 2, "bank_name": "B", "effective_rate": 4.25},
        ]
        self._stub_lookups(monkeypatch, banks, offers)

        result = await find_matching_banks(
            AsyncMock(), zipcode="94102", loan_amount=20000.0, credit_score=700
        )

        assert [o["bank_id"] for o in result] == [2, 1]

    async def test_bank_ids_restricts_to_dealer_network(self, monkeypatch) -> None:
        banks = [{"bank_id": 1, "name": "A"}, {"bank_id": 2, "name": "B"}, {"bank_id": 3, "name": "C"}]
        find_all_rates_mock = self._stub_lookups(monkeypatch, banks, offers=[])

        await find_matching_banks(
            AsyncMock(), zipcode="94102", loan_amount=20000.0, credit_score=700, bank_ids=[2, 3]
        )

        passed_banks = find_all_rates_mock.call_args.args[1]
        assert {b["bank_id"] for b in passed_banks} == {2, 3}

    async def test_empty_dealer_network_returns_empty_list_without_searching(self, monkeypatch) -> None:
        banks = [{"bank_id": 1, "name": "A"}]
        find_all_rates_mock = self._stub_lookups(monkeypatch, banks, offers=[])

        result = await find_matching_banks(
            AsyncMock(), zipcode="94102", loan_amount=20000.0, credit_score=700, bank_ids=[]
        )

        assert result == []
        find_all_rates_mock.assert_not_awaited()

    async def test_no_eligible_banks_returns_empty_list(self, monkeypatch) -> None:
        find_all_rates_mock = self._stub_lookups(monkeypatch, [], offers=[])

        result = await find_matching_banks(
            AsyncMock(), zipcode="00000", loan_amount=20000.0, credit_score=700
        )

        assert result == []
        find_all_rates_mock.assert_not_awaited()
