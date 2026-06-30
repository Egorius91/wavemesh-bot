def get_panel_email_prefix(user: dict) -> str:
    """Возвращает общий префикс email клиента в панели 3X-UI."""
    if user.get('username'):
        return f"user_{user['username']}_"
    return f"user_{user['telegram_id']}_"
