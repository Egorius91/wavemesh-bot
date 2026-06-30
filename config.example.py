"""Example local configuration for WaveMesh Bot development and CI checks.

Copy this file to config.py and replace placeholder values before deployment.
"""

BOT_TOKEN = "0000000000:TEST_TOKEN_FOR_IMPORT_CHECKS_ONLY"
ADMIN_IDS = [123456789]

# Repository used by the in-bot update mechanism.
GITHUB_REPO_URL = "https://github.com/Egorius91/wavemesh-bot.git"

# Generic retry config used by network/payment helpers.
RETRY_CONFIG = {
    "max_attempts": 3,
    "delays": [1, 3, 9],
}
