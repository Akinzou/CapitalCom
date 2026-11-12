"""capitalcom: client for the Capital.com REST API.

``CapitalCom`` is the 2.x API. ``CapitalClient`` is the 1.x API, kept working for existing code.
"""

# The star import brings the six names of capitalcom.client.__all__, the 1.x surface. There is
# deliberately no __all__ here: 1.x code doing "from capitalcom import *" received every public
# legacy name, and still does, next to the 2.x names. The 2.x names use "X as X", the explicit
# re-export a strict type checker needs to accept "from capitalcom import X".
from .api.client import (
    CapitalCom as CapitalCom,
)
from .api.stream import (
    Stream as Stream,
)
from .application.retry import (
    RetryPolicy as RetryPolicy,
)
from .client import *
from .domain.account import (
    Account as Account,
    AccountPreferences as AccountPreferences,
    Balance as Balance,
    Leverage as Leverage,
    SessionInfo as SessionInfo,
)
from .domain.confirmation import (
    DealConfirmation as DealConfirmation,
    SizeAdjustedError as SizeAdjustedError,
)
from .domain.enums import (
    Direction as Direction,
    Environment as Environment,
    OrderType as OrderType,
    Resolution as Resolution,
)
from .domain.errors import (
    ApiError as ApiError,
    AuthenticationError as AuthenticationError,
    CapitalComError as CapitalComError,
    ConfirmationTimeoutError as ConfirmationTimeoutError,
    DealRejectedError as DealRejectedError,
    NotFoundError as NotFoundError,
    OutcomeUnknownError as OutcomeUnknownError,
    RateLimitError as RateLimitError,
    ResponseFormatError as ResponseFormatError,
    StreamError as StreamError,
    SubscriptionError as SubscriptionError,
    TransportError as TransportError,
    ValidationError as ValidationError,
)
from .domain.history import (
    Activity as Activity,
    Transaction as Transaction,
)
from .domain.market_details import (
    DealingRules as DealingRules,
    Instrument as Instrument,
    MarketDetails as MarketDetails,
    MarketSnapshot as MarketSnapshot,
    PipScale as PipScale,
    RuleValue as RuleValue,
)
from .domain.markets import (
    Market as Market,
    MarketNode as MarketNode,
    NodeContents as NodeContents,
)
from .domain.order_request import (
    OrderRequest as OrderRequest,
    WorkingOrderRequest as WorkingOrderRequest,
)
from .domain.positions import (
    Position as Position,
)
from .domain.prices import (
    BidAsk as BidAsk,
    PriceBar as PriceBar,
)
from .domain.protection import (
    StopLoss as StopLoss,
    TakeProfit as TakeProfit,
)
from .domain.sentiment import (
    Sentiment as Sentiment,
)
from .domain.streaming import (
    Candle as Candle,
    CandleType as CandleType,
    Gap as Gap,
    GapReason as GapReason,
    PriceSide as PriceSide,
    Quote as Quote,
)
from .domain.watchlist import (
    Watchlist as Watchlist,
    WatchlistCreation as WatchlistCreation,
)
from .domain.working_orders import (
    WorkingOrder as WorkingOrder,
)
