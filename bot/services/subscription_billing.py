"""Background processing for YooKassa recurring subscriptions."""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from aiogram import Bot

from database.requests import (
    create_pending_order,
    fail_order,
    finalize_recurring_payment,
    get_due_subscriptions,
    get_open_recurring_order,
    get_tariff_by_id,
    mark_subscription_transient_error,
    record_subscription_payment_failure,
    reschedule_subscription_check,
    save_order_subscription_context,
    save_yookassa_payment_id,
    set_vpn_key_expiry,
    update_vpn_key_tariff_and_traffic_limit,
)
from bot.services.yookassa_recurring import (
    YooKassaAPIError,
    create_yookassa_recurring_payment,
    get_yookassa_payment,
)

logger = logging.getLogger(__name__)

SCHEDULER_INTERVAL_SECONDS = 300
PENDING_POLL_SECONDS = 300
_subscription_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _payment_method_from_payment(payment: Dict[str, Any]) -> str:
    method = payment.get('payment_method') or {}
    if isinstance(method, dict):
        return method.get('id') or ''
    return ''


def _payment_failure_reason(payment: Dict[str, Any]) -> str:
    cancellation = payment.get('cancellation_details') or {}
    if isinstance(cancellation, dict):
        return str(cancellation.get('reason') or cancellation.get('party') or 'payment_canceled')
    return 'payment_canceled'


def _is_future(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


async def _sync_key_state(key_id: Optional[int], *, reset_traffic: bool = False) -> bool:
    if not key_id:
        return True
    from bot.services.vpn_api import sync_key_to_panel_state

    try:
        result = await sync_key_to_panel_state(int(key_id), reset_traffic=reset_traffic)
        errors = int(result.get('errors', 0) or 0)
        if errors:
            logger.warning('Ключ %s синхронизирован с ошибками: %s', key_id, result)
            return False
        return True
    except Exception as exc:
        logger.warning('Не удалось синхронизировать ключ %s с панелью: %s', key_id, exc)
        return False


async def _apply_failure_access(
    subscription: Dict[str, Any],
    failure: Dict[str, Any],
) -> None:
    """Extends access only to grace end, or removes grace after final failure."""
    key_id = subscription.get('vpn_key_id')
    if not key_id:
        return

    target_expiry = failure['period_end_at']
    if not failure.get('final') and _is_future(failure.get('grace_until')):
        target_expiry = failure['grace_until']

    if set_vpn_key_expiry(int(key_id), target_expiry):
        await _sync_key_state(int(key_id), reset_traffic=False)


async def _ensure_grace_access(subscription: Dict[str, Any]) -> None:
    key_id = subscription.get('vpn_key_id')
    grace_until = subscription.get('grace_until')
    if not key_id or not _is_future(grace_until):
        return
    if set_vpn_key_expiry(int(key_id), grace_until):
        await _sync_key_state(int(key_id), reset_traffic=False)


async def _finalize_success(
    subscription: Dict[str, Any],
    order_id: str,
    payment: Dict[str, Any],
    bot: Bot,
) -> Dict[str, Any]:
    sub_id = int(subscription['id'])
    payment_id = str(payment.get('id') or '')
    payment_method_id = _payment_method_from_payment(payment) or str(
        subscription.get('payment_method_id') or ''
    )
    result = finalize_recurring_payment(
        order_id,
        sub_id,
        payment_id=payment_id,
        payment_method_id=payment_method_id,
    )
    if not result:
        logger.error(
            'Подписка %s: платёж %s успешен, но атомарная финализация не выполнена',
            sub_id,
            payment_id,
        )
        mark_subscription_transient_error(sub_id, 'local_finalize_failed')
        return {'status': 'deferred', 'subscription_id': sub_id}

    if result.get('processed_now'):
        key_id = result.get('vpn_key_id')
        if key_id:
            tariff = get_tariff_by_id(int(result.get('tariff_id') or subscription['tariff_id']))
            traffic_limit = int((tariff.get('traffic_limit_gb', 0) or 0) * (1024 ** 3)) if tariff else 0
            update_vpn_key_tariff_and_traffic_limit(
                int(key_id),
                int(result.get('tariff_id') or subscription['tariff_id']),
                traffic_limit,
            )
            await _sync_key_state(int(key_id), reset_traffic=True)
        await _notify_payment_success(subscription, bot)
        logger.info(
            'Подписка %s успешно продлена до %s, order=%s',
            sub_id,
            result.get('period_end_at'),
            order_id,
        )

    return {'status': 'succeeded', 'subscription_id': sub_id, **result}


async def _record_definitive_failure(
    subscription: Dict[str, Any],
    order_id: str,
    bot: Bot,
    *,
    payment_id: str = '',
    reason: str,
) -> Dict[str, Any]:
    sub_id = int(subscription['id'])
    fail_order(order_id)
    failure = record_subscription_payment_failure(
        sub_id,
        payment_id=payment_id,
        reason=reason,
    )
    if not failure:
        logger.error('Подписка %s: не удалось сохранить отказ платежа', sub_id)
        return {'status': 'error', 'subscription_id': sub_id}

    await _apply_failure_access(subscription, failure)
    attempts = int(failure.get('failed_attempts') or 0)
    if attempts == 1 or failure.get('final'):
        await _notify_payment_failed(subscription, bot, failure=failure)

    if failure.get('final'):
        logger.error(
            'Подписка %s окончательно остановлена после %s неудачных списаний',
            sub_id,
            attempts,
        )
    else:
        logger.warning(
            'Подписка %s: списание не удалось (попытка %s), следующая проверка %s',
            sub_id,
            attempts,
            failure.get('next_charge_at'),
        )
    return {'status': 'failed', 'subscription_id': sub_id, **failure}


async def _handle_payment(
    subscription: Dict[str, Any],
    order_id: str,
    payment: Dict[str, Any],
    bot: Bot,
) -> Dict[str, Any]:
    sub_id = int(subscription['id'])
    payment_id = str(payment.get('id') or '')
    if payment_id:
        save_yookassa_payment_id(order_id, payment_id)
    save_order_subscription_context(
        order_id,
        subscription_id=sub_id,
        payment_method_id=_payment_method_from_payment(payment)
        or str(subscription.get('payment_method_id') or ''),
        is_recurring=1,
        parent_payment_id=subscription.get('last_payment_id'),
    )

    status = str(payment.get('status') or 'pending')
    if status == 'succeeded':
        return await _finalize_success(subscription, order_id, payment, bot)
    if status == 'canceled':
        return await _record_definitive_failure(
            subscription,
            order_id,
            bot,
            payment_id=payment_id,
            reason=_payment_failure_reason(payment),
        )

    # YooKassa may keep a payment pending while it finishes processing. Poll the
    # same payment later; never create another order for this subscription.
    reschedule_subscription_check(sub_id, delay_seconds=PENDING_POLL_SECONDS)
    await _ensure_grace_access(subscription)
    logger.debug('Подписка %s: платёж %s остаётся в статусе %s', sub_id, payment_id, status)
    return {'status': 'pending', 'subscription_id': sub_id}


async def process_due_subscription(subscription: Dict[str, Any], bot: Bot) -> Dict[str, Any]:
    """Processes one due subscription without creating duplicate charges."""
    sub_id = int(subscription['id'])
    async with _subscription_locks[sub_id]:
        amount_rub = float(subscription.get('price_rub') or 0)
        payment_method_id = str(subscription.get('payment_method_id') or '')
        if amount_rub <= 0 or not payment_method_id:
            reason = 'missing_price' if amount_rub <= 0 else 'missing_payment_method'
            # Create a local order so every definitive attempt remains auditable.
            _, order_id = create_pending_order(
                user_id=int(subscription['user_id']),
                tariff_id=int(subscription['tariff_id']),
                payment_type='yookassa_recurring',
                vpn_key_id=subscription.get('vpn_key_id'),
            )
            save_order_subscription_context(order_id, subscription_id=sub_id, is_recurring=1)
            return await _record_definitive_failure(
                subscription,
                order_id,
                bot,
                reason=reason,
            )

        open_order = get_open_recurring_order(sub_id)
        if open_order:
            order_id = str(open_order['order_id'])
            payment_id = str(open_order.get('yookassa_payment_id') or '')
            if payment_id:
                try:
                    payment = await get_yookassa_payment(payment_id)
                except YooKassaAPIError as exc:
                    if exc.retryable:
                        mark_subscription_transient_error(sub_id, str(exc))
                        await _ensure_grace_access(subscription)
                        return {'status': 'transient', 'subscription_id': sub_id}
                    return await _record_definitive_failure(
                        subscription,
                        order_id,
                        bot,
                        payment_id=payment_id,
                        reason=exc.code or exc.description,
                    )
                except Exception as exc:
                    logger.warning('Подписка %s: временная ошибка проверки платежа: %s', sub_id, exc)
                    mark_subscription_transient_error(sub_id, str(exc))
                    await _ensure_grace_access(subscription)
                    return {'status': 'transient', 'subscription_id': sub_id}
                return await _handle_payment(subscription, order_id, payment, bot)
        else:
            _, order_id = create_pending_order(
                user_id=int(subscription['user_id']),
                tariff_id=int(subscription['tariff_id']),
                payment_type='yookassa_recurring',
                vpn_key_id=subscription.get('vpn_key_id'),
            )
            save_order_subscription_context(order_id, subscription_id=sub_id, is_recurring=1)

        description = (
            f"Автопродление «{subscription.get('tariff_name') or 'VPN'}» — "
            f"{subscription.get('billing_period_days')} дней"
        )
        try:
            payment = await create_yookassa_recurring_payment(
                amount_rub=amount_rub,
                order_id=order_id,
                description=description,
                payment_method_id=payment_method_id,
                metadata={
                    'subscription_id': str(sub_id),
                    'tariff_id': str(subscription['tariff_id']),
                    'vpn_key_id': str(subscription.get('vpn_key_id') or ''),
                },
            )
        except YooKassaAPIError as exc:
            if exc.retryable:
                logger.warning('Подписка %s: временная ошибка ЮKassa: %s', sub_id, exc)
                mark_subscription_transient_error(sub_id, str(exc))
                await _ensure_grace_access(subscription)
                return {'status': 'transient', 'subscription_id': sub_id}
            return await _record_definitive_failure(
                subscription,
                order_id,
                bot,
                reason=exc.code or exc.description,
            )
        except Exception as exc:
            # The request outcome may be unknown after a network timeout. Keep the
            # order pending and retry it with the same deterministic idempotence key.
            logger.warning('Подписка %s: временная ошибка создания автоплатежа: %s', sub_id, exc)
            mark_subscription_transient_error(sub_id, str(exc))
            await _ensure_grace_access(subscription)
            return {'status': 'transient', 'subscription_id': sub_id}

        return await _handle_payment(subscription, order_id, payment, bot)


async def process_due_subscriptions(bot: Bot, limit: int = 50) -> Dict[str, int]:
    """Processes subscriptions whose next_charge_at has arrived."""
    due = get_due_subscriptions(limit=limit)
    stats = {'due': len(due), 'succeeded': 0, 'failed': 0, 'pending': 0, 'errors': 0}
    if not due:
        logger.debug('Нет подписок для автосписания')
        return stats

    logger.info('Найдено подписок для автосписания: %s', len(due))
    for subscription in due:
        try:
            result = await process_due_subscription(subscription, bot)
            status = result.get('status')
            if status == 'succeeded':
                stats['succeeded'] += 1
            elif status == 'failed':
                stats['failed'] += 1
            elif status in ('pending', 'transient', 'deferred'):
                stats['pending'] += 1
            else:
                stats['errors'] += 1
        except Exception as exc:
            stats['errors'] += 1
            logger.error(
                'Ошибка обработки подписки %s: %s',
                subscription.get('id'),
                exc,
                exc_info=True,
            )
        await asyncio.sleep(0)

    logger.info('Итог автосписаний: %s', stats)
    return stats


async def run_subscription_billing_scheduler(
    bot: Bot,
    interval_seconds: int = SCHEDULER_INTERVAL_SECONDS,
) -> None:
    """Runs recurring billing every five minutes by default."""
    interval_seconds = max(60, int(interval_seconds))
    logger.info('Планировщик автосписаний подписок запущен (каждые %s сек.)', interval_seconds)

    await asyncio.sleep(10)
    while True:
        try:
            await process_due_subscriptions(bot)
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info('Планировщик автосписаний подписок остановлен')
            raise
        except Exception as exc:
            logger.error('Ошибка в планировщике автосписаний подписок: %s', exc, exc_info=True)
            await asyncio.sleep(min(interval_seconds, 300))


async def _notify_payment_success(subscription: Dict[str, Any], bot: Bot) -> None:
    telegram_id = subscription.get('user_telegram_id')
    if not telegram_id:
        return
    try:
        await bot.send_message(
            telegram_id,
            '✅ <b>Автопродление VPN успешно оплачено</b>\n\n'
            f"Тариф: <b>{subscription.get('tariff_name') or 'VPN'}</b>\n"
            f"Период: <b>{subscription.get('billing_period_days')} дней</b>",
            parse_mode='HTML',
        )
    except Exception as exc:
        logger.warning('Не удалось уведомить пользователя %s об успешном автосписании: %s', telegram_id, exc)


async def _notify_payment_failed(
    subscription: Dict[str, Any],
    bot: Bot,
    *,
    failure: Dict[str, Any],
) -> None:
    telegram_id = subscription.get('user_telegram_id')
    if not telegram_id:
        return
    final = bool(failure.get('final'))
    if final:
        text = (
            '⛔ <b>Автопродление VPN не выполнено</b>\n\n'
            f"Тариф: <b>{subscription.get('tariff_name') or 'VPN'}</b>\n"
            'Льготный период закончился, доступ остановлен. Продлите ключ вручную.'
        )
    else:
        text = (
            '⚠️ <b>Не удалось выполнить автопродление VPN</b>\n\n'
            f"Тариф: <b>{subscription.get('tariff_name') or 'VPN'}</b>\n"
            'Доступ временно сохранён на льготный период. Бот повторит попытку автоматически.'
        )
    try:
        await bot.send_message(telegram_id, text, parse_mode='HTML')
    except Exception as exc:
        logger.warning('Не удалось уведомить пользователя %s об ошибке автосписания: %s', telegram_id, exc)
