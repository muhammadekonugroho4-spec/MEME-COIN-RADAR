"""Test filter on-chain Fase 4 (murni) + adapter RPC authority fields."""
import pytest

from backend.core.onchain_filter import onchain_reasons, top10_pct_from_accounts


def test_mint_authority_active_rejected():
    r = onchain_reasons(mint_authority="AbCdEf12", freeze_authority=None, top10_pct=None)
    assert any("mint authority" in x for x in r)


def test_freeze_authority_active_rejected():
    r = onchain_reasons(mint_authority=None, freeze_authority="XyZ", top10_pct=None)
    assert any("freeze" in x for x in r)


def test_both_revoked_passes():
    assert onchain_reasons(None, None, 12.0) == []


def test_whale_concentration_rejected():
    r = onchain_reasons(None, None, 55.0)
    assert any("top-10 holder" in x for x in r)


def test_unknown_data_not_rejected():
    # data None = tidak bisa dinilai -> bukan alasan reject (jangan bunyi kandidat karena RPC mati)
    assert onchain_reasons(None, None, None) == []


def test_top10_pct_math():
    largest = [{"uiAmount": 100.0}] * 10 + [{"uiAmount": 999999.0}]  # ke-11 diabaikan
    assert top10_pct_from_accounts(largest, total_supply=1000.0) == pytest.approx(100.0)
    assert top10_pct_from_accounts([], 1000.0) == 0.0
    assert top10_pct_from_accounts(largest, None) is None
