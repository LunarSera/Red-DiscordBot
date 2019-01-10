#Disclaimer: This cog was created, heavilly based on work from others. Credit should go to where it's due.

import os, discord, random, asyncio, aiohttp, string, logging, datetime, re, time, socket
from cogs.utils import checks
from socket import AF_INET, SOCK_STREAM, SOCK_DGRAM
from discord.ext import commands
from __main__ import send_cmd_help
from random import choice as randchoice, randint
from .utils.dataIO import dataIO
from .utils.chat_formatting import escape_mass_mentions, italics, pagify, box
from .utils.chat_formatting import *
from .utils import checks
from urllib.parse import quote_plus, urlparse
DB_VERSION = 2
# System Info is from https://github.com/giampaolo/psutil/tree/master/scripts
# noinspection SpellCheckingInspection,PyPep8Naming,PyPep8Naming
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

    def __init__(self, bot):
        self.bot = bot
        self.new_data = False
        self.seen = dataIO.load_json('data/enigmata/seen.json')
        self.session = aiohttp.ClientSession(loop=self.bot.loop)
        self.say = dataIO.load_json("data/enigmata/say.json")

    async def data_writer(self):
        while self == self.bot.get_cog('Seen'):
            if self.new_data:
                dataIO.save_json('data/enigmata/seen.json', self.seen)
                self.new_data = False
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(30)

    @commands.command(pass_context=True)
    async def ping(self,ctx):
        """Shows latency from Bot to Server."""
        channel = ctx.message.channel
        t1 = time.perf_counter()
        await self.bot.send_typing(channel)
        t2 = time.perf_counter()
        await self.bot.say("Ping: {}ms".format(round((t2-t1)*1000)))

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
        if not roles: roles = ["None"]
        em = discord.Embed(title='User Info:')
        em.add_field(name='Name:\n', value=user.name)
        em.add_field(name='Nickname:\n', value=user.nick)
        em.add_field(name='ID:', value=user.id, inline=False)
        if user.game is None:
            pass
        elif user.game.url is None:
            em.add_field(name='Playing:', value=user.game)
        else:
            em.add_field(name='Streaming:', value=user.game)
            em.add_field(name='URL:', value=user.game.url, inline=False)
        em.add_field(name='Created:\n', value=user.created_at.__format__('%x at %X'))
        if user.avatar_url != "":
            em.set_thumbnail(url=user.avatar_url)
        await self.bot.say(embed=em)

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

def check_folder():
    if not os.path.exists('data/enigmata'):
        print('Creating data/enigmata')
        os.makdirs('data/enigmata')

def check_file():
    if not dataIO.is_valid_json("data/enigmata/say.json"):
        print("Creating empty say.json...")    
        dataIO.save_json("data/enigmata/say.json", {})
		
def check_file():
    data = {}
    data['db_version'] = DB_VERSION
    f = 'data/enigmata/seen.json'
    if not dataIO.is_valid_json(f):
        print('Creating seen.json...')
        dataIO.save_json(f, data)
    else:
        check = dataIO.load_json(f)
        if 'db_version' in check:
            if check['db_version'] < DB_VERSION:
                data = {}
                data['db_version'] = DB_VERSION
                dataIO.save_json(f, data)
                print('SEEN: Database version too old, resetting!')
        else:
            data = {}
            data['db_version'] = DB_VERSION
            dataIO.save_json(f, data)
            print('SEEN: Database version too old, resetting!')

def setup(bot):
    if psutilAvailable:
        check_file()
        check_folder()
        n = Utility(bot)
        loop = asyncio.get_event_loop()
        loop.create_task(n.data_writer())
        bot.add_listener(n.server_join, "on_server_join")
        bot.add_cog(Utility(bot))
    else:
        raise RuntimeError("You need to run 'pip3 install psutil'")
