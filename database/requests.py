"""
Модуль запросов к базе данных.

Единственная точка доступа к БД для всех хендлеров.
Прямой SQL в хендлерах запрещён — используйте функции из этого модуля.
"""

import logging

from database.connection import get_db
from database.db_users import *
from database.db_keys import *
from database.db_payments import *
from database.db_servers import *
from database.db_tariffs import *
from database.db_subscriptions import *
from database.db_stats import *
from database.db_groups import *
from database.db_settings import *
from database.db_pages import *
from database.db_backup import *

logger = logging.getLogger(__name__)


def fail_order(order_id: str) -> bool:
    """Marks a pending payment order as failed."""
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE payments
            SET status = 'failed'
            WHERE order_id = ? AND status = 'pending'
        """, (order_id,))
        success = cursor.rowcount > 0
        if success:
            logger.info("Order %s marked as failed", order_id)
        return success
