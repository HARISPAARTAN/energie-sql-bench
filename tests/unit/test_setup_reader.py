import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load_tool():
    spec = importlib.util.spec_from_file_location("setup_reader", REPO / "tools" / "setup_reader.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_password_meets_policy() -> None:
    tool = load_tool()
    pw = tool.generate_password()
    assert len(pw) == 32
    assert any(c.islower() for c in pw) and any(c.isupper() for c in pw)
    assert any(c.isdigit() for c in pw) and any(c in tool.SYMBOLS for c in pw)


def test_env_with_bom_is_rewritten_without_bom(tmp_path: Path) -> None:
    tool = load_tool()
    env = tmp_path / ".env"
    env.write_bytes(b"\xef\xbb\xbfANTHROPIC_API_KEY=\nESB_DB_PASSWORD=\nOLLAMA_HOST=http://x:1\n")
    pw = tool.ensure_env_password(env)
    raw = env.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    assert text.splitlines()[0] == "ANTHROPIC_API_KEY="
    assert "OLLAMA_HOST=http://x:1" in text
    assert text.count("ESB_DB_PASSWORD=") == 1
    assert tool.ensure_env_password(env) == pw
