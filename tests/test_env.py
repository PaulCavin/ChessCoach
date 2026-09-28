from chesscoach.env import load_dotenv


def test_dotenv_adds_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# commentaire\nDEEPSEEK_API_KEY="sk-test"\nCHESSCOACH_LLM_MODEL=deepseek-chat\nDEJA=fichier\n')
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("CHESSCOACH_LLM_MODEL", raising=False)
    monkeypatch.setenv("DEJA", "environnement")
    added = load_dotenv(env)
    assert added == {"DEEPSEEK_API_KEY": "sk-test", "CHESSCOACH_LLM_MODEL": "deepseek-chat"}
    import os

    assert os.environ["DEJA"] == "environnement"  # l'environnement garde la priorité


def test_dotenv_missing_file_is_noop(tmp_path):
    assert load_dotenv(tmp_path / "absent.env") == {}
