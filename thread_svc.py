import time
import os
import threading
import datetime
import random

import socks
import schedule
from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest, InviteToChannelRequest
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.errors import AuthKeyUnregisteredError, UserBannedInChannelError, PeerFloodError, \
    UserChannelsTooMuchError, ChatWriteForbiddenError, UserDeactivatedError, ChannelPrivateError, \
    PhoneNumberOccupiedError, UserNotMutualContactError, UserPrivacyRestrictedError, UserKickedError
from telegram import Bot, ParseMode
from sqlalchemy import desc

from models import TelegramAccount, Contact, Task, Proxy, InviteError
from database import session
from getsmscode_svc import get_summary, get_sms, get_mobile_number, blacklist_mobile_number
from randomuser_svc import get_random_first_last_names
import config

bot = Bot(config.TELEGRAM_TOKEN)


def run_threaded(job_func, args=None):
    if args is None:
        job_thread = threading.Thread(target=job_func)
    else:
        job_thread = threading.Thread(target=job_func, args=args)
    job_thread.start()


def start_schedule():
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            config.logger.exception(e)


def register_accounts(limit):
    registered_count = 0
    fails_count = 0
    while registered_count < limit:
        summary = get_summary()
        if summary is None or summary['balance'] < 0.12:
            fails_count += 1
            continue
        number = get_mobile_number()
        if number is None:
            fails_count += 1
            continue
        proxy = session.query(Proxy).first()
        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, '+' + str(number)),
                                config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                                proxy=(socks.HTTP, proxy.ip, proxy.port,
                                       True, proxy.username, proxy.password))
        try:
            client.connect()
            client.send_code_request('+'+str(number), force_sms=True)
            send_code_time = datetime.datetime.now()
            sms = None
            while (datetime.datetime.now() - send_code_time).total_seconds() < 65:
                sms = get_sms(number)
                if sms:
                    break
                else:
                    time.sleep(10)
            if sms is None:
                fails_count += 1
                blacklist_mobile_number(number)
                client.disconnect()
                continue

            try:
                name = get_random_first_last_names()
                myself = None
                try:
                    myself = client.sign_up(sms, first_name=name['first'], last_name=name['last'])
                except PhoneNumberOccupiedError:
                    config.logger.error('PhoneNumberOccupiedError, trying to login instead.')
                    try:
                        myself = client.sign_in('+'+str(number), sms)
                    except Exception as e:
                        config.logger.exception(e)
                        fails_count += 1
                if myself:
                    registered_count += 1
                    client.send_message('llelloboss',
                                        'Hello! This account ({}) is'
                                        ' active.'.format('+'+str(number)))
                    account = TelegramAccount(phone_number='+' + str(number))
                    session.add(account)
                    session.commit()

                client.disconnect()
            except Exception as e:
                config.logger.exception(e)
                fails_count += 1
                client.disconnect()
                continue
        except Exception as e:
            config.logger.exception(e)
            if client.is_connected():
                client.disconnect()
            fails_count += 1

    for adm in config.ADMIN_IDS:
        bot.send_message(adm, f'Registration finished.\n'
                              f'Registered: {registered_count}\n' 
                              f'Failed: {fails_count}')


def scrape_contacts(group, phone_number=None):
    if phone_number is None:
        free_accounts = session.query(TelegramAccount).filter(
            TelegramAccount.active == True,
            TelegramAccount.task == None
        ).all()
        account = random.choice(free_accounts)
        if not account:
            active_accounts = session.query(TelegramAccount).filter(
                TelegramAccount.active == True
            ).all()
            account = random.choice(active_accounts)
            if not account:
                for adm in config.ADMIN_IDS:
                    bot.send_message(adm,
                                     f'No available accounts for scrapping. '
                                     f'Add an account at first.')
                return
    else:
        account = session.query(TelegramAccount).filter(
            TelegramAccount.phone_number == phone_number,
        ).first()
    try:
        proxy = session.query(Proxy).first()
        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, account.phone_number),
                                config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                                proxy=(socks.HTTP, proxy.ip, proxy.port,
                                       True, proxy.username, proxy.password))
        client.connect()
        if isinstance(group, dict):
            group_link = group['id']
        else:
            group_link = group.lower()
        account_id = client.get_me().id
        group = client.get_entity(group_link)
        participants = client.get_participants(group, aggressive=True)
        last_messages = client.get_messages(group, 1000)
        last_active_users_ids = set([msg.from_id for msg in last_messages])
        if client.get_me().id not in [i.id for i in participants]:
            client(JoinChannelRequest(group))
        channel_admins = client.get_participants(group, filter=ChannelParticipantsAdmins)
        admins_list = list()
        for i in channel_admins:
            admins_list.append(i)
        admins_ids = [i.id for i in admins_list]
        client.disconnect()
        filtered_participants = [p for p in list(participants) if not p.bot and
                                 p.id not in admins_ids and
                                 p.id != account_id and p.username]
        contacts = [Contact(tg_id=user.id, source_group=group_link, username=user.username,
                            source_group_name=group.title,
                            priority=Contact.PRIORITY_HIGH
                            if user.id in last_active_users_ids
                            else Contact.PRIORITY_LOW)
                    for user in filtered_participants]
        session.add_all(contacts)
        session.commit()
        for adm in config.ADMIN_IDS:
            bot.send_message(adm, f'Scrapped {len(filtered_participants)} from {group.title}.\n'
                                  f'Skipped {abs(len(filtered_participants)-len(participants))} '
                                  f'admins, bots and users without usernames.')
    except Exception as e:
        for adm in config.ADMIN_IDS:
            bot.send_message(adm, str(e))


def perform_tasks():
    tasks = session.query(Task).all()
    for task in tasks:
        if task.last_invite != None:
            delta = datetime.datetime.now() - task.last_invite
            seconds_passed = delta.total_seconds()
            interval = [
                (task.interval * 60) - (task.interval * 60) * 0.1,
                (task.interval * 60) + (task.interval * 60) * 0.3,
            ]
            random_interval = random.randint(interval[0], interval[1])
            if seconds_passed > random_interval:
                contacts = session.query(Contact).filter(
                    Contact.source_group == task.source_group
                ).all()
                invited_contacts = session.query(Contact).filter(Contact.task == task).all()
                if len(invited_contacts) < task.invites_limit and \
                        len(contacts) > len(invited_contacts):
                    invited = invite_contact(task.id)
                    if invited:
                        task.last_invite = datetime.datetime.now()
                        session.commit()
                else:
                    session.delete(task)
                    session.commit()
                    for adm in config.ADMIN_IDS:
                        bot.send_message(adm,
                                         f'<code>Inviting to {task.target_group} '
                                         f'from {task.source_group}</code> completed.\n'
                                         f'Invited {len(task.invited_contacts)} users.',
                                         parse_mode=ParseMode.HTML)
            else:
                continue
        else:
            contacts = session.query(Contact).filter(
                Contact.source_group == task.source_group
            ).all()
            invited_contacts = session.query(Contact).filter(Contact.task == task).all()
            if len(invited_contacts) < task.invites_limit and \
                    len(contacts) > len(invited_contacts):
                invite_contact(task.id)
                task.last_invite = datetime.datetime.now()
                session.commit()
            else:
                session.delete(task)
                session.commit()
                for adm in config.ADMIN_IDS:
                    bot.send_message(adm,
                                     f'<code> Inviting to {task.target_group} '
                                     f'from {task.source_group}</code> completed.\n'
                                     f'Invited {len(task.invited_contacts)} users.',
                                     parse_mode=ParseMode.HTML)


def invite_contact(task_id):
    task = session.query(Task).filter(
        Task.id == task_id
    ).first()
    accounts = session.query(TelegramAccount).filter(
        TelegramAccount.active == True,
        TelegramAccount.task == task
    ).order_by(TelegramAccount.last_used).all()
    if not accounts:
        session.delete(task)
        session.commit()
        for adm in config.ADMIN_IDS:
            bot.send_message(adm,
                             f'<code>Inviting to {task.target_group} '
                             f'from {task.source_group}</code> stopped.\n'
                             f'No active accounts left.',
                             parse_mode=ParseMode.HTML)
        return
    account = random.choice(accounts)
    contacts = session.query(Contact).filter(
        Contact.source_group == task.source_group
    ).order_by(desc(Contact.priority)).all()
    invite_errors = session.query(InviteError).filter(
        InviteError.task == task
    ).all()
    contacts_with_errors_ids = [i.contact_id for i in invite_errors]
    invited_contacts_ids = [c.id for c in task.invited_contacts]
    contacts = [c for c in contacts if c.id not in invited_contacts_ids and
                c.id not in contacts_with_errors_ids]
    proxy = session.query(Proxy).first()
    client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, account.phone_number),
                            config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                            proxy=(socks.HTTP, proxy.ip, proxy.port,
                                   True, proxy.username, proxy.password))
    try:
        client.connect()
        target_participants = client.get_participants(task.target_group, aggressive=True)
        target_participants_ids = [i.id for i in target_participants]
        if int(contacts[0].tg_id) not in target_participants_ids:
            target = int(task.target_group) if task.target_group.startswith('-') \
                else task.target_group.lower()
            if int(client.get_me().id) not in target_participants_ids:
                client(JoinChannelRequest(target))
            client(InviteToChannelRequest(target, [contacts[0].username]))
            task.invited_contacts.append(contacts[0])
            account.last_used = datetime.datetime.now()
            session.commit()
        else:
            error = InviteError(task=task, contact=contacts[0])
            session.add(error)
            account.last_used = datetime.datetime.now()
            session.commit()
    except PeerFloodError as e:
        config.logger.exception(e)
        account.active = False
        account.task = None
        account.error_time = datetime.datetime.now()
        session.commit()
    except UserKickedError as e:
        config.logger.exception(e)
        account.active = False
        account.task = None
        account.error_time = datetime.datetime.now()
        session.commit()
    except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
        config.logger.exception(e)
        session.delete(account)
        session.commit()
        path = os.path.join(config.TELETHON_SESSIONS_DIR,
                            '{}.session'.format(account.phone_number))
        if os.path.exists(path):
            os.remove(path)
        for adm in config.ADMIN_IDS:
            bot.send_message(adm,
                             f'Account {account.phone_number} had {e.__class__.__name__} '
                             f'and was removed.')
    except (UserNotMutualContactError, UserPrivacyRestrictedError) as e:
        config.logger.exception(e)
        error = InviteError(task=task, contact=contacts[0])
        session.add(error)
        session.commit()
    except Exception as e:
        config.logger.exception(e)

    if client.is_connected():
        client.disconnect()
