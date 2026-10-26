from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'postgresql://enigma:enigma_local_only@localhost:5433/enigma'
    data_dir: str = '/app/data'
    finance_source: str = 'fixture'
    # Provider selection and failover
    ai_provider: str = 'meterless'
    ai_fallback_order: str = 'meterless,nim,offline'

    # Meterless/Nightshift
    meterless_base_url: str = 'http://host.docker.internal:8088/v1'
    meterless_token: str = ''
    meterless_model: str = 'meterless/auto'
    meterless_timeout_seconds: int = 180

    # NVIDIA NIM hosted API
    nvidia_nim_base_url: str = 'https://integrate.api.nvidia.com/v1'
    nvidia_nim_api_key: str = ''
    nvidia_nim_model: str = ''
    nvidia_nim_timeout_seconds: int = 60

    # Offline fallback
    ai_offline_fallback: bool = True
    ai_max_retries_per_provider: int = 1

    # Zetaris federation
    zetaris_base_url: str = 'http://host.docker.internal:8888/api/v1.0'
    zetaris_auth_url: str = 'http://host.docker.internal:3000/api/auth/login'
    zetaris_api_key: str = ''
    zetaris_admin_email: str = 'admin@zetaris.com'
    zetaris_admin_password: str = ''
    zetaris_org_id: str = '1'
    zetaris_invoice_view: str = 'enigma_invoices'
    zetaris_payment_view: str = 'enigma_payments'
    zetaris_bank_view: str = 'enigma_bank_transactions'

    # SMTP Email Credentials & Infrastructure
    smtp_enabled: bool = False
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from_email: str = 'notifications@equilibra.ai'
    smtp_from_name: str = 'EQUILIBRA Property Operations'
    smtp_use_tls: bool = True

    # SMS Carrier & Field Technician Dispatch (Twilio)
    twilio_enabled: bool = False
    twilio_account_sid: str = ''
    twilio_auth_token: str = ''
    twilio_phone_number: str = ''

    # Payment Gateway & Bank Account Verification (Stripe / Plaid)
    stripe_secret_key: str = ''
    stripe_publishable_key: str = ''
    stripe_webhook_secret: str = ''
    plaid_client_id: str = ''
    plaid_secret: str = ''
    plaid_env: str = 'sandbox'

    # Document Intelligence & Optical Character Recognition (PaddleOCR)
    ocr_enabled: bool = True
    ocr_provider: str = 'paddleocr'
    ocr_lang: str = 'en'
    ocr_use_angle_cls: bool = True
    ocr_use_gpu: bool = False

    # Semantic RAG & Vector Embeddings Configuration
    embedding_provider: str = 'meterless' # meterless, auto, nvidia, offline
    embedding_model: str = 'meterless/auto'
    embedding_base_url: str = 'https://integrate.api.nvidia.com/v1'
    embedding_dimension: int = 384

    # Security, JWT Authentication & API Secrets
    secret_key: str = 'equilibra_dev_secret_key_change_in_production'
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 1440

    request_timeout_seconds: int = 30
    max_agent_rounds: int = 3

settings = Settings()
