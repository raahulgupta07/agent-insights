from .config import Settings

class Production(Settings):
    # Production runs with debug OFF by default (dev keeps DEBUG=True in development.py).
    # Overridable via the DEBUG env var if ever needed for a prod investigation.
    DEBUG: bool = False
    mock_preset_repo: bool = False
    mock_model_repo: bool = False

    # POSTGRES_PORT: int
    # POSTGRES_PASSWORD: str
    # POSTGRES_USER: str
    # POSTGRES_DB: str
    # POSTGRES_HOST: str

    class Config:
        env_prefix = ""
