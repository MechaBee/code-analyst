from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "sandbox-supervisor"
    app_env: str = "local"
    analysis_backend: str = "claude"
    analysis_fallback_to_deterministic: bool = False
    analysis_max_search_results: int = 8
    analysis_max_read_lines: int = 120
    analysis_max_list_files: int = 200
    openai_model: str = "gpt-5.4-mini"
    openai_reasoning_effort: str = "low"
    claude_model: str = "claude-sonnet-4-20250514"
    anthropic_api_key: str | None = None
    s3_endpoint: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "code-analyst-dev"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    sandbox_runtime_image: str = "code-analyst/sandbox-worker:dev"
    docker_socket_path: str = "/var/run/docker.sock"
    workspace_root_dir: str = "/tmp/code-analyst/sandboxes"
    s3_force_path_style: bool = True


settings = Settings()
