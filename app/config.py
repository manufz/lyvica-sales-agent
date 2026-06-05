from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/lyvica"
    LYVICA_SCORING_URL: str = "http://localhost:8000"
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "Manuel <manuel@yourdomain.com>"
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
    # Qwen3.5-VL works out of the box on TrueFoundry. Claude Sonnet 4.5
    # (aws-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1-0) is a stronger
    # vision model but requires the Anthropic use-case form on the AWS account.
    VISION_MODEL: str = "nvidia-kimi-k2/qwen3.5-122b-a10b"
    # Pipeline defaults — override per request or leave as defaults
    PIPELINE_DEFAULT_CITY: str = "San Francisco"
    PIPELINE_DEFAULT_INDUSTRY: str = "dentist"
    PIPELINE_DEFAULT_LIMIT: int = 10
    PIPELINE_MIN_SCORE: float = 40.0

    class Config:
        env_file = ".env"
        extra = "ignore"  # tolerate stale/unrelated keys in .env


settings = Settings()
