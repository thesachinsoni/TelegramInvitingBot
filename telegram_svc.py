from functools import wraps

from telegram.error import TelegramError

import config


def error_callback(bot, update, error):
    try:
        raise error
    except TelegramError as e:
        config.logger.exception(e)


def restricted(func):
    @wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.ADMIN_IDS:
            config.logger.warning("Unauthorized access denied "
                                  "for {}.".format(user_id))
            return
        return func(bot, update, *args, **kwargs)
    return wrapped


def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)
    return menu
