import os

from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (CommandHandler, Updater, MessageHandler,
                          Filters, CallbackQueryHandler, ConversationHandler)
from telethon import TelegramClient
import socks

import config
from models import TelegramAccount, Task
from database import session
from telegram_svc import restricted, error_callback, build_menu
from thread_svc import run_threaded, register_accounts, scrape_contacts

updater = Updater(token=config.TELEGRAM_TOKEN)
dispatcher = updater.dispatcher


# Conversation states
SET_SOURCE_GROUP, SET_TARGET_GROUP, SET_INVITES_LIMIT, SET_INTERVAL, \
    SET_ACCOUNTS_AMOUNT, SELECT_TASK, TASK_MENU, EDIT_INTERVAL, LOGIN_CODE, SELECT_ACCOUNT, \
    SET_CUSTOM_INTERVAL, SELECT_GROUP, SET_CUSTOM_INVITES_LIMIT, SET_CUSTOM_TARGET_GROUP, \
    SELECT_GROUP_FOR_SCRAPPING = range(15)


def start(bot, update):
    update.message.reply_text("Hello, @{} "
                              "[<code>{}</code>]".format(update.message.from_user.username,
                                                         update.message.chat_id),
                              parse_mode=ParseMode.HTML)


def cancel(bot, update):
    update.message.reply_text("Action cancelled.")
    return ConversationHandler.END


@restricted
def register(bot, update, args):
    if len(args) == 1:
        limit = args[0]
        if not limit.isdigit():
            update.message.reply_text("Limit must be integer value.")
            return
        run_threaded(register_accounts, (int(limit), ))
        update.message.reply_text("Registration process started. "
                                  "Please, wait.")
    else:
        update.message.reply_text("Please, include the limit of new accounts to the "
                                  "command, like in the example:\n"
                                  "<code>/register 10</code>",
                                  parse_mode=ParseMode.HTML)


@restricted
def scrape(bot, update, args):
    if len(args) == 1:
        group = args[0]
        run_threaded(scrape_contacts, (group, ))
        update.message.reply_text("Scrapping started. Please, wait.")
    else:
        update.message.reply_text("Please, include group link to this "
                                  "command, like in the example:\n"
                                  "<code>/scrape https://t.me/source_group</code>",
                                  parse_mode=ParseMode.HTML)


@restricted
def invite(bot, update):
    update.message.reply_text("Send me the link to the source group.")
    return SET_SOURCE_GROUP


@restricted
def source_group(bot, update, user_data):
    user_data['source_group'] = update.message.text
    update.message.reply_text("Now send me the link to the target group.")
    return SET_TARGET_GROUP


@restricted
def target_group(bot, update, user_data):
    user_data['target_group'] = update.message.text
    update.message.reply_text("Send me the invites limit. Maybe, you want to invite only "
                              "10 members of source group, maybe, 5000.")
    return SET_INVITES_LIMIT


@restricted
def invites_limit(bot, update, user_data):
    if update.message.text.isdigit():
        user_data['limit'] = int(update.message.text)
        update.message.reply_text("Now send me the interval to invite people (in minutes). "
                                  "Maybe, every 5 or 15 minutes.")
        return SET_INTERVAL
    else:
        update.message.reply_text("Limit must be integer. Send me a valid limit.")
        return SET_INVITES_LIMIT


@restricted
def interval(bot, update, user_data):
    if update.message.text.isdigit():
        user_data['interval'] = int(update.message.text)
        update.message.reply_text("Send me the amount of accounts for this task.")
        return SET_ACCOUNTS_AMOUNT
    else:
        update.message.reply_text("Interval must be integer. Send me a valid interval.")
        return SET_INTERVAL


@restricted
def accounts_amount(bot, update, user_data):
    if update.message.text.isdigit():
        amount = int(update.message.text)
        task = Task(source_group=user_data['source_group'],
                    target_group=user_data['target_group'],
                    interval=user_data['interval'],
                    invites_limit=user_data['limit'])
        session.add(task)
        session.commit()
        free_accounts = session.query(TelegramAccount).filter(
            TelegramAccount.task == None
        ).limit(amount).all()
        for acc in free_accounts:
            acc.task = task
        session.commit()
        update.message.reply_text("Great! Inviting started.")
        return ConversationHandler.END
    else:
        update.message.reply_text("Amount must be integer. Send me a valid amount.")
        return SET_ACCOUNTS_AMOUNT


@restricted
def tasks(bot, update):
    active_tasks = session.query(Task).all()
    accounts = session.query(TelegramAccount).all()
    active_accounts = [acc for acc in accounts if acc.active == True]
    banned_accounts = [acc for acc in accounts if acc.active == False]
    text = f'<b>Report</b>\n' \
           f'<pre>' \
           f'Tasks: {len(active_tasks)}\n' \
           f'Accounts: {len(accounts)}\n' \
           f'    working: {len(active_accounts)}\n' \
           f'    banned: {len(banned_accounts)}' \
           f'</pre>'\
           f'Please, choose the task or /cancel'

    if active_tasks:

        buttons = [InlineKeyboardButton(f'Inviting to {t.target_group}',
                   callback_data=t.id) for t in active_tasks]
        if len(buttons) > 6:
            buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
            next_page_btn = InlineKeyboardButton('➡️', callback_data='tasks_next_page:1')
            buttons[0].append(next_page_btn)
            reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
        else:
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
        bot.send_message(chat_id=update.message.chat_id,
                         text=text,
                         reply_markup=reply_markup,
                         timeout=30,
                         parse_mode=ParseMode.HTML)
        return SELECT_TASK
    else:
        update.message.reply_text('You don\'t have any tasks yet. '
                                  'Please, /invite at first.')
        return ConversationHandler.END


@restricted
def select_task(bot, update, user_data):
    query = update.callback_query

    if query.data.startswith('tasks_next_page') or \
            query.data.startswith('tasks_prev_page'):
        active_tasks = session.query(Task).all()
        buttons = [InlineKeyboardButton(f'Inviting to {t.target_group}',
                                        callback_data=t.id) for t in active_tasks]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('tasks_next_page'):
            go_to_page = int(query.data.split(':')[1])

        else:
            go_to_page = int(query.data.split(':')[1])

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='tasks_prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='tasks_next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)

        return SELECT_TASK

    else:
        task = session.query(Task).filter(
            Task.id == int(query.data)
        ).first()
        user_data['task_id'] = task.id
        edit_interval_btn = InlineKeyboardButton('Edit interval',
                                                 callback_data='edit_interval')
        delete_task_btn = InlineKeyboardButton('Delete task',
                                               callback_data='delete_task')
        buttons = [edit_interval_btn, delete_task_btn]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons,
                                                       n_cols=2))
        text = f'Inviting to {task.target_group}\n' \
               f'Source group: {task.source_group}\n' \
               f'Accounts used: {len(task.accounts)}\n' \
               f'Interval: every {task.interval} minutes\n' \
               f'Last invite: {task.last_invite} \n' \
               f'Please, choose action or /cancel'
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text=text,
                              reply_markup=reply_markup,
                              timeout=30)
        return TASK_MENU


@restricted
def task_menu(bot, update, user_data):
    query = update.callback_query

    task = session.query(Task).filter(
        Task.id == user_data['task_id']
    ).first()

    if query.data == 'delete_task':
        session.delete(task)
        session.commit()
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Task deleted!',
                              reply_markup=None,
                              timeout=30)
        return ConversationHandler.END
    elif query.data == 'edit_interval':
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Please, send me the new interval '
                                   '(in minutes) or /cancel',
                              reply_markup=None,
                              timeout=30)
        return EDIT_INTERVAL


@restricted
def edit_interval(bot, update, user_data):
    value = update.message.text
    if value.isdigit():
        task = session.query(Task).filter(
            Task.id == user_data['task_id'],
        ).first()
        task.interval = int(value)
        session.commit()
        update.message.reply_text('Interval changed.')
    else:
        update.message.reply_text('You entered wrong value.')

    return ConversationHandler.END


@restricted
def add_account(bot, update, args, user_data):
    if len(args) == 1:
        phone_number = args[0]
        accounts = session.query(TelegramAccount).filter(
            TelegramAccount.phone_number == phone_number
        ).all()
        phone_numbers = [s.phone_number for s in accounts]
        if phone_number in phone_numbers:
            update.message.reply_text("Sorry, this phone number already exists.")
            return ConversationHandler.END
        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, phone_number),
                                config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                                proxy=(socks.SOCKS5, 'localhost', 9050))
        client.connect()

        result = client.send_code_request(phone_number, force_sms=True)
        client.disconnect()
        user_data['phone_number'] = phone_number
        user_data['phone_code_hash'] = result.phone_code_hash
        update.message.reply_text("Please, send the login code to continue")
        return LOGIN_CODE
    else:
        update.message.reply_text("Please, include the phone number to this "
                                  "command.")
        return ConversationHandler.END


@restricted
def confirm_tg_account(bot, update, user_data):
    code = update.message.text
    client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, user_data['phone_number']),
                            config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                            proxy=(socks.SOCKS5, 'localhost', 9050))
    client.connect()

    try:
        client.sign_in(user_data['phone_number'], code,
                       phone_code_hash=user_data['phone_code_hash'])
        account = TelegramAccount(phone_number=user_data['phone_number'])
        session.add(account)
        session.commit()
        update.message.reply_text('Account added successfully.')
    except Exception as e:
        update.message.reply_text('Error: {}.'.format(e))
        path = os.path.join(config.TELETHON_SESSIONS_DIR,
                            '{}.session'.format(user_data['phone_number']))
        if os.path.exists(path):
            os.remove(path)

    client.disconnect()

    return ConversationHandler.END


@restricted
def custom_inviting(bot, update):
    accounts = session.query(TelegramAccount).filter(
        TelegramAccount.active == True,
        TelegramAccount.task == None
    ).order_by(TelegramAccount.created_at).all()
    if accounts:
        buttons = [InlineKeyboardButton(s.phone_number, callback_data=s.id)
                   for s in accounts]
        if len(buttons) > 6:
            buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
            next_page_btn = InlineKeyboardButton('➡️', callback_data='next_page:1')
            buttons[0].append(next_page_btn)
            reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
        else:
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
        bot.send_message(chat_id=update.message.chat_id,
                         text='Please, choose the account or /cancel',
                         reply_markup=reply_markup,
                         timeout=30)
        return SELECT_ACCOUNT
    else:
        update.message.reply_text('You don\'t have any active accounts yet. '
                                  'Please, /register or /add_account at first.')
        return ConversationHandler.END


@restricted
def select_account(bot, update, user_data):
    query = update.callback_query

    if query.data.startswith('next_page') or query.data.startswith('prev_page'):
        accounts = session.query(TelegramAccount).filter(
            TelegramAccount.active == True,
            TelegramAccount.task == None
        ).order_by(TelegramAccount.created_at).all()
        buttons = [InlineKeyboardButton(s.phone_number, callback_data=s.id)
                   for s in accounts]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('next_page'):
            go_to_page = int(query.data.split(':')[1])

        else:
            go_to_page = int(query.data.split(':')[1])

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)

        return SELECT_ACCOUNT

    else:
        account = session.query(TelegramAccount).filter(
            TelegramAccount.id == int(query.data),
        ).first()
        user_data['account_id'] = account.id
        user_data['phone_number'] = account.phone_number
        bot.edit_message_text(chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              text='Great! Now send me the interval for inviting '
                                   '(in minutes).',
                              timeout=30)
        return SET_CUSTOM_INTERVAL


@restricted
def custom_interval(bot, update, user_data):
    value = update.message.text
    if value.isdigit():
        user_data['interval'] = interval.id
        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, user_data['phone_number']),
                                config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                                proxy=(socks.SOCKS5, 'localhost', 9050))
        client.connect()
        try:
            dialogs = client.get_dialogs()
        except Exception as e:
            update.message.reply_text('Error happened. Can\'t get groups.')
            config.logger.exception(e)
            return ConversationHandler.END
        client.disconnect()
        groups = [{'id': i.id, 'title': i.title}
                  for i in dialogs if i.is_group]
        user_data['groups'] = groups
        if groups:
            buttons = [InlineKeyboardButton(g['title'], callback_data=g['id'])
                       for g in groups]
            if len(buttons) > 6:
                buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
                next_page_btn = InlineKeyboardButton('➡️', callback_data='next_page:1')
                buttons[0].append(next_page_btn)
                reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
            else:
                reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
            user_data['page'] = 0
            bot.send_message(chat_id=update.message.chat_id,
                             text='Please, choose a group to invite users from.',
                             parse_mode=ParseMode.MARKDOWN,
                             reply_markup=reply_markup,
                             timeout=30)
            return SELECT_GROUP
        else:
            update.message.reply_text('This account doesn\'t have any groups. '
                                      'Try using another account via /add_account')
            return ConversationHandler.END
    else:
        update.message.reply_text('Oops! Interval has to be integer '
                                  'value (in minutes). Send me another '
                                  'interval.')
        return SET_CUSTOM_INTERVAL


@restricted
def select_group(bot, update, user_data):
    query = update.callback_query

    if query.data.startswith('next_page') or query.data.startswith('prev_page'):
        buttons = [InlineKeyboardButton(g['title'], callback_data=g['id'])
                   for g in user_data['groups']]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('next_page'):
            go_to_page = int(query.data.split(':')[1])
        else:
            go_to_page = int(query.data.split(':')[1])

        user_data['page'] = go_to_page

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        user_data['page'] = go_to_page

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)
        return SELECT_GROUP
    else:
        user_data['source_group'] = query.data
        update.message.reply_text("Now send me the link to target group.")
        return SET_CUSTOM_TARGET_GROUP


@restricted
def custom_target_group(bot, update, user_data):
    user_data['target_group'] = update.message.text
    update.message.reply_text("Send me the invites limit. Maybe, you want to invite only "
                              "10 members of source group, maybe, 5000.")
    return SET_CUSTOM_INVITES_LIMIT


@restricted
def custom_invites_limit(bot, update, user_data):
    if update.message.text.isdigit():
        amount = int(update.message.text)
        account = session.query(TelegramAccount).filter(
            TelegramAccount.id == user_data['account_id']
        ).first()
        task = Task(source_group=user_data['source_group'],
                    target_group=user_data['target_group'],
                    interval=user_data['interval'],
                    invites_limit=amount)
        session.add(task)
        account.task = task
        session.commit()
        update.message.reply_text("Great! Inviting started.")
        return ConversationHandler.END
    else:
        update.message.reply_text("Limit must be integer. Send me a valid limit.")
        return SET_CUSTOM_INVITES_LIMIT


@restricted
def custom_scrape(bot, update, args, user_data):
    if len(args) == 1:
        phone_number = args[0]
        user_data['phone_number'] = phone_number
        client = TelegramClient(os.path.join(config.TELETHON_SESSIONS_DIR, phone_number),
                                config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                                proxy=(socks.SOCKS5, 'localhost', 9050))
        client.connect()
        try:
            dialogs = client.get_dialogs()
        except Exception as e:
            update.message.reply_text('Error happened. Can\'t get groups.')
            config.logger.exception(e)
            return ConversationHandler.END
        client.disconnect()
        groups = [{'id': i.id, 'title': i.title}
                  for i in dialogs if i.is_group]
        user_data['groups'] = groups
        if groups:
            buttons = [InlineKeyboardButton(g['title'], callback_data=g['id'])
                       for g in groups]
            if len(buttons) > 6:
                buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
                next_page_btn = InlineKeyboardButton('➡️', callback_data='next_page:1')
                buttons[0].append(next_page_btn)
                reply_markup = InlineKeyboardMarkup(build_menu(buttons[0], n_cols=2))
            else:
                reply_markup = InlineKeyboardMarkup(build_menu(buttons, n_cols=2))
            user_data['page'] = 0
            bot.send_message(chat_id=update.message.chat_id,
                             text='Please, choose a group to scrape users from.',
                             parse_mode=ParseMode.MARKDOWN,
                             reply_markup=reply_markup,
                             timeout=30)
            return SELECT_GROUP_FOR_SCRAPPING
    else:
        update.message.reply_text("Please, include phone number of the account that "
                                  "you've added to the"
                                  "command, like in the example:\n"
                                  "<code>/custom_scrape +123456789</code>",
                                  parse_mode=ParseMode.HTML)


@restricted
def select_group_for_scrapping(bot, update, user_data):
    query = update.callback_query

    if query.data.startswith('next_page') or query.data.startswith('prev_page'):
        buttons = [InlineKeyboardButton(g['title'], callback_data=g['id'])
                   for g in user_data['groups']]
        buttons = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]

        if query.data.startswith('next_page'):
            go_to_page = int(query.data.split(':')[1])
        else:
            go_to_page = int(query.data.split(':')[1])

        user_data['page'] = go_to_page

        if go_to_page > 0:
            prev_page_btn = InlineKeyboardButton(
                '⬅️', callback_data='prev_page:{}'.format(go_to_page - 1)
            )
            buttons[go_to_page].append(prev_page_btn)
        if go_to_page < len(buttons) - 1:
            next_page_btn = InlineKeyboardButton(
                '➡️', callback_data='next_page:{}'.format(go_to_page + 1)
            )
            buttons[go_to_page].append(next_page_btn)

        user_data['page'] = go_to_page

        reply_markup = InlineKeyboardMarkup(build_menu(buttons[go_to_page],
                                                       n_cols=2))

        bot.edit_message_reply_markup(chat_id=query.message.chat_id,
                                      message_id=query.message.message_id,
                                      reply_markup=reply_markup,
                                      timeout=30)
        return SELECT_GROUP_FOR_SCRAPPING
    else:
        run_threaded(scrape_contacts, (query.data, user_data['phone_number']))
        update.message.reply_text("Scrapping started. Please, wait.")
        return ConversationHandler.END


new_task_handler = ConversationHandler(
    entry_points=[CommandHandler('invite', invite)],
    states={
        SET_SOURCE_GROUP: [MessageHandler(Filters.text, source_group, pass_user_data=True)],
        SET_TARGET_GROUP: [MessageHandler(Filters.text, target_group, pass_user_data=True)],
        SET_INVITES_LIMIT: [MessageHandler(Filters.text, invites_limit, pass_user_data=True)],
        SET_INTERVAL: [MessageHandler(Filters.text, interval, pass_user_data=True)],
        SET_ACCOUNTS_AMOUNT: [MessageHandler(Filters.text, accounts_amount, pass_user_data=True)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

custom_new_task_handler = ConversationHandler(
    entry_points=[CommandHandler('custom_invite', custom_inviting)],
    states={
        SELECT_ACCOUNT: [CallbackQueryHandler(select_account, pass_user_data=True)],
        SET_CUSTOM_INTERVAL: [MessageHandler(Filters.text, custom_interval, pass_user_data=True)],
        SELECT_GROUP: [CallbackQueryHandler(select_group, pass_user_data=True)],
        SET_CUSTOM_TARGET_GROUP: [MessageHandler(Filters.text, custom_target_group, pass_user_data=True)],
        SET_CUSTOM_INVITES_LIMIT: [MessageHandler(Filters.text, custom_invites_limit, pass_user_data=True)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)


edit_tasks_handler = ConversationHandler(
    entry_points=[CommandHandler('tasks', tasks)],
    states={
        SELECT_TASK: [CallbackQueryHandler(select_task, pass_user_data=True)],
        TASK_MENU: [CallbackQueryHandler(task_menu, pass_user_data=True)],
        EDIT_INTERVAL: [MessageHandler(Filters.text, edit_interval, pass_user_data=True)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)


new_tg_account_handler = ConversationHandler(
    entry_points=[CommandHandler('add_account', add_account,
                                 pass_args=True, pass_user_data=True)],
    states={
        LOGIN_CODE: [MessageHandler(Filters.text, confirm_tg_account,
                                    pass_user_data=True)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

custom_scrape_handler = ConversationHandler(
    entry_points=[CommandHandler('custom_scrape', custom_scrape,
                                 pass_args=True, pass_user_data=True)],
    states={
        SELECT_GROUP_FOR_SCRAPPING: [CallbackQueryHandler(select_group_for_scrapping,
                                                          pass_user_data=True)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)


dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CommandHandler('scrape', scrape, pass_args=True))
dispatcher.add_handler(CommandHandler('register', register, pass_args=True))
dispatcher.add_handler(new_task_handler)
dispatcher.add_handler(edit_tasks_handler)
dispatcher.add_handler(new_tg_account_handler)
dispatcher.add_handler(custom_new_task_handler)
dispatcher.add_handler(custom_scrape_handler)
dispatcher.add_error_handler(error_callback)
