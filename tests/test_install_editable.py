"""Guard test: electric_blue must be imported from this checkout's src/, not site-packages.

This test is NOT marked @pytest.mark.smoke, so it runs under `pytest -m "not smoke"` and
`make gate`. It fails loud if the venv holds a non-editable (stale copy) install, which
would silently invalidate gate-attested invariants INV-3/4/8 by verifying the wrong code.
"""

import pathlib

import electric_blue


def test_editable_install() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    expected_src = repo_root / "src"
    pkg = pathlib.Path(electric_blue.__file__).resolve()

    assert pkg.is_relative_to(expected_src), (
        f"electric_blue imported from {pkg}, not {expected_src} — "
        "the venv is not an editable install of this checkout; run `make dev`. "
        "Gate-attested invariants (INV-3/4/8) would otherwise verify a stale copy, not this code."
    )
