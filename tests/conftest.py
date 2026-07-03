"""
Konfigurace pytest a pomocné fixtures pro testy Warehouse Control Tower.
"""
import sys
from pathlib import Path

# Přidáme root projektu do PYTHONPATH aby importy fungovaly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# Streamlit stub pro testy bez běžícího Streamlit serveru
class StubSessionState(dict):
    """Náhražka st.session_state pro testy."""
    def __getattr__(self, key):
        if key in self:
            return self[key]
        return None

    def __setattr__(self, key, value):
        self[key] = value


class StubStreamlit:
    """Minimální stub pro streamlit import."""
    def __init__(self):
        self.session_state = StubSessionState()

    def __getattr__(self, name):
        # Catch-all pro metody které nepoužíváme v testech
        return lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def stub_streamlit(monkeypatch):
    """Automaticky nahradí streamlit stubem ve všech testech."""
    import modules.utils as utils_module

    fake_st = StubStreamlit()
    monkeypatch.setattr(utils_module, "st", fake_st)
    return fake_st