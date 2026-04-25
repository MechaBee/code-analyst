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
    workspace_tmp_dir: str = "/tmp/code-analyst/workspaces"
    s3_force_path_style: bool = True


settings = Settings()
