"""capitalcom: client for the Capital.com REST API.

``CapitalCom`` is the 2.x API. ``CapitalClient`` is the 1.x API, kept working for existing code.
"""

# The 2.x names come from their own modules and none of them exists in the legacy module, so the
# star import keeps the 1.x surface exactly as it was. There is deliberately no __all__: 1.x
# code doing "from capitalcom import *" received every public legacy name, and still does.
from .api.client import CapitalCom
from .application.retry import RetryPolicy
from .client import *
from .domain.account import Account, AccountPreferences, Balance, Leverage, SessionInfo
from .domain.confirmation import DealConfirmation
from .domain.enums import Direction, Environment
from .domain.errors import (
    ApiError,
    AuthenticationError,
    CapitalComError,
    ConfirmationTimeoutError,
    DealRejectedError,
    NotFoundError,
    OutcomeUnknownError,
    RateLimitError,
    ResponseFormatError,
    TransportError,
    ValidationError,
)
from .domain.history import Activity, Transaction
