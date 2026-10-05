from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ConfigError(RuntimeError):
    """Configuração inválida: a aplicação não deve subir."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: SecretStr = Field(min_length=1)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_models: Annotated[list[str], NoDecode] = Field(
        default=["nvidia/nemotron-3.5-lightning:free", "google/gemma-4-26b-a4b-it:free", "openrouter/free"],
        min_length=1,
    )
    db_path: Path = Path("data/cinerocket.db")
    sql_timeout_s: float = Field(default=10, gt=0)
    sql_max_rows: int = Field(default=200, gt=0)
    agent_request_limit: int = Field(default=4, ge=1)
    cache_path: Path = Path(".cache/answers.db")
    cache_ttl_s: int = Field(default=86400, ge=0)
    log_level: str = "INFO"

    @field_validator("llm_models", mode="before")
    @classmethod
    def _split_models(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("db_path")
    @classmethod
    def _db_must_exist(cls, value: Path) -> Path:
        if not value.is_file():
            raise ValueError(
                f"arquivo do banco não encontrado em '{value}'. "
                "Baixe o cinerocket.db para data/cinerocket.db ou ajuste DB_PATH."
            )
        return value


def load_settings(**overrides: object) -> Settings:
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            field = ".".join(str(part) for part in err["loc"]).upper()
            if field == "OPENROUTER_API_KEY":
                problems.append("OPENROUTER_API_KEY ausente: copie .env.example para .env e preencha a chave.")
            else:
                problems.append(f"{field}: {err['msg']}")
        raise ConfigError("Configuração inválida:\n- " + "\n- ".join(problems)) from None
