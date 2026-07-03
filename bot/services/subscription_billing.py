"""Фоновая обработка автосписаний подписок."""
import asyncio
import logging
from typing import Any, Dict

from aiogram import Bot

from database.requests import (
    create_pending_order,
    get_due_subscriptions,
    mark_subscription_payment_succeeded,
    mark_subscription_payment_failed,
    save_order_subscription_context,
    save_yookassa_payment_id,
    update_payment_type,
)
from bot.services.billing import process_payment_order
from bot.services.yookassa_recurring import create_yookassa_recurring_payment

logger = logging.getLogger(__name__)


def _payment_method_from_payment(payment: Dict[str, Any]) -> str:
    method = payment.get('payment_method') or {}
    if isinstance(method, dict):
        return method.get('id') or ''
    return ''


async def process_due_subscription(subscription: Dict[str, Any], bot: Bot) -> None:
    """Проводит одно автосписание по подписке."""
    sub_id = int(subscription['id'])
    amount_rub = float(subscription.get('price_rub') or 0)
    if amount_rub <= 0:
        logger.error('Подписка %s: цена в рублях не задана, автосписание невозможно', sub_id)
        mark_subscription_payment_failed(sub_id)
        return

    user_id = int(subscription['user_id'])
    tariff_id = int(subscription['tariff_id'])
    vpn_key_id = subscription.get('vpn_key_id')
    payment_method_id = subscription.get('payment_method_id')
    if not payment_method_id:
        logger.error('Подписка %s: нет payment_method_id', sub_id)
        mark_subscription_payment_failed(sub_id)
        return

    _, order_id = create_pending_order(
        user_id=user_id,
        tariff_id=tariff_id,
        payment_type='yookassa_recurring',
        vpn_key_id=vpn_key_id,
    )
    save_order_subscription_context(order_id, subscription_id=sub_id, is_recurring=1)

    description = f"Автопродление «{subscription.get('tariff_name') or 'VPN'}» — {subscription.get('billing_period_days')} дней"

    try:
        payment = await create_yookassa_recurring_payment(
            amount_rub=amount_rub,
            order_id=order_id,
            description=description,
            payment_method_id=payment_method_id,
            metadata={
                'subscription_id': str(sub_id),
                'tariff_id': str(tariff_id),
                'vpn_key_id': str(vpn_key_id or ''),
            },
        )
    except Exception as e:
        logger.error('Подписка %s: ошибка создания автоплатежа: %s', sub_id, e, exc_info=True)
        mark_subscription_payment_failed(sub_id)
        await _notify_payment_failed(subscription, bot)
        return

    payment_id = payment.get('id') or ''
    if payment_id:
        save_yookassa_payment_id(order_id, payment_id)
    save_order_subscription_context(
        order_id,
        subscription_id=sub_id,
        payment_method_id=_payment_method_from_payment(payment) or payment_method_id,
        is_recurring=1,
        parent_payment_id=subscription.get('last_payment_id'),
    )

    status = payment.get('status')
    if status == 'succeeded':
        update_payment_type(order_id, 'yookassa_recurring')
        success, text, order = await process_payment_order(order_id, bot=bot, process_referrals=True)
        if success:
            mark_subscription_payment_succeeded(
                sub_id,
                payment_id=payment_id,
                payment_method_id=_payment_method_from_payment(payment) or payment_method_id,
            )
            await _notify_payment_success(subscription, bot)
            logger.info('Подписка %s успешно продлена, order=%s', sub_id, order_id)
        else:
            logger.error('Подписка %s: платёж прошёл, но order не обработался: %s', sub_id, text)
            mark_subscription_payment_failed(sub_id, payment_id=payment_id)
        return

    logger.warning('Подписка %s: автоплатёж создан, но статус=%s', sub_id, status)
    mark_subscription_payment_failed(sub_id, payment_id=payment_id)
    await _notify_payment_failed(subscription, bot)


async def process_due_subscriptions(bot: Bot, limit: int = 50) -> None:
    """Обрабатывает все подписки, у которых наступил next_charge_at."""
    due = get_due_subscriptions(limit=limit)
    if not due:
        logger.info('Нет подписок для автосписания')
        return

    logger.info('Найдено подписок для автосписания: %s', len(due))
    for subscription in due:
        try:
            await process_due_subscription(subscription, bot)
        except Exception as e:
            logger.error('Ошибка обработки подписки %s: %s', subscription.get('id'), e, exc_info=True)
        await asyncio.sleep(1)


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
    except Exception as e:
        logger.warning('Не удалось уведомить пользователя %s об успешном автосписании: %s', telegram_id, e)


async def _notify_payment_failed(subscription: Dict[str, Any], bot: Bot) -> None:
    telegram_id = subscription.get('user_telegram_id')
    if not telegram_id:
        return
    try:
        await bot.send_message(
            telegram_id,
            '⚠️ <b>Не удалось выполнить автопродление VPN</b>\n\n'
            f"Тариф: <b>{subscription.get('tariff_name') or 'VPN'}</b>\n"
            'Проверьте способ оплаты или продлите доступ вручную.',
            parse_mode='HTML',
        )
    except Exception as e:
        logger.warning('Не удалось уведомить пользователя %s об ошибке автосписания: %s', telegram_id, e)
