"""capitalcom: client for the Capital.com REST API.

``CapitalCom`` is the 2.x API. ``CapitalClient`` is the 1.x API, kept working for existing code.
"""

# The star import brings the six names of capitalcom.client.__all__, the 1.x surface. There is
# deliberately no __all__ here: 1.x code doing "from capitalcom import *" received every public
# legacy name, and still does, next to the 2.x names.
from .api.client import CapitalCom
from .api.stream import Stream
from .application.retry import RetryPolicy
from .client import *
from .domain.account import Account, AccountPreferences, Balance, Leverage, SessionInfo
from .domain.confirmation import DealConfirmation, SizeAdjustedError
from .domain.enums import Direction, Environment, OrderType, Resolution
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
    StreamError,
    SubscriptionError,
    TransportError,
    ValidationError,
)
from .domain.history import Activity, Transaction
from .domain.market_details import (
    DealingRules,
    Instrument,
    MarketDetails,
    MarketSnapshot,
    PipScale,
    RuleValue,
)
from .domain.markets import Market, MarketNode, NodeContents
from .domain.order_request import OrderRequest, WorkingOrderRequest
from .domain.positions import Position
from .domain.prices import BidAsk, PriceBar
from .domain.protection import StopLoss, TakeProfit
from .domain.sentiment import Sentiment
from .domain.streaming import Candle, CandleType, Gap, GapReason, PriceSide, Quote
from .domain.watchlist import Watchlist, WatchlistCreation
from .domain.working_orders import WorkingOrder
