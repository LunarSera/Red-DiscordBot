#Disclaimer: This cog was created, heavilly based on work from others. Credit should go to where it's due.

from collections import namedtuple
import os, discord, random, asyncio, string, logging, datetime, re, time, socket, subprocess, typing, os.path
from cogs.utils import checks
from socket import AF_INET, SOCK_STREAM, SOCK_DGRAM
from discord.ext import commands
from __main__ import send_cmd_help, settings
from random import choice as randchoice, randint
from .utils.dataIO import dataIO
from .utils.chat_formatting import escape, escape_mass_mentions, italics, pagify, box
from .utils.chat_formatting import *
from .utils import checks
from urllib.parse import quote_plus, urlparse
MessageList = typing.List[discord.Message]
OpenRift = namedtuple("Rift", ["source", "destination"])
# Speedtest is forked from DinnerCogs
# System Info is from https://github.com/giampaolo/psutil/tree/master/scripts
# noinspection SpellCheckingInspection,PyPep8Naming,PyPep8Naming
try:
    import speedtest

    module_avail = True
except ImportError:
    module_avail = False

try:
    import psutil
    psutilAvailable = True
except ImportError:
    psutilAvailable = False
def get_role(ctx, role_id):
    roles = set(ctx.message.server.roles)
    for role in roles:
        if role.id == role_id:
            return role
    return None
def process_avatar(url):
    if ".gif" in url:
        new_url = re.sub("\?size\=\d+.*", "?size=2048", url)
        return new_url
    else:
        new_url = url.replace('.webp', '.png')
        return new_url
class Utility:
    """Useful backend commands"""

    # File related constants
    DATA_FOLDER = "data/utility"
    DATA_FILE_PATH = DATA_FOLDER + "/voicelock.json"

    # Configuration default
    CONFIG_DEFAULT = {"locks": {}, "not_lockable": [], "exclusivities": {}}

    # Behavior constants
    TEMP_MESSAGE_TIMEOUT = 15

    # Message constants
    NOT_IN_CHANNEL_MSG = ":x: You must be in a voice channel to do that."
    CHANNEL_ALREADY_LOCKED = ":x: {} is already locked."
    CHANNEL_NOT_LOCKABLE = ":x: {} cannot be locked."
    CHANNEL_LOCKED = """:lock: {channel} has been locked.
You can now use `{p}voice permit @user` to allow the user to join you or `{p}voice unlock` to completely unlock it."""
    NOT_A_VOICE_CHANNEL = ":x: Error: {} is not a voice channel."
    CHANNEL_NOT_LOCKED = ":x: Error: {} is not locked."
    CHANNEL_UNLOCKED = ":unlock: {} has been unlocked."
    USER_PERMITTED = ":inbox_tray: {user} has been allowed in {channel}."
    NOW_LOCKABLE = ":white_check_mark: {} can now be locked."
    NOW_NOT_LOCKABLE = ":negative_squared_cross_mark: {} can no longer be locked."
    NOT_A_TEXT_CHANNEL = ":x: Error: {} is not a text channel."
    EXCLUSIVITY_SET = ":white_check_mark: The exclusivity for **{s}** has been set to **{c}**."
    WRONG_CHANNEL = ":x: Wrong channel. Please do that in <#{}>."
    EXCLUSIVITY_RESET = ":put_litter_in_its_place: The exclusivity for **{}** has been removed."

    def __init__(self, bot):
        self.bot = bot
        self.new_data = False
        self.data = dataIO.load_json('data/utility/vcrole.json')
        self.say = dataIO.load_json("data/utility/say.json")
        self.open_rifts = {}
        self.filepath = "data/utility/speedtest.json"
        self.settings = dataIO.load_json(self.filepath)
        self.logger = logging.getLogger("red.ZeCogs.voice_lock")
        self.check_configs()
        self.load_data()
        self.leave_dir = "data/utility/leave.json"
        self.leave_data = dataIO.load_json(self.leave_dir)
        self.cant_connect_perms = discord.PermissionOverwrite(connect=False)
        self.can_connect_perms = discord.PermissionOverwrite(connect=True)
        asyncio.ensure_future(self.initialize())

    async def _save_data(self):
        dataIO.save_json('data/utility/vcrole.json', self.data)

    def save_data(self):
        """Saves the json"""
        dataIO.save_json(self.leave_dir, self.leave_data)

    async def _on_voice_state_update(self, before, after):
        try:
            server = after.server
            if server.id in self.data:
                server_role = self.data[server.id]['ROLE']
                if server_role:
                    for role in server.roles:
                        if role.name.lower() == server_role.lower():
                            if role in after.roles and after.voice_channel is None:
                                await self.bot.remove_roles(after, role)
                            elif role not in before.roles and after.voice_channel:
                                await self.bot.add_roles(after, role)
        except Exception as e:
            print('Houston, we have a problem: {}'.format(e))

    # Events
    async def on_voice_state_update(self, before: discord.Member, after: discord.Member):
        channel = before.voice_channel
        if channel is not None and channel != after.voice_channel and channel.id in self.config["locks"]:
            if before.id == self.config["locks"][channel.id]["who_locked"]:
                await self.unlock_channel(channel, before)
                self.save_data()
            else:
                try:
                    await self.bot.delete_channel_permissions(channel, before)
                except discord.NotFound:
                    self.logger.warning("Couldn't find the channel from which permissions are deleted. Ignoring.")
        elif after.voice_channel is not None and channel != after.voice_channel \
                and after.voice_channel.id in self.config["locks"] \
                and after.id in self.config["locks"][after.voice_channel.id]["permits"]:
            self.config["locks"][after.voice_channel.id]["permits"].remove(after.id)
    
    async def initialize(self):
        await self.bot.wait_until_ready()
        await self.verify_locked_channels()

    async def data_writer(self):
        while self == self.bot.get_cog('Seen'):
            if self.new_data:
                dataIO.save_json('data/enigmata/seen.json', self.seen)
                self.new_data = False
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(30)

    def speed_test(self):
        return str(subprocess.check_output(['speedtest-cli'], stderr=subprocess.STDOUT))

    @commands.group(pass_context=True, no_pm=False)
    async def speedtest(self, ctx):
        """..."""
        await self.bot.say('You can set Parameters as an Admin with *n/speedtest parameters*')
        if ctx.invoked_subcommand is None:
            try:
                channel = ctx.message.channel
                author = ctx.message.author
                user = author
                high = self.settings[author.id]['upperbound']
                low = self.settings[author.id]['lowerbound']
                multiplyer = (self.settings[author.id]['data_type'])
                message12 = await self.bot.say(" :stopwatch: **Running speedtest. This may take a while!** :stopwatch:")
                DOWNLOAD_RE = re.compile(r"Download: ([\d.]+) .bit")
                UPLOAD_RE = re.compile(r"Upload: ([\d.]+) .bit")
                PING_RE = re.compile(r"([\d.]+) ms")
                speedtest_result = await self.bot.loop.run_in_executor(None, self.speed_test)
                download = float(DOWNLOAD_RE.search(speedtest_result).group(1)) * float(multiplyer)
                upload = float(UPLOAD_RE.search(speedtest_result).group(1)) * float(multiplyer)
                ping = float(PING_RE.search(speedtest_result).group(1)) * float(multiplyer)
                message = 'Your speedtest results are'
                message_down = '**{}** mbps'.format(download)
                message_up = '**{}** mbps'.format(upload)
                message_ping = '**{}** ms'.format(ping)
                if download >= float(high):
                    colour = 0x45FF00
                    indicator = 'Fast'
                if download > float(low) and download < float(high):
                    colour = 0xFF4500
                    indicator = 'Fair'
                if download <= float(low):
                    colour = 0xFF3A00
                    indicator = 'Slow'
                embed = discord.Embed(colour=colour, description=message)
                embed.title = 'Speedtest Results'
                embed.add_field(name='Download', value=message_down)
                embed.add_field(name=' Upload', value=message_up)
                embed.add_field(name=' Ping', value=message_ping)
                embed.set_footer(text='The Bots internet is pretty {}'.format(indicator))
                await self.bot.say(embed=embed)
            except KeyError:
                await self.bot.say('Please setup the speedtest settings using **{}parameters**'.format(ctx.prefix))

    @speedtest.command(pass_context=True, no_pm=False, hidden=True)
    @checks.mod_or_permissions(manage_server=True)
    async def parameters(self, ctx, high: int, low: int, units='bits'):
        ''' Settings of the speedtest cog,
        High stands for the value above which your download is considered fast
        Low  stands for the value above which your download is considered Slow
        units stands for units of measurement of speed, either megaBITS/s or megaBYTES/s (By default it is megaBITS/s)'''
        author = ctx.message.author
        self.settings[author.id] = {}
        unitz = ['bits', 'bytes']
        if units.lower() in unitz:
            if units == 'bits':
                self.settings[author.id].update({'data_type': '1'})
                dataIO.save_json(self.filepath, self.settings)
            else:
                self.settings[author.id].update({'data_type': '0.125'})
                dataIO.save_json(self.filepath, self.settings)
            if float(high) < float(low):
                await self.bot.say('Error High is less that low')
            else:
                self.settings[author.id].update({'upperbound': high})
                self.settings[author.id].update({'lowerbound': low})
                dataIO.save_json(self.filepath, self.settings)
                embed2 = discord.Embed(colour=0x45FF00, descriprion='These are your settings')
                embed2.title = 'Speedtest settings'
                embed2.add_field(name='High', value='{}'.format(high))
                embed2.add_field(name='Low', value='{}'.format(low))
                embed2.add_field(name='Units', value='mega{}/s'.format(units))
                await self.bot.say(embed=embed2)
        elif not units.lower() in unitz:
            await self.bot.say('Invalid Units Input')

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(administrator=True)
    async def farewell_channel(self, ctx):
        server = ctx.message.server
        if 'CHANNEL' not in self.leave_data[server.id]:
            self.leave_data[server.id]['CHANNEL'] = ''

        self.leave_data[server.id]['CHANNEL'] = ctx.message.channel.id
        self.save_data()
        await self.bot.say("Channel set to " + ctx.message.channel.name)

    async def when_leave(self, member):
        server = member.server
        if member.nick:
            farewellmessage = str(member) + " (*" + str(member.nick) + "*) has left Enigmata: Stellar War! R.I.P."
        else:
            farewellmessage = str(member) + " has left Enigmata: Stellar War! R.I.P."

        if server.id in self.leave_data:
            await self.bot.send_message(server.get_channel(self.leave_data[server.id]['CHANNEL']),
                                        farewellmessage)
        else:
            # server not enabled
            pass

    @commands.group(pass_context=True, no_pm=True, invoke_without_command=True)
    @checks.admin_or_permissions(manage_server=True)
    async def voice(self, ctx):
        """Voice lock commands"""
        await self.bot.send_cmd_help(ctx)
    
    @voice.command(name="lock", pass_context=True)
    async def _voice_lock(self, ctx):
        """Locks the voice channel you're in"""
        message = ctx.message
        channel = message.channel
        server = message.server
        exclusive = self.config.get("exclusivities", {}).get(server.id)
        if exclusive is not None and exclusive != channel.id:
            response = self.WRONG_CHANNEL.format(exclusive)
        else:
            who_locked = message.author
            vc = who_locked.voice_channel
            if vc is None:
                response = self.NOT_IN_CHANNEL_MSG
            else:
                if vc.id in self.config["locks"]:
                    response = self.CHANNEL_ALREADY_LOCKED.format(vc.name)
                elif vc.id in self.config["not_lockable"]:
                    response = self.CHANNEL_NOT_LOCKABLE.format(vc.name)
                else:
                    await self.lock_channel(vc, who_locked)
                    self.save_data()
                    response = self.CHANNEL_LOCKED.format(channel=vc.name, p=ctx.prefix)
        await self.temp_send(channel, [message], response)

    @voice.command(name="unlock", pass_context=True)
    async def _voice_unlock(self, ctx):
        """Unlocks the voice channel you're in"""
        message = ctx.message
        author = message.author
        if author.voice_channel is None:
            response = self.NOT_IN_CHANNEL_MSG
        else:
            channel = author.voice_channel
            if channel.id not in self.config["locks"]:
                response = self.CHANNEL_NOT_LOCKED.format(channel.name)
            else:
                await self.unlock_channel(channel)
                self.save_data()
                response = self.CHANNEL_UNLOCKED.format(channel.name)
        await self.temp_send(message.channel, [message], response)
    
    @voice.command(name="force_unlock", pass_context=True)
    @checks.mod_or_permissions(manage_channels=True)
    async def _voice_force_unlock(self, ctx, *, channel: discord.Channel):
        """Forcefully unlocks a locked voice channel"""
        if channel.type != discord.ChannelType.voice:
            response = self.NOT_A_VOICE_CHANNEL.format(channel.name)
        elif channel.id not in self.config["locks"]:
            response = self.CHANNEL_NOT_LOCKED.format(channel.name)
        else:
            await self.unlock_channel(channel)
            self.save_data()
            response = self.CHANNEL_UNLOCKED.format(channel.name)
        await self.temp_send(ctx.message.channel, [ctx.message], response)
    
    @voice.command(name="permit", pass_context=True)
    async def _voice_permit(self, ctx, *, user: discord.Member):
        """Permits someone to join your locked voice channel"""
        message = ctx.message
        author = message.author
        if author.voice_channel is None:
            response = self.NOT_IN_CHANNEL_MSG
        else:
            channel = author.voice_channel
            if channel.id not in self.config["locks"]:
                response = self.CHANNEL_NOT_LOCKED.format(channel.name)
            else:
                await self.permit_user(channel, user)
                self.save_data()
                response = self.USER_PERMITTED.format(channel=channel.name, user=user.name)
        await self.temp_send(message.channel, [message], response)
    
    @voice.command(name="not_lockable", pass_context=True)
    @checks.mod_or_permissions(manage_channels=True)
    async def _voice_not_lockable(self, ctx, *, channel: discord.Channel):
        """Toggles the not lockable state of a channel"""
        if channel.type != discord.ChannelType.voice:
            response = self.NOT_A_VOICE_CHANNEL.format(channel.name)
        else:
            if channel.id in self.config["not_lockable"]:
                self.config["not_lockable"].remove(channel.id)
                response = self.NOW_LOCKABLE.format(channel.name)
            else:
                self.config["not_lockable"].append(channel.id)
                response = self.NOW_NOT_LOCKABLE.format(channel.name)
            self.save_data()
        await self.temp_send(ctx.message.channel, [ctx.message], response)
    
    @voice.command(name="set_exclusive", pass_context=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def _voice_set_exclusivity(self, ctx, *, channel: discord.Channel=None):
        """Sets the channel where the voice commands should be done

        if `channel` isn't given, removes the exclusive channel"""
        reply_channel = ctx.message.channel
        server = reply_channel.server
        if channel is None:
            self.config["exclusivities"][server.id] = None
            self.save_data()
            response = self.EXCLUSIVITY_RESET.format(server.name)
        elif channel.type != discord.ChannelType.text:
            response = self.NOT_A_TEXT_CHANNEL.format(channel.name)
        else:
            self.config["exclusivities"][server.id] = channel.id
            self.save_data()
            response = self.EXCLUSIVITY_SET.format(c=channel.name, s=server.name)
        await self.temp_send(reply_channel, [ctx.message], response)
    
    # Utilities
    async def lock_channel(self, channel, who_locked):
        for member in channel.voice_members:
            await self.bot.edit_channel_permissions(channel, member, self.can_connect_perms)
        default_role = channel.server.default_role
        self.config["locks"][channel.id] = {"who_locked": who_locked.id, "permits": [],
                                            "previous_perm": channel.overwrites_for(default_role).connect}
        await self.bot.edit_channel_permissions(channel, default_role, self.cant_connect_perms)
    
    async def unlock_channel(self, channel, *additionnal_members):
        config = self.config["locks"][channel.id]
        permits = [channel.server.get_member(u_id) for u_id in config["permits"]]
        default_perm = discord.PermissionOverwrite(connect=config["previous_perm"])
        try:
            await self.bot.edit_channel_permissions(channel, channel.server.default_role, default_perm)
            for member in channel.voice_members + permits + list(additionnal_members):
                if member is not None:
                    await self.bot.delete_channel_permissions(channel, member)
#                    await self.bot.edit_channel_permissions(channel, channel.server.default_role, self.can_connect_perms)
        except discord.NotFound:
            self.logger.warning("Could not find the channel while unlocking.")
        del self.config["locks"][channel.id]
    
    async def permit_user(self, channel, member):
        self.config["locks"][channel.id]["permits"].append(member.id)
        await self.bot.edit_channel_permissions(channel, member, self.can_connect_perms)
    
    async def verify_locked_channels(self):
        for channel_id in list(self.config["locks"].keys()):
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                del self.config["locks"][channel_id]
                self.logger.debug("Could not find the channel with id {}. "
                                  "Removing it from the locked channels".format(channel_id))
            else:
                who_locked_id = self.config["locks"][channel_id]["who_locked"]
                who_locked = discord.utils.get(channel.voice_members, id=who_locked_id)
                if who_locked is None:
                    who_locked_mem = channel.server.get_member(who_locked_id)
                    additionnal_people = [] if who_locked_mem is None else [who_locked_mem]
                    await self.unlock_channel(channel, *additionnal_people)

    async def temp_send(self, channel: discord.Channel, messages: MessageList, *args, **kwargs):
        """Sends a message with *args **kwargs in `channel` and deletes it after some time

        If sleep_timeout is given as a named parameter (in kwargs), uses it
        Else it defaults to TEMP_MESSAGE_TIMEOUT

        Deletes all messages in `messages` if we have the manage_messages perms
        Else, deletes only the sent message"""
        sleep_timeout = kwargs.pop("sleep_timeout", self.TEMP_MESSAGE_TIMEOUT)
        messages.append(await self.bot.send_message(channel, *args, **kwargs))
        await asyncio.sleep(sleep_timeout)
        await self.delete_messages(messages)

    async def delete_messages(self, messages: MessageList):
        """Deletes an arbitrary number of messages by batches

        Basically runs discord.Client.delete_messages for every 100 messages until none are left"""
        messages = list(filter(self.message_filter, messages))
        while len(messages) > 0:
            if len(messages) == 1:
                await self.bot.delete_message(messages.pop())
            else:
                await self.bot.delete_messages(messages[-100:])
                messages = messages[:-100]

    def message_filter(self, message: discord.Message):
        result = False
        channel = message.channel
        if not channel.is_private:
            if channel.permissions_for(channel.server.me).manage_messages:
                result = True
        return result

    @commands.group(no_pm=True, pass_context=True)
    async def info(self, ctx):
        """Detailed information."""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @info.command(pass_context=True)
    async def avatar(self, ctx, *, user: discord.Member=None):
        """Returns user avatar URL."""
        author = ctx.message.author

        if not user:
            user = author

        u = await self.bot.get_user_info(str(user.id))
        url0 = u.avatar_url
        url = process_avatar(url0)
        await self.bot.say("{}'s Avatar URL : {}".format(user.name, url))

    @info.command(no_pm=True, pass_context=True)
    async def bot(self):
        """Shows info about this Bot."""
        author_repo = "https://github.com/Twentysix26"
        red_repo = author_repo + "/Red-DiscordBot"
        server_url = "https://discord.gg/red"
        dpy_repo = "https://github.com/Rapptz/discord.py"
        python_url = "https://www.python.org/"
        since = datetime.datetime(2016, 1, 2, 0, 0)
        days_since = (datetime.datetime.utcnow() - since).days
        dpy_version = "[{}]({})".format(discord.__version__, dpy_repo)
        py_version = "[{}.{}.{}]({})".format(*os.sys.version_info[:3],
                                             python_url)

        owner_set = self.bot.settings.owner is not None
        owner = self.bot.settings.owner if owner_set else None
        if owner:
            owner = discord.utils.get(self.bot.get_all_members(), id=owner)
            if not owner:
                try:
                    owner = await self.bot.get_user_info(self.bot.settings.owner)
                except:
                    owner = None
        if not owner:
            owner = "Unknown"

        about = (
            "Neko is based off Red - Discordbot (Created by Twentysix26 and improved by many.)\n\n"
            "Red is backed by a passionate community who contributes and "
            "creates content for everyone to enjoy. [Join us today]({}) "
            "and help us improve!\n\n"
            "".format(red_repo, author_repo, server_url))

        embed = discord.Embed(colour=discord.Colour.red())
        embed.add_field(name="Bot owned by:", value=str(owner))
        embed.add_field(name="Python", value=py_version)
        embed.add_field(name="discord.py", value=dpy_version)
        embed.add_field(name="About Red", value=about, inline=False)
        embed.set_footer(text="Bringing joy since 02 Jan 2016 (over "
                         "{} days ago!)".format(days_since))

        try:
            await self.bot.say(embed=embed)
        except discord.HTTPException:
            await self.bot.say("I need the `Embed links` permission "
                               "to send this")

    @info.command(pass_context=True, no_pm=True, aliases=['rinfo'])
    async def role(self, ctx, msg):
        """Get more info about a specific role.
        You need to quote roles with spaces. e.g. n/info role \"New Role\""""
        server = ctx.message.server
        server_roles = ctx.message.server.roles
        for role in server_roles:
            if msg.lower() == role.name.lower() or msg == role.id:
                em = discord.Embed(title='Detailed Role Info:', color=role.color)
                em.add_field(name='Role Name', value=role.name)
                em.add_field(name='Role ID', value=role.id, inline=False)
                em.add_field(name='Role color hex value', value=str(role.color))
                em.add_field(name='Can Mention?', value=role.mentionable)
                em.add_field(name='Created:', value=role.created_at.__format__('%x at %X'))
                em.set_thumbnail(url='http://www.colorhexa.com/{}.png'.format(str(role.color).strip("#")))
                return await self.bot.say(embed=em)
        await self.bot.say('Could not find role ``{}``'.format(msg))

    @info.command(pass_context=True, no_pm=True, aliases=['sinfo'])
    async def server(self, ctx):
        """Shows information about the server."""
        server = ctx.message.server
        online = str(len([m.status for m in server.members if str(m.status) == "online" or str(m.status) == "idle"]))
        server_roles = str(len(server.roles))
        total_users = str(len(server.members))
        text_channels = len([x for x in server.channels if str(x.type) == "text"])
        voice_channels = len(server.channels) - text_channels
        try:
            em = discord.Embed()
            em.add_field(name='Server:', value=server.name)
            em.add_field(name='ID:', value=server.id, inline=False)
            em.add_field(name='Location:', value=server.region)
            em.add_field(name='Online Users:', value=online)
            em.add_field(name='Total Users:', value=total_users)
            em.add_field(name='Channels:', value=text_channels)
            em.add_field(name='Voice Channels:', value=voice_channels)
            em.add_field(name='Roles:', value=server_roles)
            em.add_field(name='Created:', value=server.created_at.__format__('%x at %X'))
            em.add_field(name='Owner:', value=server.owner)
            em.set_thumbnail(url=server.icon_url)
            await self.bot.say(embed=em)
        except:
            await self.bot.say('Error has occured.')

    @info.command(pass_context=True)
    @checks.is_owner()
    async def system(self, ctx, *args: str):
        """Summary of cpu, memory, disk and network information."""

        options = ('cpu', 'memory', 'disk', 'network', 'boot')
        cpu_count_p = psutil.cpu_count(logical=False)
        cpu_count_l = psutil.cpu_count()
        if cpu_count_p is None:
            cpu_count_p = "N/A"
        cpu_cs = ("CPU Count"
                  "\n\t{0:<9}: {1:>3}".format("Physical", cpu_count_p) +
                  "\n\t{0:<9}: {1:>3}".format("Logical", cpu_count_l))
        psutil.cpu_percent(interval=None, percpu=True)
        await asyncio.sleep(1)
        cpu_p = psutil.cpu_percent(interval=None, percpu=True)
        cpu_ps = ("CPU Usage"
                  "\n\t{0:<8}: {1}".format("Per CPU", cpu_p) +
                  "\n\t{0:<8}: {1:.1f}%".format("Overall", sum(cpu_p) / len(cpu_p)))
        cpu_t = psutil.cpu_times()
        width = max([len("{:,}".format(int(n))) for n in [cpu_t.user, cpu_t.system, cpu_t.idle]])
        cpu_ts = ("CPU Times"
                  "\n\t{0:<7}: {1:>{width},}".format("User", int(cpu_t.user), width=width) +
                  "\n\t{0:<7}: {1:>{width},}".format("System", int(cpu_t.system), width=width) +
                  "\n\t{0:<7}: {1:>{width},}".format("Idle", int(cpu_t.idle), width=width))
        mem_v = psutil.virtual_memory()
        width = max([len(self._size(n)) for n in [mem_v.total, mem_v.available, (mem_v.total - mem_v.available)]])
        mem_vs = ("Virtual Memory"
                  "\n\t{0:<10}: {1:>{width}}".format("Total", self._size(mem_v.total), width=width) +
                  "\n\t{0:<10}: {1:>{width}}".format("Available", self._size(mem_v.available), width=width) +
                  "\n\t{0:<10}: {1:>{width}} {2}%".format("Used", self._size(mem_v.total - mem_v.available),
                                                          mem_v.percent, width=width))
        mem_s = psutil.swap_memory()
        width = max([len(self._size(n)) for n in [mem_s.total, mem_s.free, (mem_s.total - mem_s.free)]])
        mem_ss = ("Swap Memory"
                  "\n\t{0:<6}: {1:>{width}}".format("Total", self._size(mem_s.total), width=width) +
                  "\n\t{0:<6}: {1:>{width}}".format("Free", self._size(mem_s.free), width=width) +
                  "\n\t{0:<6}: {1:>{width}} {2}%".format("Used", self._size(mem_s.total - mem_s.free),
                                                         mem_s.percent, width=width))
        disk_u = psutil.disk_usage(os.path.sep)
        width = max([len(self._size(n)) for n in [disk_u.total, disk_u.free, disk_u.used]])
        disk_us = ("Disk Usage"
                   "\n\t{0:<6}: {1:>{width}}".format("Total", self._size(disk_u.total), width=width) +
                   "\n\t{0:<6}: {1:>{width}}".format("Free", self._size(disk_u.free), width=width) +
                   "\n\t{0:<6}: {1:>{width}} {2}%".format("Used", self._size(disk_u.used),
                                                          disk_u.percent, width=width))
        net_io = psutil.net_io_counters()
        width = max([len(self._size(n)) for n in [net_io.bytes_sent, net_io.bytes_recv]])
        net_ios = ("Network"
                   "\n\t{0:<11}: {1:>{width}}".format("Bytes sent", self._size(net_io.bytes_sent), width=width) +
                   "\n\t{0:<11}: {1:>{width}}".format("Bytes recv", self._size(net_io.bytes_recv), width=width))
        boot_s = ("Boot Time"
                  "\n\t{0}".format(datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")))

        # Output
        msg = ""
        if not args or args[0].lower() not in options:
            msg = "\n\n".join([cpu_cs, cpu_ps, mem_vs, disk_us, net_ios, boot_s])
        elif args[0].lower() == 'cpu':
            msg = "\n" + "\n\n".join([cpu_cs, cpu_ps])#, cpu_ts])
        elif args[0].lower() == 'memory':
            msg = "\n" + "\n\n".join([mem_vs])#, mem_ss])
        elif args[0].lower() == 'disk':
            msg = "\n" + disk_us
        elif args[0].lower() == 'network':
            msg = "\n" + net_ios
        elif args[0].lower() == 'boot':
            msg = "\n" + boot_s
        await self._say(ctx, msg)
        return

    @staticmethod
    def _size(num):
        for unit in ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB"]:
            if abs(num) < 1024.0:
                return "{0:.1f}{1}".format(num, unit)
            num /= 1024.0
        return "{0:.1f}{1}".format(num, "YB")

    # Respect 2000 character limit per message
    async def _say(self, ctx, msg, escape=True, wait=True):
        template = "```{0}```" if escape else "{0}"
        buf = ""
        for line in msg.splitlines():
            if len(buf) + len(line) >= 1900:
                await self.bot.say(template.format(buf))
                buf = ""
                if wait:
                    await self.bot.say("Type 'more' or 'm' to continue...")
                    answer = await self.bot.wait_for_message(timeout=10, author=ctx.message.author)
                    if not answer or answer.content.lower() not in ["more", "m"]:
                        await self.bot.say("Command output stopped.")
                        return
            buf += line + "\n"
        if buf:
            await self.bot.say(template.format(buf))

    @info.command(pass_context=True, no_pm=True, aliases=['uinfo'])
    async def user(self, ctx, *, user: discord.Member=None):
        """Shows a user's information."""
        author = ctx.message.author
        server = ctx.message.server

        if not user:
            user = author

        roles = [x.name for x in user.roles if x.name != "@everyone"]

        joined_at = self.fetch_joined_at(user, server)
        since_created = (ctx.message.timestamp - user.created_at).days
        since_joined = (ctx.message.timestamp - joined_at).days
        user_joined = joined_at.strftime("%d %b %Y %H:%M")
        user_created = user.created_at.strftime("%d %b %Y %H:%M")
        member_number = sorted(server.members,
                               key=lambda m: m.joined_at).index(user) + 1

        created_on = "{}\n({} days ago)".format(user_created, since_created)
        special = "January 2nd 2019 @9:08PM"
        joined_on = "{}\n({} days ago)".format(user_joined, since_joined)

        game = "Chilling in {} status".format(user.status)

        if user.game is None:
            pass
        elif user.game.url is None:
            game = "Playing {}".format(user.game)
        else:
            game = "Streaming: [{}]({})".format(user.game, user.game.url)

        if roles:
            roles = sorted(roles, key=[x.name for x in server.role_hierarchy
                                       if x.name != "@everyone"].index)
            roles = ", ".join(roles)
        else:
            roles = "None"

        data = discord.Embed(description=game, colour=user.colour)
        data.add_field(name="Joined Discord on", value=created_on)
        data.add_field(name="Joined this server on", value=joined_on)

        if user.id == "305100357930057729":
            data.add_field(name="Do not forget:", value=special, inline=False)
        data.add_field(name="Roles", value=roles, inline=False)
        data.set_footer(text="Member #{} | User ID:{}"
                             "".format(member_number, user.id))

        name = str(user)
        name = " ~ ".join((name, user.nick)) if user.nick else name

        if user.avatar_url:
            data.set_author(name=name, url=user.avatar_url)
            data.set_thumbnail(url=user.avatar_url)
        else:
            data.set_author(name=name)

        try:
            await self.bot.say(embed=data)
        except discord.HTTPException:
            await self.bot.say("I need the `Embed links` permission "
                               "to send this")
    @commands.command(pass_context=True, name='vcrole')
    @checks.mod_or_permissions(administrator=True)
    async def _invoicerole(self, context, role):
        """Set a role"""
        server = context.message.server
        roles = [r.name.lower() for r in server.roles]
        if role.lower() in roles:
            if server.id not in self.data:
                self.data[server.id] = {}
            self.data[server.id]['ROLE'] = role
            await self._save_data()
            message = 'Role `{}` set.'.format(role)
            message += ' Users will now receive `{}` when joining any Voice Channel.'.format(role)
        else:
            message = 'Role `{}` does not exist on this server.'.format(role)
        await self.bot.say(message)

    @commands.group(name="setsay", pass_context=True, no_pm=True, invoke_without_command=True)
    @checks.admin_or_permissions()
    async def sayset(self, ctx):
        """The 'Say' command set
add - Adds a user to have the abillity to use the say command
list - list users allowed and permited role
remove - Removes a user to have the abillity to use the say command
role - Adds a permited role to use the say command"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_message(ctx.message.channel, "```Please use the say command with: \n add - Adds a **user** to have the abillity to use the say command \n remove - Removes a **user** to have the abillity to use the say command \n role - Adds a role and those with it can use the say command \n list - lists permited users and the permited role```")

    @sayset.command(name="list", pass_context=True)
    @checks.admin_or_permissions()
    async def say_list(self,ctx):
        """Lists permited users and the permitted role"""
        names = []
        for user_id in self.say[ctx.message.server.id]["USERS"]:
            names.append(discord.utils.get(self.bot.get_all_members(), id=user_id).name)
                    
        msg = ("+ Permited\n"
               "{}\n\n"
               "".format(", ".join(sorted(names))))

        for page in pagify(msg, [" "], shorten_by=16):
            await self.bot.say(box(page.lstrip(" "), lang="diff"))

        #gets the name of the role and displays it
        if self.say[ctx.message.server.id]["ROLE"] is not None:
            await self.bot.send_message(ctx.message.channel, "Permited Role: **{}**".format(get_role(ctx, self.say[ctx.message.server.id]["ROLE"]).name))
        else:
            await self.bot.send_message(ctx.message.channel, "No role has permission")
            
    @sayset.command(name="add", pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def say_add (self, ctx, user: discord.Member):
        """Adds a [user] to have the abillity to use the say command"""
        self.say[ctx.message.server.id]["USERS"].append(user.id)
        self.save()
        await self.bot.send_message(ctx.message.channel, "Done!")

    @sayset.command(name="remove", pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def say_remove (self, ctx, user: discord.Member):
        """Removes a [user] to have the abillity to use the say command"""
        try:
            self.say[ctx.message.server.id]["USERS"].remove(user.id)
            self.save()
            await self.bot.send_message(ctx.message.channel, "Done!")

        except:
            await self.bot.send_message(ctx.message.channel, "Are you sure that {} had the permision in the first place?".format(user.mention))

    @sayset.command(name="role", pass_context=True)
    @checks.admin_or_permissions()
    async def say_role(self, ctx, role_name:str):
        """Sets the permitted role"""
        role = discord.utils.get(ctx.message.server.roles, name=role_name)

        if role is not None:
            self.say[ctx.message.server.id]["ROLE"] = role.id
            self.save()
            await self.bot.send_message(ctx.message.channel, "Role added!")

        else:
            await self.bot.send_message(ctx.message.channel, "Role not found!")

    @commands.command(name="say", pass_context=True, no_pm =True)
    async def bot_say(self, ctx, *, text):
        """The bot repeats what you tell it to"""

        if '@everyone' in ctx.message.content and '@here' in ctx.message.content:
            await self.bot.send_message(ctx.message.channel, "Woh! {}, please don't do that".format(ctx.message.author.mention))
            return
    
        #IF there are no mentions such as @everyone or @here must test useing a string
        
        if ctx.message.channel.permissions_for(ctx.message.server.me).manage_messages is not True:
            await self.bot.say("This command requires the **Manage Messages** permission.")
            return
        
            #checks if they are allowed (role or permitted)         
        if ctx.message.author.id in self.say[ctx.message.server.id]["USERS"] or get_role(ctx, self.say[ctx.message.server.id]["ROLE"])  in ctx.message.author.roles:
            await self.bot.delete_message(ctx.message)
            await self.bot.send_message(ctx.message.channel, text)
        else: 
            await self.bot.say("You need to be given access to this command") 
        


    def save(self):
        dataIO.save_json("data/enigmata/say.json", self.say)

    async def server_join(self, server):
        self.say[server.id]={
            "ROLE":None,
            "USERS":[],
        }

        self.save()

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def rift(self, ctx, channel):
        """Makes you able to communicate with other channels through Red
        This is cross-server. Type only the channel name or the ID."""
        author = ctx.message.author
        author_channel = ctx.message.channel

        def check(m):
            try:
                return channels[int(m.content)]
            except:
                return False

        channels = self.bot.get_all_channels()
        channels = [c for c in channels
                    if c.name.lower() == channel.lower() or c.id == channel]
        channels = [c for c in channels if c.type == discord.ChannelType.text]

        if not channels:
            await self.bot.say("No channels found. Remember to type just "
                               "the channel name, no `#`.")
            return

        if len(channels) > 1:
            msg = "Multiple results found.\nChoose a server:\n"
            for i, channel in enumerate(channels):
                msg += "{} - {} ({})\n".format(i, channel.server, channel.id)
            for page in pagify(msg):
                await self.bot.say(page)
            choice = await self.bot.wait_for_message(author=author,
                                                     timeout=30,
                                                     check=check,
                                                     channel=author_channel)
            if choice is None:
                await self.bot.say("You haven't chosen anything.")
                return
            channel = channels[int(choice.content)]
        else:
            channel = channels[0]

        key = "{}-{}".format(author.id, channel.id)

        if key in self.open_rifts:
            await self.bot.say("You already have a rift opened for that "
                               "channel!")
            return

        self.open_rifts[key] = OpenRift(source=author_channel,
                                        destination=channel)

        await self.bot.say("A rift has been opened! Everything you say "
                           "will be relayed to that channel.\n"
                           "Responses will be relayed here.\nType "
                           "`exit` to quit.")
        msg = ""
        while msg == "" or msg is not None:
            msg = await self.bot.wait_for_message(author=author,
                                                  channel=author_channel)
            if msg is not None and msg.content.lower() != "exit":
                try:
                    await self.bot.send_message(channel, msg.content)
                except:
                    await self.bot.say("Couldn't send your message.")
            else:
                break
        del self.open_rifts[key]
        await self.bot.say("Rift closed.")

    async def on_message(self, message):
        if message.author == self.bot.user:
            return
        for k, v in self.open_rifts.items():
            if v.destination == message.channel:
                msg = "{}: {}".format(message.author, message.content)
                msg = escape(msg, mass_mentions=True)
                await self.bot.send_message(v.source, msg)

    def fetch_joined_at(self, user, server):
            return user.joined_at

    def check_configs(self):
        self.check_folders()
        self.check_files()
    
    def check_folders(self):
        if not os.path.exists(self.DATA_FOLDER):
            self.logger.debug("Creating data folder...")
            os.makedirs(self.DATA_FOLDER, exist_ok=True)
    
    def check_files(self):
        self.check_file(self.DATA_FILE_PATH, self.CONFIG_DEFAULT)
    
    def check_file(self, file, default):
        if not dataIO.is_valid_json(file):
            self.logger.debug("Creating empty " + file + "...")
            dataIO.save_json(file, default)
    
    def load_data(self):
        # Here, you load the data from the config file.
        self.config = dataIO.load_json(self.DATA_FILE_PATH)
    
    def save_data(self):
        # Save all the data (if needed)
        dataIO.save_json(self.DATA_FILE_PATH, self.config)


def check_folder():
    if not os.path.exists("data/utility"):
        print("Creating data/utility folder...")
        os.makedirs("data/utility")

def check_file():
    data = {}
    f = "data/utility/speedtest.json"
    if not dataIO.is_valid_json(f):
        print("Creating data/utility/speedtest.json")
        dataIO.save_json(f, data)

def check_file():
    data = {}
    f = "data/utility/vcrole.json"
    if not dataIO.is_valid_json(f):
        print("Creating default vcrole.json...")
        dataIO.save_json(f, data)

def check_file():
    if not dataIO.is_valid_json("data/utility/say.json"):
        print("Creating empty say.json...")    
        dataIO.save_json("data/utility/say.json", {})
		
def check_file():
    if not dataIO.is_valid_json("data/utility/leave.json"):
        print("Creating empty leave.json...")    
        dataIO.save_json("data/utility/leave.json", {})
def setup(bot):
    if psutilAvailable:
        check_file()
        check_folder()
        n = Utility(bot)
        loop = asyncio.get_event_loop()
        loop.create_task(n.data_writer())
        bot.add_listener(n.when_leave, "on_member_remove")
        bot.add_listener(n._on_voice_state_update, 'on_voice_state_update')
        bot.add_listener(n.server_join, "on_server_join")
        bot.add_cog(Utility(bot))
    else:
        raise RuntimeError("You may need to run 'pip3 install speedtest-cli' or 'pip3 install psutil'")
