"""ЮKassa API helpers for initial and recurring subscription payments."""
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
HTTP_TIMEOUT_SECONDS = 20


class YooKassaAPIError(RuntimeError):
    """Structured YooKassa API error with a retryability hint."""

    def __init__(self, status: int, description: str, *, code: str = '') -> None:
        self.status = int(status)
        self.code = str(code or '')
        self.description = str(description or 'Неизвестная ошибка')
        super().__init__(f'ЮKassa API ошибка ({self.status}): {self.description}')

    @property
    def retryable(self) -> bool:
        return self.status in (408, 425, 429) or self.status >= 500


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
        'customer': {'email': f'user_{order_id}@t.me'},
        'items': [
            {
                'description': description[:128],
                'quantity': '1.00',
                'amount': {'value': f'{amount_rub:.2f}', 'currency': 'RUB'},
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


async def _response_json(response: aiohttp.ClientResponse) -> Dict[str, Any]:
    try:
        data = await response.json()
    except (aiohttp.ContentTypeError, ValueError):
        text = await response.text()
        data = {'description': text[:500] or f'HTTP {response.status}'}
    return data if isinstance(data, dict) else {'description': f'HTTP {response.status}'}


def _raise_api_error(response_status: int, data: Dict[str, Any]) -> None:
    raise YooKassaAPIError(
        response_status,
        data.get('description') or 'Неизвестная ошибка',
        code=data.get('code') or '',
    )


async def get_yookassa_payment(payment_id: str) -> Dict[str, Any]:
    """Returns the full YooKassa payment object."""
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f'{YOOKASSA_API_URL}/{payment_id}', headers=_auth_headers()) as response:
            data = await _response_json(response)
            if response.status != 200:
                logger.warning('ЮKassa payment status error %s: %s', response.status, data.get('description'))
                _raise_api_error(response.status, data)
            return data


async def create_yookassa_initial_subscription_payment(
    amount_rub: float,
    order_id: str,
    description: str,
    bot_name: str,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Creates the first payment and requests a saved payment method."""
    idempotence_key = f'sub-init-{order_id}-{uuid.uuid4().hex[:8]}'
    return_url = build_payment_return_url(bot_name, 'yookassa', order_id)
    payload = {
        'amount': {'value': f'{amount_rub:.2f}', 'currency': 'RUB'},
        'capture': True,
        'save_payment_method': True,
        'confirmation': {'type': 'redirect', 'return_url': return_url},
        'description': description,
        'receipt': _build_receipt(amount_rub=amount_rub, description=description, order_id=order_id),
        'metadata': {
            'order_id': order_id,
            'is_subscription_initial': '1',
            **(metadata or {}),
        },
    }

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            YOOKASSA_API_URL,
            json=payload,
            headers=_auth_headers(idempotence_key),
        ) as response:
            data = await _response_json(response)
            if response.status not in (200, 201):
                logger.warning('ЮKassa initial subscription error %s: %s', response.status, data.get('description'))
                _raise_api_error(response.status, data)

            confirmation = data.get('confirmation', {})
            qr_url = confirmation.get('confirmation_url', '')
            if not qr_url:
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
    """Creates an off-session payment using a saved payment method.

    The idempotence key is deterministic for the internal order. Retrying the
    same order after a timeout therefore cannot create a second charge.
    """
    idempotence_key = f'sub-rec-{order_id}'
    payload = {
        'amount': {'value': f'{amount_rub:.2f}', 'currency': 'RUB'},
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

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            YOOKASSA_API_URL,
            json=payload,
            headers=_auth_headers(idempotence_key),
        ) as response:
            data = await _response_json(response)
            if response.status not in (200, 201):
                # Do not log payload: it contains the saved payment-method token.
                logger.warning('ЮKassa recurring error %s: %s', response.status, data.get('description'))
                _raise_api_error(response.status, data)
            return data
