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
    BOT_TOKEN = os.getenv("8793482183:AAEaY4MKp_-CCURz3OK3cnJ-Av8f4MVSmDQ")
    OWNER_ID = int(os.getenv("8793482183", 0))
    DB_PATH = os.getenv("panel.db", "panel.db")
    ADMIN_IDS = [int(x.strip()) for x in os.getenv("8793482183", "").split(",") if x.strip()]
    
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
    id: int
    telegram_id: int
    username: Optional[str]
    role: UserRole
    balance: float = 0.0
    created_at: str = ""
    banned: bool = False
    referral_code: Optional[str] = None
    referred_by: Optional[int] = None

@dataclass
class VPNConfig:
    id: int
    protocol: str  # VLESS, Trojan, etc.
    server: str
    port: int
    sni: Optional[str] = None
    path: Optional[str] = None
    security: Optional[str] = None
    expiry_date: str
    traffic_limit_gb: float
    price: float
    notes: Optional[str] = None
    status: ConfigStatus = ConfigStatus.ACTIVE
    user_id: Optional[int] = None
    reseller_id: Optional[int] = None
    created_at: str = ""
    last_used: Optional[str] = None

@dataclass
class Transaction:
    id: int
    config_id: int
    buyer_id: int
    reseller_id: Optional[int]
    amount: float
    created_at: str

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
            id=0,
            protocol=protocol,
            server=server,
            port=port,
            sni=sni,
            path=path,
            security=security,
            expiry_date=expiry,
            traffic_limit_gb=traffic_gb,
            price=price,
            notes=notes,
            status=ConfigStatus.ACTIVE,
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
            id=0,
            config_id=config_id,
            buyer_id=user.id,
            reseller_id=config.reseller_id,
            amount=config.price,
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

# ==================== BOT HANDLERS ====================
class PanelBot:
    def __init__(self):
        self.db = Database(Config.DB_PATH)
        self.config_service = ConfigService(self.db)
        self.bot = Bot(token=Config.BOT_TOKEN)
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        self._setup_handlers()
    
    def _setup_handlers(self):
        # Start command
        self.dp.message.register(self.cmd_start, Command("start"))
        
        # Main menu callbacks
        self.dp.callback_query.register(self.cb_main_menu, F.data == "main_menu")
        self.dp.callback_query.register(self.cb_manage_configs, F.data == "manage_configs")
        self.dp.callback_query.register(self.cb_manage_users, F.data == "manage_users")
        self.dp.callback_query.register(self.cb_finance, F.data == "finance")
        self.dp.callback_query.register(self.cb_system, F.data == "system")
        self.dp.callback_query.register(self.cb_help, F.data == "help")
        self.dp.callback_query.register(self.cb_back, F.data == "back")
        
        # Config management
        self.dp.callback_query.register(self.cb_create_config, F.data == "create_config")
        self.dp.callback_query.register(self.cb_list_configs, F.data == "list_configs")
        self.dp.callback_query.register(self.cb_view_config, F.data.startswith("view_config_"))
        self.dp.callback_query.register(self.cb_delete_config, F.data.startswith("delete_config_"))
        self.dp.callback_query.register(self.cb_change_status, F.data.startswith("change_status_"))
        self.dp.callback_query.register(self.cb_assign_config, F.data.startswith("assign_config_"))
        
        # User management
        self.dp.callback_query.register(self.cb_list_users, F.data == "list_users")
        self.dp.callback_query.register(self.cb_view_user, F.data.startswith("view_user_"))
        self.dp.callback_query.register(self.cb_set_role, F.data.startswith("set_role_"))
        self.dp.callback_query.register(self.cb_set_balance, F.data.startswith("set_balance_"))
        self.dp.callback_query.register(self.cb_ban_user, F.data.startswith("ban_user_"))
        self.dp.callback_query.register(self.cb_unban_user, F.data.startswith("unban_user_"))
        
        # Finance
        self.dp.callback_query.register(self.cb_finance_report, F.data == "finance_report")
        self.dp.callback_query.register(self.cb_reseller_report, F.data == "reseller_report")
        
        # System
        self.dp.callback_query.register(self.cb_system_settings, F.data == "system_settings")
        self.dp.callback_query.register(self.cb_view_logs, F.data == "view_logs")
        
        # Message handlers for state inputs
        self.dp.message.register(self.handle_create_config_protocol, StateFilter(PanelStates.CREATE_CONFIG_PROTOCOL))
        self.dp.message.register(self.handle_create_config_server, StateFilter(PanelStates.CREATE_CONFIG_SERVER))
        self.dp.message.register(self.handle_create_config_port, StateFilter(PanelStates.CREATE_CONFIG_PORT))
        self.dp.message.register(self.handle_create_config_sni, StateFilter(PanelStates.CREATE_CONFIG_SNI))
        self.dp.message.register(self.handle_create_config_path, StateFilter(PanelStates.CREATE_CONFIG_PATH))
        self.dp.message.register(self.handle_create_config_security, StateFilter(PanelStates.CREATE_CONFIG_SECURITY))
        self.dp.message.register(self.handle_create_config_expiry, StateFilter(PanelStates.CREATE_CONFIG_EXPIRY))
        self.dp.message.register(self.handle_create_config_traffic, StateFilter(PanelStates.CREATE_CONFIG_TRAFFIC))
        self.dp.message.register(self.handle_create_config_price, StateFilter(PanelStates.CREATE_CONFIG_PRICE))
        self.dp.message.register(self.handle_create_config_notes, StateFilter(PanelStates.CREATE_CONFIG_NOTES))
        self.dp.message.register(self.handle_assign_user_id, StateFilter(PanelStates.ASSIGN_USER_ID))
        self.dp.message.register(self.handle_set_role_user, StateFilter(PanelStates.SET_ROLE_USER))
        self.dp.message.register(self.handle_set_balance_user, StateFilter(PanelStates.SET_BALANCE_USER))
        self.dp.message.register(self.handle_set_balance_amount, StateFilter(PanelStates.SET_BALANCE_AMOUNT))
        self.dp.message.register(self.handle_delete_config_id, StateFilter(PanelStates.DELETE_CONFIG_ID))
        self.dp.message.register(self.handle_change_status_id, StateFilter(PanelStates.CHANGE_STATUS_ID))
        self.dp.message.register(self.handle_view_user_configs_id, StateFilter(PanelStates.VIEW_USER_CONFIGS_ID))
    
    # ===== COMMANDS =====
    async def cmd_start(self, message: Message, state: FSMContext):
        user = self.db.get_user_by_telegram_id(message.from_user.id)
        if not user:
            user = self.db.create_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username or "Unknown"
            )
        
        if user.banned:
            await message.answer("🚫 You are banned from using this bot.")
            return
        
        await state.clear()
        await message.answer(
            f"🌟 **Welcome to {Config.BRAND} Panel** 🌟\n"
            f"✨ {Config.VIP_STYLE}\n\n"
            f"👤 **User:** @{user.username or 'Unknown'}\n"
            f"📋 **Role:** `{user.role.value.upper()}`\n"
            f"💰 **Balance:** `${user.balance:.2f}`\n\n"
            f"Choose an option below:",
            reply_markup=self.main_menu_keyboard(user.role),
            parse_mode="Markdown"
        )
        
        self.db.log_action(user.id, "start", "User started the bot")
    
    def main_menu_keyboard(self, role: UserRole) -> InlineKeyboardMarkup:
        buttons = [
            [InlineKeyboardButton(text="📡 Manage Configs", callback_data="manage_configs")],
            [InlineKeyboardButton(text="👥 Manage Users", callback_data="manage_users")],
            [InlineKeyboardButton(text="💰 Finance & Reports", callback_data="finance")],
        ]
        
        if role in [UserRole.OWNER, UserRole.ADMIN]:
            buttons.append([InlineKeyboardButton(text="⚙️ System Settings", callback_data="system")])
        
        buttons.append([InlineKeyboardButton(text="❓ Help & Info", callback_data="help")])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # ===== MAIN MENU CALLBACKS =====
    async def cb_main_menu(self, callback: CallbackQuery, state: FSMContext):
        await state.clear()
        user = self.db.get_user_by_telegram_id(callback.from_user.id)
        await callback.message.edit_text(
            f"🌟 **{Config.BRAND} Control Panel** 🌟\n"
            f"✨ {Config.VIP_STYLE}\n\n"
            f"👤 **User:** @{user.username or 'Unknown'}\n"
            f"📋 **Role:** `{user.role.value.upper()}`\n"
            f"💰 **Balance:** `${user.balance:.2f}`",
            reply_markup=self.main_menu_keyboard(user.role),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_manage_configs(self, callback: CallbackQuery, state: FSMContext):
        user = self.db.get_user_by_telegram_id(callback.from_user.id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Create Config", callback_data="create_config")],
            [InlineKeyboardButton(text="📋 List All Configs", callback_data="list_configs")],
            [InlineKeyboardButton(text="🔍 View User Configs", callback_data="view_user_configs")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(
            f"📡 **Config Management**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Total Configs: {len(self.db.get_all_configs())}\n\n"
            f"Select an action:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_manage_users(self, callback: CallbackQuery):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 List Users", callback_data="list_users")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(
            f"👥 **User Management**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Manage users, roles, and permissions.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_finance(self, callback: CallbackQuery):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Daily Report", callback_data="finance_report")],
            [InlineKeyboardButton(text="🏪 Reseller Report", callback_data="reseller_report")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
        ])
        
        transactions = self.db.get_transactions(limit=50)
        total_revenue = sum(t.amount for t in transactions)
        
        await callback.message.edit_text(
            f"💰 **Finance Dashboard**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Recent Transactions: {len(transactions)}\n"
            f"💵 Total Revenue: ${total_revenue:.2f}\n\n"
            f"Select a report:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_system(self, callback: CallbackQuery):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Settings", callback_data="system_settings")],
            [InlineKeyboardButton(text="📜 View Logs", callback_data="view_logs")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(
            f"⚙️ **System Settings**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔐 Owner ID: {Config.OWNER_ID}\n"
            f"📊 Database: {Config.DB_PATH}\n\n"
            f"System administration panel.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_help(self, callback: CallbackQuery):
        await callback.message.edit_text(
            f"❓ **Help & Information**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🌟 Welcome to {Config.BRAND} Panel!\n\n"
            f"📌 **Features:**\n"
            f"• Manage VPN configs\n"
            f"• User management\n"
            f"• Finance tracking\n"
            f"• Reseller system\n\n"
            f"📞 Support: @RezaGrootzSupport\n"
            f"🌐 Website: reza-grootz.com\n\n"
            f"🟡 **{Config.BRAND} - Premium VPN Solutions**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="main_menu")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_back(self, callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await self.cb_main_menu(callback, state)
    
    # ===== CONFIG MANAGEMENT =====
    async def cb_create_config(self, callback: CallbackQuery, state: FSMContext):
        await state.set_state(PanelStates.CREATE_CONFIG_PROTOCOL)
        await callback.message.edit_text(
            f"📡 **Create New Config**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Step 1/10: Enter protocol\n"
            f"(VLESS, Trojan, VMess, etc.)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Cancel", callback_data="manage_configs")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def handle_create_config_protocol(self, message: Message, state: FSMContext):
        await state.update_data(protocol=message.text.strip())
        await state.set_state(PanelStates.CREATE_CONFIG_SERVER)
        await message.answer(
            f"Step 2/10: Enter server address\n"
            f"(e.g., server.reza-grootz.com)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Cancel", callback_data="manage_configs")]
            ])
        )
    
    async def handle_create_config_server(self, message: Message, state: FSMContext):
        await state.update_data(server=message.text.strip())
        await state.set_state(PanelStates.CREATE_CONFIG_PORT)
        await message.answer(
            f"Step 3/10: Enter port number\n"
            f"(e.g., 443)"
        )
    
    async def handle_create_config_port(self, message: Message, state: FSMContext):
        try:
            port = int(message.text.strip())
            await state.update_data(port=port)
            await state.set_state(PanelStates.CREATE_CONFIG_SNI)
            await message.answer(
                f"Step 4/10: Enter SNI (optional)\n"
                f"(Press /skip to skip)"
            )
        except ValueError:
            await message.answer("❌ Invalid port. Please enter a number.")
    
    async def handle_create_config_sni(self, message: Message, state: FSMContext):
        if message.text.lower() == "/skip":
            await state.update_data(sni=None)
        else:
            await state.update_data(sni=message.text.strip())
        await state.set_state(PanelStates.CREATE_CONFIG_PATH)
        await message.answer(
            f"Step 5/10: Enter path (optional)\n"
            f"(Press /skip to skip)"
        )
    
    async def handle_create_config_path(self, message: Message, state: FSMContext):
        if message.text.lower() == "/skip":
            await state.update_data(path=None)
        else:
            await state.update_data(path=message.text.strip())
        await state.set_state(PanelStates.CREATE_CONFIG_SECURITY)
        await message.answer(
            f"Step 6/10: Enter security (optional)\n"
            f"(e.g., reality, tls, none)"
        )
    
    async def handle_create_config_security(self, message: Message, state: FSMContext):
        await state.update_data(security=message.text.strip() or None)
        await state.set_state(PanelStates.CREATE_CONFIG_EXPIRY)
        await message.answer(
            f"Step 7/10: Enter expiry days\n"
            f"(e.g., 30 for 30 days)"
        )
    
    async def handle_create_config_expiry(self, message: Message, state: FSMContext):
        try:
            days = int(message.text.strip())
            await state.update_data(expiry_days=days)
            await state.set_state(PanelStates.CREATE_CONFIG_TRAFFIC)
            await message.answer(
                f"Step 8/10: Enter traffic limit (GB)\n"
                f"(e.g., 100)"
            )
        except ValueError:
            await message.answer("❌ Invalid number. Please enter days.")
    
    async def handle_create_config_traffic(self, message: Message, state: FSMContext):
        try:
            traffic = float(message.text.strip())
            await state.update_data(traffic_gb=traffic)
            await state.set_state(PanelStates.CREATE_CONFIG_PRICE)
            await message.answer(
                f"Step 9/10: Enter price (USD)\n"
                f"(e.g., 9.99)"
            )
        except ValueError:
            await message.answer("❌ Invalid number. Please enter GB.")
    
    async def handle_create_config_price(self, message: Message, state: FSMContext):
        try:
            price = float(message.text.strip())
            await state.update_data(price=price)
            await state.set_state(PanelStates.CREATE_CONFIG_NOTES)
            await message.answer(
                f"Step 10/10: Enter notes (optional)\n"
                f"(Press /skip to skip)"
            )
        except ValueError:
            await message.answer("❌ Invalid price. Please enter a number.")
    
    async def handle_create_config_notes(self, message: Message, state: FSMContext):
        if message.text.lower() == "/skip":
            await state.update_data(notes=None)
        else:
            await state.update_data(notes=message.text.strip())
        
        data = await state.get_data()
        
        # Create config
        config = self.config_service.create_config(
            protocol=data["protocol"],
            server=data["server"],
            port=data["port"],
            expiry_days=data["expiry_days"],
            traffic_gb=data["traffic_gb"],
            price=data["price"],
            sni=data.get("sni"),
            path=data.get("path"),
            security=data.get("security"),
            notes=data.get("notes")
        )
        
        user = self.db.get_user_by_telegram_id(message.from_user.id)
        self.db.log_action(user.id, "create_config", f"Config {config.id} created")
        
        await state.clear()
        await message.answer(
            f"✅ **Config Created Successfully!**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{config.id}`\n"
            f"📡 Protocol: `{config.protocol}`\n"
            f"🌐 Server: `{config.server}`\n"
            f"📅 Expiry: `{config.expiry_date[:10]}`\n"
            f"💰 Price: `${config.price:.2f}`\n\n"
            f"Use /start to return to the main menu.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 View Config", callback_data=f"view_config_{config.id}")],
                [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="main_menu")]
            ])
        )
    
    async def cb_list_configs(self, callback: CallbackQuery):
        configs = self.db.get_all_configs()
        
        if not configs:
            await callback.message.edit_text(
                "📋 **No configs found.**\n\n"
                "Create your first config using the menu.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Create Config", callback_data="create_config")],
                    [InlineKeyboardButton(text="🔙 Back", callback_data="manage_configs")]
                ]),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        # Show first 10 configs
        keyboard = []
        for config in configs[:10]:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{config.id} - {config.protocol} ({config.status.value})",
                    callback_data=f"view_config_{config.id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="manage_configs")])
        
        await callback.message.edit_text(
            f"📋 **Configs List**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Total: {len(configs)}\n"
            f"Showing: {min(10, len(configs))}\n\n"
            f"Click a config to view details:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_view_config(self, callback: CallbackQuery):
        config_id = int(callback.data.split("_")[2])
        config = self.db.get_config(config_id)
        
        if not config:
            await callback.answer("❌ Config not found")
            return
        
        user = None
        if config.user_id:
            user = self.db.get_user(config.user_id)
        
        # Generate VIP message
        vip_message = self.config_service.generate_vip_message(config, user)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📌 Assign User", callback_data=f"assign_config_{config.id}"),
                InlineKeyboardButton(text="🔧 Change Status", callback_data=f"change_status_{config.id}")
            ],
            [
                InlineKeyboardButton(text="🗑️ Delete", callback_data=f"delete_config_{config.id}"),
                InlineKeyboardButton(text="🔙 Back", callback_data="list_configs")
            ]
        ])
        
        await callback.message.edit_text(
            vip_message,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_delete_config(self, callback: CallbackQuery, state: FSMContext):
        config_id = int(callback.data.split("_")[2])
        await state.update_data(delete_config_id=config_id)
        await state.set_state(PanelStates.DELETE_CONFIG_ID)
        
        await callback.message.edit_text(
            f"⚠️ **Delete Config**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Are you sure you want to delete config #{config_id}?\n\n"
            f"Type `YES` to confirm, or `CANCEL` to abort.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Cancel", callback_data="manage_configs")]
            ])
        )
        await callback.answer()
    
    async def handle_delete_config_id(self, message: Message, state: FSMContext):
        if message.text.upper() == "YES":
            data = await state.get_data()
            config_id = data.get("delete_config_id")
            self.db.delete_config(config_id)
            
            user = self.db.get_user_by_telegram_id(message.from_user.id)
            self.db.log_action(user.id, "delete_config", f"Config {config_id} deleted")
            
            await message.answer("✅ Config deleted successfully.")
        else:
            await message.answer("❌ Deletion cancelled.")
        
        await state.clear()
        await self.cmd_start(message, state)
    
    async def cb_assign_config(self, callback: CallbackQuery, state: FSMContext):
        config_id = int(callback.data.split("_")[2])
        await state.update_data(assign_config_id=config_id)
        await state.set_state(PanelStates.ASSIGN_USER_ID)
        
        await callback.message.edit_text(
            f"📌 **Assign Config**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Enter the Telegram ID of the user to assign this config to:\n\n"
            f"Config ID: `{config_id}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Cancel", callback_data="manage_configs")]
            ])
        )
        await callback.answer()
    
    async def handle_assign_user_id(self, message: Message, state: FSMContext):
        try:
            telegram_id = int(message.text.strip())
            data = await state.get_data()
            config_id = data.get("assign_config_id")
            
            if self.config_service.assign_to_user(config_id, telegram_id):
                await message.answer(
                    f"✅ Config #{config_id} assigned to user {telegram_id} successfully!"
                )
                user = self.db.get_user_by_telegram_id(message.from_user.id)
                self.db.log_action(user.id, "assign_config", f"Config {config_id} -> User {telegram_id}")
            else:
                await message.answer("❌ Failed to assign config. User not found.")
        except ValueError:
            await message.answer("❌ Invalid Telegram ID. Please enter a number.")
        
        await state.clear()
        await self.cmd_start(message, state)
    
    async def cb_change_status(self, callback: CallbackQuery, state: FSMContext):
        config_id = int(callback.data.split("_")[2])
        await state.update_data(status_config_id=config_id)
        await state.set_state(PanelStates.CHANGE_STATUS_NEW)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ACTIVE", callback_data="status_active")],
            [InlineKeyboardButton(text="❌ EXPIRED", callback_data="status_expired")],
            [InlineKeyboardButton(text="⚠️ SUSPENDED", callback_data="status_suspended")],
            [InlineKeyboardButton(text="🔙 Cancel", callback_data="manage_configs")]
        ])
        
        await callback.message.edit_text(
            f"🔧 **Change Status**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Select new status for config #{config_id}:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    # ===== USER MANAGEMENT =====
    async def cb_list_users(self, callback: CallbackQuery):
        users = self.db.db.get_all_users()
        
        if not users:
            await callback.message.edit_text(
                "👥 **No users found.**",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Back", callback_data="manage_users")]
                ]),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        keyboard = []
        for user in users[:15]:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"@{user.username or user.telegram_id} ({user.role.value})",
                    callback_data=f"view_user_{user.telegram_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="manage_users")])
        
        await callback.message.edit_text(
            f"👥 **Users List**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Total: {len(users)}\n\n"
            f"Click a user to manage:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_view_user(self, callback: CallbackQuery):
        telegram_id = int(callback.data.split("_")[2])
        user = self.db.get_user_by_telegram_id(telegram_id)
        
        if not user:
            await callback.answer("❌ User not found")
            return
        
        configs = self.db.get_configs_by_user(user.id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="👑 Set Role", callback_data=f"set_role_{user.telegram_id}"),
                InlineKeyboardButton(text="💰 Set Balance", callback_data=f"set_balance_{user.telegram_id}")
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Ban" if not user.banned else "✅ Unban",
                    callback_data=f"ban_user_{user.telegram_id}" if not user.banned else f"unban_user_{user.telegram_id}"
                ),
                InlineKeyboardButton(text="📋 Configs", callback_data=f"view_user_configs_{user.telegram_id}")
            ],
            [InlineKeyboardButton(text="🔙 Back", callback_data="list_users")]
        ])
        
        await callback.message.edit_text(
            f"👤 **User Details**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{user.telegram_id}`\n"
            f"👤 Username: @{user.username or 'Unknown'}\n"
            f"📋 Role: `{user.role.value.upper()}`\n"
            f"💰 Balance: `${user.balance:.2f}`\n"
            f"📌 Status: {'🚫 Banned' if user.banned else '✅ Active'}\n"
            f"📅 Created: `{user.created_at[:10]}`\n"
            f"📡 Configs: {len(configs)}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🟡 **{Config.BRAND}**",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_set_role(self, callback: CallbackQuery, state: FSMContext):
        telegram_id = int(callback.data.split("_")[2])
        await state.update_data(role_user_id=telegram_id)
        await state.set_state(PanelStates.SET_ROLE_TARGET)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👑 Owner", callback_data="role_owner")],
            [InlineKeyboardButton(text="🛡️ Admin", callback_data="role_admin")],
            [InlineKeyboardButton(text="🤝 Support", callback_data="role_support")],
            [InlineKeyboardButton(text="💼 Reseller", callback_data="role_reseller")],
            [InlineKeyboardButton(text="👤 User", callback_data="role_user")],
            [InlineKeyboardButton(text="🔙 Cancel", callback_data="manage_users")]
        ])
        
        await callback.message.edit_text(
            f"👑 **Set Role**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Select new role for user {telegram_id}:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_set_balance(self, callback: CallbackQuery, state: FSMContext):
        telegram_id = int(callback.data.split("_")[2])
        await state.update_data(balance_user_id=telegram_id)
        await state.set_state(PanelStates.SET_BALANCE_AMOUNT)
        
        await callback.message.edit_text(
            f"💰 **Set Balance**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Enter new balance for user {telegram_id}:\n"
            f"(Use +amount to add, -amount to subtract)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Cancel", callback_data="manage_users")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_view_user_configs(self, callback: CallbackQuery, state: FSMContext):
        telegram_id = int(callback.data.split("_")[3])
        user = self.db.get_user_by_telegram_id(telegram_id)
        
        if not user:
            await callback.answer("❌ User not found")
            return
        
        configs = self.db.get_configs_by_user(user.id)
        
        if not configs:
            await callback.answer("No configs for this user")
            return
        
        keyboard = []
        for config in configs[:10]:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{config.id} - {config.protocol} ({config.status.value})",
                    callback_data=f"view_config_{config.id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"view_user_{telegram_id}")])
        
        await callback.message.edit_text(
            f"📡 **User Configs**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"User: @{user.username or user.telegram_id}\n"
            f"Total: {len(configs)}\n\n"
            f"Click a config to view:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    # ===== FINANCE =====
    async def cb_finance_report(self, callback: CallbackQuery):
        transactions = self.db.get_transactions(limit=100)
        
        if not transactions:
            await callback.message.edit_text(
                "📊 **No transactions found.**",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Back", callback_data="finance")]
                ]),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        total = sum(t.amount for t in transactions)
        today = datetime.now().date()
        today_transactions = [t for t in transactions if t.created_at.startswith(str(today))]
        today_total = sum(t.amount for t in today_transactions)
        
        report = (
            f"📊 **Daily Finance Report**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Date: {today}\n"
            f"💵 Today Revenue: ${today_total:.2f}\n"
            f"💰 Total Revenue: ${total:.2f}\n"
            f"📊 Transactions: {len(transactions)}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 **Recent Transactions:**\n"
        )
        
        for t in transactions[:10]:
            report += f"  • ${t.amount:.2f} - Config #{t.config_id} ({t.created_at[:10]})\n"
        
        report += f"\n🟡 **{Config.BRAND}**"
        
        await callback.message.edit_text(
            report,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊 Weekly Report", callback_data="finance_report_weekly")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="finance")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_reseller_report(self, callback: CallbackQuery):
        resellers = []
        all_users = self.db.db.get_all_users()
        
        for user in all_users:
            if user.role == UserRole.RESELLER:
                configs = self.db.get_configs_by_user(user.id)
                resellers.append({
                    "user": user,
                    "configs": configs,
                    "revenue": sum(c.price for c in configs if c.status == ConfigStatus.ACTIVE)
                })
        
        if not resellers:
            await callback.message.edit_text(
                "🏪 **No resellers found.**",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Back", callback_data="finance")]
                ]),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        report = (
            f"🏪 **Reseller Report**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Total Resellers: {len(resellers)}\n\n"
        )
        
        for r in resellers:
            report += f"👤 @{r['user'].username or r['user'].telegram_id}\n"
            report += f"  📡 Configs: {len(r['configs'])}\n"
            report += f"  💰 Revenue: ${r['revenue']:.2f}\n"
            report += f"  💳 Balance: ${r['user'].balance:.2f}\n\n"
        
        report += f"🟡 **{Config.BRAND}**"
        
        await callback.message.edit_text(
            report,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="finance")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    # ===== SYSTEM =====
    async def cb_system_settings(self, callback: CallbackQuery):
        await callback.message.edit_text(
            f"⚙️ **System Settings**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 Owner ID: `{Config.OWNER_ID}`\n"
            f"🔹 Database: `{Config.DB_PATH}`\n"
            f"🔹 Brand: `{Config.BRAND}`\n"
            f"🔹 Max Configs/User: `{Config.MAX_CONFIGS_PER_USER}`\n"
            f"🔹 Default Expiry: `{Config.DEFAULT_EXPIRY_DAYS} days`\n\n"
            f"📌 **Configuration**\n"
            f"• Edit .env file to change settings\n"
            f"• Restart bot to apply changes\n\n"
            f"🟡 **{Config.BRAND}**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="system")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    async def cb_view_logs(self, callback: CallbackQuery):
        # Simple log viewer - just show recent actions from audit log
        log_entries = []
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT 20"
            ).fetchall()
            for row in rows:
                user = self.db.get_user(row["user_id"])
                username = f"@{user.username}" if user else f"ID:{row['user_id']}"
                log_entries.append(
                    f"• [{row['created_at'][:16]}] {username}: {row['action']} - {row['details']}"
                )
        
        if not log_entries:
            await callback.answer("No logs available")
            return
        
        log_text = (
            f"📜 **Audit Log**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Recent 20 actions:\n\n"
            f"{chr(10).join(log_entries[:15])}\n\n"
            f"🟡 **{Config.BRAND}**"
        )
        
        await callback.message.edit_text(
            log_text[:4096],  # Telegram message limit
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="system")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
    
    # ===== RUN =====
    async def run(self):
        print(f"🌟 Starting {Config.BRAND} Panel...")
        print(f"✨ {Config.VIP_STYLE}")
        print(f"👤 Owner ID: {Config.OWNER_ID}")
        print(f"📊 Database: {Config.DB_PATH}")
        print("━" * 40)
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            await self.bot.session.close()

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
        await callback.answer()
    
    async def cb_ban_user(self, callback: CallbackQuery):
        telegram_id = int(callback.data.split("_")[2])
        self.db.ban_user(telegram_id)
        
        user = self.db.get_user_by_telegram_id(callback.from_user.id)
        self.db.log_action(user.id, "ban_user", f"Banned {telegram_id}")
        
        await callback.answer("✅ User banned successfully")
        await self.cb_view_user(callback)
    
    async def cb_unban_user(self, callback: CallbackQuery):
        telegram_id = int(callback.data.split("_")[2])
        self.db.unban_user(telegram_id)
        
        user = self.db.get_user_by_telegram_id(callback.from_user.id)
        self.db.log_action(user.id, "unban_user", f"Unbanned {telegram_id}")
        
        await callback.answer("✅ User unbanned successfully")
        await self.cb_view_user(callback)
    
    async def cb_ban_user(self, callback: CallbackQuery):
        telegram_id = int(callback.data.split("_")[2])
        self.db.ban_user(telegram_id)
        
        user = self.db.get_user_by_telegram_id(callback.from_user.id)
        self.db.log_action(user.id, "ban_user", f"Banned {telegram_id}")
        
        await callback.answer("✅ User banned successfully")
        await self.cb_view_user(callback)
    
    # Add missing handlers to PanelBot
    PanelBot.cb_set_role_target = cb_set_role_target
    PanelBot.cb_ban_user = cb_ban_user
    PanelBot.cb_unban_user = cb_unban_user
    
    # Register additional callbacks
    bot = PanelBot()
    
    # Register the role callback
    for role_cb in ["role_owner", "role_admin", "role_support", "role_reseller", "role_user"]:
        bot.dp.callback_query.register(
            PanelBot.cb_set_role_target,
            F.data == role_cb
        )
    
    bot.dp.callback_query.register(PanelBot.cb_ban_user, F.data.startswith("ban_user_"))
    bot.dp.callback_query.register(PanelBot.cb_unban_user, F.data.startswith("unban_user_"))
    
    # Run the bot
    asyncio.run(bot.run())

if __name__ == "__main__":
    main()
