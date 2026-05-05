from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "control-plane"
    app_env: str = "local"
    s3_endpoint: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "code-analyst-dev"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    sandbox_supervisor_url: str = "http://localhost:8090"
    sandbox_supervisor_timeout_seconds: float = 280.0
    workspace_tmp_dir: str = "/tmp/code-analyst/workspaces"
    s3_force_path_style: bool = True
    secret_store_provider: str = "s3"
    secret_store_s3_endpoint: str | None = None
    secret_store_s3_region: str | None = None
    secret_store_s3_bucket: str | None = None
    secret_store_s3_access_key_id: str | None = None
    secret_store_s3_secret_access_key: str | None = None
    secret_store_s3_force_path_style: bool | None = None
    secret_store_s3_prefix: str = "secret-store"
    auth_backend: str = "session_cookie"
    auth_store: str = "sqlite"
    auth_sqlite_path: str = "/tmp/code-analyst/auth/auth.db"
    auth_cookie_name: str = "ca_session"
    auth_cookie_secure: bool | None = None
    auth_session_ttl_seconds: int = 60 * 60 * 24 * 30
    auth_invite_ttl_seconds: int = 60 * 60 * 72
    auth_sign_in_link_ttl_seconds: int = 60 * 15
    auth_bootstrap_secret: str = "local-bootstrap-secret"
    app_public_url: str = "http://localhost:3000"

    @property
    def resolved_auth_cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.app_env.strip().lower() != "local"


settings = Settings()
