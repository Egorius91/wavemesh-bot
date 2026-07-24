"""
Модуль запросов к базе данных.

Единственная точка доступа к БД для всех хендлеров.
Прямой SQL в хендлерах запрещён — используйте функции из этого модуля.
"""

from database.connection import get_db
from database.db_users import *
from database.db_keys import *
from database.db_keys_shadow import *
from database.db_key_expiry import *
from database.db_payments import *
from database.db_servers import *
from database.db_tariffs import *
from database.db_stats import *
from database.db_groups import *
from database.db_settings import *
from database.db_pages import *
from database.db_backup import *
from database.db_subscriptions import *
from database.db_live_screens import *


def fail_order(order_id: str) -> bool:
    """Помечает pending order как failed без изменения уже оплаченных заказов."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE payments
            SET status = 'failed'
            WHERE order_id = ? AND status = 'pending'
            """,
            (order_id,),
        )
        return cursor.rowcount > 0
