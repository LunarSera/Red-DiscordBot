import os, discord, random, asyncio, aiohttp, string
import datetime, time
from datetime import datetime
from discord.ext import commands
from __main__ import send_cmd_help
from random import choice as randchoice, randint
from .utils.dataIO import dataIO
from .utils.chat_formatting import escape_mass_mentions, italics, pagify
from .utils.chat_formatting import *
from .utils import checks
from urllib.parse import quote_plus

class Enigmata:
    """These commands give you insight into the lore of Enigmata: Stellar War."""

    def __init__(self, bot):
        self.bot = bot
        self.lore = dataIO.load_json("data/enigmata/lore.json")
        self.images = dataIO.load_json("data/enigmata/image.index.json")
        self.session = aiohttp.ClientSession(loop=self.bot.loop)
        self.staffapp = dataIO.load_json('data/enigmata/staffapp.json')
        for s in self.staffapp:
            self.staffapp[s]['usercache'] = []

    def save_json(self):
        dataIO.save_json("data/enigmata/staffapp.json", self.staffapp)

    def __unload(self):
        self.session.close()

    async def first_word(self, msg):
        return msg.split(" ")[0].lower()

    async def get_prefix(self, server, msg):
        prefixes = self.bot.settings.get_prefixes(server)
        for p in prefixes:
            if msg.startswith(p):
                return p
        return None
		
    async def part_of_existing_command(self, alias, server):
        '''Command or alias'''
        for command in self.bot.commands:
            if alias.lower() == command.lower():
                return True
        return False

    async def make_server_folder(self, server):
        if not os.path.exists("data/enigmata/{}".format(server.id)):
            print("Creating server folder")
            os.makedirs("data/enigmata/{}".format(server.id))

    async def on_message(self, message):
        if len(message.content) < 2 or message.channel.is_private:
            return

        msg = message.content
        server = message.server
        channel = message.channel
        prefix = await self.get_prefix(server, msg)
        if not prefix:
            return
        alias = await self.first_word(msg[len(prefix):])

        if alias in self.images["server"][server.id]:
            image = self.images["server"][server.id][alias]
            await self.bot.send_typing(channel)
            await self.bot.send_file(channel, image)

    async def check_command_exists(self, command, server):
        if command in self.images["server"][server.id]:
            return True
        elif await self.part_of_existing_command(command, server):
            return True
        else:
            return False

    @commands.group(name="staffapp", pass_context=True, no_pm=True)
    @checks.admin_or_permissions(Manage_server=True)
    async def appset(self, ctx):
        """configuration settings"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
    def initial_config(self, server_id):
        """makes an entry for the server, defaults to turned off"""
        if server_id not in self.staffapp:
            self.staffapp[server_id] = {'inactive': True,
                                        'output': [],
                                        'cleanup': False,
                                        'usercache': [],
                                        'multiout': False
                                        }
            self.save_json()

    @checks.admin_or_permissions(Manage_server=True)
    @appset.command(name="reset", pass_context=True, no_pm=True)
    async def fix_cache(self, ctx):
        """Reset cache for applications"""
        server = ctx.message.server
        self.initial_config(ctx.message.server.id)
        self.staffapp[server.id]['usercache'] = []
        self.save_json()
        await self.bot.say("Cache has been reset")

    @checks.admin_or_permissions(Manage_server=True)
    @appset.command(name="roles", pass_context=True, no_pm=True)
    async def rolecreation(self, ctx):
        server = ctx.message.server
        author = ctx.message.author
        aprole = discord.utils.get(server.roles, name="Staff Applicant")
        if aprole not in server.roles:
            await self.bot.create_role(server, name="Staff Applicant")
            await self.bot.say("All done!")
        else:
            await self.bot.say("Roles already present")

    @checks.admin_or_permissions(Manage_server=True)
    @appset.command(name="channel", pass_context=True, no_pm=True)
    async def setoutput(self, ctx, chan=None):
        """sets the place to output application embed to when finished."""
        server = ctx.message.server
        if server.id not in self.staffapp:
            self.initial_config(server.id)
        if chan in self.staffapp[server.id]['output']:
            return await self.bot.say("Channel already set as output")
        for channel in server.channels:
            if str(chan) == str(channel.id):
                if self.staffapp[server.id]['multiout']:
                    self.staffapp[server.id]['output'].append(chan)
                    self.save_json()
                    return await self.bot.say("Channel added to output list")
                else:
                    self.staffapp[server.id]['output'] = [chan]
                    self.save_json()
                    return await self.bot.say("Channel set as output")
        await self.bot.say("I could not find a channel with that id")

    @checks.admin_or_permissions(Manage_server=True)
    @appset.command(name="toggle", pass_context=True, no_pm=True)
    async def reg_toggle(self, ctx):
        """Toggles applications for the server"""
        server = ctx.message.server
        if server.id not in self.staffapp:
            self.initial_config(server.id)
        self.staffapp[server.id]['inactive'] = \
            not self.staffapp[server.id]['inactive']
        self.save_json()
        if self.staffapp[server.id]['inactive']:
            await self.bot.say("Registration disabled.")
        else:
            await self.bot.say("Registration enabled.")

    @commands.command(name="apply", pass_context=True, hidden=True, no_pm=True)
    async def application(self, ctx):
        """"make an application by following the prompts"""
        author = ctx.message.author
        server = ctx.message.server
        aprole = discord.utils.get(server.roles, name="Staff Applicant")
        if server.id not in self.staffapp:
            return await self.bot.say("Applications are not setup on this server!")
        if self.staffapp[server.id]['inactive']:
            return await self.bot.say("We are not currently accepting applications, Try again later")
        if aprole in author.roles:
            await self.bot.say("{}You have already applied to this server!".format(author.mention))
        else:
            await self.bot.say("{}Ok lets start the application".format(author.mention))
            while True:
                avatar = author.avatar_url if author.avatar \
                    else author.default_avatar_url
                em = discord.Embed(timestamp=ctx.message.timestamp, title="ID: {}".format(author.id), color=discord.Color.blue())
                em.set_author(name='Staff Application for {}'.format(author.name), icon_url=avatar)
                agemsg = await self.bot.send_message(author, "What is your Age?")
                while True:
                    age = await self.bot.wait_for_message(channel=agemsg.channel, author=author, timeout=30)
                    if age is None:
                        await self.bot.send_message(author, "Sorry you took to long, please try again later!")
                        break
                    else:
                        em.add_field(name="Age: ", value=age.content, inline=True)
                        break
                if age is None:
                    break
                timemsg = await self.bot.send_message(author, "What TimeZone are you in? [Google is your Friend]")
                while True:
                    time = await self.bot.wait_for_message(channel=timemsg.channel, author=author, timeout=30)
                    if time is None:
                        await self.bot.send_message(author, "Timed out, Please run command again.")
                        break
                    else:
                        em.add_field(name="Timezone:", value=time.content, inline=True)
                        break
                if time is None:
                    break
                nationmsg = await self.bot.send_message(author, "What country are you from?")
                while True:
                    nation = await self.bot.wait_for_message(channel=nationmsg.channel, author=author, timeout=30)
                    if nation is None:
                        await self.bot.send_message(author, "Timed out Please run command again")
                        break
                    else:
                        em.add_field(name="Country: ", value=nation.content, inline=True)
                        em.add_field(name='Join Date', value=author.joined_at.__format__('%A, %d. %B %Y @ %H:%M:%S'))
                        break
                if nation is None:
                    break
                activemsg = await self.bot.send_message(author, "How many hours per day can you be active?")
                while True:
                    active = await self.bot.wait_for_message(channel=activemsg.channel, author=author, timeout=60)
                    if active is None:
                        await self.bot.send_message(author, "Timed Out. Please re-run command and try again!")
                        break
                    else:
                        em.add_field(name="Active Hours per Day:", value=active.content, inline=False)
                        break
                if active is None:
                    break
                whymsg = await self.bot.send_message(author, "Why do you want to be staff?")
                while True:
                    why = await self.bot.wait_for_message(channel=whymsg.channel, author=author, timeout=60)
                    if why is None:
                        await self.bot.send_message(author, "Timed out, Please Re-Run command and try again!")
                        break
                    else:
                        em.add_field(name="Why do you want to be staff", value=why.content, inline=False)
                        aprole = discord.utils.get(server.roles, name="Staff Applicant")
                        await self.bot.add_roles(author, aprole)
                        await self.bot.send_message(author, "You have finished the application. Thank you")
                        break
                if why is None:
                    break
                for output in self.staffapp[server.id]['output']:
                    where = server.get_channel(output)
                    if where is not None:
                        await self.bot.send_message(where, embed=em)
                        break
                    break
                return
			
			
			
			
#-----------------------------------------------------------------------------------------------------------------
    @commands.group(no_pm=True, pass_context=True)
    async def enigmata(self, ctx):
        """Enigmata Lore."""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @enigmata.command(hidden=True)
    async def story(self):
        """Says a random piece of lore from Enigmata: Stellar War"""
        await self.bot.say(randchoice(self.lore))
		
    @enigmata.command(pass_context=True)
    @checks.admin_or_permissions(manage_server=True)
    async def select(self, ctx, file=None, *, comment=None):
        """Upload a file from the bot."""

        message = ctx.message
        server = message.server

        if file == None:
            if os.listdir("data/enigmata/453668709396119562") == []:
                await self.bot.say("There is nothing saved yet. Use the save command to begin.")
                return

            msg = "Send `n/enigmata select 'filename'` to reupload.\nSend `n/enigmata delete 'filename'` to remove file from this list.\nRequires *Manage Server Permission*\n\nList of available files to upload:\n"
            for file in os.listdir("data/enigmata/453668709396119562"):
                msg += "`{}\n".format(file)[:-5] + "`"
            await self.bot.say(msg)
            return

        if "." not in file:
            for fname in os.listdir("data/enigmata/453668709396119562"):
                if fname.startswith(file):
                    file += "." + fname.partition(".")[2]
                    break

        if os.path.isfile("data/enigmata/453668709396119562/{}".format(file)) is True:
                await self.bot.upload(fp="data/enigmata/453668709396119562/{}".format(file))
        else:
            await self.bot.say(
                "That file doesn't seem to exist. Make sure it is an available name, try to add the extention (especially if two files have the same name)"
            )

    @enigmata.command(pass_context=True, no_pm=True, invoke_without_command=True)
    @checks.admin_or_permissions(manage_server=True)
    async def delete(self, ctx, cmd):
        """Removes selected image."""
        author = ctx.message.author
        server = ctx.message.server
        channel = ctx.message.channel
        cmd = cmd.lower()
        if server.id not in self.images["server"]:
            await self.bot.say("I have no images on this server!")
            return
        if cmd not in self.images["server"][server.id]:
            await self.bot.say("{} is not an image for this server!".format(cmd))
            return
        os.remove(self.images["server"][server.id][cmd])
        del self.images["server"][server.id][cmd]
        dataIO.save_json("data/enigmata/image.index.json", self.images)
        await self.bot.say("{} has been deleted from my directory.".format(cmd))

    @enigmata.command(pass_context=True, no_pm=True, invoke_without_command=True)
    async def save(self, ctx, cmd):
        """Add an image to direct upload.\n Where cmd = name of your choice."""
        author = ctx.message.author
        server = ctx.message.server
        channel = ctx.message.channel
        prefix = await self.get_prefix(server, ctx.message.content)
        msg = ctx.message
        if server.id not in self.images["server"]:
            await self.make_server_folder(server)
            self.images["server"][server.id] = {}
        if cmd is not "":
            if await self.check_command_exists(cmd, server):
                await self.bot.say("{} is already in the list, try another!".format(cmd))
                return
            else:
                await self.bot.say("{} added as the command!".format(cmd))
        await self.bot.say("Upload an image for me to use! You have 1 minute.")
        while msg is not None:
            msg = await self.bot.wait_for_message(author=author, timeout=60)
            if msg is None:
                await self.bot.say("No image uploaded then.")
                break

            if msg.attachments != []:
                filename = msg.attachments[0]["filename"][-4:]
                directory = "data/enigmata/{}{}".format(server.id, filename)
                if cmd is None:
                    cmd = filename.split(".")[0]
                cmd = cmd.lower()
                directory = "data/enigmata/{}/{}{}".format(server.id, cmd, filename)
                self.images["server"][server.id][cmd] = directory
                dataIO.save_json("data/enigmata/image.index.json", self.images)
                async with self.session.get(msg.attachments[0]["url"]) as resp:
                    test = await resp.read()
                    with open(self.images["server"][server.id][cmd], "wb") as f:
                        f.write(test)
                await self.bot.send_message(channel, "{} has been added to my files!"
                                            .format(cmd))
                break
            if msg.content.lower().strip() == "exit":
                await self.bot.say("Your changes have been saved.")
                break

def check_folder():
    if not os.path.exists("data/enigmata"):
        print("Creating data/enigmata folder")
        os.makedirs("data/enigmata")

def check_file():
    data = {"server":{}}
    f = "data/enigmata/image.index.json"
    if not dataIO.is_valid_json(f):
        print("Creating default image.index.json...")
        dataIO.save_json(f, data)

def check_file():
    lore = {"server":{}}
    f = "data/enigmata/lore.json"
    if not dataIO.is_valid_json(f):
        print("Creating default lore.json...")
        dataIO.save_json(f, lore)

def check_file():
    f = 'data/enigmata/staffapp.json'
    if dataIO.is_valid_json(f) is False:
        dataIO.save_json(f, {})

def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(Enigmata(bot))
