from discord.ext import commands
from cogs.utils import checks
import datetime
from cogs.utils.dataIO import fileIO
import discord
import asyncio
import os
from random import choice, randint

inv_settings = {"embed": False, "toggleuser": False}


class nicklog:
    def __init__(self, bot):
        self.bot = bot
        self.direct = "data/nickdetectset/settings.json"

    @checks.admin_or_permissions(administrator=True)
    @commands.group(name='nickdetecttoggle', pass_context=True, no_pm=True)
    async def nickdetecttoggles(self, ctx):
        """toggle which server activity to log"""
        if ctx.invoked_subcommand is None:
            db = fileIO(self.direct, "load")
            server = ctx.message.server
            await self.bot.send_cmd_help(ctx)
            try:
                e = discord.Embed(title="Setting for {}".format(server.name), colour=discord.Colour.blue())
                e.add_field(name="User", value=str(db[ctx.message.server.id]['toggleuser']))
                e.set_thumbnail(url=server.icon_url)
                await self.bot.say(embed=e)
            except KeyError:
                return

    @checks.admin_or_permissions(administrator=True)
    @commands.group(pass_context=True, no_pm=True)
    async def nickdetectset(self, ctx):
        """Change nickdetect settings"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @nickdetectset.command(name='channel', pass_context=True, no_pm=True)
    async def _channel(self, ctx):
        """Set the channel to send notifications too"""
        server = ctx.message.server
        db = fileIO(self.direct, "load")
        if ctx.message.server.me.permissions_in(ctx.message.channel).send_messages:
            if server.id in db:
                db[server.id]['Channel'] = ctx.message.channel.id
                fileIO(self.direct, "save", db)
                await self.bot.say("Channel changed.")
                return
            if not server.id in db:
                db[server.id] = inv_settings
                db[server.id]["Channel"] = ctx.message.channel.id
                fileIO(self.direct, "save", db)
                await self.bot.say("I will now send toggled nickdetect notifications here")
        else:
            return

    @nickdetectset.command(pass_context=True, no_pm=True)
    async def embed(self, ctx):
        """Enables or disables embed nickdetect."""
        server = ctx.message.server
        db = fileIO(self.direct, "load")
        if db[server.id]["embed"] == False:
            db[server.id]["embed"] = True
            fileIO(self.direct, "save", db)
            await self.bot.say("Enabled embed nickdetect.")
        elif db[server.id]["embed"] == True:
            db[server.id]["embed"] = False
            fileIO(self.direct, "save", db)
            await self.bot.say("Disabled embed nickdetect.")

    @nickdetectset.command(pass_context=True, no_pm=True)
    async def disable(self, ctx):
        """disables the nickdetect"""
        server = ctx.message.server
        db = fileIO(self.direct, "load")
        if not server.id in db:
            await self.bot.say("Server not found, use nickdetectset to set a channnel")
            return
        del db[server.id]
        fileIO(self.direct, "save", db)
        await self.bot.say("I will no longer send nickdetect notifications here")

    @nickdetectset.command(pass_context=True, no_pm=True)
    async def toggle(self, ctx):
        """toggle notifications when a user changes his profile"""
        server = ctx.message.server
        db = fileIO(self.direct, "load")
        if db[server.id]["toggleuser"] == False:
            db[server.id]["toggleuser"] = True
            fileIO(self.direct, "save", db)
            await self.bot.say("User messages enabled")
        elif db[server.id]["toggleuser"] == True:
            db[server.id]["toggleuser"] = False
            fileIO(self.direct, "save", db)
            await self.bot.say("User messages disabled")

    async def on_member_update(self, before, after):
        server = before.server
        db = fileIO(self.direct, "load")
        if not server.id in db:
            return
        channel = db[server.id]["Channel"]
        time = datetime.datetime.utcnow()
        fmt = '%H:%M:%S'
        if not before.nick == after.nick and db[server.id]['toggleuser']:
            if db[server.id]["embed"] == True:
                name = before
                name = " ~ ".join((name.name, name.nick)) if name.nick else name.name
                infomessage = "{}'s nickname has changed".format(before.mention)
                updmessage = discord.Embed(description=infomessage, colour=discord.Color.orange(), timestamp=time)
                updmessage.add_field(name="Nickname Before:", value=before.nick)
                updmessage.add_field(name="Nickname After:", value=after.nick)
                updmessage.set_footer(text="User ID: {}".format(before.id), icon_url=after.avatar_url)
                updmessage.set_author(name=name + " - Nickname Changed", icon_url=after.avatar_url)
                # updmessage.set_thumbnail(url="http://i.imgur.com/I5q71rj.png")
                try:
                    await self.bot.send_message(server.get_channel(channel), embed=updmessage)
                except:
                    pass
            else:
                await self.bot.send_message(server.get_channel(channel),
                                            ":person_with_pouting_face::skin-tone-3: `{}` **{}** changed their nickname from **{}** to **{}**".format(
                                                time.strftime(fmt), before.name, before.kick, after.nick))

def check_folder():
    if not os.path.exists('data/nickdetectset'):
        print('Creating data/nickdetectset folder...')
        os.makedirs('data/nickdetectset')


def check_file():
    f = 'data/nickdetectset/settings.json'
    if not fileIO(f, 'check'):
        print('Creating default settings.json...')
        fileIO(f, 'save', {})


def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(nicklog(bot))
