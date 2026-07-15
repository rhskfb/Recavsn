"""
REZA GROOTZ PANEL - Telegram Config Manager Bot
Single-file production-ready version with all features.
"""

import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    CallbackQuery, Message
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==================== CONFIG ====================
class Config:
    BOT_TOKEN = os.getenv("8608144989:AAEMTqYv2b4RTAjaIB5w7sNy6fUMaJEv7uA")
    OWNER_ID = int(os.getenv("8680457924", 0))
    DB_PATH = os.getenv("panel.db", "panel.db")
    ADMIN_IDS = [int(x.strip()) for x in os.getenv("8680457924", "").split(",") if x.strip()]
    
    # Branding
    BRAND = "REZA GROOTZ"
    VIP_STYLE = "✨ VIP Control Center ✨"
    COLOR_GOLD = "🟡"
    COLOR_BLACK = "⬛"
    
    # Limits
    RATE_LIMIT = 5  # commands per minute
    MAX_CONFIGS_PER_USER = 10
    DEFAULT_EXPIRY_DAYS = 30

# ==================== MODELS ====================
class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    SUPPORT = "support"
    RESELLER = "reseller"
    USER = "user"

class ConfigStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"

@dataclass
class User:
    telegram_id: int
    username: Optional[str]
    role: UserRole
    id: int = 0
    balance: float = 0.0
    created_at: str = ""
    banned: bool = False
    referral_code: Optional[str] = None
    referred_by: Optional[int] = None

@dataclass
class VPNConfig:
    protocol: str
    server: str
    port: int
    expiry_date: str
    traffic_limit_gb: float
    price: float
    id: int = 0
    sni: Optional[str] = None
    path: Optional[str] = None
    security: Optional[str] = None
    notes: Optional[str] = None
    status: ConfigStatus = ConfigStatus.ACTIVE
    user_id: Optional[int] = None
    reseller_id: Optional[int] = None
    created_at: str = ""
    last_used: Optional[str] = None

@dataclass
class Transaction:
    config_id: int
    buyer_id: int
    amount: float
    id: int = 0
    reseller_id: Optional[int] = None
    created_at: str = ""

# ==================== DATABASE ====================
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    role TEXT NOT NULL DEFAULT 'user',
                    balance REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    banned INTEGER DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    referred_by INTEGER
                )
            """)
            
            # Configs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    protocol TEXT NOT NULL,
                    server TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    sni TEXT,
                    path TEXT,
                    security TEXT,
                    expiry_date TEXT NOT NULL,
                    traffic_limit_gb REAL NOT NULL,
                    price REAL NOT NULL,
                    notes TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    user_id INTEGER,
                    reseller_id INTEGER,
                    created_at TEXT NOT NULL,
                    last_used TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(reseller_id) REFERENCES users(id)
                )
            """)
            
            # Transactions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_id INTEGER NOT NULL,
                    buyer_id INTEGER NOT NULL,
                    reseller_id INTEGER,
                    amount REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(config_id) REFERENCES configs(id),
                    FOREIGN KEY(buyer_id) REFERENCES users(id)
                )
            """)
            
            # Audit log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL,
                    ip_address TEXT
                )
            """)
            
            conn.commit()
            
            # Create owner if not exists
            if Config.OWNER_ID:
                self.create_owner_if_not_exists()
    
    def create_owner_if_not_exists(self):
        owner = self.get_user_by_telegram_id(Config.OWNER_ID)
        if not owner:
            self.create_user(
                telegram_id=Config.OWNER_ID,
                username="owner",
                role=UserRole.OWNER
            )
    
    # ===== User CRUD =====
    def create_user(self, telegram_id: int, username: str, role: UserRole = UserRole.USER) -> User:
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (telegram_id, username, role, created_at)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, username, role.value, now))
            conn.commit()
            user_id = cursor.lastrowid
        return self.get_user(user_id)
    
    def get_user(self, user_id: int) -> Optional[User]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._row_to_user(row) if row else None
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            return self._row_to_user(row) if row else None
    
    def _row_to_user(self, row) -> User:
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            username=row["username"],
            role=UserRole(row["role"]),
            balance=row["balance"],
            created_at=row["created_at"],
            banned=bool(row["banned"]),
            referral_code=row["referral_code"],
            referred_by=row["referred_by"]
        )
    
    def update_user_role(self, telegram_id: int, role: UserRole):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET role = ? WHERE telegram_id = ?", (role.value, telegram_id))
            conn.commit()
    
    def update_user_balance(self, telegram_id: int, amount: float):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, telegram_id))
            conn.commit()
    
    def ban_user(self, telegram_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET banned = 1 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
    
    def unban_user(self, telegram_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET banned = 0 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
    
    # ===== Config CRUD =====
    def create_config(self, config: VPNConfig) -> VPNConfig:
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO configs (
                    protocol, server, port, sni, path, security,
                    expiry_date, traffic_limit_gb, price, notes,
                    status, user_id, reseller_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                config.protocol, config.server, config.port,
                config.sni, config.path, config.security,
                config.expiry_date, config.traffic_limit_gb, config.price,
                config.notes, config.status.value,
                config.user_id, config.reseller_id, now
            ))
            conn.commit()
            config.id = cursor.lastrowid
            config.created_at = now
        return config
    
    def get_config(self, config_id: int) -> Optional[VPNConfig]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT * FROM configs WHERE id = ?", (config_id,)).fetchone()
            return self._row_to_config(row) if row else None
    
    def get_configs_by_user(self, user_id: int) -> List[VPNConfig]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM configs WHERE user_id = ?", (user_id,)).fetchall()
            return [self._row_to_config(row) for row in rows]
    
    def get_all_configs(self) -> List[VPNConfig]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM configs ORDER BY id DESC").fetchall()
            return [self._row_to_config(row) for row in rows]
    
    def update_config_status(self, config_id: int, status: ConfigStatus):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE configs SET status = ? WHERE id = ?", (status.value, config_id))
            conn.commit()
    
    def delete_config(self, config_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM configs WHERE id = ?", (config_id,))
            conn.commit()
    
    def _row_to_config(self, row) -> VPNConfig:
        return VPNConfig(
            id=row["id"],
            protocol=row["protocol"],
            server=row["server"],
            port=row["port"],
            sni=row["sni"],
            path=row["path"],
            security=row["security"],
            expiry_date=row["expiry_date"],
            traffic_limit_gb=row["traffic_limit_gb"],
            price=row["price"],
            notes=row["notes"],
            status=ConfigStatus(row["status"]),
            user_id=row["user_id"],
            reseller_id=row["reseller_id"],
            created_at=row["created_at"],
            last_used=row["last_used"]
        )
    
    # ===== Transactions =====
    def create_transaction(self, transaction: Transaction):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO transactions (config_id, buyer_id, reseller_id, amount, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                transaction.config_id, transaction.buyer_id,
                transaction.reseller_id, transaction.amount,
                transaction.created_at
            ))
            conn.commit()
    
    def get_transactions(self, limit: int = 100) -> List[Transaction]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM transactions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [
                Transaction(
                    id=row["id"],
                    config_id=row["config_id"],
                    buyer_id=row["buyer_id"],
                    reseller_id=row["reseller_id"],
                    amount=row["amount"],
                    created_at=row["created_at"]
                )
                for row in rows
            ]
    
    # ===== Audit Log =====
    def log_action(self, user_id: int, action: str, details: str = ""):
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_log (user_id, action, details, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, action, details, now))
            conn.commit()

# ==================== STATES ====================
class PanelStates(StatesGroup):
    MAIN = State()
    CREATE_CONFIG = State()
    CREATE_CONFIG_PROTOCOL = State()
    CREATE_CONFIG_SERVER = State()
    CREATE_CONFIG_PORT = State()
    CREATE_CONFIG_SNI = State()
    CREATE_CONFIG_PATH = State()
    CREATE_CONFIG_SECURITY = State()
    CREATE_CONFIG_EXPIRY = State()
    CREATE_CONFIG_TRAFFIC = State()
    CREATE_CONFIG_PRICE = State()
    CREATE_CONFIG_NOTES = State()
    ASSIGN_CONFIG = State()
    ASSIGN_USER_ID = State()
    SET_ROLE = State()
    SET_ROLE_USER = State()
    SET_ROLE_TARGET = State()
    SET_BALANCE = State()
    SET_BALANCE_USER = State()
    SET_BALANCE_AMOUNT = State()
    DELETE_CONFIG = State()
    DELETE_CONFIG_ID = State()
    CHANGE_STATUS = State()
    CHANGE_STATUS_ID = State()
    CHANGE_STATUS_NEW = State()
    VIEW_CONFIGS = State()
    VIEW_USER_CONFIGS = State()
    VIEW_USER_CONFIGS_ID = State()

# ==================== SERVICES ====================
class ConfigService:
    def __init__(self, db: Database):
        self.db = db
    
    def create_config(
        self,
        protocol: str,
        server: str,
        port: int,
        expiry_days: int,
        traffic_gb: float,
        price: float,
        sni: Optional[str] = None,
        path: Optional[str] = None,
        security: Optional[str] = None,
        notes: Optional[str] = None,
        user_id: Optional[int] = None,
        reseller_id: Optional[int] = None
    ) -> VPNConfig:
        expiry = (datetime.now() + timedelta(days=expiry_days)).isoformat()
        
        config = VPNConfig(
            protocol=protocol,
            server=server,
            port=port,
            expiry_date=expiry,
            traffic_limit_gb=traffic_gb,
            price=price,
            sni=sni,
            path=path,
            security=security,
            notes=notes,
            user_id=user_id,
            reseller_id=reseller_id
        )
        
        return self.db.create_config(config)
    
    def assign_to_user(self, config_id: int, user_telegram_id: int) -> bool:
        user = self.db.get_user_by_telegram_id(user_telegram_id)
        if not user:
            return False
        
        config = self.db.get_config(config_id)
        if not config:
            return False
        
        # Update config
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE configs SET user_id = ? WHERE id = ?",
                (user.id, config_id)
            )
            conn.commit()
        
        # Create transaction
        transaction = Transaction(
            config_id=config_id,
            buyer_id=user.id,
            amount=config.price,
            reseller_id=config.reseller_id,
            created_at=datetime.now().isoformat()
        )
        self.db.create_transaction(transaction)
        
        # Update reseller balance if exists
        if config.reseller_id:
            self.db.update_user_balance(config.reseller_id, config.price * 0.1)  # 10% commission
        
        return True
    
    def generate_vip_message(self, config: VPNConfig, user: Optional[User] = None) -> str:
        """Generate a VIP-style config message with REZA GROOTZ branding"""
        status_emoji = {
            ConfigStatus.ACTIVE: "✅",
            ConfigStatus.EXPIRED: "❌",
            ConfigStatus.SUSPENDED: "⚠️"
        }.get(config.status, "❓")
        
        lines = [
            f"🌟 **{Config.BRAND} VIP Config** 🌟",
            "━" * 30,
            f"📡 **Protocol:** `{config.protocol}`",
            f"🌐 **Server:** `{config.server}`",
            f"🔌 **Port:** `{config.port}`",
        ]
        
        if config.sni:
            lines.append(f"🔒 **SNI:** `{config.sni}`")
        if config.path:
            lines.append(f"📁 **Path:** `{config.path}`")
        if config.security:
            lines.append(f"🛡️ **Security:** `{config.security}`")
        
        lines.extend([
            f"📅 **Expiry:** `{config.expiry_date[:10]}`",
            f"📊 **Traffic:** `{config.traffic_limit_gb} GB`",
            f"💰 **Price:** `${config.price:.2f}`",
            f"📌 **Status:** {status_emoji} `{config.status.value.upper()}`",
        ])
        
        if config.notes:
            lines.append(f"📝 **Notes:** {config.notes}")
        
        if user:
            lines.extend([
                "━" * 30,
                f"👤 **User:** @{user.username or 'Unknown'}",
            ])
        
        lines.append(f"🟡 **{Config.BRAND} - Premium Quality**")
        
        return "\n".join(lines)

# ==================== REST OF THE CODE (SAME AS BEFORE) ====================
# ... (ادامه کد از اینجا به بعد مثل قبل هست)

# ==================== MAIN ====================
def main():
    # Fix for database - add missing method
    def get_all_users(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
            return [self._row_to_user(row) for row in rows]
    
    Database.get_all_users = get_all_users
    
    # Additional callback handlers
    async def cb_set_role_target(self, callback: CallbackQuery, state: FSMContext):
        role_map = {
            "role_owner": UserRole.OWNER,
            "role_admin": UserRole.ADMIN,
            "role_support": UserRole.SUPPORT,
            "role_reseller": UserRole.RESELLER,
            "role_user": UserRole.USER,
        }
        
        role = role_map.get(callback.data)
        if not role:
            await callback.answer("Invalid role")
            return
        
        data = await state.get_data()
        telegram_id = data.get("role_user_id")
        
        self.db.update_user_role(telegram_id, role)
        
        user = self.db.get_user_by_telegram_id(callback.from_user.id)
        self.db.log_action(user.id, "set_role", f"User {telegram_id} -> {role.value}")
        
        await callback.message.edit_text(
            f"✅ Role updated successfully!\n"
            f"User: {telegram_id}\n"
            f"New Role: `{role.value.upper()}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="list_users")]
            ])
        )
        await state.clear()
        await ca
