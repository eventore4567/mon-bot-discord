"""Contract tests for the /setup external economy importer."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "sentrix_economy_import_tested",
    Path(__file__).resolve().parents[1] / "cogs" / "economy_import.py",
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

USER_A = 123456789012345678
USER_B = 223456789012345678


def test_csv_aliases_and_semicolon_and_json():
    csv_data = f"user_id;balance;banque\n{USER_A};100000;5000\n{USER_B};300;0\n"
    rows = module.parse_export(csv_data, "other-bot.csv")
    assert rows == [
        module.MemberBalance(USER_A, 100000, 5000),
        module.MemberBalance(USER_B, 300, 0),
    ]
    json_rows = module.parse_export(
        f'{{"users":[{{"discord_id":"{USER_A}","wallet":100000,"bank":5000}}]}}',
        "other-bot.json",
    )
    assert json_rows == [module.MemberBalance(USER_A, 100000, 5000)]


def test_duplicate_ids_and_negative_or_decimal_money_rejected():
    with pytest.raises(module.ImportErrorData, match="Doublon"):
        module.parse_export(f"user_id,cash\n{USER_A},100\n{USER_A},100\n")
    with pytest.raises(module.ImportErrorData):
        module.parse_export(f"user_id,cash\n{USER_A},-100\n")
    with pytest.raises(module.ImportErrorData):
        module.parse_export(f"user_id,cash\n{USER_A},12.5\n")
    with pytest.raises(module.ImportErrorData):
        module.parse_export("user_id,cash\nfake-name,1000\n")
    with pytest.raises(module.ImportErrorData):
        module.parse_export(b"\xff\xfe", "export.csv")


def test_count_size_and_amount_limits():
    too_many = "user_id,cash\n" + "".join(f"{10**17 + n},1\n" for n in range(1001))
    with pytest.raises(module.ImportErrorData, match="Trop de membres"):
        module.parse_export(too_many)
    with pytest.raises(module.ImportErrorData, match="volumineux"):
        module.parse_export(b"x" * (module.MAX_FILE_BYTES + 1))
    with pytest.raises(module.ImportErrorData, match="limite"):
        module.parse_export(f"user_id,cash\n{USER_A},{10**13}\n")


async def _test_atomic_add_replace_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "guild.sqlite3")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE economy (
                guild_id INTEGER, user_id INTEGER, cash INTEGER DEFAULT 0, bank INTEGER DEFAULT 0,
                last_daily INTEGER DEFAULT 0, last_weekly INTEGER DEFAULT 0, last_work INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE economy_transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER, sender_id INTEGER, receiver_id INTEGER,
                transaction_type TEXT, amount INTEGER, created_at INTEGER, reason TEXT
            );
        """)
        conn.execute(
            "INSERT INTO economy (guild_id,user_id,cash,bank,last_daily) VALUES (1,?,1000,500,555)",
            (USER_A,),
        )
        conn.commit()
        conn.close()

        fake_bot = SimpleNamespace(db=SimpleNamespace(path=path, _economy_lock=asyncio.Lock()))
        incoming = [module.MemberBalance(USER_A, 100000, 10), module.MemberBalance(USER_B, 50, 0)]
        batch, delta = await module.apply_import(fake_bot, 1, USER_A, incoming, "add", "foreign.csv")
        assert batch == 1
        assert delta == 100060
        with pytest.raises(module.ImportErrorData, match="déjà été importé"):
            await module.apply_import(fake_bot, 1, USER_A, incoming, "add", "foreign.csv")

        replacement = [module.MemberBalance(USER_A, 9000, 20)]
        batch2, delta2 = await module.apply_import(fake_bot, 1, USER_A, replacement, "replace", "foreign-update.csv")
        assert batch2 == 2
        assert delta2 == -92490

        con = sqlite3.connect(path)
        assert con.execute("SELECT cash,bank,last_daily FROM economy WHERE user_id=?", (USER_A,)).fetchone() == (9000, 20, 555)
        assert con.execute("SELECT cash,bank FROM economy WHERE user_id=?", (USER_B,)).fetchone() == (50, 0)
        assert con.execute("SELECT COUNT(*) FROM economy_import_rows").fetchone()[0] == 3
        assert con.execute("SELECT COUNT(*) FROM economy_transactions WHERE transaction_type='external_import'").fetchone()[0] == 3
        con.close()


def test_import_atomicity_and_duplicate_protection():
    asyncio.run(_test_atomic_add_replace_idempotent())
