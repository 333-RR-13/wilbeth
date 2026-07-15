from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./wilbeth.db"
    app_env: str = "development"

    auth_mode: str = "dev"
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_discovery_url: str = ""
    oidc_redirect_uri: str = ""
    oidc_group_admin: str = ""
    oidc_group_ausbilder: str = ""
    oidc_group_orga: str = ""
    session_secret: str = "dev-insecure-session-key"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
