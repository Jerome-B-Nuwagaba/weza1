"""scripts/configure_env.py: writes only the untracked .env, never echoes values, skips blanks, refuses if not ignored."""

from pathlib import Path

from scripts import configure_env as ce

ROOT = Path(__file__).resolve().parents[1]
FAKE_SECRET = "FAKE_secret_value_for_test_only"
FAKE_ID = "000000000000000"


def _setup(tmp_path):
    (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _run(root, answers, ignored=True):
    out = []
    ask = lambda prompt: answers.get(prompt.strip().rstrip(":"), "")  # noqa: E731
    code = ce.run(root, ask=ask, ask_secret=ask, ignored=lambda p: ignored, out=out.append)
    return code, "\n".join(out)


def test_refuses_when_env_is_not_gitignored(tmp_path):
    root = _setup(tmp_path)
    code, out = _run(root, {"WHATSAPP_TOKEN": FAKE_SECRET}, ignored=False)
    assert code == 2 and not (root / ".env").exists() and FAKE_SECRET not in out


def test_creates_env_writes_only_given_values_and_never_prints_them(tmp_path):
    root = _setup(tmp_path)
    code, out = _run(root, {"WHATSAPP_TOKEN": FAKE_SECRET, "WHATSAPP_PHONE_NUMBER_ID": FAKE_ID})
    assert code == 0
    assert FAKE_SECRET not in out and FAKE_ID not in out
    env = ce.read_env(root / ".env")
    assert env["WHATSAPP_TOKEN"] == FAKE_SECRET and env["WHATSAPP_PHONE_NUMBER_ID"] == FAKE_ID
    assert env["WHATSAPP_APP_SECRET"] == "REPLACE_ME"  # blank answers leave the placeholder
    assert "SET:   WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID" in out
    assert "WHATSAPP_APP_SECRET" in out.split("UNSET:")[1]
    # the minimal .env must not carry the example's placeholder core secrets that would break the local vault
    assert "VAULT_MASTER_KEY" not in (root / ".env").read_text(encoding="utf-8")


def test_blank_keeps_existing_value_and_other_lines(tmp_path):
    root = _setup(tmp_path)
    (root / ".env").write_text("DATABASE_URL=keepme\nWHATSAPP_TOKEN=existing_fake\n", encoding="utf-8")
    code, out = _run(root, {"WHATSAPP_VERIFY_TOKEN": "fake verify"})
    text = (root / ".env").read_text(encoding="utf-8")
    assert "DATABASE_URL=keepme" in text and "WHATSAPP_TOKEN=existing_fake" in text
    assert 'WHATSAPP_VERIFY_TOKEN="fake verify"' in text  # quoted because it has a space
    assert "existing_fake" not in out and "fake verify" not in out
    assert "WHATSAPP_TOKEN" in out.split("UNSET:")[0]  # counted as set


def test_sms_provider_console_counts_as_unset():
    assert not ce.is_set("console", "SMS_PROVIDER") and ce.is_set("someprovider", "SMS_PROVIDER")
    assert not ce.is_set("REPLACE_ME") and not ce.is_set("") and ce.is_set("x")


def test_covers_every_whatsapp_and_sms_setting_in_the_example():
    names = [n for n, _ in ce.managed_settings(ROOT / ".env.example")]
    for expected in ("WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
                     "WHATSAPP_BUSINESS_NUMBER", "SMS_PROVIDER", "SMS_API_KEY"):
        assert expected in names


def test_real_env_path_is_gitignored():
    assert ce.git_ignores(ROOT / ".env")
