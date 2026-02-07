class GPAssistantError(Exception):
    """Base exception for gp_assistant."""


class DataProviderError(GPAssistantError):
    def __init__(self, message: str, *, symbol: str | None = None):
        if symbol:
            message = f"{message} [symbol={symbol}]"
        super().__init__(message)
        self.symbol = symbol


class MissingCredentialsError(GPAssistantError):
    def __init__(self, provider: str, hint: str | None = None):
        msg = f"官方数据源凭证未配置: provider={provider}"
        if hint:
            msg += f"; {hint}"
        super().__init__(msg)
        self.provider = provider


class ConfigError(GPAssistantError):
    pass

