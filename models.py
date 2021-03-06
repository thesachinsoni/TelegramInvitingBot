import datetime

from sqlalchemy import Column, Integer, String, \
    ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship

from database import Base


class TelegramAccount(Base):
    __tablename__ = "telegram_account"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String(50))
    created_at = Column(DateTime, default=datetime.datetime.now)
    error_time = Column(DateTime)
    active = Column(Boolean, default=True)
    use_for_inviting = Column(Boolean, default=False)
    last_used = Column(DateTime)
    task_id = Column(Integer, ForeignKey('task.id'))
    task = relationship('Task', backref="accounts")

    def __init__(self, phone_number):
        self.phone_number = phone_number


class Task(Base):
    __tablename__ = "task"

    id = Column(Integer, primary_key=True)
    source_group = Column(String(300))
    target_group = Column(String(300))
    invites_limit = Column(Integer)
    interval = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.now)
    last_invite = Column(DateTime)

    def __init__(self, source_group, target_group, interval, invites_limit):
        self.source_group = source_group
        self.target_group = target_group
        self.interval = interval
        self.invites_limit = invites_limit


class Contact(Base):
    __tablename__ = "contact"

    PRIORITY_HIGH = 1
    PRIORITY_LOW = 0

    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer)
    source_group = Column(String(300))
    source_group_name = Column(String(500))
    created_at = Column(DateTime, default=datetime.datetime.now)
    username = Column(String(300))
    priority = Column(Integer)
    task_id = Column(Integer, ForeignKey('task.id'))
    task = relationship('Task', backref="invited_contacts")

    def __init__(self, tg_id, source_group, source_group_name, username, priority):
        self.tg_id = tg_id
        self.source_group = source_group
        self.source_group_name = source_group_name
        self.username = username
        self.priority = priority


class InviteError(Base):
    __tablename__ = "invite_error"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey('task.id'))
    task = relationship('Task', backref="invite_errors")
    contact_id = Column(Integer, ForeignKey('contact.id'))
    contact = relationship('Contact', backref="invite_errors")

    def __init__(self, task, contact):
        self.task = task
        self.contact = contact


class Proxy(Base):
    __tablename__ = "proxy"

    id = Column(Integer, primary_key=True)
    ip = Column(String(300))
    port = Column(Integer)
    username = Column(String(300))
    password = Column(String(400))

    def __init__(self, ip, port, username, password):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
