from pathlib import Path


SERVICE_PATH = Path(__file__).resolve().parents[1] / "systemd" / "wavemesh-bot.service"


def _service_lines() -> set[str]:
    return {
        line.strip()
        for line in SERVICE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_service_has_required_systemd_hardening() -> None:
    lines = _service_lines()

    required = {
        "User=wavemesh",
        "Group=wavemesh",
        "UMask=0077",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "ProtectClock=true",
        "ProtectHostname=true",
        "RestrictSUIDSGID=true",
        "LockPersonality=true",
        "RestrictRealtime=true",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "ReadWritePaths=/opt/wavemesh-bot",
    }

    assert required <= lines


def test_service_repairs_sensitive_file_modes_before_start() -> None:
    lines = _service_lines()

    assert (
        "ExecStartPre=-/usr/bin/chmod 0600 "
        "/opt/wavemesh-bot/database/wavemesh_bot.db"
    ) in lines
    assert (
        "ExecStartPre=-/usr/bin/chmod 0600 "
        "/opt/wavemesh-bot/logs/bot.log"
    ) in lines
