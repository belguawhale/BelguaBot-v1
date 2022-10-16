import asyncio
import traceback
from datetime import datetime, timedelta
import os
import sys
import copy
import random
import json
import re
import discord
from config import *
from settings import *
from io import BytesIO, StringIO

client = discord.Client()

MAX_RECURSION_DEPTH = 10

starttime = None

MODERATOR_ROLE = None
ADMIN_ROLE = None
MUTED_ROLE = None
prev_currency = datetime.now() - timedelta(seconds=CURRENCY_COOLDOWN)

data = {}
commands = {}
ignore_list = []
aliases = {}
scheduler = {}
mutes = {}
warnings = {}

random.seed(datetime.now())

if os.path.isfile('aliases.json'):
    with open('aliases.json', 'r') as aliases_file:
        aliases = json.load(aliases_file)
else:
    with open('aliases.json', 'a+') as aliases_file:
        aliases_file.write('{}')

if os.path.isfile('warnings.json'):
    with open('warnings.json', 'r') as warnings_file:
        warnings = json.load(warnings_file)
else:
    with open('warnings.json', 'a+') as warnings_file:
        warnings_file.write('{}')

if os.path.isfile('mutes.json'):
    with open('mutes.json', 'r') as mutes_file:
        mutes = json.load(mutes_file)
        for muted in mutes:
            temp_timestamp = mutes[muted][0].lstrip('datetime.datetime(').rstrip(')')
            mutes[muted][0] = datetime(*list(map(int, temp_timestamp.split(', '))))
else:
    with open('mutes.json', 'a+') as mutes_file:
        mutes_file.write('{}')

if os.path.isfile(DATA_FILE):
    with open(DATA_FILE, 'r') as data_file:
        data = json.load(data_file)
else:
    with open(DATA_FILE, 'a+') as data_file:
        data_file.write('{}')

if os.path.isfile(IGNORE_FILE):
    with open(IGNORE_FILE, 'r') as ignore_file:
        ignore_list = json.load(ignore_file)
else:
    with open(IGNORE_FILE, 'a+') as ignore_file:
        ignore_file.write('[]')

def cmd(name, perm, description, *aliases):
    def real_decorator(func):
        commands[name] = [func, perm, description]
        for alias in aliases:
            if alias not in commands:
                commands[alias] = [func, perm, "```\nAlias for {0}{1}.```".format(PREFIX, name)]
            else:
                print("ERROR: Cannot assign alias {0} to command {1} since it is already the name of a command!".format(alias, name))
        return func
    return real_decorator

async def scheduler_loop():
    while not client.is_closed:
        for i in list(scheduler):
            if scheduler[i][0] < datetime.now():
                scheduler_array = scheduler[i][:]
                del scheduler[i]
                command_string = scheduler_array[2]
                print("Executing scheduled command with id {}".format(i))
                command = command_string.split(' ')[0]
                parameters = ' '.join(command_string.split(' ')[1:])
                await parse_command(scheduler_array[1], command, parameters, scheduler_array[3])
        await asyncio.sleep(0.1)

async def mute_loop():
    # 'id' : [datetime of expiry, user who muted]
    def update_file():
        with open('mutes.json', 'w', encoding='utf-8') as muted_file:
            temp_mutes = copy.deepcopy(mutes)
            for muted in temp_mutes:
                temp_mutes[muted][0] = repr(temp_mutes[muted][0])
            json.dump(temp_mutes, muted_file)
    while starttime == None:
        await asyncio.sleep(1)
    while not client.is_closed:
        for muted in list(mutes):
            member = client.get_server(SERVER).get_member(muted)
            if mutes[muted][0] < datetime.now():
                if member:
                    await log(0, "Removing {} ({})'s muted role".format(member.display_name, member.id))
                    await client.remove_roles(member, get_muted_role())
                    await log(1, "{} ({})'s mute expired".format(member.display_name, member.id))
                else:
                    await log(1, "user not in server with id {}'s mute expired".format(muted))
                del mutes[muted]
                update_file()
            else:
                if member and get_muted_role() not in member.roles:
                    await log(0, "Adding muted role to {} ({})".format(member.display_name, member.id))
                    await client.add_roles(member, get_muted_role())
                    update_file()
        await asyncio.sleep(0.1)

@client.event
async def on_ready():
    global MODERATOR_ROLE
    global ADMIN_ROLE
    global MUTED_ROLE
    global starttime

    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')
    await log(1, "on_ready triggered!")
    get_moderator_role()
    get_admin_role()
    get_muted_role()
    if not MODERATOR_ROLE:
        await log(3, "Could not find moderator role with id " + MODERATOR_ROLE_ID)
    if not ADMIN_ROLE:
        await log(3, "Could not find admin role with id " + ADMIN_ROLE_ID)
    if not MUTED_ROLE:
        await log(3, "Could not find muted role with id " + MUTED_ROLE_ID)
    print('Admin role: ' + ADMIN_ROLE.name)
    print('Moderator role: ' + MODERATOR_ROLE.name)
    print('Muted role: ' + MUTED_ROLE.name)
    starttime = datetime.now()

@client.event
async def on_message(message):
    global prev_currency
    if message.author.bot:
        return
    if message.author.id != OWNER and (message.channel.is_private or message.server.id != SERVER\
                                       or message.author.id in ignore_list):
        return
    if message.content.startswith(PREFIX):
        # Command
        raw_message = message.content.strip()[len(PREFIX):].strip()
        command = raw_message.split(' ')[0].lower()
        parameters = ' '.join(raw_message.split(' ')[1:]).strip()
        await parse_command(message, command, parameters)
    if message.channel.id in CURRENCY_ENABLED:
        if datetime.now() - prev_currency > timedelta(seconds=CURRENCY_COOLDOWN) and random.random() < CURRENCY_CHANCE:
            prev_currency = datetime.now()
            await generate_random_amount(message.channel)

async def parse_command(message, command, parameters, permissions=-1, recursion=0):
    if recursion >= MAX_RECURSION_DEPTH:
        await log(2, "Hit max recursion depth of {}".format(MAX_RECURSION_DEPTH))
        await reply(message, "ERROR: reached max recursion depth of {}".format(MAX_RECURSION_DEPTH))
        return

    permlevel = permissions
    if permissions == -1:
        permlevel = get_permissions(message.author)

    await log(0, "Received command {} with parameters {} from {} ({}) with "
                 "permission level {} (command invoker has permission level {})".format(
                     command, parameters, message.author.display_name, message.author.id,
                     permlevel, get_permissions(message.author)))

    if command in commands:
        if permlevel >= commands[command][1]:
            await log(0, "Parsing command {} with parameters {} from {} ({})".format(
                command, parameters, message.author.display_name, message.author.id))
            try:
                await commands[command][0](message, parameters, recursion=recursion)
            except:
                traceback.print_exc()
                try:
                    await echo(message, "An error has occurred and has been logged.")
                    msg = '```py\n{}\n```'.format(traceback.format_exc())
                    await log(3, msg)
                except:
                    print("Printing error message failed, wtf?")
        else:
            await log(2, "{} ({}) tried to use command without permissions: {} with parameters `{}`".format(
                message.author.name, message.author.id, command, parameters))
    elif command in aliases:
        aliased_command = aliases[command][0].split(' ')[0]
        actual_params = ' '.join(aliases[command][0].split(' ')[1:]).format(parameters, *parameters.split(' '),
            message=message, channel=message.channel, author=message.author, server=message.server)
        if permlevel >= aliases[command][1]:
            if aliased_command in commands:
                newperms = commands[aliased_command][1]
            elif aliased_command in aliases:
                newperms = aliases[aliased_command][1]
            else:
                newperms = -1
            await parse_command(message, aliased_command, actual_params, permissions=newperms, recursion=recursion + 1)
        else:
            await log(2, "{} ({}) tried to use alias without permissions: {} with parameters `{}`".format(
                message.author.name, message.author.id, command, parameters))

@cmd('shutdown', 3, "```\n{0}shutdown takes no arguments\n\nShuts down the bot.```")
async def cmd_shutdown(message, parameters, recursion=0):
    await echo(message, ':thumbsup:')
    await client.logout()

@cmd('ping', 0, "```\n{0}ping takes no arguments\n\nTests the bot's responsiveness.```")
async def cmd_ping(message, parameters, recursion=0):
    await echo(message, 'pong')

@cmd('eval', 3, "```\n{0}eval <evaluation string>\n\nEvaluates <evaluation string> using eval().```")
async def cmd_eval(message, parameters, recursion=0):
    output = None
    if parameters == '':
        await echo(message, commands['eval'][2].format(PREFIX))
        return
    try:
        output = eval(parameters)
    except:
        traceback.print_exc()
        await echo(message, '```\n' + str(traceback.format_exc()) + '\n```')
        return
    if asyncio.iscoroutine(output):
        output = await output
    await echo(message, '```\n' + str(output) + '\n```', cleanmessage=False)

@cmd('exec', 3, "```\n{0}exec <code>\n\nExecutes <code> using exec().```")
async def cmd_exec(message, parameters, recursion=0):
    if parameters == '':
        await echo(message, commands['exec'][2].format(PREFIX))
        return
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    try:
        exec(parameters)
    except Exception:
        await echo(message, '```py\n{}\n```'.format(traceback.format_exc()))
        return
    finally:
        sys.stdout = old_stdout
    if redirected_output.getvalue():
        await echo(message, redirected_output.getvalue(), cleanmessage=False)
        return
    await echo(message, ':thumbsup:')

@cmd('async', 3, "```\n{0}async <code>\n\nExecutes <code> as a coroutine.```")
async def cmd_async(message, parameters, recursion=0):
    if parameters == '':
        await reply(message, commands['async'][2].format(PREFIX))
        return
    env = {'message' : message,
           'parameters' : parameters,
           'recursion' : recursion,
           'client' : client,
           'channel' : message.channel,
           'author' : message.author,
           'server' : message.server}
    env.update(globals())
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    result = None
    exec_string = "async def _temp_exec():\n"
    exec_string += '\n'.join(' ' * 4 + line for line in parameters.split('\n'))
    try:
        exec(exec_string, env)
    except Exception:
        traceback.print_exc()
        result = traceback.format_exc()
    else:
        _temp_exec = env['_temp_exec']
        try:
            returnval = await _temp_exec()
            value = redirected_output.getvalue()
            if returnval == None:
                result = value
            else:
                result = value + '\n' + str(returnval)
        except Exception:
            traceback.print_exc()
            result = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
    await echo(message, "```py\n{}\n```".format(result), cleanmessage=False)

@cmd('help', 0, "```\n{0}help <command>\n\nReturns hopefully helpful information on <command>. Try {0}list for a list of commands.```")
async def cmd_help(message, parameters, recursion=0):
    if parameters == '':
        await echo(message, commands['help'][2].format(PREFIX))
    elif parameters in commands:
        await echo(message, commands[parameters][2].format(PREFIX))
    else:
        await echo(message, "Command {} does not exist.".format(parameters))

@cmd('list', 0, "```\n{0}list takes no arguments\n\nReturns a list of commands.```")
async def cmd_list(message, parameters, recursion=0):
    await echo(message, "Commands: {}".format(', '.join(sorted(
        x for x in commands if get_permissions(message.author) >= commands[x][1]))))

@cmd('info', 0, "```\n{0}info takes no arguments\n\nReturns information about me.```", '')
async def cmd_info(message, parameters, recursion=0):
    info = "BelguaBot is an advanced moderation bot made by belungawhale#4813 using discord.py "
    info += "and Python 3.5.1. Its key features are its unique warning point system, permission"
    info += " levels, timed and unavoidable mutes, multi warn/mute/kick/ban, forceban by id, an"
    info += "d probably the coolest feature, aliases.\n"
    info += "My code can be found at https://github.com/belguawhale/BelguaBot-v1.\n\n"
    info += "Use the command `{p}info` to view this message. Use the command `{p}list`"
    info += " to display a listing of all commands. Use the "
    info += "command `{p}help command` to display help for a command. "
    await echo(message, info.format(p=PREFIX))

@cmd('perms', 0, "```\n{0}perms [<command>]\n\nTells you what permission level you have.```")
async def cmd_perms(message, parameters, recursion=0):
    if parameters in commands and parameters != '':
        perms = commands[parameters][1]
        msg = "Permission level {} is required to use the command {}.".format(perms, parameters)
    elif parameters in aliases:
        perms = aliases[parameters][1]
        msg = "Permission level {} is required to use the alias {}.".format(perms, parameters)
    else:
        perms = get_permissions(message.author)
        msg = "Your permission level is {}.".format(perms)
    await echo(message, msg)

@cmd('balance', 0, "```\n{0}balance [<user>]\n\nChecks your balance or [<user>]'s balance.```")
async def cmd_balance(message, parameters, recursion=0):
    if parameters == '':
        user = message.author.id
    else:
        user = parameters.strip('<!@>')
    if user.isdigit():
        member = client.get_server(SERVER).get_member(user)
        if member:
            name = member.display_name
        else:
            name = "user not in server with id " + user
        await echo(message, "**{}** ({}) has a balance of {} {}.".format(
            name, user, change_balance(user), CURRENCY_NAME))
    else:
        await echo(message, "Please use a valid id/mention.")

@cmd('leaderboard', 0, "```\n{0}leaderboard [<entries>]\n\nViews the XP leaderboard.```")
async def cmd_leaderboard(message, parameters, recursion=0):
    if parameters.isdigit():
        parameters = max(1, min(50, int(parameters)))
    else:
        parameters = 10
    sorted_players = sorted(sorted(data), reverse=True, key=lambda x: data[x])
    msg = "Leaderboard for **{}** (showing top {} entries)```\n".format(client.get_server(SERVER).name, parameters)
    prev_player = (0, '')
    for i, player in enumerate(sorted_players[:parameters]):
        if prev_player[1] and data[player] == data[prev_player[1]]:
            rank = prev_player[0] + 1
        else:
            rank = i + 1
            prev_player = (i, player)
        member = client.get_server(SERVER).get_member(player)
        if member:
            name = member.display_name
        else:
            name = "user not in server with id " + player
        msg += "{}{} {} {}{} {}\n".format(rank, (4 - len(str(rank))) * ' ', data[player], CURRENCY_NAME,
                                          (9 - len(str(data[player]))) * ' ', name)
    msg += '```'
    await send_multi_message(message, msg, handle_codeblock=True)

@cmd('spawn', 1, "```\n{0}spawn [<channel>]\n\nSpawns something in [<channel>] or the current channel.```")
async def cmd_spawn(message, parameters, recursion=0):
    channel = None
    if parameters:
        channel = client.get_channel(parameters.strip('<#>'))
    if not channel:
        channel = message.channel
    await generate_random_amount(channel)

@cmd('fspawn', 2, "```\n{0}fspawn <channel> [<amount>] [<timeout>]\n\nForcibly spawns something in <channel>.```")
async def cmd_fspawn(message, parameters, recursion=0):
    channel = None
    params = parameters.split(' ')
    chan = params[0]
    if chan:
        channel = client.get_channel(chan.strip('<#>'))
    if not channel:
        channel = message.channel
    if len(params) == 1:
        await generate_random_amount(channel)
    elif len(params) == 2:
        if params[1].lstrip('-').isdigit():
            await generate_currency(channel, amount=int(params[1]))
        else:
            await generate_random_amount(channel)
    else:
        if params[2].isdigit():
            if params[1].lstrip('-').isdigit():
                await generate_currency(channel, amount=int(params[1]), timeout=int(params[2]))
            else:
                await generate_random_amount(channel)
        else:
            await generate_random_amount(channel)

@cmd('ignore', 2, "```\n{0}ignore <add|remove|list> <user>\n\nAdds or removes <user> from the "
                  "ignore list, or outputs the ignore list.```")
async def cmd_ignore(message, parameters, recursion=0):
    if parameters == '':
        await echo(message, commands['ignore'][2].format(PREFIX))
    else:
        action = parameters.split(' ')[0].lower()
        target = ' '.join(parameters.split(' ')[1:])
        member_by_id = client.get_server(SERVER).get_member(target.strip('<@!>'))
        member_by_name = client.get_server(SERVER).get_member_named(target)
        member = None
        if member_by_id:
            member = member_by_id
        elif member_by_name:
            member = member_by_name
        if action not in ['+', 'add', '-', 'remove', 'list']:
            await echo(message, "Error: invalid flag `" + action + "`. Supported flags are add, remove, list")
            return
        if not member and action != 'list':
            await echo(message, "Error: could not find target " + target)
            return
        if action in ['+', 'add']:
            if member.id in ignore_list:
                await echo(message, member.name + " is already in the ignore list!")
            else:
                do_ignore(member.id, True)
                await echo(message, member.name + " was added to the ignore list.")
        elif action in ['-', 'remove']:
            if member.id in ignore_list:
                do_ignore(member.id, False)
                await echo(message, member.name + " was removed from the ignore list.")
            else:
                await echo(message, member.name + " is not in the ignore list!")
        elif action == 'list':
            if len(ignore_list) == 0:
                await echo(message, "The ignore list is empty.")
            else:
                msg_dict = {}
                for ignored in ignore_list:
                    member = client.get_server(SERVER).get_member(ignored)
                    msg_dict[ignored] = member.name if member else "<user not in server with id " + ignored + ">"
                await echo(message, "{} ignored users:```\n{}\n```".format(
                    len(ignore_list), '\n'.join('{} ({})'.format(x, msg_dict[x]) for x in msg_dict)))
        else:
            await echo(message, commands['ignore'][2].format(PREFIX))

@cmd("alias", 1, "```\n{0}alias <add | edit | remove | list | show | restrict | permission> "
                 "<alias name> [<command string | permission level>]\n\nManipulates aliases.```")
async def cmd_alias(message, parameters, recursion=0):
    # alias: [command string, permissions required to use it, permissions required to modify]
    params = parameters.split(' ')
    if len(params) == 0:
        await reply(message, commands['alias'][2].format(PREFIX))
        return
    action = params[0]
    if action not in ['add', '+', 'edit', '=', 'remove', 'del', 'delete', '-', 'list', 'show', 'restrict', 'permission', 'perm']:
        await reply(message, commands['alias'][2].format(PREFIX))
        return
    if len(params) == 1:
        if action in ['add', '+', 'edit', '=', 'restrict', 'permission', 'perm']:
            await reply(message, "```\n{0}alias {1} <alias name> <command string>```".format(PREFIX, action))
        elif action in ['show', 'remove', '-', 'del', 'delete']:
            await reply(message, "```\n{0}alias {1} <alias name>```".format(PREFIX, action))
        elif action == 'list':
            await send_multi_message(message, "Available aliases: {}".format(', '.join(
                sorted(a for a in aliases if get_permissions(message.author) >= aliases[a][1]))), mention_author=True)
        return
    alias = params[1]
    if not alias in aliases and action not in ['add', '+']:
        await reply(message, "ERROR: alias {} does not exist!".format(alias))
        return
    if alias in aliases and action in ['add', '+']:
        await reply(message, "ERROR: alias {} already exists. Use `{}alias edit` instead.".format(alias, PREFIX))
        return
    if len(params) == 2:
        if action in ['add', '+', 'edit', '=']:
            await reply(message, "```\n{0}alias {1} {2} <command string>```".format(PREFIX, action, alias))
        elif action == 'restrict':
            await reply(message, "Alias **{}** is restricted to permission level {}.".format(alias, aliases[alias][1]))
        elif action in ['permission', 'perm']:
            await reply(message, "Alias **{}** is set to permission level {}.".format(alias, aliases[alias][2]))
        elif action == 'show':
            await reply(message, "**{}** is an alias for: ```\n{}\n```".format(alias, aliases[alias][0]))
        elif action in ['remove', 'del', 'delete', '-']:
            perms = aliases[alias][2]
            if get_permissions(message.author) >= perms:
                del aliases[alias]
                await reply(message, "Successfully deleted alias **{}**.".format(alias))
            else:
                await reply(message, "You do not have enough permissions to delete this alias.")
    else:
        if action in ['restrict', 'permission', 'perm']:
            authorperms = get_permissions(message.author)
            perm = params[2]
            if perm.isdigit() and int(perm) in range(0, 4):
                perm = int(perm)
                if authorperms < perm:
                    await reply(message, "You cannot set a permission level higher than your permission level.")
                elif action == 'restrict':
                    if authorperms >= aliases[alias][1]:
                        aliases[alias][1] = perm
                        await reply(message, "Succesfully restricted alias **{}** to permission level **{}**.".format(alias, perm))
                    else:
                        await reply(message, "You do not have enough permissions to change the restrictions on this alias.")
                elif action in ['permission', 'perm']:
                    if authorperms >= aliases[alias][2]:
                        aliases[alias][2] = perm
                        await reply(message, "Succesfully set permission level of alias {} to {}.".format(alias, perm))
                    else:
                        await reply(message, "You do not have enough permissions to change the permission level of this alias.")
            else:
                await reply(message, "Permission level must be an integer between 0 and 3, inclusive.")
        elif action in ['add', '+', 'edit', '=']:
            commandstring = ' '.join(params[2:])
            actualcommand = commandstring.split(' ')[0]
            authorperms = get_permissions(message.author)
            perms = authorperms
            if actualcommand in commands:
                perms = commands[actualcommand][1]
            elif actualcommand in aliases:
                perms = aliases[actualcommand][1]
            if perms > get_permissions(message.author):
                await reply(message, "You do not have enough permissions {} this alias.".format(action))
            else:
                if action == 'add' or authorperms >= aliases[alias][2]:
                    aliases[alias] = [commandstring, perms, get_permissions(message.author)]
                    await reply(message, "Successfully {}ed alias **{}**.".format(action, alias))
                elif action == 'edit':
                    await reply(message, "You do not have enough permissions to edit this alias.")
    with open('aliases.json', 'w') as aliases_file:
        json.dump(aliases, aliases_file)

@cmd("reply", 1, "```\n{0}reply <message>\n\nReplies with <message>. Use with aliases for more fun!```")
async def cmd_reply(message, parameters, recursion=0):
    await reply(message, parameters, cleanmessage=False)

@cmd("echo", 1, "```\n{0}echo <message>\n\nSends <message> to the channel this command was used in.```")
async def cmd_echo(message, parameters, recursion=0):
    if parameters != '':
        await echo(message, parameters, cleanmessage=False)
    else:
        await reply(message, "ERROR: Cannot send an empty message!")

@cmd("say", 1, "```\n{0}say <channel> <message>\n\nSends <message> to <channel>.```")
async def cmd_say(message, parameters, recursion=0):
    target = parameters.split(' ')[0].strip("<@!#>")
    msg = ' '.join(parameters.split(' ')[1:])
    tgt = client.get_channel(target)
    if tgt:
        if msg:
            await client.send_message(tgt, msg)
        else:
            await reply(message, "ERROR: Cannot send an empty message.")
    else:
        await reply(message, "ERROR: Target with id {} not found.".format(target))

@cmd("role", 1, "```\n{0}role <add | remove> <mention1 [mention2 ...]> <role name>\n\nAdds or removes <role name> from each member in <mentions>.```")
async def cmd_role(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if len(params) < 3:
        await reply(message, commands['role'][2].format(PREFIX))
        return
    action = params[0].lower()
    if action in ['add', '+']:
        action = 'add'
    elif action in ['remove', '-']:
        action = 'remove'
    else:
        await reply(message, "ERROR: first parameter must be one of: add, remove.")
        return
    params = params[1:]
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    members = [server.get_member(x) for x in ids]
    members = [x for x in members if x]
    params = [x for x in params if x.strip('<@!>') not in (x.id for x in members)]
    if not members:
        await reply(message, "ERROR: no valid mentions found.")
        return
    role = ' '.join(params)
    if not role:
        await reply(message, "ERROR: no role name given!")
        return
    roles = [x for x in server.role_hierarchy if x.name == role]
    if not roles:
        await reply(message, "ERROR: could not find role named {}. Please ensure the role is spelled correctly and your capitalization is correct.".format(role))
        return
    role = roles[0]
    if role >= message.author.top_role:
        await reply(message, "ERROR: cannot assign roles higher than your highest role!")
        return
    if role >= client.get_server(SERVER).me.top_role:
        await reply(message, "ERROR: cannot assign roles higher than my highest role!")
        return
    if action == 'add':
        function = client.add_roles
    elif action == 'remove':
        function = client.remove_roles
    for member in members:
        await function(member, role)
    if action == 'add':
        msg = "Successfully added **{}** to **{}** member{}."
        await publiclog("**{}** was added to **{}** by **{}**.".format(
            role.name, ', '.join(x.display_name for x in members),
            message.author.display_name))
    elif action == 'remove':
        msg = "Successfully removed **{}** from **{}** member{}."
        await publiclog("**{}** was removed from **{}** by **{}**.".format(
            role.name, ', '.join(x.display_name for x in members),
            message.author.display_name))
    await reply(message, msg.format(role.name, len(members), '' if len(members) == 1 else 's'))

@cmd('mute', 1, "```\n{0}mute <mention1 [mention2 ...]> <amount of time> [<reason>]\n\nMutes each mention "
                "for <amount of time> with reason [<reason>]. <amount of time> is in the format #w#d#h#m#s, "
                "standing for weeks, days, hours, minutes, and seconds, respectively.```")
async def cmd_mute(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if len(params) < 2:
        await reply(message, commands['mute'][2].format(PREFIX))
        return
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    members = [server.get_member(x) for x in ids]
    members = [x for x in members if x]
    params = [x for x in params if x.strip('<@!>') not in (x.id for x in members)]
    if not members:
        await reply(message, "ERROR: no valid mentions found.")
        return
    datestring = params[0].lower()
    delta = convdatestring(datestring)
    if len(datestring) == len(datestring.strip('0123456789')) and delta == timedelta(0):
        delta = timedelta(seconds=DEFAULT_MUTE)
    else:
        params = params[1:]
    reason = ' '.join(params)
    if reason == '':
        reason = "No reason specified"

    if get_muted_role() >= client.get_server(SERVER).me.top_role:
        await reply(message, "ERROR: cannot assign muted role due to it being higher than my highest role!")
        return

    for member in members:
        await _mute(member.id, message.author.id, reason, set_to=delta)

    msg = "Successfully muted **{}** member{}.".format(
        len(members), '' if len(members) == 1 else 's')
    await publiclog("**{}** was muted for **{}** by **{}** for reason: `{}`".format(
        ', '.join(x.display_name for x in members), strfdelta(delta),
        message.author.display_name, reason))
    await reply(message, msg)

@cmd('unmute', 1, "```\n{0}unmute <mention1 [mention2 ...]> [<reason>]\n\nUnmutes each mention in mentions.```")
async def cmd_unmute(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if parameters == '':
        await reply(message, commands['unmute'][2].format(PREFIX))
        return
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    members = [server.get_member(x) for x in ids]
    members = [x for x in members if x]
    params = [x for x in params if x.strip('<@!>') not in (x.id for x in members)]
    if not members:
        await reply(message, "ERROR: no valid mentions found.")
        return
    reason = ' '.join(params)
    if reason == '':
        reason = "No reason specified"

    if get_muted_role() >= client.get_server(SERVER).me.top_role:
        await reply(message, "ERROR: cannot remove muted role due to it being higher than my highest role!")
        return

    for member in members:
        await _mute(member.id, message.author.id, reason, set_to=0)

    msg = "Successfully unmuted **{}** member{}.".format(
        len(members), '' if len(members) == 1 else 's')
    await publiclog("**{}** was unmuted by **{}** for reason: `{}`".format(
        ', '.join(x.display_name for x in members), message.author.display_name, reason))
    await reply(message, msg)

@cmd('warn', 1, "```\n{0}warn <mention1 [mention2 ...]> [<warning points>] [<reason>]\n\n"
                "Gives each mention [<warning points>] (defaults to 1) for reason [<reason>].```")
async def cmd_warn(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if parameters == '':
        await reply(message, commands['warn'][2].format(PREFIX))
        return
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    members = [server.get_member(x) for x in ids]
    members = [x for x in members if x]
    params = [x for x in params if x.strip('<@!>') not in (x.id for x in members)]
    if not members:
        await reply(message, "ERROR: no valid mentions found.")
        return

    points_string = params[0] if params else '1'
    if points_string.isdigit():
        points = int(points_string)
        params = params[1:]
    else:
        points = 1

    reason = ' '.join(params)
    if reason == '':
        reason = "No reason specified"

    msg = "Successfully warned **{}** member{}.".format(
        len(members), '' if len(members) == 1 else 's')
    await publiclog("**{}** was warned for **{}** warning point{} by **{}** for reason: `{}`".format(
        ', '.join(x.display_name for x in members), points, '' if points == 1 else 's',
        message.author.display_name, reason))

    for member in members:
        await do_warns(member.id, points)

    await log(1, "{} ({}) WARN {} FOR {} POINT{} FOR {}".format(message.author.display_name,
        message.author.id, ', '.join('{} ({})'.format(x.display_name, x.id) for x in members),
        points, '' if points == 1 else 'S', reason))
    await reply(message, msg)

@cmd('mutes', 1, "```\n{0}mutes [<user>]\n\nDisplays a list of all muted users or just [<user>].```")
async def cmd_mutes(message, parameters,recursion=0):
    def _format_mute(muted):
        member = client.get_server(SERVER).get_member(muted)
        if member:
            name = member.display_name
        else:
            name = "user not in server with id " + muted
        member2 = client.get_server(SERVER).get_member(mutes[muted][1])
        if member2:
            name2 = member2.display_name
        else:
            name2 = "user not in server with id " + mutes[muted][1]
        return "{} was muted by {} for reason: {}. Remaining time: {}".format(name, name2,
        mutes[muted][2], strfdelta(mutes[muted][0] - datetime.now()))
    if parameters == '':
        msg = '**Muted users:**```\n'
        for muted in sorted(mutes, key=lambda x: datetime.now() - mutes[x][0]):
            msg += _format_mute(muted) + '\n'
        msg += '```'
        await reply(message, msg)
    else:
        parameters = parameters.strip('<!@>')
        if parameters in mutes:
            await reply(message, "```\n{}\n```".format(_format_mute(parameters)))
        elif parameters.isdigit() and len(parameters) in range(17, 21):
            member = client.get_server(SERVER).get_member(parameters)
            if member:
                name = member.display_name
            else:
                name = "user not in server with id " + parameters
            await reply(message, "{} is not muted.".format(name))
        else:
            await reply(message, "Invalid mention/user id.")

@cmd('uptime', 0, "```\n{0}uptime takes no arguments\n\nDisplays the bot's uptime.```")
async def cmd_uptime(message, parameters, recursion=0):
    await reply(message, "Uptime: **{}**".format(strfdelta(datetime.now() - starttime)))

@cmd('kick', 1, "```\n{0}kick <mention1 [mention2 ...]> [<reason>]\n\nKicks each mention with reason [<reason>].```")
async def cmd_kick(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if parameters == '':
        await reply(message, commands['kick'][2].format(PREFIX))
        return
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    members = [server.get_member(x) for x in ids]
    members = [x for x in members if x]
    params = [x for x in params if x.strip('<@!>') not in (x.id for x in members)]
    if not members:
        await reply(message, "ERROR: no valid mentions found.")
        return
    reason = ' '.join(params)
    if reason == '':
        reason = "No reason specified"

    unable_to_kick = []
    for member in members:
        if member.top_role >= client.get_server(SERVER).me.top_role:
            unable_to_kick.append(member)
        else:
            await client.kick(member)

    msg = "Successfully kicked **{}** member{}.".format(
        len(members) - len(unable_to_kick), '' if len(members) - len(unable_to_kick) == 1 else 's')
    if len(members) - len(unable_to_kick) > 0:
        await publiclog("**{}** was kicked by **{}** for reason: `{}`".format(
            ', '.join(x.display_name for x in set(members) - set(unable_to_kick)), message.author.display_name, reason))
        await log(1, "{} ({}) KICK {} FOR {}".format(message.author.display_name,
            message.author.id, ', '.join('{} ({})'.format(x.display_name, x.id) for x in\
            set(members) - set(unable_to_kick)), reason))
    if len(unable_to_kick) > 0:
        await log(2, "Unable to kick {}".format(', '.join("{} ({})".format(x.display_name, x.id) for x in unable_to_kick)))
    await reply(message, msg)

@cmd('ban', 1, "```\n{0}ban <mention1 [mention2 ...]> [<reason>]\n\nBans each mention with reason [<reason>].```")
async def cmd_ban(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if parameters == '':
        await reply(message, commands['ban'][2].format(PREFIX))
        return
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    members = [server.get_member(x) for x in ids]
    members = [x for x in members if x]
    params = [x for x in params if x.strip('<@!>') not in (x.id for x in members)]
    if not members:
        await reply(message, "ERROR: no valid mentions found.")
        return
    reason = ' '.join(params)
    if reason == '':
        reason = "No reason specified"

    unable_to_ban = []
    for member in members:
        if member.top_role >= client.get_server(SERVER).me.top_role:
            unable_to_ban.append(member)
        else:
            await client.ban(member)

    msg = "Successfully banned **{}** member{}.".format(
        len(members) - len(unable_to_ban), '' if len(members) - len(unable_to_ban) == 1 else 's')
    if len(members) - len(unable_to_ban) > 0:
        await publiclog("**{}** was banned by **{}** for reason: `{}`".format(
            ', '.join(x.display_name for x in set(members) - set(unable_to_ban)), message.author.display_name, reason))
        await log(1, "{} ({}) BAN {} FOR {}".format(message.author.display_name,
            message.author.id, ', '.join('{} ({})'.format(x.display_name, x.id) for x in\
            set(members) - set(unable_to_ban)), reason))
    if len(unable_to_ban) > 0:
        await log(2, "Unable to ban {}".format(', '.join("{} ({})".format(x.display_name, x.id) for x in unable_to_ban)))
    await reply(message, msg)

@cmd('unban', 1, "```\n{0}unban <mention1 [mention2 ...]> [<reason>]\n\nUnbans each mention with reason [<reason>].```")
async def cmd_unban(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if parameters == '':
        await reply(message, commands['unban'][2].format(PREFIX))
        return
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    users = []
    for x in ids:
        try:
            u = await client.get_user_info(x)
            users.append(u)
        except discord.NotFound:
            pass
    params = [x for x in params if x.strip('<@!>') not in (x.id for x in users)]
    if not users:
        await reply(message, "ERROR: no valid mentions found.")
        return
    reason = ' '.join(params)
    if reason == '':
        reason = "No reason specified"

    banlist = await client.get_bans(client.get_server(SERVER))
    unable_to_unban = []

    for user in users:
        if user in banlist:
            await client.unban(client.get_server(SERVER), user)
        else:
            unable_to_unban.append(user)

    msg = "Successfully unbanned **{}** user{}.".format(
        len(users) - len(unable_to_unban), '' if len(users) - len(unable_to_unban) == 1 else 's')
    if len(users) - len(unable_to_unban) > 0:
        await publiclog("**{}** was unbanned by **{}** for reason: `{}`".format(
            ', '.join(x.display_name for x in set(users) - set(unable_to_unban)), message.author.display_name, reason))
        await log(1, "{} ({}) UNBAN {} FOR {}".format(message.author.display_name,
            message.author.id, ', '.join('{} ({})'.format(x.display_name, x.id) for x in\
            set(users) - set(unable_to_unban)), reason))
    if len(unable_to_unban) > 0:
        await log(2, "Did not unban {} since not in banlist".format(
            ', '.join("{} ({})".format(x.display_name, x.id) for x in unable_to_unban)))
    await reply(message, msg)

@cmd('forceban', 1, "```\n{0}forceban <id1 [id2 ...]> [<reason>]\n\nForcibly "
                    "bans each id with reason [<reason>].```")
async def cmd_forceban(message, parameters, recursion=0):
    server = client.get_server(SERVER)
    params = parameters.split(' ')
    if parameters == '':
        await reply(message, commands['forceban'][2].format(PREFIX))
        return
    ids = [x.strip('<@!>') for x in params if x.strip('<@!>').isdigit() and len(x.strip('<@!>')) in range(17, 21)]
    params = [x for x in params if x.strip('<@!>') not in ids]
    if not ids:
        await reply(message, "ERROR: no valid mentions found.")
        return
    reason = ' '.join(params)
    if reason == '':
        reason = "No reason specified"

    unable_to_ban = []
    for id in ids:
        try:
            await client.http.ban(id, SERVER, 0)
        except (discord.NotFound, discord.Forbidden):
            unable_to_ban.append(id)

    msg = "Successfully forcebanned **{}** member{}.".format(
        len(ids) - len(unable_to_ban), '' if len(ids) - len(unable_to_ban) == 1 else 's')
    if len(ids) - len(unable_to_ban) > 0:
        await publiclog("ID{} **{}** w{} forcebanned by **{}** for reason: `{}`".format(
            '' if len(ids) - len(unable_to_ban) == 1 else 's', ', '.join(set(ids) - set(unable_to_ban)),
            'as' if len(ids) - len(unable_to_ban) == 1 else 'ere', message.author.display_name, reason))
        await log(1, "{} ({}) FORCEBAN {} FOR {}".format(message.author.display_name,
            message.author.id, ', '.join(set(ids) - set(unable_to_ban)), reason))
    if len(unable_to_ban) > 0:
        await log(2, "Unable to ban {}".format(', '.join("{} ({})".format(x.display_name, x.id) for x in unable_to_ban)))
    await reply(message, msg)

@cmd('warns', 1, "```\n{0}warns [<user>]\n\nReturns a list of warnings for everyone or just [<user>].```")
async def cmd_warns(message, parameters,recursion=0):
    def _format_warn(warned):
        SPACING = 15
        member = client.get_server(SERVER).get_member(warned)
        if member:
            name = member.display_name
        else:
            name = "user not in server with id " + warned
        return "{}{}: {}".format(name, ' ' * (SPACING - len(name)), warnings[warned])
    if parameters == '':
        msg = '**Users with warning points:**```\n'
        for warned in sorted(warnings, key=lambda x: warnings[x], reverse=True):
            if warnings[warned] > 0:
                msg += _format_warn(warned) + '\n'
        msg += '```'
        await reply(message, msg)
    else:
        parameters = parameters.strip('<!@>')
        if parameters in warnings:
            member = client.get_server(SERVER).get_member(parameters)
            if member:
                name = member.display_name
            else:
                name = "user not in server with id " + parameters
            await reply(message, "**{}** has **{}** warning points.".format(name, warnings[parameters]))
        elif parameters.isdigit() and len(parameters) in range(17, 21):
            member = client.get_server(SERVER).get_member(parameters)
            if member:
                name = member.display_name
            else:
                name = "user not in server with id " + parameters
            await reply(message, "**{}** has **0** warning points.".format(name))
        else:
            await reply(message, "Invalid mention/user id.")

@cmd("changegame", 3, "```\n{0}changegame [<game>]\n\nChanges the bot's Playing... status to [<game>] or unsets it.```")
async def cmd_changegame(message, parameters, recursion=0):
    if message.server:
        me = message.server.me
    else:
        me = list(client.servers)[0].me
    if parameters == '':
        game = None
    else:
        game = discord.Game(name=parameters)
    await client.change_presence(game=game, status=me.status)
    await reply(message, ":thumbsup:")

@cmd("changestatus", 3, "```\n{0}changestatus <status>\n\nChanges the bot's status to one of: online, idle, dnd, invisible.```")
async def cmd_changestatus(message, parameters, recursion=0):
    parameters = parameters.lower()
    statusmap = {'online' : discord.Status.online,
                 'idle' : discord.Status.idle,
                 'dnd' : discord.Status.dnd,
                 'invisible' : discord.Status.invisible}
    if message.server:
        me = message.server.me
    else:
        me = list(client.servers)[0].me
    if parameters == '':
        msg = "Current status is " + str(me.status)
    else:
        if parameters in statusmap:
            await client.change_presence(status=statusmap[parameters], game=me.game)
            msg = ":thumbsup:"
        else:
            msg = "Status must be one of: online, idle, dnd, invisible."
    await reply(message, msg)

######################## END OF COMMANDS ###########################

def get_moderator_role():
    global MODERATOR_ROLE
    MODERATOR_ROLE = MODERATOR_ROLE or discord.utils.get(client.get_server(SERVER).roles, id=MODERATOR_ROLE_ID)
    return MODERATOR_ROLE

def get_admin_role():
    global ADMIN_ROLE
    ADMIN_ROLE = ADMIN_ROLE or discord.utils.get(client.get_server(SERVER).roles, id=ADMIN_ROLE_ID)
    return ADMIN_ROLE

def get_muted_role():
    global MUTED_ROLE
    MUTED_ROLE = MUTED_ROLE or discord.utils.get(client.get_server(SERVER).roles, id=MUTED_ROLE_ID)
    return MUTED_ROLE
    

def get_permissions(member):
    permissions = 0
    if member.id == OWNER:
        permissions = 3
    elif isinstance(member, discord.Member):
        if get_admin_role() in member.roles:
            permissions = 2
        elif get_moderator_role() in member.roles:
            permissions = 1
    return permissions

def change_balance(user, amount=0):
    if user in data:
        data[user] += amount
    else:
        data[user] = amount
    with open(DATA_FILE, 'w', encoding='utf-8') as data_file:
        json.dump(data, data_file)
    return data[user]

def do_ignore(user, ignore=False):
    global ignore_list
    if user in ignore_list and not ignore:
        print("Removed {} from the ignore list.".format(user))
        ignore_list.remove(user)
    elif user not in ignore_list and ignore:
        print("Added {} to the ignore list.".format(user))
        ignore_list.append(user)
    with open(IGNORE_FILE, 'w', encoding='utf-8') as ignore_file:
        json.dump(ignore_list, ignore_file)

async def do_warns(user, amount=0):
    if user in warnings:
        warnings[user] += amount
    else:
        warnings[user] = amount
    with open('warnings.json', 'w', encoding='utf-8') as warnings_file:
        json.dump(warnings, warnings_file)
    await apply_sanctions(user)
    return warnings[user]

async def _mute(user, setter=None, reason=None, change=None, set_to=0):
    if setter == None:
        setter = client.user.id
    if reason == None:
        reason = "No reason specified"
    if not isinstance(set_to, timedelta):
        set_to = timedelta(seconds=set_to)

    if client.get_server(SERVER).get_member(user):
        user_name = client.get_server(SERVER).get_member(user).display_name
    else:
        user_name = "user not in server with id " + user

    if client.get_server(SERVER).get_member(setter):
        setter_name = client.get_server(SERVER).get_member(setter).display_name
    else:
        setter_name = "user not in server with id " + setter

    if change == None:
        mutes[user] = [datetime.now() + set_to, setter, reason]
        await log(1, "{} ({}) set {} ({})'s mute to {} for reason: {}".format(
            setter_name, setter, user_name, user, strfdelta(set_to), reason))
    else:
        if not isinstance(change, timedelta):
            change = timedelta(seconds=change)
        if user in mutes:
            mutes[user][0] += change
            await log(1, "{} ({}) changed {} ({})'s mute by {} for reason: {}".format(
                setter_name, setter, user_name, user, strfdelta(change), reason))
        else:
            mutes[user] = [datetime.now() + change, setter, reason]
            await log(1, "{} ({}) set {} ({})'s mute to {} for reason: {}".format(
                setter_name, setter, user_name, user, strfdelta(set_to), reason))

async def apply_sanctions(user):
    if client.get_server(SERVER).get_member(user):
        user_name = client.get_server(SERVER).get_member(user).display_name
    else:
        user_name = "user not in server with id " + user

    setter_name = client.get_server(SERVER).me.display_name
    points = warnings[user]
    mutelength = 0
    for sanction in SANCTIONS:
        if points in range(sanction[0], sanction[1] + 1):
            actions = sanction[2]
            if 'mute' in actions:
                mutelength += actions['mute']
            if 'scalemute' in actions:
                a, b, c = actions['scalemute']
                mutelength += a * points ** 2 + b * points + c
    if mutelength > 0:
        await _mute(user, reason="Auto-mute from warning points", change=mutelength)
        await publiclog("**{}** was muted for **{}** by **{}** for reason: `Auto-mute "
                        "from warning point threshold`".format(user_name,
                        strfdelta(timedelta(seconds=mutelength)), setter_name))


async def generate_random_amount(channel):
    amount = max(1, int(5 / random.random() ** 2.5))
    await log(1, "Generating currency with amount {} in channel {} ({})".format(amount, channel.name, channel.id))
    await generate_currency(channel, amount)

async def generate_currency(channel, amount=0, timeout=CURRENCY_TIMEOUT, secret=False):
    tier = 'swarm of base drones'
    for t in CURRENCY_TIERS:
        if CURRENCY_TIERS[t] <= amount and CURRENCY_TIERS[t] > CURRENCY_TIERS[tier]:
            tier = t
    if tier == 'basic tank':
        tier = random.choice(['fast basic rammer',
                              'tank shooting at you',
                              'tank running from a swarm of crashers',
                              'tank with very little health left',
                              'glass cannon tank'] + ["level {} basic tank".format(x) for x in range(1, 15)])
    elif tier.startswith('level 30 tank'):
        tier = random.choice(['Assassin', 'Auto 3', 'Basic Tank', 'Destroyer',
        'Flank Guard', 'Gunner', 'Hunter', 'Machine Gun', 'Overseer', 'Quad Tank',
        'Smasher', 'Sniper', 'Trapper', 'Tri-Angle', 'Triple Shot', 'Twin', 'Twin Flank'])
    elif tier.startswith('level 45 tank'):
        tier = random.choice(['Annihilator', 'Assassin', 'Auto 3', 'Auto 5', 'Auto Gunner', 'Auto Smasher',
        'Auto Trapper', 'Basic Tank', 'Battleship', 'Booster', 'Destroyer', 'Factory', 'Fighter', 'Flank Guard',
        'Gunner', 'Gunner Trapper', 'Hunter', 'Hybrid', 'Landmine', 'Machine Gun', 'Manager', 'Mega Trapper',
        'Necromancer', 'Octo Tank', 'Overlord', 'Overseer', 'Overtrapper', 'Penta Shot', 'Predator', 'Quad Tank',
        'Ranger', 'Rocketeer', 'Skimmer', 'Smasher', 'Sniper', 'Spike', 'Sprayer', 'Spread Shot', 'Stalker', 'Streamliner',
        'Trapper', 'Tri-Angle', 'Tri-Trapper', 'Triple Shot', 'Triple Twin', 'Triplet', 'Twin', 'Twin Flank'])
    
    if amount >= 0:
        cmds = CURRENCY_GETTERS
    else:
        cmds = CURRENCY_GETTERS_BAD
    
    if cmds:
        cmd = random.choice(cmds)
    else:
        cmd = 'shoot'

    def check(m):
        return m.content.lower().startswith('{}{}'.format(PREFIX, cmd)) and m.author.id not in ignore_list and not m.author.bot
    if not secret:
        msg = await client.send_message(channel,
        "A{} **{}** appeared! Type **{}{}** in this channel to gain **{} {}**!".format(
            'n' if tier[0] in ('a', 'e', 'i', 'o', 'u') else '', tier, PREFIX, cmd, amount, CURRENCY_NAME))
    before = datetime.now()
    answer = await client.wait_for_message(timeout=timeout, channel=channel, check=check)
    after = datetime.now()
    try:
        await client.delete_message(msg)
    except:
        pass
    if answer:
        await log(1, "{} ({}) SHOOT FOR {} {} (time taken: {} ms) ".format(answer.author.display_name,
        answer.author.id, amount, CURRENCY_NAME, round((after - before).total_seconds() * 1000, 2)))
        try:
            await client.delete_message(answer)
        except:
            pass
        await client.send_message(channel,
        "**{}** {}{}s the **{}** and gains **{} {}**!".format(answer.author.display_name,
            cmd, 'e' if cmd.endswith('sh') else '', tier, amount, CURRENCY_NAME))
        if amount > 0 and (after - before).total_seconds() * 1000 < CURRENCY_IGNORE_THRESHOLD:
            await log(2, "Anti-botting activated on {} ({})".format(answer.author.display_name, answer.author.id))
            amount *= -1
        change_balance(answer.author.id, amount)
    else:
        response = random.choice(CURRENCY_TOO_LATE)
        change_balance(client.user.id, abs(amount))
        await client.send_message(channel, "Too late! {} the {}.".format(response, tier))

async def echo(message, text, cleanmessage=True):
    if cleanmessage:
        text = text.replace('@', '@\u200b')
    return await client.send_message(message.channel, text)

async def reply(message, text, cleanmessage=True):
    if cleanmessage:
        text = text.replace('@', '@\u200b')
    return await client.send_message(message.channel, message.author.mention + ', ' + text)

async def send_multi_message(message: discord.Message, content: str, *, mention_author=False, clean_message=True, handle_codeblock=False):
    """Sends a message, breaking the message up into multiple messages if necessary.
    Tries to break at commas (for comma-separated lists) and newlines.
    Optionally handles codeblocks.""" 
    if clean_message:
        content = content.replace('@', '@\u200b')
    if mention_author:
        content = message.author.mention + ", " + content
    return await send_multi_message_helper(message, content, handle_codeblock=handle_codeblock)

async def send_multi_message_helper(message: discord.Message, content: str, *, handle_codeblock=False):
    """Recursive helper for send_multi_message. If handle_codeblock is set, assumes message ends with three backticks and formats accordingly."""
    if len(content) <= DISCORD_MAX_MSG_LEN:
        return await client.send_message(message.channel, content)

    # Content is too large for one message.
    # Prioritize breaking after a comma or linebreak, then as far as possible.
    max_amount_to_send = DISCORD_MAX_MSG_LEN - len("\n...\n")
    if handle_codeblock:
        max_amount_to_send -= len("```")
    content_truncated = content[:max_amount_to_send]
    # The indexes will be the break point in content, *including* the comma or newline
    try:
        last_comma_idx = max_amount_to_send - content_truncated[::-1].index(",")
    except ValueError:
        last_comma_idx = -1
    try:
        last_newline_idx = max_amount_to_send - content_truncated[::-1].index("\n")
    except ValueError:
        last_newline_idx = -1
    break_idx = max(last_comma_idx, last_newline_idx)
    if break_idx == -1:
        break_idx = max_amount_to_send
    
    should_use_newline = break_idx == last_newline_idx
    broken_content = content[:break_idx]
    
    if should_use_newline:
        broken_content += "\n..."
    else:
        broken_content += " ..."
    
    if handle_codeblock:
        broken_content += "\n```"
    
    await client.send_message(message.channel, broken_content)

    remaining_content = content[break_idx:].strip()
    remaining_content = ("```\n" if handle_codeblock else "") + "..." + ("\n" if should_use_newline else " ") + remaining_content

    return await send_multi_message_helper(message, remaining_content, handle_codeblock=handle_codeblock)

async def log(loglevel, text):
    # loglevels
    # 0 = DEBUG
    # 1 = INFO
    # 2 = WARNING
    # 3 = ERROR
    levelmsg = {0 : '[DEBUG] ',
                1 : '[INFO] ',
                2 : '**[WARNING]** ',
                3 : '**[ERROR]** <@' + OWNER + '> '}

    logmsg = levelmsg[loglevel] + str(text)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write("[{}] {}\n".format(datetime.now(), logmsg))
    if loglevel >= MIN_LOG_LEVEL:
        print(logmsg)
        await client.send_message(client.get_channel(PRIVATE_LOG_CHANNEL), logmsg)

async def publiclog(text):
    await client.send_message(client.get_channel(LOG_CHANNEL), text)

def strtodatetime(string):
    return datetime.strptime(string, '%Y-%m-%d %H:%M:%S.%f')

def strfdelta(delta):
    output = [[delta.days, 'day'],
              [delta.seconds // 3600, 'hour'],
              [delta.seconds // 60 % 60, 'minute'],
              [delta.seconds % 60, 'second']]
    for i in range(len(output)):
        if output[i][0] != 1:
            output[i][1] += 's'
    reply_msg = ''
    if output[0][0] != 0:
        reply_msg += "{} {} ".format(output[0][0], output[0][1])
    for i in range(1, len(output)):
        reply_msg += "{} {} ".format(output[i][0], output[i][1])
    reply_msg = reply_msg[:-1]
    return reply_msg

def convdatestring(datestring):
    datestring = datestring.replace(' ', '')
    datearray = []
    funcs = {'w' : lambda x: x * 7 * 24 * 60 * 60,
             'd' : lambda x: x * 24 * 60 * 60,
             'h' : lambda x: x * 60 * 60,
             'm' : lambda x: x * 60,
             's' : lambda x: x}
    currentnumber = ''
    for char in datestring:
        if char.isdigit():
            currentnumber += char
        else:
            if currentnumber == '':
                continue
            datearray.append((int(currentnumber), char))
            currentnumber = ''
    seconds = 0
    if currentnumber:
        seconds += int(currentnumber)
    for i in datearray:
        if i[1] in funcs:
            seconds += funcs[i[1]](i[0])
    return timedelta(seconds=seconds)

async def warning_loop():
    while starttime == None:
        await asyncio.sleep(1)
    while not client.is_closed:
        await asyncio.sleep(WARNING_EXPIRE)
        await log(1, "Decaying all warning points by 1")
        for warned in list(warnings):
            if warnings[warned] > 0:
                warnings[warned] -= 1
            else:
                del warnings[warned]
        with open('warnings.json', 'w', encoding='utf-8') as warnings_file:
            json.dump(warnings, warnings_file)


mute_task = client.loop.create_task(mute_loop())
warning_task = client.loop.create_task(warning_loop())
client.run(TOKEN)
mute_task.cancel()
warning_task.cancel()