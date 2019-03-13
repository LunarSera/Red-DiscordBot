import discord
from discord.ext import commands
from .utils.dataIO import dataIO
from .utils import checks
from __main__ import send_cmd_help, settings
from datetime import datetime
from collections import deque, defaultdict, OrderedDict
from cogs.utils.chat_formatting import escape_mass_mentions
import os
import re
import logging
import asyncio
import inspect
import textwrap
import time

from .utils.chat_formatting import pagify, box, warning, error, info, bold

try:
    import tabulate
except ImportError as e:
    raise RuntimeError("Punish requires tabulate. To install it, run `pip3 install tabulate` from the console or "
                       "`[p]debug bot.pip_install('tabulate')` from in Discord.") from e

log = logging.getLogger('red.punish')

try:
    from .mod import CaseMessageNotFound, NoModLogAccess
    ENABLE_MODLOG = True
except ImportError:
    log.warn("Could not import modlog exceptions from mod cog, most likely because mod.py was deleted or Red is out of "
             "date. Modlog integration will be disabled.")
    ENABLE_MODLOG = False

__version__ = '2.1.1'

ACTION_STR = "Timed mute \N{HOURGLASS WITH FLOWING SAND} \N{SPEAKER WITH CANCELLATION STROKE}"
PURGE_MESSAGES = 1  # for cpunish
PATH = 'data/punish/'
JSON = PATH + 'settings.json'

DEFAULT_ROLE_NAME = 'Muted'
DEFAULT_TEXT_OVERWRITE = discord.PermissionOverwrite(send_messages=False, read_messages=False, add_reactions=False)
DEFAULT_VOICE_OVERWRITE = discord.PermissionOverwrite(speak=False, connect=False)
DEFAULT_TIMEOUT_OVERWRITE = discord.PermissionOverwrite(send_messages=True, read_messages=True)

QUEUE_TIME_CUTOFF = 30

DEFAULT_TIMEOUT = '30m'
DEFAULT_CASE_MIN_LENGTH = '30m'  # only create modlog cases when length is longer than this

UNIT_TABLE = (
    (('weeks', 'wks', 'w'),    60 * 60 * 24 * 7),
    (('days',  'dys', 'd'),    60 * 60 * 24),
    (('hours', 'hrs', 'h'),    60 * 60),
    (('minutes', 'mins', 'm'), 60),
    (('seconds', 'secs', 's'), 1),
)


class BadTimeExpr(Exception):
    pass


def _find_unit(unit):
    for names, length in UNIT_TABLE:
        if any(n.startswith(unit) for n in names):
            return names, length
    raise BadTimeExpr("Invalid unit: %s" % unit)


def _parse_time(time):
    time = time.lower()
    if not time.isdigit():
        time = re.split(r'\s*([\d.]+\s*[^\d\s,;]*)(?:[,;\s]|and)*', time)
        time = sum(map(_timespec_sec, filter(None, time)))
    return int(time)


def _timespec_sec(expr):
    atoms = re.split(r'([\d.]+)\s*([^\d\s]*)', expr)
    atoms = list(filter(None, atoms))

    if len(atoms) > 2:  # This shouldn't ever happen
        raise BadTimeExpr("invalid expression: '%s'" % expr)
    elif len(atoms) == 2:
        names, length = _find_unit(atoms[1])
        if atoms[0].count('.') > 1 or \
                not atoms[0].replace('.', '').isdigit():
            raise BadTimeExpr("Not a number: '%s'" % atoms[0])
    else:
        names, length = _find_unit('seconds')

    try:
        return float(atoms[0]) * length
    except ValueError:
        raise BadTimeExpr("invalid value: '%s'" % atoms[0])


def _generate_timespec(sec, short=False, micro=False):
    timespec = []

    for names, length in UNIT_TABLE:
        n, sec = divmod(sec, length)

        if n:
            if micro:
                s = '%d%s' % (n, names[2])
            elif short:
                s = '%d%s' % (n, names[1])
            else:
                s = '%d %s' % (n, names[0])
            if n <= 1:
                s = s.rstrip('s')
            timespec.append(s)

    if len(timespec) > 1:
        if micro:
            return ''.join(timespec)

        segments = timespec[:-1], timespec[-1:]
        return ' and '.join(', '.join(x) for x in segments)

    return timespec[0]


def format_list(*items, join='and', delim=', '):
    if len(items) > 1:
        return (' %s ' % join).join((delim.join(items[:-1]), items[-1]))
    elif items:
        return items[0]
    else:
        return ''


def permissions_for_roles(channel, *roles):
    """
    Calculates the effective permissions for a role or combination of roles.
    Naturally, if no roles are given, the default role's permissions are used
    """
    default = channel.server.default_role
    base = discord.Permissions(default.permissions.value)

    # Apply all role values
    for role in roles:
        base.value |= role.permissions.value

    # Server-wide Administrator -> True for everything
    # Bypass all channel-specific overrides
    if base.administrator:
        return discord.Permissions.all()

    role_ids = set(map(lambda r: r.id, roles))
    denies = 0
    allows = 0

    # Apply channel specific role permission overwrites
    for overwrite in channel._permission_overwrites:
        # Handle default role first, if present
        if overwrite.id == default.id:
            base.handle_overwrite(allow=overwrite.allow, deny=overwrite.deny)

        if overwrite.type == 'role' and overwrite.id in role_ids:
            denies |= overwrite.deny
            allows |= overwrite.allow

    base.handle_overwrite(allow=allows, deny=denies)

    # default channels can always be read
    if channel.is_default:
        base.read_messages = True

    # if you can't send a message in a channel then you can't have certain
    # permissions as well
    if not base.send_messages:
        base.send_tts_messages = False
        base.mention_everyone = False
        base.embed_links = False
        base.attach_files = False

    # if you can't read a channel then you have no permissions there
    if not base.read_messages:
        denied = discord.Permissions.all_channel()
        base.value &= ~denied.value

    # text channels do not have voice related permissions
    if channel.type is discord.ChannelType.text:
        denied = discord.Permissions.voice()
        base.value &= ~denied.value

    return base


def overwrite_from_dict(data):
    allow = discord.Permissions(data.get('allow', 0))
    deny = discord.Permissions(data.get('deny', 0))
    return discord.PermissionOverwrite.from_pair(allow, deny)


def overwrite_to_dict(overwrite):
    allow, deny = overwrite.pair()
    return {
        'allow' : allow.value,
        'deny'  : deny.value
    }


def format_permissions(permissions, include_null=False):
    entries = []

    for perm, value in sorted(permissions, key=lambda t: t[0]):
        if value is True:
            symbol = "\N{WHITE HEAVY CHECK MARK}"
        elif value is False:
            symbol = "\N{NO ENTRY SIGN}"
        elif include_null:
            symbol = "\N{RADIO BUTTON}"
        else:
            continue

        entries.append(symbol + ' ' + perm.replace('_', ' ').title().replace("Tts", "TTS"))

    if entries:
        return '\n'.join(entries)
    else:
        return "No permission entries."


def getmname(mid, server):
    member = discord.utils.get(server.members, id=mid)

    if member:
        return str(member)
    else:
        return '(absent user #%s)' % mid


ACTIONS_REPR = {
    "BAN"     : ("Ban", "\N{HAMMER}"),
    "KICK"    : ("Kick", "\N{WOMANS BOOTS}"),
    "CMUTE"   : ("Channel mute", "\N{SPEAKER WITH CANCELLATION STROKE}"),
    "SMUTE"   : ("Server mute", "\N{SPEAKER WITH CANCELLATION STROKE}"),
    "SOFTBAN" : ("Softban", "\N{DASH SYMBOL} \N{HAMMER}"),
    "HACKBAN" : ("Preemptive ban", "\N{BUST IN SILHOUETTE} \N{HAMMER}"),
    "UNBAN"   : ("Unban", "\N{DOVE OF PEACE}")
}

ACTIONS_CASES = {
    "BAN"     : True,
    "KICK"    : True,
    "CMUTE"   : False,
    "SMUTE"   : True,
    "SOFTBAN" : True,
    "HACKBAN" : True,
    "UNBAN"   : True
}

default_settings = {
    "ban_mention_spam"  : False,
    "delete_repeats"    : False,
    "mod-log"           : None,
    "respect_hierarchy" : False
}


for act, enabled in ACTIONS_CASES.items():
    act = act.lower() + '_cases'
    default_settings[act] = enabled


class ModError(Exception):
    pass


class UnauthorizedCaseEdit(ModError):
    pass


class CaseMessageNotFound(ModError):
    pass


class NoModLogChannel(ModError):
    pass


class NoModLogAccess(ModError):
    pass


class TempCache:
    """
    This is how we avoid events such as ban and unban
    from triggering twice in the mod-log.
    Kinda hacky but functioning
    """
    def __init__(self, bot):
        self.bot = bot
        self._cache = []

    def add(self, user, server, action, seconds=1):
        tmp = (user.id, server.id, action)
        self._cache.append(tmp)

        async def delete_value():
            await asyncio.sleep(seconds)
            self._cache.remove(tmp)

        self.bot.loop.create_task(delete_value())

    def check(self, user, server, action):
        return (user.id, server.id, action) in self._cache


class Mod:
    """Moderation tools."""

    def __init__(self, bot):
        self.bot = bot
        self.ignore_list = dataIO.load_json("data/mod/ignorelist.json")
        self.filter = dataIO.load_json("data/mod/filter.json")
        self.past_names = dataIO.load_json("data/mod/past_names.json")
        self.past_nicknames = dataIO.load_json("data/mod/past_nicknames.json")
        settings = dataIO.load_json("data/mod/settings.json")
        self.settings = defaultdict(lambda: default_settings.copy(), settings)
        self.cache = OrderedDict()
        self.cases = dataIO.load_json("data/mod/modlog.json")
        self.last_case = defaultdict(dict)
        self.temp_cache = TempCache(bot)
        perms_cache = dataIO.load_json("data/mod/perms_cache.json")
        self._perms_cache = defaultdict(dict, perms_cache)
        self.json = compat_load(JSON)

        # queue variables
        self.queue = asyncio.PriorityQueue(loop=bot.loop)
        self.queue_lock = asyncio.Lock(loop=bot.loop)
        self.pending = {}
        self.enqueued = set()

        self.task = bot.loop.create_task(self.on_load())

    def __unload(self):
        self.task.cancel()
        self.save()

    def save(self):
        dataIO.save_json(JSON, self.json)

    def can_create_cases(self):
        mod = self.bot.get_cog('Mod')
        if not mod:
            return False

        sig = inspect.signature(mod.new_case)
        return 'force_create' in sig.parameters

    @commands.group(pass_context=True, no_pm=True)
    @checks.serverowner_or_permissions(administrator=True)
    async def modset(self, ctx):
        """Manages server administration settings."""
        if ctx.invoked_subcommand is None:
            server = ctx.message.server
            await send_cmd_help(ctx)
            roles = settings.get_server(server).copy()
            _settings = {**self.settings[server.id], **roles}
            if "respect_hierarchy" not in _settings:
                _settings["respect_hierarchy"] = default_settings["respect_hierarchy"]
            if "delete_delay" not in _settings:
                _settings["delete_delay"] = "Disabled"

            msg = ("Admin role: {ADMIN_ROLE}\n"
                   "Mod role: {MOD_ROLE}\n"
                   "Mod-log: {mod-log}\n"
                   "Delete repeats: {delete_repeats}\n"
                   "Ban mention spam: {ban_mention_spam}\n"
                   "Delete delay: {delete_delay}\n"
                   "Respects hierarchy: {respect_hierarchy}"
                   "".format(**_settings))
            await self.bot.say(box(msg))

    @modset.command(pass_context=True, no_pm=True, name='setup')
    async def modset_setup(self, ctx):
        """
        (Re)configures the punish role and channel overrides
        """
        server = ctx.message.server
        default_name = DEFAULT_ROLE_NAME
        role_id = self.json.get(server.id, {}).get('ROLE_ID')

        if role_id:
            role = discord.utils.get(server.roles, id=role_id)
        else:
            role = discord.utils.get(server.roles, name=default_name)

        perms = server.me.server_permissions
        if not perms.manage_roles and perms.manage_channels:
            await self.bot.say("I need the Manage Roles and Manage Channels permissions for that command to work.")
            return

        if not role:
            msg = "The %s role doesn't exist; Creating it now... " % default_name

            msgobj = await self.bot.say(msg)

            perms = discord.Permissions.none()
            role = await self.bot.create_role(server, name=default_name, permissions=perms)
        else:
            msgobj = await self.bot.say('%s role exists... ' % role.name)

        if role.position != (server.me.top_role.position - 1):
            if role < server.me.top_role:
                msgobj = await self.bot.edit_message(msgobj, msgobj.content + 'moving role to higher position... ')
                await self.bot.move_role(server, role, server.me.top_role.position - 1)
            else:
                await self.bot.edit_message(msgobj, msgobj.content + 'role is too high to manage.'
                                            ' Please move it to below my highest role.')
                return

        msgobj = await self.bot.edit_message(msgobj, msgobj.content + '(re)configuring channels... ')

        for channel in server.channels:
            await self.setup_channel(channel, role)

        await self.bot.edit_message(msgobj, msgobj.content + 'done.')

        if role and role.id != role_id:
            if server.id not in self.json:
                self.json[server.id] = {}
            self.json[server.id]['ROLE_ID'] = role.id
            self.save()

    @modset.command(pass_context=True, no_pm=True, name='channel')
    async def modset_channel(self, ctx, channel: discord.Channel = None):
        """
        Sets or shows the punishment "timeout" channel.

        This channel has special settings to allow punished users to discuss their
        infraction(s) with moderators.

        If there is a role deny on the channel for the punish role, it is
        automatically set to allow. If the default permissions don't allow the
        punished role to see or speak in it, an overwrite is created to allow
        them to do so.
        """
        server = ctx.message.server
        current = self.json.get(server.id, {}).get('CHANNEL_ID')
        current = current and server.get_channel(current)

        if channel is None:
            if not current:
                await self.bot.say("No timeout channel has been set.")
            else:
                await self.bot.say("The timeout channel is currently %s." % current.mention)
        else:
            if server.id not in self.json:
                self.json[server.id] = {}
            elif current == channel:
                await self.bot.say("The timeout channel is already %s. If you need to repair its permissions, use "
                                   "`%smodset setup`." % (current.mention, ctx.prefix))
                return

            self.json[server.id]['CHANNEL_ID'] = channel.id
            self.save()

            role = await self.get_role(server, create=True)
            update_msg = '{} to the %s role' % role
            grants = []
            denies = []
            perms = permissions_for_roles(channel, role)
            overwrite = channel.overwrites_for(role) or discord.PermissionOverwrite()

            for perm, value in DEFAULT_TIMEOUT_OVERWRITE:
                if value is None:
                    continue

                if getattr(perms, perm) != value:
                    setattr(overwrite, perm, value)
                    name = perm.replace('_', ' ').title().replace("Tts", "TTS")

                    if value:
                        grants.append(name)
                    else:
                        denies.append(name)

            # Any changes made? Apply them.
            if grants or denies:
                grants = grants and ('grant ' + format_list(*grants))
                denies = denies and ('deny ' + format_list(*denies))
                to_join = [x for x in (grants, denies) if x]
                update_msg = update_msg.format(format_list(*to_join))

                if current and current.id != channel.id:
                    if current.permissions_for(server.me).manage_roles:
                        msg = info("Resetting permissions in the old channel (%s) to the default...")
                    else:
                        msg = error("I don't have permissions to reset permissions in the old channel (%s)")

                    await self.bot.say(msg % current.mention)
                    await self.setup_channel(current, role)

                if channel.permissions_for(server.me).manage_roles:
                    await self.bot.say(info('Updating permissions in %s to %s...' % (channel.mention, update_msg)))
                    await self.bot.edit_channel_permissions(channel, role, overwrite)
                else:
                    await self.bot.say(error("I don't have permissions to %s." % update_msg))

            await self.bot.say("Timeout channel set to %s." % channel.mention)

    @modset.command(pass_context=True, no_pm=True, name='clear-channel')
    async def modset_clear_channel(self, ctx):
        """
        Clears the timeout channel and resets its permissions
        """
        server = ctx.message.server
        current = self.json.get(server.id, {}).get('CHANNEL_ID')
        current = current and server.get_channel(current)

        if current:
            msg = None
            self.json[server.id]['CHANNEL_ID'] = None
            self.save()

            if current.permissions_for(server.me).manage_roles:
                role = await self.get_role(server, quiet=True)
                await self.setup_channel(current, role)
                msg = ' and its permissions reset'
            else:
                msg = ", but I don't have permissions to reset its permissions."

            await self.bot.say("Timeout channel has been cleared%s." % msg)
        else:
            await self.bot.say("No timeout channel has been set yet.")

    @modset.command(pass_context=True, allow_dm=False, name='case-min')
    async def modset_case_min(self, ctx, *, timespec: str = None):
        """
        Set/disable or display the minimum punishment case duration

        If the punishment duration is less than this value, a case will not be created.
        Specify 'disable' to turn off case creation altogether.
        """
        server = ctx.message.server
        current = self.json[server.id].get('CASE_MIN_LENGTH', _parse_time(DEFAULT_CASE_MIN_LENGTH))

        if not timespec:
            if current:
                await self.bot.say('Punishments longer than %s will create cases.' % _generate_timespec(current))
            else:
                await self.bot.say("Punishment case creation is disabled.")
        else:
            if timespec.strip('\'"').lower() == 'disable':
                value = None
            else:
                try:
                    value = _parse_time(timespec)
                except BadTimeExpr as e:
                    await self.bot.say(error(e.args[0]))
                    return

            if server.id not in self.json:
                self.json[server.id] = {}

            self.json[server.id]['CASE_MIN_LENGTH'] = value
            self.save()

    @modset.command(pass_context=True, no_pm=True, name='overrides')
    async def modset_overrides(self, ctx, *, channel: discord.Channel = None):
        """
        Copy or display the punish role overrides

        If a channel is specified, the allow/deny settings for it are saved
        and applied to new channels when they are created. To apply the new
        settings to existing channels, use [p]modset setup.

        An important caveat: voice channel and text channel overrides are
        configured separately! To set the overrides for a channel type,
        specify the name of or mention a channel of that type.
        """

        server = ctx.message.server
        settings = self.json.get(server.id, {})
        role = await self.get_role(server, quiet=True)
        timeout_channel_id = settings.get('CHANNEL_ID')
        confirm_msg = None

        if not role:
            await self.bot.say(error("Punish role has not been created yet. Run `%smodset setup` first."
                                     % ctx.prefix))
            return

        if channel:
            overwrite = channel.overwrites_for(role)
            if channel.id == timeout_channel_id:
                confirm_msg = "Are you sure you want to copy overrides from the timeout channel?"
            elif overwrite is None:
                overwrite = discord.PermissionOverwrite()
                confirm_msg = "Are you sure you want to copy blank (no permissions set) overrides?"

            if channel.type is discord.ChannelType.text:
                key = 'text'
            elif channel.type is discord.ChannelType.voice:
                key = 'voice'
            else:
                await self.bot.say(error("Unknown channel type!"))
                return

            if confirm_msg:
                await self.bot.say(warning(confirm_msg + '(reply `yes` within 30s to confirm)'))
                reply = await self.bot.wait_for_message(channel=ctx.message.channel, author=ctx.message.author,
                                                        timeout=30)

                if reply is None:
                    await self.bot.say('Timed out waiting for a response.')
                    return
                elif reply.content.strip(' `"\'').lower() != 'yes':
                    await self.bot.say('Commmand cancelled.')
                    return

            self.json[server.id][key.upper() + '_OVERWRITE'] = overwrite_to_dict(overwrite)
            self.save()
            await self.bot.say("{} channel overrides set to:\n".format(key.title()) +
                               format_permissions(overwrite) +
                               "\n\nRun `%smodset setup` to apply them to all channels." % ctx.prefix)

        else:
            msg = []
            for key, default in [('text', DEFAULT_TEXT_OVERWRITE), ('voice', DEFAULT_VOICE_OVERWRITE)]:
                data = settings.get(key.upper() + '_OVERWRITE')
                title = '%s permission overrides:' % key.title()

                if not data:
                    data = overwrite_to_dict(default)
                    title = title[:-1] + ' (defaults):'

                msg.append(bold(title) + '\n' + format_permissions(overwrite_from_dict(data)))

            await self.bot.say('\n\n'.join(msg))

    @modset.command(pass_context=True, no_pm=True, name='reset-overrides')
    async def modset_reset_overrides(self, ctx, channel_type: str = 'both'):
        """
        Resets the punish role overrides for text, voice or both (default)

        This command exists in case you want to restore the default settings
        for newly created channels.
        """

        settings = self.json.get(ctx.message.server.id, {})
        channel_type = channel_type.strip('`"\' ').lower()

        msg = []
        for key, default in [('text', DEFAULT_TEXT_OVERWRITE), ('voice', DEFAULT_VOICE_OVERWRITE)]:
            if channel_type not in ['both', key]:
                continue

            settings.pop(key.upper() + '_OVERWRITE', None)
            title = '%s permission overrides reset to:' % key.title()
            msg.append(bold(title) + '\n' + format_permissions(default))

        if not msg:
            await self.bot.say("Invalid channel type. Use `text`, `voice`, or `both` (the default, if not specified)")
            return

        msg.append("Run `%smodset setup` to apply them to all channels." % ctx.prefix)

        self.save()
        await self.bot.say('\n\n'.join(msg))

    @modset.command(name="adminrole", pass_context=True, no_pm=True, hidden=True)
    async def _modset_adminrole(self, ctx):
        """Use [p]set adminrole instead"""
        await self.bot.say("This command has been renamed "
                           "`{}set adminrole`".format(ctx.prefix))

    @modset.command(name="modrole", pass_context=True, no_pm=True, hidden=True)
    async def _modset_modrole(self, ctx):
        """Use [p]set modrole instead"""
        await self.bot.say("This command has been renamed "
                           "`{}set modrole`".format(ctx.prefix))

    @modset.command(pass_context=True, no_pm=True)
    async def modlog(self, ctx, channel : discord.Channel=None):
        """Sets a channel as mod log

        Leaving the channel parameter empty will deactivate it"""
        server = ctx.message.server
        if channel:
            self.settings[server.id]["mod-log"] = channel.id
            await self.bot.say("Mod events will be sent to {}"
                               "".format(channel.mention))
        else:
            if self.settings[server.id]["mod-log"] is None:
                await send_cmd_help(ctx)
                return
            self.settings[server.id]["mod-log"] = None
            await self.bot.say("Mod log deactivated.")
        dataIO.save_json("data/mod/settings.json", self.settings)

    @modset.command(pass_context=True, no_pm=True)
    async def banmentionspam(self, ctx, max_mentions : int=False):
        """Enables auto ban for messages mentioning X different people

        Accepted values: 5 or superior"""
        server = ctx.message.server
        if max_mentions:
            if max_mentions < 5:
                max_mentions = 5
            self.settings[server.id]["ban_mention_spam"] = max_mentions
            await self.bot.say("Autoban for mention spam enabled. "
                               "Anyone mentioning {} or more different people "
                               "in a single message will be autobanned."
                               "".format(max_mentions))
        else:
            if self.settings[server.id]["ban_mention_spam"] is False:
                await send_cmd_help(ctx)
                return
            self.settings[server.id]["ban_mention_spam"] = False
            await self.bot.say("Autoban for mention spam disabled.")
        dataIO.save_json("data/mod/settings.json", self.settings)

    @modset.command(pass_context=True, no_pm=True)
    async def deleterepeats(self, ctx):
        """Enables auto deletion of repeated messages"""
        server = ctx.message.server
        if not self.settings[server.id]["delete_repeats"]:
            self.settings[server.id]["delete_repeats"] = True
            await self.bot.say("Messages repeated up to 3 times will "
                               "be deleted.")
        else:
            self.settings[server.id]["delete_repeats"] = False
            await self.bot.say("Repeated messages will be ignored.")
        dataIO.save_json("data/mod/settings.json", self.settings)

    @modset.command(pass_context=True, no_pm=True)
    async def resetcases(self, ctx):
        """Resets modlog's cases"""
        server = ctx.message.server
        self.cases[server.id] = {}
        dataIO.save_json("data/mod/modlog.json", self.cases)
        await self.bot.say("Cases have been reset.")

    @modset.command(pass_context=True, no_pm=True)
    async def deletedelay(self, ctx, time: int=None):
        """Sets the delay until the bot removes the command message.
            Must be between -1 and 60.

        A delay of -1 means the bot will not remove the message."""
        server = ctx.message.server
        if time is not None:
            time = min(max(time, -1), 60)  # Enforces the time limits
            self.settings[server.id]["delete_delay"] = time
            if time == -1:
                await self.bot.say("Command deleting disabled.")
            else:
                await self.bot.say("Delete delay set to {}"
                                   " seconds.".format(time))
            dataIO.save_json("data/mod/settings.json", self.settings)
        else:
            try:
                delay = self.settings[server.id]["delete_delay"]
            except KeyError:
                await self.bot.say("Delete delay not yet set up on this"
                                   " server.")
            else:
                if delay != -1:
                    await self.bot.say("Bot will delete command messages after"
                                       " {} seconds. Set this value to -1 to"
                                       " stop deleting messages".format(delay))
                else:
                    await self.bot.say("I will not delete command messages.")

    @modset.command(pass_context=True, no_pm=True, name='cases')
    async def set_cases(self, ctx, action: str = None, enabled: bool = None):
        """Enables or disables case creation for each type of mod action

        Enabled can be 'on' or 'off'"""
        server = ctx.message.server

        if action == enabled:  # No args given
            await self.bot.send_cmd_help(ctx)
            msg = "Current settings:\n```py\n"
            maxlen = max(map(lambda x: len(x[0]), ACTIONS_REPR.values()))
            for action, name in ACTIONS_REPR.items():
                action = action.lower() + '_cases'
                value = self.settings[server.id].get(action,
                                                     default_settings[action])
                value = 'enabled' if value else 'disabled'
                msg += '%s : %s\n' % (name[0].ljust(maxlen), value)

            msg += '```'
            await self.bot.say(msg)

        elif action.upper() not in ACTIONS_CASES:
            msg = "That's not a valid action. Valid actions are: \n"
            msg += ', '.join(sorted(map(str.lower, ACTIONS_CASES)))
            await self.bot.say(msg)

        elif enabled == None:
            action = action.lower() + '_cases'
            value = self.settings[server.id].get(action,
                                                 default_settings[action])
            await self.bot.say('Case creation for %s is currently %s' %
                               (action, 'enabled' if value else 'disabled'))
        else:
            name = ACTIONS_REPR[action.upper()][0]
            action = action.lower() + '_cases'
            value = self.settings[server.id].get(action,
                                                 default_settings[action])
            if value != enabled:
                self.settings[server.id][action] = enabled
                dataIO.save_json("data/mod/settings.json", self.settings)
            msg = ('Case creation for %s actions %s %s.' %
                   (name.lower(),
                    'was already' if enabled == value else 'is now',
                    'enabled' if enabled else 'disabled')
                   )
            await self.bot.say(msg)

    @modset.command(pass_context=True, no_pm=True)
    @checks.serverowner_or_permissions()
    async def hierarchy(self, ctx):
        """Toggles role hierarchy check for mods / admins"""
        server = ctx.message.server
        toggled = self.settings[server.id].get("respect_hierarchy",
                                               default_settings["respect_hierarchy"])
        if not toggled:
            self.settings[server.id]["respect_hierarchy"] = True
            await self.bot.say("Role hierarchy will be checked when "
                               "moderation commands are issued.")
        else:
            self.settings[server.id]["respect_hierarchy"] = False
            await self.bot.say("Role hierarchy will be ignored when "
                               "moderation commands are issued.")
        dataIO.save_json("data/mod/settings.json", self.settings)

    @commands.command(no_pm=True, pass_context=True)
    @checks.admin_or_permissions(kick_members=True)
    async def kick(self, ctx, user: discord.Member, *, reason: str = None):
        """Kicks user."""
        author = ctx.message.author
        server = author.server

        if author == user:
            await self.bot.say("I cannot let you do that. Self-harm is "
                               "bad \N{PENSIVE FACE}")
            return
        elif not self.is_allowed_by_hierarchy(server, author, user):
            await self.bot.say("I cannot let you do that. You are "
                               "not higher than the user in the role "
                               "hierarchy.")
            return

        try:
            await self.bot.kick(user)
            logger.info("{}({}) kicked {}({})".format(
                author.name, author.id, user.name, user.id))
            await self.new_case(server,
                                action="KICK",
                                mod=author,
                                user=user,
                                reason=reason)
            await self.bot.say("Done. That felt good.")
        except discord.errors.Forbidden:
            await self.bot.say("I'm not allowed to do that.")
        except Exception as e:
            print(e)

    @commands.command(no_pm=True, pass_context=True)
    @checks.admin_or_permissions(ban_members=True)
    async def ban(self, ctx, user: discord.Member, days: str = None, *, reason: str = None):
        """Bans user and deletes last X days worth of messages.

        If days is not a number, it's treated as the first word of the reason.
        Minimum 0 days, maximum 7. Defaults to 0."""
        author = ctx.message.author
        server = author.server

        if author == user:
            await self.bot.say("I cannot let you do that. Self-harm is "
                               "bad \N{PENSIVE FACE}")
            return
        elif not self.is_allowed_by_hierarchy(server, author, user):
            await self.bot.say("I cannot let you do that. You are "
                               "not higher than the user in the role "
                               "hierarchy.")
            return

        if days:
            if days.isdigit():
                days = int(days)
            else:
                if reason:
                    reason = days + ' ' + reason
                else:
                    reason = days
                days = 0
        else:
            days = 0

        if days < 0 or days > 7:
            await self.bot.say("Invalid days. Must be between 0 and 7.")
            return

        try:
            self.temp_cache.add(user, server, "BAN")
            await self.bot.ban(user, days)
            logger.info("{}({}) banned {}({}), deleting {} days worth of messages".format(
                author.name, author.id, user.name, user.id, str(days)))
            await self.new_case(server,
                                action="BAN",
                                mod=author,
                                user=user,
                                reason=reason)
            await self.bot.say("Done. It was about time.")
        except discord.errors.Forbidden:
            await self.bot.say("I'm not allowed to do that.")
        except Exception as e:
            print(e)

    @commands.command(no_pm=True, pass_context=True)
    @checks.admin_or_permissions(ban_members=True)
    async def hackban(self, ctx, user_id: int, *, reason: str = None):
        """Preemptively bans user from the server

        A user ID needs to be provided
        If the user is present in the server a normal ban will be
        issued instead"""
        user_id = str(user_id)
        author = ctx.message.author
        server = author.server

        ban_list = await self.bot.get_bans(server)
        is_banned = discord.utils.get(ban_list, id=user_id)

        if is_banned:
            await self.bot.say("User is already banned.")
            return

        user = server.get_member(user_id)
        if user is not None:
            await ctx.invoke(self.ban, user=user, reason=reason)
            return

        try:
            await self.bot.http.ban(user_id, server.id, 0)
        except discord.NotFound:
            await self.bot.say("User not found. Have you provided the "
                               "correct user ID?")
        except discord.Forbidden:
            await self.bot.say("I lack the permissions to do this.")
        else:
            logger.info("{}({}) hackbanned {}"
                        "".format(author.name, author.id, user_id))
            user = await self.bot.get_user_info(user_id)
            await self.new_case(server,
                                action="HACKBAN",
                                mod=author,
                                user=user,
                                reason=reason)
            await self.bot.say("Done. The user will not be able to join this "
                               "server.")

    @commands.command(no_pm=True, pass_context=True)
    @checks.admin_or_permissions(ban_members=True)
    async def softban(self, ctx, user: discord.Member, *, reason: str = None):
        """Kicks the user, deleting 1 day worth of messages."""
        server = ctx.message.server
        channel = ctx.message.channel
        can_ban = channel.permissions_for(server.me).ban_members
        author = ctx.message.author

        if author == user:
            await self.bot.say("I cannot let you do that. Self-harm is "
                               "bad \N{PENSIVE FACE}")
            return
        elif not self.is_allowed_by_hierarchy(server, author, user):
            await self.bot.say("I cannot let you do that. You are "
                               "not higher than the user in the role "
                               "hierarchy.")
            return

        try:
            invite = await self.bot.create_invite(server, max_age=3600*24)
            invite = "\nInvite: " + invite
        except:
            invite = ""
        if can_ban:
            try:
                try:  # We don't want blocked DMs preventing us from banning
                    msg = await self.bot.send_message(user, "You have been banned and "
                              "then unbanned as a quick way to delete your messages.\n"
                              "You can now join the server again.{}".format(invite))
                except:
                    pass
                self.temp_cache.add(user, server, "BAN")
                await self.bot.ban(user, 1)
                logger.info("{}({}) softbanned {}({}), deleting 1 day worth "
                    "of messages".format(author.name, author.id, user.name,
                     user.id))
                await self.new_case(server,
                                    action="SOFTBAN",
                                    mod=author,
                                    user=user,
                                    reason=reason)
                self.temp_cache.add(user, server, "UNBAN")
                await self.bot.unban(server, user)
                await self.bot.say("Done. Enough chaos.")
            except discord.errors.Forbidden:
                await self.bot.say("My role is not high enough to softban that user.")
                await self.bot.delete_message(msg)
            except Exception as e:
                print(e)
        else:
            await self.bot.say("I'm not allowed to do that.")

    @commands.command(no_pm=True, pass_context=True)
    @checks.admin_or_permissions(manage_nicknames=True)
    async def rename(self, ctx, user : discord.Member, *, nickname=""):
        """Changes user's nickname

        Leaving the nickname empty will remove it."""
        nickname = nickname.strip()
        if nickname == "":
            nickname = None
        try:
            await self.bot.change_nickname(user, nickname)
            await self.bot.say("Done.")
        except discord.Forbidden:
            await self.bot.say("I cannot do that, I lack the "
                               "\"Manage Nicknames\" permission.")

    @commands.group(pass_context=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def cleanup(self, ctx):
        """Deletes messages."""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @cleanup.command(pass_context=True, no_pm=True)
    async def text(self, ctx, text: str, number: int):
        """Deletes last X messages matching the specified text.

        Example:
        cleanup text \"test\" 5

        Remember to use double quotes."""

        channel = ctx.message.channel
        author = ctx.message.author
        server = author.server
        is_bot = self.bot.user.bot
        has_permissions = channel.permissions_for(server.me).manage_messages

        def check(m):
            if text in m.content:
                return True
            elif m == ctx.message:
                return True
            else:
                return False

        to_delete = [ctx.message]

        if not has_permissions:
            await self.bot.say("I'm not allowed to delete messages.")
            return

        tries_left = 5
        tmp = ctx.message

        while tries_left and len(to_delete) - 1 < number:
            async for message in self.bot.logs_from(channel, limit=100,
                                                    before=tmp):
                if len(to_delete) - 1 < number and check(message):
                    to_delete.append(message)
                tmp = message
            tries_left -= 1

        logger.info("{}({}) deleted {} messages "
                    " containing '{}' in channel {}".format(author.name,
                    author.id, len(to_delete), text, channel.id))

        if is_bot:
            await self.mass_purge(to_delete)
        else:
            await self.slow_deletion(to_delete)

    @cleanup.command(pass_context=True, no_pm=True)
    async def user(self, ctx, user: discord.Member, number: int):
        """Deletes last X messages from specified user.

        Examples:
        cleanup user @\u200bTwentysix 2
        cleanup user Red 6"""

        channel = ctx.message.channel
        author = ctx.message.author
        server = author.server
        is_bot = self.bot.user.bot
        has_permissions = channel.permissions_for(server.me).manage_messages
        self_delete = user == self.bot.user

        def check(m):
            if m.author == user:
                return True
            elif m == ctx.message:
                return True
            else:
                return False

        to_delete = [ctx.message]

        if not has_permissions and not self_delete:
            await self.bot.say("I'm not allowed to delete messages.")
            return

        tries_left = 5
        tmp = ctx.message

        while tries_left and len(to_delete) - 1 < number:
            async for message in self.bot.logs_from(channel, limit=100,
                                                    before=tmp):
                if len(to_delete) - 1 < number and check(message):
                    to_delete.append(message)
                tmp = message
            tries_left -= 1

        logger.info("{}({}) deleted {} messages "
                    " made by {}({}) in channel {}"
                    "".format(author.name, author.id, len(to_delete),
                              user.name, user.id, channel.name))

        if is_bot and not self_delete:
            # For whatever reason the purge endpoint requires manage_messages
            await self.mass_purge(to_delete)
        else:
            await self.slow_deletion(to_delete)

    @cleanup.command(pass_context=True, no_pm=True)
    async def after(self, ctx, message_id : int):
        """Deletes all messages after specified message

        To get a message id, enable developer mode in Discord's
        settings, 'appearance' tab. Then right click a message
        and copy its id.

        This command only works on bots running as bot accounts.
        """

        channel = ctx.message.channel
        author = ctx.message.author
        server = channel.server
        is_bot = self.bot.user.bot
        has_permissions = channel.permissions_for(server.me).manage_messages

        if not is_bot:
            await self.bot.say("This command can only be used on bots with "
                               "bot accounts.")
            return

        to_delete = []

        after = await self.bot.get_message(channel, message_id)

        if not has_permissions:
            await self.bot.say("I'm not allowed to delete messages.")
            return
        elif not after:
            await self.bot.say("Message not found.")
            return

        async for message in self.bot.logs_from(channel, limit=2000,
                                                after=after):
            to_delete.append(message)

        logger.info("{}({}) deleted {} messages in channel {}"
                    "".format(author.name, author.id,
                              len(to_delete), channel.name))

        await self.mass_purge(to_delete)

    @cleanup.command(pass_context=True, no_pm=True)
    async def messages(self, ctx, number: int):
        """Deletes last X messages.

        Example:
        cleanup messages 26"""

        channel = ctx.message.channel
        author = ctx.message.author
        server = author.server
        is_bot = self.bot.user.bot
        has_permissions = channel.permissions_for(server.me).manage_messages

        to_delete = []

        if not has_permissions:
            await self.bot.say("I'm not allowed to delete messages.")
            return

        async for message in self.bot.logs_from(channel, limit=number+1):
            to_delete.append(message)

        logger.info("{}({}) deleted {} messages in channel {}"
                    "".format(author.name, author.id,
                              number, channel.name))

        if is_bot:
            await self.mass_purge(to_delete)
        else:
            await self.slow_deletion(to_delete)

    @cleanup.command(pass_context=True, no_pm=True, name='bot')
    async def cleanup_bot(self, ctx, number: int):
        """Cleans up command messages and messages from the bot"""

        channel = ctx.message.channel
        author = ctx.message.author
        server = channel.server
        is_bot = self.bot.user.bot
        has_permissions = channel.permissions_for(server.me).manage_messages

        prefixes = self.bot.command_prefix
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        elif callable(prefixes):
            if asyncio.iscoroutine(prefixes):
                await self.bot.say('Coroutine prefixes not yet implemented.')
                return
            prefixes = prefixes(self.bot, ctx.message)

        # In case some idiot sets a null prefix
        if '' in prefixes:
            prefixes.pop('')

        def check(m):
            if m.author.id == self.bot.user.id:
                return True
            elif m == ctx.message:
                return True
            p = discord.utils.find(m.content.startswith, prefixes)
            if p and len(p) > 0:
                return m.content[len(p):].startswith(tuple(self.bot.commands))
            return False

        to_delete = [ctx.message]

        if not has_permissions:
            await self.bot.say("I'm not allowed to delete messages.")
            return

        tries_left = 5
        tmp = ctx.message

        while tries_left and len(to_delete) - 1 < number:
            async for message in self.bot.logs_from(channel, limit=100,
                                                    before=tmp):
                if len(to_delete) - 1 < number and check(message):
                    to_delete.append(message)
                tmp = message
            tries_left -= 1

        logger.info("{}({}) deleted {} "
                    " command messages in channel {}"
                    "".format(author.name, author.id, len(to_delete),
                              channel.name))

        if is_bot:
            await self.mass_purge(to_delete)
        else:
            await self.slow_deletion(to_delete)

    @cleanup.command(pass_context=True, name='self')
    async def cleanup_self(self, ctx, number: int, match_pattern: str = None):
        """Cleans up messages owned by the bot.

        By default, all messages are cleaned. If a third argument is specified,
        it is used for pattern matching: If it begins with r( and ends with ),
        then it is interpreted as a regex, and messages that match it are
        deleted. Otherwise, it is used in a simple substring test.

        Some helpful regex flags to include in your pattern:
        Dots match newlines: (?s); Ignore case: (?i); Both: (?si)
        """
        channel = ctx.message.channel
        author = ctx.message.author
        is_bot = self.bot.user.bot

        # You can always delete your own messages, this is needed to purge
        can_mass_purge = False
        if type(author) is discord.Member:
            me = channel.server.me
            can_mass_purge = channel.permissions_for(me).manage_messages

        use_re = (match_pattern and match_pattern.startswith('r(') and
                  match_pattern.endswith(')'))

        if use_re:
            match_pattern = match_pattern[1:]  # strip 'r'
            match_re = re.compile(match_pattern)

            def content_match(c):
                return bool(match_re.match(c))
        elif match_pattern:
            def content_match(c):
                return match_pattern in c
        else:
            def content_match(_):
                return True

        def check(m):
            if m.author.id != self.bot.user.id:
                return False
            elif content_match(m.content):
                return True
            return False

        to_delete = []
        # Selfbot convenience, delete trigger message
        if author == self.bot.user:
            to_delete.append(ctx.message)
            number += 1

        tries_left = 5
        tmp = ctx.message

        while tries_left and len(to_delete) < number:
            async for message in self.bot.logs_from(channel, limit=100,
                                                    before=tmp):
                if len(to_delete) < number and check(message):
                    to_delete.append(message)
                tmp = message
            tries_left -= 1

        if channel.name:
            channel_name = 'channel ' + channel.name
        else:
            channel_name = str(channel)

        logger.info("{}({}) deleted {} messages "
                    "sent by the bot in {}"
                    "".format(author.name, author.id, len(to_delete),
                              channel_name))

        if is_bot and can_mass_purge:
            await self.mass_purge(to_delete)
        else:
            await self.slow_deletion(to_delete)

    @commands.command(pass_context=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def reason(self, ctx, case, *, reason : str=""):
        """Lets you specify a reason for mod-log's cases

        Defaults to last case assigned to yourself, if available."""
        author = ctx.message.author
        server = author.server
        try:
            case = int(case)
            if not reason:
                await send_cmd_help(ctx)
                return
        except:
            if reason:
                reason = "{} {}".format(case, reason)
            else:
                reason = case
            case = self.last_case[server.id].get(author.id)
            if case is None:
                await send_cmd_help(ctx)
                return
        try:
            await self.update_case(server, case=case, mod=author,
                                   reason=reason)
        except UnauthorizedCaseEdit:
            await self.bot.say("That case is not yours.")
        except KeyError:
            await self.bot.say("That case doesn't exist.")
        except NoModLogChannel:
            await self.bot.say("There's no mod-log channel set.")
        except CaseMessageNotFound:
            await self.bot.say("I couldn't find the case's message.")
        except NoModLogAccess:
            await self.bot.say("I'm not allowed to access the mod-log "
                               "channel (or its message history)")
        else:
            await self.bot.say("Case #{} updated.".format(case))

    @commands.group(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_channels=True)
    async def ignore(self, ctx):
        """Adds servers/channels to ignorelist"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
            await self.bot.say(self.count_ignored())

    @ignore.command(name="channel", pass_context=True)
    async def ignore_channel(self, ctx, channel: discord.Channel=None):
        """Ignores channel

        Defaults to current one"""
        current_ch = ctx.message.channel
        if not channel:
            if current_ch.name not in self.ignore_list["CHANNELS"]:
                self.ignore_list["CHANNELS"].append(current_ch.name)
                dataIO.save_json("data/mod/ignorelist.json", self.ignore_list)
                await self.bot.say("Channel added to ignore list.")
            else:
                await self.bot.say("Channel already in ignore list.")
        else:
            if channel.name not in self.ignore_list["CHANNELS"]:
                self.ignore_list["CHANNELS"].append(channel.name)
                dataIO.save_json("data/mod/ignorelist.json", self.ignore_list)
                await self.bot.say("Channel added to ignore list.")
            else:
                await self.bot.say("Channel already in ignore list.")

    @ignore.command(name="server", pass_context=True)
    async def ignore_server(self, ctx):
        """Ignores current server"""
        server = ctx.message.server
        if server.name not in self.ignore_list["SERVERS"]:
            self.ignore_list["SERVERS"].append(server.name)
            dataIO.save_json("data/mod/ignorelist.json", self.ignore_list)
            await self.bot.say("This server has been added to the ignore list.")
        else:
            await self.bot.say("This server is already being ignored.")

    @commands.group(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_channels=True)
    async def unignore(self, ctx):
        """Removes servers/channels from ignorelist"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
            await self.bot.say(self.count_ignored())

    @unignore.command(name="channel", pass_context=True)
    async def unignore_channel(self, ctx, channel: discord.Channel=None):
        """Removes channel from ignore list

        Defaults to current one"""
        current_ch = ctx.message.channel
        if not channel:
            if current_ch.name in self.ignore_list["CHANNELS"]:
                self.ignore_list["CHANNELS"].remove(current_ch.name)
                dataIO.save_json("data/mod/ignorelist.json", self.ignore_list)
                await self.bot.say("This channel has been removed from the ignore list.")
            else:
                await self.bot.say("This channel is not in the ignore list.")
        else:
            if channel.name in self.ignore_list["CHANNELS"]:
                self.ignore_list["CHANNELS"].remove(channel.name)
                dataIO.save_json("data/mod/ignorelist.json", self.ignore_list)
                await self.bot.say("Channel removed from ignore list.")
            else:
                await self.bot.say("That channel is not in the ignore list.")

    @unignore.command(name="server", pass_context=True)
    async def unignore_server(self, ctx):
        """Removes current server from ignore list"""
        server = ctx.message.server
        if server.name in self.ignore_list["SERVERS"]:
            self.ignore_list["SERVERS"].remove(server.name)
            dataIO.save_json("data/mod/ignorelist.json", self.ignore_list)
            await self.bot.say("This server has been removed from the ignore list.")
        else:
            await self.bot.say("This server is not in the ignore list.")

    def count_ignored(self):
        msg = "```Currently ignoring:\n"
        msg += str(self.ignore_list["CHANNELS"]) + "```\n"
#        msg += str(self.ignore_list["SERVERS"]) + "```\n"
        return msg

    @commands.group(name="filter", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def _filter(self, ctx):
        """Adds/removes words from filter

        Use double quotes to add/remove sentences
        Using this command with no subcommands will send
        the list of the server's filtered words."""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
            server = ctx.message.server
            author = ctx.message.author
            if server.id in self.filter:
                if self.filter[server.id]:
                    words = ", ".join(self.filter[server.id])
                    words = "Filtered in this server:\n\n" + words
                    try:
                        for page in pagify(words, delims=[" ", "\n"], shorten_by=8):
                            await self.bot.send_message(author, page)
                    except discord.Forbidden:
                        await self.bot.say("I can't send direct messages to you.")

    @_filter.command(name="add", pass_context=True)
    async def filter_add(self, ctx, *words: str):
        """Adds words to the filter

        Use double quotes to add sentences
        Examples:
        filter add word1 word2 word3
        filter add \"This is a sentence\""""
        if words == ():
            await send_cmd_help(ctx)
            return
        server = ctx.message.server
        added = 0
        if server.id not in self.filter.keys():
            self.filter[server.id] = []
        for w in words:
            if w.lower() not in self.filter[server.id] and w != "":
                self.filter[server.id].append(w.lower())
                added += 1
        if added:
            dataIO.save_json("data/mod/filter.json", self.filter)
            await self.bot.say("Words added to filter.")
        else:
            await self.bot.say("Words already in the filter.")

    @_filter.command(name="remove", pass_context=True)
    async def filter_remove(self, ctx, *words: str):
        """Remove words from the filter

        Use double quotes to remove sentences
        Examples:
        filter remove word1 word2 word3
        filter remove \"This is a sentence\""""
        if words == ():
            await send_cmd_help(ctx)
            return
        server = ctx.message.server
        removed = 0
        if server.id not in self.filter.keys():
            await self.bot.say("There are no filtered words in this server.")
            return
        for w in words:
            if w.lower() in self.filter[server.id]:
                self.filter[server.id].remove(w.lower())
                removed += 1
        if removed:
            dataIO.save_json("data/mod/filter.json", self.filter)
            await self.bot.say("Words removed from filter.")
        else:
            await self.bot.say("Those words weren't in the filter.")

    @commands.group(no_pm=True, pass_context=True)
    @checks.admin_or_permissions(manage_roles=True)
    async def editrole(self, ctx):
        """Edits roles settings"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @editrole.command(aliases=["color"], pass_context=True)
    async def colour(self, ctx, role: discord.Role, value: discord.Colour):
        """Edits a role's colour

        Use double quotes if the role contains spaces.
        Colour must be in hexadecimal format.
        \"http://www.w3schools.com/colors/colors_picker.asp\"
        Examples:
        !editrole colour \"The Transistor\" #ff0000
        !editrole colour Test #ff9900"""
        author = ctx.message.author
        try:
            await self.bot.edit_role(ctx.message.server, role, color=value)
            logger.info("{}({}) changed the colour of role '{}'".format(
                author.name, author.id, role.name))
            await self.bot.say("Done.")
        except discord.Forbidden:
            await self.bot.say("I need permissions to manage roles first.")
        except Exception as e:
            print(e)
            await self.bot.say("Something went wrong.")

    @editrole.command(name="name", pass_context=True)
    @checks.admin_or_permissions(administrator=True)
    async def edit_role_name(self, ctx, role: discord.Role, name: str):
        """Edits a role's name

        Use double quotes if the role or the name contain spaces.
        Examples:
        !editrole name \"The Transistor\" Test"""
        if name == "":
            await self.bot.say("Name cannot be empty.")
            return
        try:
            author = ctx.message.author
            old_name = role.name  # probably not necessary?
            await self.bot.edit_role(ctx.message.server, role, name=name)
            logger.info("{}({}) changed the name of role '{}' to '{}'".format(
                author.name, author.id, old_name, name))
            await self.bot.say("Done.")
        except discord.Forbidden:
            await self.bot.say("I need permissions to manage roles first.")
        except Exception as e:
            print(e)
            await self.bot.say("Something went wrong.")

    @commands.command()
    async def names(self, user : discord.Member):
        """Show previous names/nicknames of a user"""
        server = user.server
        names = self.past_names[user.id] if user.id in self.past_names else None
        try:
            nicks = self.past_nicknames[server.id][user.id]
            nicks = [escape_mass_mentions(nick) for nick in nicks]
        except:
            nicks = None
        msg = ""
        if names:
            names = [escape_mass_mentions(name) for name in names]
            msg += "**Past 20 names**:\n"
            msg += ", ".join(names)
        if nicks:
            if msg:
                msg += "\n\n"
            msg += "**Past 20 nicknames**:\n"
            msg += ", ".join(nicks)
        if msg:
            await self.bot.say(msg)
        else:
            await self.bot.say("That user doesn't have any recorded name or "
                               "nickname change.")
    @commands.group(pass_context=True, invoke_without_command=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def punish(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        if ctx.invoked_subcommand:
            return
        elif user:
            await ctx.invoke(self.punish_start, user=user, duration=duration, reason=reason)
        else:
            await self.bot.send_cmd_help(ctx)

    @punish.command(pass_context=True, no_pm=True, name='mute')
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_start(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        """
        Puts a user into timeout for a specified time, with optional reason.

        Time specification is any combination of number with the units s,m,h,d,w.
        Example: !punish @idiot 1.1h10m Enough bitching already!
        """

        await self._punish_cmd_common(ctx, user, duration, reason)

    @punish.command(pass_context=True, no_pm=True, name='purge')
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_cstart(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        """
        Same as [p]punish mute, but cleans up the target's last message.
        """

        success = await self._punish_cmd_common(ctx, user, duration, reason, quiet=True)

        if not success:
            return

        def check(m):
            return m.id == ctx.message.id or m.author == user

        try:
            await self.bot.purge_from(ctx.message.channel, limit=PURGE_MESSAGES + 1, check=check)
        except discord.errors.Forbidden:
            await self.bot.say("Punishment set, but I need permissions to manage messages to clean up.")

    @punish.command(pass_context=True, no_pm=True, name='list')
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_list(self, ctx):
        """
        Shows a table of punished users with time, mod and reason.

        Displays punished users, time remaining, responsible moderator and
        the reason for punishment, if any.
        """

        server = ctx.message.server
        server_id = server.id
        table = []
        now = time.time()
        headers = ['Member', 'Remaining', 'Moderator', 'Reason']
        msg = ''

        # Multiline cell/header support was added in 0.8.0
        if tabulate.__version__ >= '0.8.0':
            headers = [';\n'.join(headers[i::2]) for i in (0, 1)]
        else:
            msg += warning('Compact formatting is only supported with tabulate v0.8.0+ (currently v%s). '
                           'Please update it.\n\n' % tabulate.__version__)

        for member_id, data in self.json.get(server_id, {}).items():
            if not member_id.isdigit():
                continue

            member_name = getmname(member_id, server)
            moderator = getmname(data['by'], server)
            reason = data['reason']
            until = data['until']
            sort = until or float("inf")

            remaining = _generate_timespec(until - now, short=True) if until else 'forever'

            row = [member_name, remaining, moderator, reason or 'No reason set.']

            if tabulate.__version__ >= '0.8.0':
                row[-1] = textwrap.fill(row[-1], 35)
                row = [';\n'.join(row[i::2]) for i in (0, 1)]

            table.append((sort, row))

        if not table:
            await self.bot.say("No users are currently punished.")
            return

        table.sort()
        msg += tabulate.tabulate([k[1] for k in table], headers, tablefmt="grid")

        for page in pagify(msg):
            await self.bot.say(box(page))

    @punish.command(pass_context=True, no_pm=True, name='clean')
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_clean(self, ctx, clean_pending: bool = False):
        """
        Removes absent members from the punished list.

        If run without an argument, it only removes members who are no longer
        present but whose timer has expired. If the argument is 'yes', 1,
        or another trueish value, it will also remove absent members whose
        timers have yet to expire.

        Use this option with care, as removing them will prevent the punished
        role from being re-added if they rejoin before their timer expires.
        """

        count = 0
        now = time.time()
        server = ctx.message.server
        data = self.json.get(server.id, {})

        for mid, mdata in data.copy().items():
            if not mid.isdigit() or server.get_member(mid):
                continue

            elif clean_pending or ((mdata['until'] or 0) < now):
                del(data[mid])
                count += 1

        await self.bot.say('Cleaned %i absent members from the list.' % count)

    @punish.command(pass_context=True, no_pm=True, name='warn')
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_warn(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Warns a user with boilerplate about the rules
        """

        msg = ['Hey %s, ' % user.mention]
        msg.append("you're doing something that might get you muted if you keep "
                   "doing it.")
        if reason:
            msg.append(" Specifically, %s." % reason)

        msg.append("Be sure to review the server rules.")
        await self.bot.say(' '.join(msg))

    @punish.command(pass_context=True, no_pm=True, name='end', aliases=['remove'])
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_end(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Removes punishment from a user before time has expired

        This is the same as removing the role directly.
        """

        role = await self.get_role(user.server, quiet=True)
        sid = user.server.id
        now = time.time()
        data = self.json.get(sid, {}).get(user.id, {})

        if role and role in user.roles:
            msg = 'Punishment manually ended early by %s.' % ctx.message.author

            original_start = data.get('start')
            original_end = data.get('until')
            remaining = original_end and (original_end - now)

            if remaining:
                msg += ' %s was left' % _generate_timespec(round(remaining))

                if original_start:
                    msg += ' of the original %s.' % _generate_timespec(round(original_end - original_start))
                else:
                    msg += '.'

            if reason:
                msg += '\n\nReason for ending early: ' + reason

            if data.get('reason'):
                msg += '\n\nOriginal reason was: ' + data['reason']

            if not await self._unpunish(user, msg, update=True):
                msg += '\n\n(failed to send punishment end notification DM)'

            await self.bot.say(msg)
        elif data:  # This shouldn't happen, but just in case
            now = time.time()
            until = data.get('until')
            remaining = until and _generate_timespec(round(until - now)) or 'forever'

            data_fmt = '\n'.join([
                "**Reason:** %s" % (data.get('reason') or 'no reason set'),
                "**Time remaining:** %s" % remaining,
                "**Moderator**: %s" % (user.server.get_member(data.get('by')) or 'Missing ID#%s' % data.get('by'))
            ])
            self.json[sid].pop(user.id, None)
            self.save()
            await self.bot.say("That user doesn't have the %s role, but they still have a data entry. I removed it, "
                               "but in case it's needed, this is what was there:\n\n%s" % (role.name, data_fmt))
        elif role:
            await self.bot.say("That user doesn't have the %s role." % role.name)
        else:
            await self.bot.say("The punish role couldn't be found in this server.")

    @punish.command(pass_context=True, no_pm=True, name='reason')
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_reason(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Updates the reason for a punishment, including the modlog if a case exists.
        """
        server = ctx.message.server
        data = self.json.get(server.id, {}).get(user.id, {})

        if not data:
            await self.bot.say("That user doesn't have an active punishment entry. To update modlog "
                               "cases manually, use the `%sreason` command." % ctx.prefix)
            return

        data['reason'] = reason
        self.save()
        if reason:
            msg = 'Reason updated.'
        else:
            msg = 'Reason cleared'

        caseno = data.get('caseno')
        mod = self.bot.get_cog('Mod')

        if mod and caseno and ENABLE_MODLOG:
            moderator = ctx.message.author
            case_error = None

            try:
                if moderator.id != data.get('by') and not mod.is_admin_or_superior(moderator):
                    moderator = server.get_member(data.get('by')) or server.me  # fallback gracefully

                await mod.update_case(server, case=caseno, reason=reason, mod=moderator)
            except CaseMessageNotFound:
                case_error = 'the case message could not be found'
            except NoModLogAccess:
                case_error = 'I do not have access to the modlog channel'
            except Exception:
                pass

            if case_error:
                msg += '\n\n' + warning('There was an error updating the modlog case: %s.' % case_error)

        await self.bot.say(msg)

    async def get_role(self, server, quiet=False, create=False):
        default_name = DEFAULT_ROLE_NAME
        role_id = self.json.get(server.id, {}).get('ROLE_ID')

        if role_id:
            role = discord.utils.get(server.roles, id=role_id)
        else:
            role = discord.utils.get(server.roles, name=default_name)

        if create and not role:
            perms = server.me.server_permissions
            if not perms.manage_roles and perms.manage_channels:
                await self.bot.say("The Manage Roles and Manage Channels permissions are required to use this command.")
                return

            else:
                msg = "The %s role doesn't exist; Creating it now..." % default_name

                if not quiet:
                    msgobj = await self.bot.reply(msg)

                log.debug('Creating punish role in %s' % server.name)
                perms = discord.Permissions.none()
                role = await self.bot.create_role(server, name=default_name, permissions=perms)
                await self.bot.move_role(server, role, server.me.top_role.position - 1)

                if not quiet:
                    msgobj = await self.bot.edit_message(msgobj, msgobj.content + 'configuring channels... ')

                for channel in server.channels:
                    await self.setup_channel(channel, role)

                if not quiet:
                    await self.bot.edit_message(msgobj, msgobj.content + 'done.')

        if role and role.id != role_id:
            if server.id not in self.json:
                self.json[server.id] = {}

            self.json[server.id]['ROLE_ID'] = role.id
            self.save()

        return role

    async def setup_channel(self, channel, role):
        settings = self.json.get(channel.server.id, {})
        timeout_channel_id = settings.get('CHANNEL_ID')

        if channel.id == timeout_channel_id:
            # maybe this will be used later:
            # config = settings.get('TIMEOUT_OVERWRITE')
            config = None
            defaults = DEFAULT_TIMEOUT_OVERWRITE
        elif channel.type is discord.ChannelType.voice:
            config = settings.get('VOICE_OVERWRITE')
            defaults = DEFAULT_VOICE_OVERWRITE
        else:
            config = settings.get('TEXT_OVERWRITE')
            defaults = DEFAULT_TEXT_OVERWRITE

        if config:
            perms = overwrite_from_dict(config)
        else:
            perms = defaults

        await self.bot.edit_channel_permissions(channel, role, overwrite=perms)

    async def on_load(self):
        await self.bot.wait_until_ready()

        for serverid, members in self.json.copy().items():
            server = self.bot.get_server(serverid)

            # Bot is no longer in the server
            if not server:
                del(self.json[serverid])
                continue

            me = server.me
            role = await self.get_role(server, quiet=True, create=True)

            if not role:
                log.error("Needed to create punish role in %s, but couldn't." % server.name)
                continue

            for member_id, data in members.copy().items():
                if not member_id.isdigit():
                    continue

                until = data['until']
                member = server.get_member(member_id)

                if until and (until - time.time()) < 0:
                    if member:
                        reason = 'Punishment removal overdue, maybe the bot was offline. '

                        if self.json[server.id][member_id]['reason']:
                            reason += self.json[server.id][member_id]['reason']

                        await self._unpunish(member, reason)
                    else:  # member disappeared
                        del(self.json[server.id][member_id])

                elif member:
                    if role not in member.roles:
                        if role >= me.top_role:
                            log.error("Needed to re-add punish role to %s in %s, but couldn't." % (member, server.name))
                            continue

                        await self.bot.add_roles(member, role)

                    if until:
                        await self.schedule_unpunish(until, member)

        self.save()

        try:
            while self == self.bot.get_cog('Punish'):
                while True:
                    async with self.queue_lock:
                        if not await self.process_queue_event():
                            break

                await asyncio.sleep(5)

        except asyncio.CancelledError:
            pass
        finally:
            log.debug('queue manager dying')

            while not self.queue.empty():
                self.queue.get_nowait()

            for fut in self.pending.values():
                fut.cancel()

    async def cancel_queue_event(self, *args) -> bool:
        if args in self.pending:
            self.pending.pop(args).cancel()
            return True
        else:
            events = []
            removed = None

            async with self.queue_lock:
                while not self.queue.empty():
                    item = self.queue.get_nowait()

                    if args == item[1:]:
                        removed = item
                        break
                    else:
                        events.append(item)

                for item in events:
                    self.queue.put_nowait(item)

            return removed is not None

    async def put_queue_event(self, run_at : float, *args):
        diff = run_at - time.time()

        if args in self.enqueued:
            return False

        self.enqueued.add(args)

        if diff < 0:
            self.execute_queue_event(*args)
        elif run_at - time.time() < QUEUE_TIME_CUTOFF:
            self.pending[args] = self.bot.loop.call_later(diff, self.execute_queue_event, *args)
        else:
            await self.queue.put((run_at, *args))

    async def process_queue_event(self):
        if self.queue.empty():
            return False

        now = time.time()
        item = await self.queue.get()
        next_time, *args = item

        diff = next_time - now

        if diff < 0:
            self.execute_queue_event(*args)
        elif diff < QUEUE_TIME_CUTOFF:
            self.pending[args] = self.bot.loop.call_later(diff, self.execute_queue_event, *args)
            return True
        else:
            await self.queue.put(item)
            return False

    def execute_queue_event(self, *args):
        self.enqueued.discard(args)

        try:
            self.execute_unpunish(*args)
        except Exception:
            log.exception("failed to execute scheduled event")

    async def _punish_cmd_common(self, ctx, member, duration, reason, quiet=False):
        server = ctx.message.server
        using_default = False
        updating_case = False
        case_error = None
        mod = self.bot.get_cog('Mod')

        if server.id not in self.json:
            self.json[server.id] = {}

        current = self.json[server.id].get(member.id, {})
        reason = reason or current.get('reason')  # don't clear if not given
        hierarchy_allowed = ctx.message.author.top_role > member.top_role
        case_min_length = self.json[server.id].get('CASE_MIN_LENGTH', _parse_time(DEFAULT_CASE_MIN_LENGTH))

        if mod:
            hierarchy_allowed = mod.is_allowed_by_hierarchy(server, ctx.message.author, member)

        if not hierarchy_allowed:
            await self.bot.say('Permission denied due to role hierarchy.')
            return
        elif member == server.me:
            await self.bot.say("You can't punish the bot.")
            return

        if duration and duration.lower() in ['forever', 'inf', 'infinite']:
            duration = None
        else:
            if not duration:
                using_default = True
                duration = DEFAULT_TIMEOUT

            try:
                duration = _parse_time(duration)
                if duration < 1:
                    await self.bot.say("Duration must be 1 second or longer.")
                    return False
            except BadTimeExpr as e:
                await self.bot.say("Error parsing duration: %s." % e.args)
                return False

        role = await self.get_role(server, quiet=quiet, create=True)
        if role is None:
            return

        if role >= server.me.top_role:
            await self.bot.say('The %s role is too high for me to manage.' % role)
            return

        # Call time() after getting the role due to potential creation delay
        now = time.time()
        until = (now + duration + 0.5) if duration else None
        duration_ok = (case_min_length is not None) and ((duration is None) or duration >= case_min_length)

        if mod and self.can_create_cases() and duration_ok and ENABLE_MODLOG:
            mod_until = until and datetime.utcfromtimestamp(until)

            try:
                if current:
                    case_number = current.get('caseno')
                    moderator = ctx.message.author
                    updating_case = True

                    # update_case does ownership checks, we need to cheat them in case the
                    # command author doesn't qualify to edit a case
                    if moderator.id != current.get('by') and not mod.is_admin_or_superior(moderator):
                        moderator = server.get_member(current.get('by')) or server.me  # fallback gracefully

                    await mod.update_case(server, case=case_number, reason=reason, mod=moderator,
                                          until=mod_until and mod_until.timestamp() or False)
                else:
                    case_number = await mod.new_case(server, action=ACTION_STR, mod=ctx.message.author,
                                                     user=member, reason=reason, until=mod_until,
                                                     force_create=True)
            except Exception as e:
                case_error = e
        else:
            case_number = None

        subject = 'the %s role' % role.name

        if member.id in self.json[server.id]:
            if role in member.roles:
                msg = '{0} already had the {1.name} role; resetting their timer.'
            else:
                msg = '{0} is missing the {1.name} role for some reason. I added it and reset their timer.'
        elif role in member.roles:
            msg = '{0} already had the {1.name} role, but had no timer; setting it now.'
        else:
            msg = 'Applied the {1.name} role to {0}.'
            subject = 'it'

        msg = msg.format(member, role)

        if duration:
            timespec = _generate_timespec(duration)

            if using_default:
                timespec += ' (the default)'

            msg += ' I will remove %s in %s.' % (subject, timespec)

        if duration_ok and not (self.can_create_cases() and ENABLE_MODLOG):
            if mod:
                msg += '\n\n' + warning('If you can, please update the bot so I can create modlog cases.')
            else:
                pass  # msg += '\n\nI cannot create modlog cases if the `mod` cog is not loaded.'
        elif case_error and ENABLE_MODLOG:
            if isinstance(case_error, CaseMessageNotFound):
                case_error = 'the case message could not be found'
            elif isinstance(case_error, NoModLogAccess):
                case_error = 'I do not have access to the modlog channel'
            else:
                case_error = None

            if case_error:
                verb = 'updating' if updating_case else 'creating'
                msg += '\n\n' + warning('There was an error %s the modlog case: %s.' % (verb, case_error))
        elif case_number:
            verb = 'updated' if updating_case else 'created'
            msg += ' I also %s case #%i in the modlog.' % (verb, case_number)

        voice_overwrite = self.json[server.id].get('VOICE_OVERWRITE')

        if voice_overwrite:
            voice_overwrite = overwrite_from_dict(voice_overwrite)
        else:
            voice_overwrite = DEFAULT_VOICE_OVERWRITE

        overwrite_denies_speak = (voice_overwrite.speak is False) or (voice_overwrite.connect is False)

        self.json[server.id][member.id] = {
            'start'  : current.get('start') or now,  # don't override start time if updating
            'until'  : until,
            'by'     : current.get('by') or ctx.message.author.id,  # don't override original moderator
            'reason' : reason,
            'unmute' : overwrite_denies_speak and not member.voice.mute,
            'caseno' : case_number
        }

        await self.bot.add_roles(member, role)

        if member.voice_channel and overwrite_denies_speak:
            await self.bot.server_voice_state(member, mute=True)

        self.save()

        # schedule callback for role removal
        if until:
            await self.schedule_unpunish(until, member)

        if not quiet:
            await self.bot.say(msg)

        return True

    # Functions related to unpunishing

    async def schedule_unpunish(self, until, member):
        """
        Schedules role removal, canceling and removing existing tasks if present
        """

        await self.put_queue_event(until, member.server.id, member.id)

    def execute_unpunish(self, server_id, member_id):
        server = self.bot.get_server(server_id)

        if not server:
            return

        member = server.get_member(member_id)

        if member:
            self.bot.loop.create_task(self._unpunish(member))

    async def _unpunish(self, member, reason=None, remove_role=True, update=False, moderator=None) -> bool:
        """
        Remove punish role, delete record and task handle
        """
        server = member.server
        role = await self.get_role(server, quiet=True)

        if role:
            data = self.json.get(member.server.id, {})
            member_data = data.get(member.id, {})
            caseno = member_data.get('caseno')
            mod = self.bot.get_cog('Mod')

            # Has to be done first to prevent triggering listeners
            self._unpunish_data(member)
            await self.cancel_queue_event(member.server.id, member.id)

            if remove_role:
                await self.bot.remove_roles(member, role)

            if update and caseno and mod:
                until = member_data.get('until') or False

                if until:
                    until = datetime.utcfromtimestamp(until).timestamp()

                if moderator and moderator.id != member_data.get('by') and not mod.is_admin_or_superior(moderator):
                    moderator = None

                # fallback gracefully
                moderator = moderator or server.get_member(member_data.get('by')) or server.me

                try:
                    await mod.update_case(server, case=caseno, reason=reason, mod=moderator, until=until)
                except Exception:
                    pass

            if member_data.get('unmute', False):
                if member.voice_channel:
                    await self.bot.server_voice_state(member, mute=False)
                else:
                    if 'PENDING_UNMUTE' not in data:
                        data['PENDING_UNMUTE'] = []

                    unmute_list = data['PENDING_UNMUTE']

                    if member.id not in unmute_list:
                        unmute_list.append(member.id)
                    self.save()

            msg = 'Your punishment in %s has ended.' % member.server.name

            if reason:
                msg += "\nReason: %s" % reason

            try:
                await self.bot.send_message(member, msg)
                return True
            except Exception:
                return False

    def _unpunish_data(self, member):
        """Removes punish data entry and cancels any present callback"""
        sid = member.server.id

        if member.id in self.json.get(sid, {}):
            del(self.json[member.server.id][member.id])
            self.save()

    # Listeners

    async def on_channel_create(self, channel):
        """Run when new channels are created and set up role permissions"""
        if channel.is_private:
            return

        role = await self.get_role(channel.server, quiet=True)
        if not role:
            return

        await self.setup_channel(channel, role)

    async def on_member_update(self, before, after):
        """Remove scheduled unpunish when manually removed"""
        sid = before.server.id
        data = self.json.get(sid, {})
        member_data = data.get(before.id)

        if member_data is None:
            return

        role = await self.get_role(before.server, quiet=True)
        if role and role in before.roles and role not in after.roles:
            msg = 'Punishment manually ended early by a moderator/admin.'
            if member_data['reason']:
                msg += '\nReason was: ' + member_data['reason']

            await self._unpunish(after, msg, remove_role=False, update=True)

    async def on_member_join(self, member):
        """Restore punishment if punished user leaves/rejoins"""
        sid = member.server.id
        role = await self.get_role(member.server, quiet=True)
        data = self.json.get(sid, {}).get(member.id)
        if not role or data is None:
            return

        until = data['until']
        duration = until - time.time()
        if duration > 0:
            await self.bot.add_roles(member, role)
            await self.schedule_unpunish(until, member)

    async def on_voice_state_update(self, before, after):
        data = self.json.get(before.server.id, {})
        member_data = data.get(before.id, {})
        unmute_list = data.get('PENDING_UNMUTE', [])

        if not after.voice_channel:
            return

        if member_data and not after.voice.mute:
            await self.bot.server_voice_state(after, mute=True)

        elif before.id in unmute_list:
            await self.bot.server_voice_state(after, mute=False)
            while before.id in unmute_list:
                unmute_list.remove(before.id)
            self.save()
    async def mass_purge(self, messages):
        while messages:
            if len(messages) > 1:
                await self.bot.delete_messages(messages[:100])
                messages = messages[100:]
            else:
                await self.bot.delete_message(messages[0])
                messages = []
            await asyncio.sleep(1.5)

    async def slow_deletion(self, messages):
        for message in messages:
            try:
                await self.bot.delete_message(message)
            except:
                pass

    def is_admin_or_superior(self, obj):
        if isinstance(obj, discord.Message):
            user = obj.author
        elif isinstance(obj, discord.Member):
            user = obj
        elif isinstance(obj, discord.Role):
            pass
        else:
            raise TypeError('Only messages, members or roles may be passed')

        server = obj.server
        admin_role = settings.get_server_admin(server)

        if isinstance(obj, discord.Role):
            return obj.name == admin_role

        if user.id == settings.owner:
            return True
        elif discord.utils.get(user.roles, name=admin_role):
            return True
        else:
            return False

    def is_mod_or_superior(self, obj):
        if isinstance(obj, discord.Message):
            user = obj.author
        elif isinstance(obj, discord.Member):
            user = obj
        elif isinstance(obj, discord.Role):
            pass
        else:
            raise TypeError('Only messages, members or roles may be passed')

        server = obj.server
        admin_role = settings.get_server_admin(server)
        mod_role = settings.get_server_mod(server)

        if isinstance(obj, discord.Role):
            return obj.name in [admin_role, mod_role]

        if user.id == settings.owner:
            return True
        elif discord.utils.get(user.roles, name=admin_role):
            return True
        elif discord.utils.get(user.roles, name=mod_role):
            return True
        else:
            return False

    def is_allowed_by_hierarchy(self, server, mod, user):
        toggled = self.settings[server.id].get("respect_hierarchy",
                                               default_settings["respect_hierarchy"])
        is_special = mod == server.owner or mod.id == self.bot.settings.owner

        if not toggled:
            return True
        else:
            return mod.top_role.position > user.top_role.position or is_special

    async def new_case(self, server, *, action, mod=None, user, reason=None, until=None, channel=None, force_create=False):
        action_type = action.lower() + "_cases"
        
        enabled_case = self.settings.get(server.id, {}).get(action_type, default_settings.get(action_type))
        if not force_create and not enabled_case:
            return False

        mod_channel = server.get_channel(self.settings[server.id]["mod-log"])
        if mod_channel is None:
            return None

        if server.id not in self.cases:
            self.cases[server.id] = {}

        case_n = len(self.cases[server.id]) + 1

        case = {
            "case"         : case_n,
            "created"      : datetime.utcnow().timestamp(),
            "modified"     : None,
            "action"       : action,
            "channel"      : channel.id if channel else None,
            "user"         : str(user),
            "user_id"      : user.id,
            "reason"       : reason,
            "moderator"    : str(mod) if mod is not None else None,
            "moderator_id" : mod.id if mod is not None else None,
            "amended_by"   : None,
            "amended_id"   : None,
            "message"      : None,
            "until"        : until.timestamp() if until else None,
        }

        case_msg = self.format_case_msg(case)

        try:
            msg = await self.bot.send_message(mod_channel, case_msg)
            case["message"] = msg.id
        except:
            pass

        self.cases[server.id][str(case_n)] = case

        if mod:
            self.last_case[server.id][mod.id] = case_n

        dataIO.save_json("data/mod/modlog.json", self.cases)

        return case_n

    async def update_case(self, server, *, case, mod=None, reason=None,
                          until=False):
        channel = server.get_channel(self.settings[server.id]["mod-log"])
        if channel is None:
            raise NoModLogChannel()

        case = str(case)
        case = self.cases[server.id][case]

        if case["moderator_id"] is not None:
            if case["moderator_id"] != mod.id:
                if self.is_admin_or_superior(mod):
                    case["amended_by"] = str(mod)
                    case["amended_id"] = mod.id
                else:
                    raise UnauthorizedCaseEdit()
        else:
            case["moderator"] = str(mod)
            case["moderator_id"] = mod.id

        if case["reason"]:  # Existing reason
            case["modified"] = datetime.utcnow().timestamp()
        case["reason"] = reason

        if until is not False:
            case["until"] = until

        case_msg = self.format_case_msg(case)

        dataIO.save_json("data/mod/modlog.json", self.cases)

        if case["message"] is None:  # The case's message was never sent
            raise CaseMessageNotFound()

        try:
            msg = await self.bot.get_message(channel, case["message"])
        except discord.NotFound:
            raise CaseMessageNotFound()
        except discord.Forbidden:
            raise NoModLogAccess()
        else:
            await self.bot.edit_message(msg, case_msg)


    def format_case_msg(self, case):
        tmp = case.copy()
        if case["reason"] is None:
            tmp["reason"] = "Type [p]reason %i <reason> to add it" % tmp["case"]
        if case["moderator"] is None:
            tmp["moderator"] = "Unknown"
            tmp["moderator_id"] = "Nobody has claimed responsibility yet"
        if case["action"] in ACTIONS_REPR:
            tmp["action"] = ' '.join(ACTIONS_REPR[tmp["action"]])

        channel = case.get("channel")
        if channel:
            channel = self.bot.get_channel(channel)
            tmp["action"] += ' in ' + channel.mention

        contains_invite = any(("discord.gg/"     in tmp["user"].lower(),
                               "discordapp.com/" in tmp["user"].lower()))
        if contains_invite:
            tmp["user"] = tmp["user"].replace(".", "\u200b.")
        
        case_msg = (
            "**Case #{case}** | {action}\n"
            "**User:** {user} ({user_id})\n"
            "**Moderator:** {moderator} ({moderator_id})\n"
        ).format(**tmp)

        created = case.get('created')
        until = case.get('until')
        if created and until:
            start = datetime.fromtimestamp(created)
            end = datetime.fromtimestamp(until)
            end_fmt = end.strftime('%Y-%m-%d %H:%M:%S UTC')
            duration = end - start
            dur_fmt = strfdelta(duration)
            case_msg += ("**Until:** {}\n"
                         "**Duration:** {}\n").format(end_fmt, dur_fmt)

        amended = case.get('amended_by')
        if amended:
            amended_id = case.get('amended_id')
            case_msg += "**Amended by:** %s (%s)\n" % (amended, amended_id)

        modified = case.get('modified')
        if modified:
            modified = datetime.fromtimestamp(modified)
            modified_fmt = modified.strftime('%Y-%m-%d %H:%M:%S UTC')
            case_msg += "**Last modified:** %s\n" % modified_fmt

        case_msg += "**Reason:** %s\n" % tmp["reason"]

        return case_msg

    async def check_filter(self, message):
        server = message.server
        if server.id in self.filter.keys():
            for w in self.filter[server.id]:
                if w in message.content.lower():
                    try:
                        await self.bot.delete_message(message)
                        logger.info("Message deleted in server {}."
                                    "Filtered: {}"
                                    "".format(server.id, w))
                        return True
                    except:
                        pass
        return False

    async def check_duplicates(self, message):
        server = message.server
        author = message.author
        if server.id not in self.settings:
            return False
        if self.settings[server.id]["delete_repeats"]:
            if not message.content:
                return False
            if author.id not in self.cache:
                self.cache[author.id] = deque(maxlen=3)
            self.cache.move_to_end(author.id)
            while len(self.cache) > 100000:
                self.cache.popitem(last=False) # the oldest gets discarded
            self.cache[author.id].append(message.content)
            msgs = self.cache[author.id]
            if len(msgs) == 3 and msgs[0] == msgs[1] == msgs[2]:
                try:
                    await self.bot.delete_message(message)
                    return True
                except:
                    pass
        return False

    async def check_mention_spam(self, message):
        server = message.server
        author = message.author
        if server.id not in self.settings:
            return False
        if self.settings[server.id]["ban_mention_spam"]:
            max_mentions = self.settings[server.id]["ban_mention_spam"]
            mentions = set(message.mentions)
            if len(mentions) >= max_mentions:
                try:
                    self.temp_cache.add(author, server, "BAN")
                    await self.bot.ban(author, 1)
                except:
                    logger.info("Failed to ban member for mention spam in "
                                "server {}".format(server.id))
                else:
                    await self.new_case(server,
                                        action="BAN",
                                        mod=server.me,
                                        user=author,
                                        reason="Mention spam (Autoban)")
                    return True
        return False

    async def on_command(self, command, ctx):
        """Currently used for:
            * delete delay"""
        server = ctx.message.server
        message = ctx.message
        try:
            delay = self.settings[server.id]["delete_delay"]
        except KeyError:
            # We have no delay set
            return
        except AttributeError:
            # DM
            return

        if delay == -1:
            return

        async def _delete_helper(bot, message):
            try:
                await bot.delete_message(message)
                logger.debug("Deleted command msg {}".format(message.id))
            except:
                pass  # We don't really care if it fails or not

        await asyncio.sleep(delay)
        await _delete_helper(self.bot, message)

    async def on_message(self, message):
        author = message.author
        if message.server is None or self.bot.user == author:
            return

        valid_user = isinstance(author, discord.Member) and not author.bot

        #  Bots and mods or superior are ignored from the filter
        if not valid_user or self.is_mod_or_superior(message):
            return

        deleted = await self.check_filter(message)
        if not deleted:
            deleted = await self.check_duplicates(message)
        if not deleted:
            deleted = await self.check_mention_spam(message)

    async def on_message_edit(self, _, message):
        author = message.author
        if message.server is None or self.bot.user == author:
            return

        valid_user = isinstance(author, discord.Member) and not author.bot

        if not valid_user or self.is_mod_or_superior(message):
            return

        await self.check_filter(message)

    async def on_member_ban(self, member):
        server = member.server
        if not self.temp_cache.check(member, server, "BAN"):
            await self.new_case(server,
                                user=member,
                                action="BAN")

    async def on_member_unban(self, server, user):
        if not self.temp_cache.check(user, server, "UNBAN"):
            await self.new_case(server,
                                user=user,
                                action="UNBAN")

    async def check_names(self, before, after):
        if before.name != after.name:
            if before.id not in self.past_names:
                self.past_names[before.id] = [after.name]
            else:
                if after.name not in self.past_names[before.id]:
                    names = deque(self.past_names[before.id], maxlen=20)
                    names.append(after.name)
                    self.past_names[before.id] = list(names)
            dataIO.save_json("data/mod/past_names.json", self.past_names)

        if before.nick != after.nick and after.nick is not None:
            server = before.server
            if server.id not in self.past_nicknames:
                self.past_nicknames[server.id] = {}
            if before.id in self.past_nicknames[server.id]:
                nicks = deque(self.past_nicknames[server.id][before.id],
                              maxlen=20)
            else:
                nicks = []
            if after.nick not in nicks:
                nicks.append(after.nick)
                self.past_nicknames[server.id][before.id] = list(nicks)
                dataIO.save_json("data/mod/past_nicknames.json",
                                 self.past_nicknames)

    def are_overwrites_empty(self, overwrites):
        """There is currently no cleaner way to check if a
        PermissionOverwrite object is empty"""
        original = [p for p in iter(overwrites)]
        empty = [p for p in iter(discord.PermissionOverwrite())]
        return original == empty


def strfdelta(delta):
    s = []
    if delta.days:
        ds = '%i day' % delta.days
        if delta.days > 1:
            ds += 's'
        s.append(ds)
    hrs, rem = divmod(delta.seconds, 60*60)
    if hrs:
        hs = '%i hr' % hrs
        if hrs > 1:
            hs += 's'
        s.append(hs)
    mins, secs = divmod(rem, 60)
    if mins:
        s.append('%i min' % mins)
    if secs:
        s.append('%i sec' % secs)
    return ' '.join(s)

def compat_load(path):
    data = dataIO.load_json(path)
    for server, punishments in data.items():
        for user, pdata in punishments.items():
            if not user.isdigit():
                continue

            # read Kownlin json
            by = pdata.pop('givenby', None)
            by = by if by else pdata.pop('by', None)
            pdata['by'] = by
            pdata['until'] = pdata.pop('until', None)
            pdata['reason'] = pdata.pop('reason', None)

    return data


def check_folder():
    if not os.path.exists(PATH):
        log.debug('Creating folder: data/punish')
        os.makedirs(PATH)


def check_file():
    if not dataIO.is_valid_json(JSON):
        print('Creating empty %s' % JSON)
        dataIO.save_json(JSON, {})

def check_folders():
    folders = ("data", "data/mod/")
    for folder in folders:
        if not os.path.exists(folder):
            print("Creating " + folder + " folder...")
            os.makedirs(folder)


def check_files():
    ignore_list = {"SERVERS": [], "CHANNELS": []}

    files = {
        "ignorelist.json"     : ignore_list,
        "filter.json"         : {},
        "past_names.json"     : {},
        "past_nicknames.json" : {},
        "settings.json"       : {},
        "modlog.json"         : {},
        "perms_cache.json"    : {}
    }

    for filename, value in files.items():
        if not os.path.isfile("data/mod/{}".format(filename)):
            print("Creating empty {}".format(filename))
            dataIO.save_json("data/mod/{}".format(filename), value)


def setup(bot):
    global logger
    check_folders()
    check_files()
    check_file()
    check_folder()
    logger = logging.getLogger("mod")
    # Prevents the logger from being loaded again in case of module reload
    if logger.level == 0:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(
            filename='data/mod/mod.log', encoding='utf-8', mode='a')
        handler.setFormatter(
            logging.Formatter('%(asctime)s %(message)s', datefmt="[%d/%m/%Y %H:%M]"))
        logger.addHandler(handler)
    n = Mod(bot)
    bot.add_listener(n.check_names, "on_member_update")
    bot.add_cog(n)
