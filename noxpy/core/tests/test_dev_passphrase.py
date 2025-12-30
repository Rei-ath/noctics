from central.cli import validate_dev_passphrase, require_dev_passphrase
from central.cli import NOX_DEV_PASSPHRASE_ATTEMPT_ENV


def test_validate_dev_passphrase_behaviour():
    assert validate_dev_passphrase(None, attempt=None)
    assert validate_dev_passphrase("secret", attempt="secret")
    assert not validate_dev_passphrase("secret", attempt="wrong")
    assert not validate_dev_passphrase("secret", attempt=None)


def test_require_dev_passphrase_non_interactive(monkeypatch):
    monkeypatch.setenv(NOX_DEV_PASSPHRASE_ATTEMPT_ENV, "secret")
    assert require_dev_passphrase("secret", interactive=False)
    monkeypatch.setenv(NOX_DEV_PASSPHRASE_ATTEMPT_ENV, "wrong")
    assert not require_dev_passphrase("secret", interactive=False)
    monkeypatch.delenv(NOX_DEV_PASSPHRASE_ATTEMPT_ENV, raising=False)
