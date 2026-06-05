from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/lyvica"
    LYVICA_SCORING_URL: str = "http://localhost:8000"
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "Manuel <manuel@yourdomain.com>"
    # AgentMail (preferred — agent inbox that can send + receive)
    AGENTMAIL_API_KEY: str = ""
    AGENTMAIL_BASE_URL: str = "https://api.agentmail.to/v0"
    AGENTMAIL_INBOX_ID: str = ""        # the sending inbox/address; auto-created if blank
    AGENTMAIL_USERNAME: str = ""        # optional, for a custom inbox username
    AGENTMAIL_DOMAIN: str = ""          # optional, for a custom domain
    AGENTMAIL_DISPLAY_NAME: str = "Manuel"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_STARTER_PRICE_ID: str = ""
    STRIPE_PRO_PRICE_ID: str = ""
    STRIPE_STARTER_LINK: str = ""
    STRIPE_PRO_LINK: str = ""
    HERMES_SHARED_SECRET: str = "change-this"
    APP_BASE_URL: str = "http://localhost:9000"
    GOOGLE_PLACES_API_KEY: str = ""
    TELEGRAM_CHAT_ID: str = ""  # group or personal chat ID for pipeline delivery
    # Scoring (merged in — no separate scoring service needed)
    PAGESPEED_API_KEY: str = ""
    GATEWAY_BASE_URL: str = "https://gateway.truefoundry.ai/v1"
    GATEWAY_API_KEY: str = ""
    # Qwen3-VL 235B — strong VL model, no Anthropic gating. Claude Sonnet 4.6
    # (aws-bedrock/us.anthropic.claude-sonnet-4-6) is higher quality but needs
    # the Anthropic use-case form submitted on the AWS account.
    VISION_MODEL: str = "aws-bedrock/qwen.qwen3-vl-235b-a22b"
    # Pipeline defaults — override per request or leave as defaults
    PIPELINE_DEFAULT_CITY: str = "San Francisco"
    PIPELINE_DEFAULT_INDUSTRY: str = "dentist"
    PIPELINE_DEFAULT_LIMIT: int = 10
    PIPELINE_MIN_SCORE: float = 40.0

    class Config:
        env_file = ".env"
        extra = "ignore"  # tolerate stale/unrelated keys in .env


settings = Settings()
