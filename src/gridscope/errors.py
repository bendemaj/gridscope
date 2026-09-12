"""Stable, safe errors. Never include provider URLs, tokens or XML bodies."""


class GridScopeError(Exception):
    code = "gridscope_error"
    status_code = 500


class InvalidQuery(GridScopeError):
    code = "invalid_query"
    status_code = 422


class MissingToken(GridScopeError):
    code = "missing_api_token"
    status_code = 503


class ProviderAuthenticationError(GridScopeError):
    code = "provider_authentication_failed"
    status_code = 502


class ProviderRateLimit(GridScopeError):
    code = "provider_rate_limited"
    status_code = 503


class ProviderUnavailable(GridScopeError):
    code = "provider_unavailable"
    status_code = 502


class NoData(GridScopeError):
    code = "no_data"
    status_code = 404


class MalformedResponse(GridScopeError):
    code = "malformed_provider_response"
    status_code = 502


class ProviderRejected(GridScopeError):
    code = "provider_rejected_request"
    status_code = 502
