"""Testler her zaman Türkçe arayüzle başlar (mevcut testler Türkçe metinleri denetler); dil testleri kendi
ortamlarını ayarlar."""

import urllib.request

import pytest

from pbo_tuner import i18n


@pytest.fixture(autouse=True)
def _turkish_ui(monkeypatch):
    monkeypatch.setenv(i18n.ENV_VAR, "tr")
    i18n.set_language("tr")
    yield
    i18n.set_language("tr")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Testler gerçek internete çıkmamalı (ör. CoreCycler/PawnIO indirme adımları); gerekirse kendi sahte
    `urlopen`ını verirler."""
    def blocked(*args, **kwargs):
        raise RuntimeError("test gerçek ağa çıkmaya çalıştı")
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
