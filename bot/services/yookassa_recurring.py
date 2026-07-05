"""ЮKassa API helpers для подписок и рекуррентных списаний."""
import base64
import io
import logging
import uuid
from typing import Any, Dict, Optional

import aiohttp
import qrcode

from database.requests import get_yookassa_credentials
from bot.services.billing import build_payment_return_url

logger = logging.getLogger(__name__)

YOOKASSA_API_URL = 'https://api.yookassa.ru/v3/payments'


def _auth_headers(idempotence_key: Optional[str] = None) -> Dict[str, str]:
    shop_id, secret_key = get_yookassa_credentials()
    if not shop_id or not secret_key:
        raise ValueError('ЮKassa: не настроены shop_id или secret_key')

    credentials = base64.b64encode(f'{shop_id}:{secret_key}'.encode()).decode()
    headers = {
        'Authorization': f'Basic {credentials}',
        'Content-Type': 'application/json',
    }
    if idempotence_key:
        headers['Idempotence-Key'] = idempotence_key
    return headers


def _build_receipt(*, amount_rub: float, description: str, order_id: str) -> Dict[str, Any]:
    return {
        'customer': {
            'email': f'user_{order_id}@t.me',
        },
        'items': [
            {
                'description': description[:128],
                'quantity': '1.00',
                'amount': {
                    'value': f'{amount_rub:.2f}',
                    'currency': 'RUB',
                },
                'vat_code': 1,
                'payment_mode': 'full_prepayment',
                'payment_subject': 'service',
            }
        ],
    }


def _qr_bytes(url: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    bio = io.BytesIO()
    img.save(bio, format='PNG')
    return bio.getvalue()


async def get_yookassa_payment(payment_id: str) -> Dict[str, Any]:
    """Возвращает полный объект платежа ЮKassa."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f'{YOOKASSA_API_URL}/{payment_id}', headers=_auth_headers()) as response:
            data = await response.json()
            if response.status != 200:
                error_desc = data.get('description', 'Неизвестная ошибка') if isinstance(data, dict) else f'HTTP {response.status}'
                logger.error('ЮKassa статус ошибка %s: %s', response.status, error_desc)
                raise RuntimeError(f'ЮKassa API ошибка: {error_desc}')
            return data


async def create_yookassa_initial_subscription_payment(
    amount_rub: float,
    order_id: str,
    description: str,
    bot_name: str,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Создаёт первый платёж подписки с сохранением payment_method."""
    idempotence_key = f'sub-init-{order_id}-{uuid.uuid4().hex[:8]}'
    return_url = build_payment_return_url(bot_name, 'yookassa', order_id)
    payload = {
        'amount': {
            'value': f'{amount_rub:.2f}',
            'currency': 'RUB',
        },
        'capture': True,
        'save_payment_method': True,
        'confirmation': {
            'type': 'redirect',
            'return_url': return_url,
        },
        'description': description,
        'receipt': _build_receipt(amount_rub=amount_rub, description=description, order_id=order_id),
        'metadata': {
            'order_id': order_id,
            'is_subscription_initial': '1',
            **(metadata or {}),
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(YOOKASSA_API_URL, json=payload, headers=_auth_headers(idempotence_key)) as response:
            data = await response.json()
            if response.status not in (200, 201):
                error_desc = data.get('description', 'Неизвестная ошибка') if isinstance(data, dict) else f'HTTP {response.status}'
                logger.error('ЮKassa subscription init error %s: %s | payload=%s', response.status, error_desc, payload)
                raise RuntimeError(f'ЮKassa API ошибка: {error_desc}')

            confirmation = data.get('confirmation', {})
            qr_url = confirmation.get('confirmation_url', '')
            if not qr_url:
                logger.error('ЮKassa API не вернул confirmation_url для подписки: %s', data)
                raise RuntimeError('ЮKassa API не вернул ссылку оплаты')

            return {
                'yookassa_payment_id': data['id'],
                'qr_image_data': _qr_bytes(qr_url),
                'qr_url': qr_url,
                'status': data.get('status', 'pending'),
            }


async def create_yookassa_recurring_payment(
    *,
    amount_rub: float,
    order_id: str,
    description: str,
    payment_method_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Создаёт автоплатёж по сохранённому payment_method_id."""
    idempotence_key = f'sub-rec-{order_id}-{uuid.uuid4().hex[:8]}'
    payload = {
        'amount': {
            'value': f'{amount_rub:.2f}',
            'currency': 'RUB',
        },
        'capture': True,
        'payment_method_id': payment_method_id,
        'description': description,
        'receipt': _build_receipt(amount_rub=amount_rub, description=description, order_id=order_id),
        'metadata': {
            'order_id': order_id,
            'is_recurring_charge': '1',
            **(metadata or {}),
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(YOOKASSA_API_URL, json=payload, headers=_auth_headers(idempotence_key)) as response:
            data = await response.json()
            if response.status not in (200, 201):
                error_desc = data.get('description', 'Неизвестная ошибка') if isinstance(data, dict) else f'HTTP {response.status}'
                logger.error('ЮKassa recurring error %s: %s | payload=%s', response.status, error_desc, payload)
                raise RuntimeError(f'ЮKassa API ошибка: {error_desc}')
            return data
