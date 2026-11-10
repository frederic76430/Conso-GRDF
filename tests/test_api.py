"""Enveloppe pygazpar : connexion, lecture, traduction des erreurs, déconnexion."""

from datetime import date
from unittest.mock import MagicMock, patch

import pygazpar
import pytest

from custom_components.conso_grdf.api import ApiError, AuthError, GrdfClient, async_pces


def fausse_source(**kw):
    source = MagicMock()
    source.load.return_value = {pygazpar.Frequency.DAILY: [{"time_period": "09/11/2026", "volume_m3": 1.0}]}
    source.get_pce_identifiers.return_value = ["123"]
    for k, v in kw.items():
        setattr(source, k, v)
    return source


async def test_lecture_et_deconnexion(hass):
    source = fausse_source()
    with patch("pygazpar.JsonWebDataSource", return_value=source) as classe:
        client = GrdfClient(hass, "a@b.fr", "x", "123", "published")
        releves = await client.async_lire(date(2026, 11, 1), date(2026, 11, 10))
    assert releves == [{"time_period": "09/11/2026", "volume_m3": 1.0}]
    assert classe.call_args.kwargs["consumption_type"] is pygazpar.ConsumptionType.PUBLISHED
    source.load.assert_called_once_with("123", date(2026, 11, 1), date(2026, 11, 10), [pygazpar.Frequency.DAILY])
    source.logout.assert_called_once()


@pytest.mark.parametrize(
    ("erreur", "attendue"),
    [(pygazpar.LoginError("non", 401), AuthError), (pygazpar.RateLimitError("429"), ApiError), (OSError("réseau"), ApiError)],
)
async def test_erreurs(hass, erreur, attendue):
    source = fausse_source()
    source.login.side_effect = erreur
    with patch("pygazpar.JsonWebDataSource", return_value=source):
        with pytest.raises(attendue):
            await GrdfClient(hass, "a", "b", "1", "informative").async_lire(date(2026, 1, 1), date(2026, 1, 2))
        with pytest.raises(attendue):
            await async_pces(hass, "a", "b")
    assert source.logout.called
