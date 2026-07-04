import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from bot.handlers.user.payments.base import create_qr_payment_flow, finalize_payment_ui
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()

_YK_TITLE = '📱 <b>QR-код для оплаты</b>'
_YK_TYPE = 'yookassa_qr'
_YK_ERROR = 'ЮКасса'
_YK_QR_FILE = 'qr.png'
_YK_CHECK_PREFIX = 'check_yookassa_qr'
_YK_RESULT_KEY = 'yookassa_payment_id'
_YK_LOADING = '⏳ Создаём QR-код для оплаты...'


def _tariff_is_recurring(tariff: dict) -> bool:
    return bool(tariff.get('is_recurring')) or tariff.get('billing_type') == 'recurring'


# ============================================================================
# Telegram Payments / Provider Token: только разовые тарифы
# ============================================================================


@router.callback_query(F.data.startswith('pay_cards'))
async def pay_cards_select_tariff(callback: CallbackQuery):
    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb
    from bot.keyboards.admin import home_only_kb
    order_id = callback.data.split(':')[1] if ':' in callback.data else None
    tariffs = [t for t in get_all_tariffs(include_hidden=False) if not _tariff_is_recurring(t)]
    if not tariffs:
        await safe_edit_or_send(callback.message, '💳 <b>Оплата картой</b>\n\n😔 Нет доступных разовых тарифов.', reply_markup=home_only_kb())
        await callback.answer()
        return
    await safe_edit_or_send(callback.message, '💳 <b>Оплата картой</b>\n\nВыберите тариф:', reply_markup=tariff_select_kb(tariffs, order_id=order_id, is_cards=True))
    await callback.answer()


@router.callback_query(F.data.startswith('cards_pay:'))
async def pay_cards_invoice(callback: CallbackQuery):
    import json
    from aiogram.exceptions import TelegramBadRequest
    from database.requests import get_tariff_by_id, get_user_internal_id, create_pending_order, update_order_tariff, get_setting

    parts = callback.data.split(':')
    tariff_id = int(parts[1])
    order_id = parts[2] if len(parts) > 2 else None
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return
    if _tariff_is_recurring(tariff):
        await callback.answer('🔁 Подписки оплачиваются через прямую ЮKassa API.', show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    provider_token = get_setting('cards_provider_token', '')
    if not provider_token:
        await callback.answer('❌ Провайдер платежей не настроен', show_alert=True)
        return
    if order_id:
        update_order_tariff(order_id, tariff_id, payment_type='cards')
    else:
        if not user_id:
            await callback.answer('❌ Ошибка пользователя', show_alert=True)
            return
        _, order_id = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type='cards', vpn_key_id=None)

    price_rub = float(tariff.get('price_rub') or 0)
    price_kopecks = int(round(price_rub * 100))
    if price_kopecks <= 0:
        await callback.answer('❌ Цена тарифа в рублях не задана.', show_alert=True)
        return

    provider_data = {
        'receipt': {
            'customer': {'email': f'user_{order_id}@t.me'},
            'items': [{
                'description': f"Тариф «{tariff['name']}»",
                'quantity': '1.00',
                'amount': {'value': f'{price_rub:.2f}', 'currency': 'RUB'},
                'vat_code': 1,
                'payment_mode': 'full_prepayment',
                'payment_subject': 'service',
            }],
        }
    }
    try:
        bot_info = await callback.bot.get_me()
        await callback.message.answer_invoice(
            title=bot_info.first_name,
            description=f"Оплата тарифа «{tariff['name']}» ({tariff['duration_days']} дн.).",
            payload=f'vpn_key:{order_id}',
            provider_token=provider_token,
            currency='RUB',
            prices=[LabeledPrice(label=f"Тариф {tariff['name']}", amount=price_kopecks)],
            provider_data=json.dumps(provider_data),
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text=f'💳 Оплатить {price_rub} ₽', pay=True)
            ).row(InlineKeyboardButton(text='❌ Отмена', callback_data='buy_key')).as_markup(),
        )
    except TelegramBadRequest as e:
        if 'CURRENCY_TOTAL_AMOUNT_INVALID' in str(e):
            await callback.answer('❌ Сумма тарифа меньше допустимого лимита эквайринга.', show_alert=True)
            return
        raise
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.startswith('renew_cards_tariff:'))
async def renew_cards_select_tariff(callback: CallbackQuery):
    from database.requests import get_key_details_for_user
    from bot.keyboards.user import renew_tariff_select_kb
    from bot.utils.groups import get_tariffs_for_renewal
    parts = callback.data.split(':')
    key_id = int(parts[1])
    order_id = parts[2] if len(parts) > 2 else None
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer('❌ Ключ не найден', show_alert=True)
        return
    tariffs = [t for t in get_tariffs_for_renewal(key.get('tariff_id', 0)) if not _tariff_is_recurring(t)]
    if not tariffs:
        await callback.answer('Нет доступных разовых тарифов', show_alert=True)
        return
    await safe_edit_or_send(callback.message, f"💳 <b>Оплата картой</b>\n\n🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n\nВыберите тариф для продления:", reply_markup=renew_tariff_select_kb(tariffs, key_id, order_id=order_id, is_cards=True))
    await callback.answer()


@router.callback_query(F.data.startswith('renew_pay_cards:'))
async def renew_cards_invoice(callback: CallbackQuery):
    # Сохраняем старую UX-модель продления: только разовые тарифы.
    from database.requests import get_tariff_by_id, get_key_details_for_user
    tariff_id = int(callback.data.split(':')[2])
    tariff = get_tariff_by_id(tariff_id)
    if tariff and _tariff_is_recurring(tariff):
        await callback.answer('🔁 Подписку нужно оформить как новую покупку через ЮKassa API.', show_alert=True)
        return
    await callback.answer('Используйте прямую ЮKassa-оплату для продления этого тарифа.', show_alert=True)


# ============================================================================
# Прямая ЮKassa API: разовые платежи и первый платёж подписки
# ============================================================================


@router.callback_query(F.data == 'pay_qr')
async def pay_qr_select_tariff(callback: CallbackQuery):
    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb
    from bot.keyboards.admin import home_only_kb
    rub_tariffs = [t for t in get_all_tariffs(include_hidden=False) if t.get('price_rub') and t['price_rub'] > 0]
    if not rub_tariffs:
        await safe_edit_or_send(callback.message, '📱 <b>ЮKassa</b>\n\n😔 Для оплаты не настроены цены в рублях.', reply_markup=home_only_kb())
        await callback.answer()
        return
    await safe_edit_or_send(callback.message, '📱 <b>ЮKassa (Карта/СБП)</b>\n\nВыберите тариф:\n\n<i>Подписки сохраняют способ оплаты для автосписаний.</i>', reply_markup=tariff_select_kb(rub_tariffs, is_qr=True))
    await callback.answer()


@router.callback_query(F.data.startswith('qr_pay:'))
async def qr_pay_create(callback: CallbackQuery):
    from database.requests import get_tariff_by_id, save_yookassa_payment_id
    from bot.services.billing import create_yookassa_qr_payment
    from bot.services.yookassa_recurring import create_yookassa_initial_subscription_payment

    tariff_id = int(callback.data.split(':')[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return
    price_rub = float(tariff.get('price_rub') or 0)
    if price_rub <= 0:
        await callback.answer('❌ Цена в рублях не задана для этого тарифа', show_alert=True)
        return

    is_recurring = _tariff_is_recurring(tariff)
    await create_qr_payment_flow(
        callback=callback,
        tariff=tariff,
        price_rub=price_rub,
        payment_type=_YK_TYPE,
        create_func=create_yookassa_initial_subscription_payment if is_recurring else create_yookassa_qr_payment,
        save_func=save_yookassa_payment_id,
        result_key=_YK_RESULT_KEY,
        title='🔁 <b>Первый платёж подписки</b>' if is_recurring else _YK_TITLE,
        check_prefix=_YK_CHECK_PREFIX,
        error_name=_YK_ERROR,
        qr_filename=_YK_QR_FILE,
        back_callback='pay_qr',
        loading_text=_YK_LOADING,
        hint_text='После оплаты нажмите «✅ Я оплатил». Способ оплаты будет сохранён для автопродления.' if is_recurring else None,
    )


async def _yookassa_referral_amount(order: dict, state: FSMContext) -> int:
    state_data = await state.get_data()
    remaining_cents = state_data.get('remaining_cents', 0)
    if remaining_cents > 0:
        return remaining_cents
    from database.requests import get_tariff_by_id
    tariff = get_tariff_by_id(order.get('tariff_id'))
    return int((tariff.get('price_rub', 0) or 0) * 100) if tariff else 0


@router.callback_query(F.data.startswith('check_yookassa_qr:'))
async def check_yookassa_payment(callback: CallbackQuery, state: FSMContext):
    await _run_yookassa_check(callback.message, state, order_id=callback.data.split(':', 1)[1], telegram_id=callback.from_user.id, callback=callback)


async def _run_yookassa_check(message, state, order_id: str, telegram_id: int, callback=None) -> None:
    from database.requests import (
        find_order_by_order_id, get_user_internal_id, is_order_already_paid,
        update_payment_type, get_tariff_by_id, create_subscription,
        fail_order, save_order_subscription_context,
    )
    from bot.keyboards.admin import home_only_kb
    from bot.services.billing import complete_payment_flow
    from bot.services.yookassa_recurring import get_yookassa_payment

    order = find_order_by_order_id(order_id)
    if not order:
        if callback:
            await callback.answer('❌ Ордер не найден', show_alert=True)
        else:
            await safe_edit_or_send(message, '❌ Ордер не найден', reply_markup=home_only_kb())
        return

    owner_user_id = get_user_internal_id(telegram_id)
    if not owner_user_id or int(order.get('user_id') or 0) != int(owner_user_id):
        if callback:
            await callback.answer('❌ Ордер не найден', show_alert=True)
        return

    if order.get('status') == 'paid' or is_order_already_paid(order_id):
        await finalize_payment_ui(message, state, '✅ Оплата уже была обработана ранее.', order, user_id=telegram_id)
        if callback:
            await callback.answer()
        return

    payment_id = order.get(_YK_RESULT_KEY)
    if not payment_id:
        if callback:
            await callback.answer('⚠️ Нет данных о платеже. Попробуйте чуть позже.', show_alert=True)
        return

    if callback:
        await callback.answer('🔍 Проверяем платёж...')

    try:
        payment = await get_yookassa_payment(payment_id)
    except Exception as e:
        logger.error('Ошибка проверки ЮKassa %s: %s', order_id, e, exc_info=True)
        await safe_edit_or_send(message, '❌ Не удалось проверить статус платежа. Попробуйте позже.', reply_markup=home_only_kb(), force_new=True)
        return

    status = payment.get('status', 'pending')
    if status == 'succeeded':
        update_payment_type(order_id, _YK_TYPE)
        referral_amount = await _yookassa_referral_amount(order, state)
        try:
            await message.delete()
        except Exception:
            pass

        await complete_payment_flow(order_id=order_id, message=message, state=state, telegram_id=telegram_id, payment_type=_YK_TYPE, referral_amount=referral_amount)

        tariff = get_tariff_by_id(order.get('tariff_id'))
        if tariff and _tariff_is_recurring(tariff):
            payment_method = payment.get('payment_method') or {}
            payment_method_id = payment_method.get('id') if isinstance(payment_method, dict) else None
            if not payment_method_id:
                await message.answer('⚠️ Оплата прошла, но автопродление не включено: ЮKassa не вернула сохранённый способ оплаты.', parse_mode='HTML')
                return
            paid_order = find_order_by_order_id(order_id) or order
            subscription_id = create_subscription(
                user_id=paid_order['user_id'],
                tariff_id=paid_order['tariff_id'],
                vpn_key_id=paid_order.get('vpn_key_id'),
                payment_method_id=payment_method_id,
                billing_period_days=tariff.get('billing_period_days') or tariff.get('duration_days') or 30,
                initial_payment_id=payment_id,
                provider='yookassa',
            )
            save_order_subscription_context(order_id, subscription_id=subscription_id, payment_method_id=payment_method_id, is_recurring=1)
            await message.answer('🔁 <b>Автопродление включено</b>', parse_mode='HTML')
        return

    if status == 'canceled':
        fail_order(order_id)
        await safe_edit_or_send(message, '❌ <b>Платёж отменён</b>\n\nПопробуйте снова выбрать тариф.', reply_markup=home_only_kb(), force_new=True)
        return

    await safe_edit_or_send(message, '⏳ <b>Платёж ещё не поступил</b>\n\nОплатите по ссылке и нажмите «✅ Я оплатил» снова.\n\n<i>Если только что оплатили — подождите пару секунд.</i>', force_new=True)


@router.callback_query(F.data.startswith('renew_qr_tariff:'))
async def renew_qr_select_tariff(callback: CallbackQuery):
    from database.requests import get_key_details_for_user
    from bot.keyboards.user import renew_tariff_select_kb
    from bot.utils.groups import get_tariffs_for_renewal
    key_id = int(callback.data.split(':')[1])
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer('❌ Ключ не найден', show_alert=True)
        return
    tariffs = [t for t in get_tariffs_for_renewal(key.get('tariff_id', 0)) if t.get('price_rub') and t['price_rub'] > 0 and not _tariff_is_recurring(t)]
    if not tariffs:
        await callback.answer('😔 Нет разовых тарифов с ценой в рублях', show_alert=True)
        return
    await safe_edit_or_send(callback.message, f"📱 <b>QR-оплата (Карта/СБП)</b>\n\n🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n\nВыберите тариф для продления:", reply_markup=renew_tariff_select_kb(tariffs, key_id, is_qr=True))
    await callback.answer()


@router.callback_query(F.data.startswith('renew_pay_qr:'))
async def renew_qr_create(callback: CallbackQuery):
    from database.requests import get_tariff_by_id, get_key_details_for_user, save_yookassa_payment_id
    from bot.services.billing import create_yookassa_qr_payment
    parts = callback.data.split(':')
    key_id = int(parts[1])
    tariff_id = int(parts[2])
    tariff = get_tariff_by_id(tariff_id)
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not tariff or not key:
        await callback.answer('❌ Ошибка тарифа или ключа', show_alert=True)
        return
    if _tariff_is_recurring(tariff):
        await callback.answer('🔁 Подписку нужно оформить как новую покупку.', show_alert=True)
        return
    price_rub = float(tariff.get('price_rub') or 0)
    if price_rub <= 0:
        await callback.answer('❌ Цена в рублях не задана', show_alert=True)
        return
    await create_qr_payment_flow(
        callback=callback, tariff=tariff, price_rub=price_rub,
        payment_type=_YK_TYPE, create_func=create_yookassa_qr_payment,
        save_func=save_yookassa_payment_id, result_key=_YK_RESULT_KEY,
        title=_YK_TITLE, check_prefix=_YK_CHECK_PREFIX, error_name=_YK_ERROR,
        qr_filename=_YK_QR_FILE, back_callback=f'renew_qr_tariff:{key_id}',
        loading_text=_YK_LOADING, key=key, vpn_key_id=key_id,
    )
